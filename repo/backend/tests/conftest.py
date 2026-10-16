"""Shared fixtures. The app runs in-process; unit tests never open a database connection."""

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings
from app.main import create_app


@asynccontextmanager
async def _serve(app: FastAPI) -> AsyncIterator[AsyncClient]:
    """Runs the app lifespan, so the engine is disposed afterwards, and yields a client."""
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=transport, base_url="http://test") as http,
    ):
        yield http


@pytest.fixture
def make_app(tmp_path: Path) -> Callable[..., FastAPI]:
    """Builds an app from test settings. Keyword arguments override single settings."""

    def _make(**overrides: Any) -> FastAPI:
        values: dict[str, Any] = {
            "app_env": "test",
            "frontend_dist_dir": tmp_path / "no-frontend-build",
            # No model and no ISBN lookup, whatever the environment holds: tests never reach
            # the network.
            "openrouter_api_key": None,
            "copilot_fake_model": False,
            "isbn_lookup_enabled": False,
            # No holds sweep in the background: a test that needs it turns it on or runs it.
            "hold_sweep_seconds": 0,
            **overrides,
        }
        return create_app(Settings(_env_file=None, **values))

    return _make


@pytest.fixture
def serve() -> Callable[[FastAPI], AbstractAsyncContextManager[AsyncClient]]:
    return _serve


@pytest.fixture
def app(make_app: Callable[..., FastAPI]) -> FastAPI:
    return make_app()


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with _serve(app) as http:
        yield http
