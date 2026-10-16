"""Application factory. Run with: uvicorn app.main:create_app --factory"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

import httpx
from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware

from app.api.cookies import OAUTH_STATE_COOKIE, OAUTH_STATE_COOKIE_PATH, OAUTH_STATE_MAX_AGE_SECONDS
from app.api.google import create_google_client
from app.api.router import api_router
from app.copilot.clients import create_model_client
from app.copilot.rate_limit import RateLimiter
from app.core.config import Settings, get_settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging
from app.db.session import create_engine, create_session_factory
from app.frontend import mount_frontend
from app.middleware.access_log import AccessLogMiddleware
from app.middleware.errors import UnhandledErrorMiddleware
from app.middleware.origin_check import OriginCheckMiddleware
from app.middleware.request_id import RequestIdMiddleware
from app.middleware.security_headers import SecurityHeadersMiddleware
from app.services import holds
from app.services.isbn_lookup import IsbnLookup

DOCS_URL = "/api/docs"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, json=settings.is_production)

    engine = create_engine(settings.database_url)
    session_factory = create_session_factory(engine)
    # The Copilot's connection pool to the model service, and the ISBN lookup's to Open Library.
    # Neither opens a connection until used.
    copilot_http = httpx.AsyncClient()
    isbn_http = httpx.AsyncClient()

    @asynccontextmanager
    async def lifespan(running_app: FastAPI) -> AsyncIterator[None]:
        # The holds sweep runs beside the requests while the app is up, unless turned off.
        sweeper = None
        if settings.hold_sweep_seconds > 0:
            sweeper = asyncio.create_task(
                holds.run_sweeps(
                    session_factory,
                    every_seconds=settings.hold_sweep_seconds,
                    hold_pickup_days=settings.hold_pickup_days,
                ),
                name="hold-sweeps",
            )
        running_app.state.hold_sweeper = sweeper
        yield
        if sweeper is not None:
            sweeper.cancel()
            with suppress(asyncio.CancelledError):
                await sweeper
        await copilot_http.aclose()
        await isbn_http.aclose()
        await engine.dispose()

    docs_enabled = not settings.is_production
    app = FastAPI(
        title="Raff API",
        version="0.1.0",
        lifespan=lifespan,
        docs_url=DOCS_URL if docs_enabled else None,
        redoc_url=None,
        openapi_url="/api/openapi.json" if docs_enabled else None,
        swagger_ui_oauth2_redirect_url=None,
    )
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = session_factory
    # The running holds sweep while the app is up (see lifespan); None when turned off.
    app.state.hold_sweeper = None
    app.state.google = create_google_client(settings)
    # None when no model is configured: the Copilot then shows as unavailable.
    app.state.copilot_model = create_model_client(settings, copilot_http)
    app.state.copilot_rate_limiter = RateLimiter(settings.copilot_rate_per_minute)
    # None when turned off: the lookup then answers 503.
    app.state.isbn_lookup = IsbnLookup(isbn_http) if settings.isbn_lookup_enabled else None

    # Starlette runs the last added middleware first, so these read from innermost to outermost.
    if app.state.google is not None:
        # request.session for the Google sign-in routes, carried by the signed oauth_state cookie.
        app.add_middleware(
            SessionMiddleware,
            secret_key=settings.session_secret.get_secret_value(),
            session_cookie=OAUTH_STATE_COOKIE,
            max_age=OAUTH_STATE_MAX_AGE_SECONDS,
            path=OAUTH_STATE_COOKIE_PATH,
            same_site="lax",
            https_only=settings.is_production,
        )
    app.add_middleware(OriginCheckMiddleware, allowed_origins=settings.allowed_origins)
    app.add_middleware(UnhandledErrorMiddleware)
    app.add_middleware(AccessLogMiddleware)
    app.add_middleware(RequestIdMiddleware)
    app.add_middleware(
        SecurityHeadersMiddleware,
        hsts=settings.is_production,
        docs_paths=[DOCS_URL] if docs_enabled else [],
    )
    register_exception_handlers(app)

    app.include_router(api_router, prefix="/api")
    mount_frontend(app, settings.frontend_dist_dir)
    return app
