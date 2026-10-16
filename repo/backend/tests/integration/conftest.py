"""Fixtures for tests that need a real PostgreSQL database.

Tests run against their own database, never the development one: TEST_DATABASE_URL, or
DATABASE_URL with "_test" appended to the database name. It is created if missing and
migrated to the latest revision once per test run.

When the server is unreachable these tests are skipped. With REQUIRE_DB=1 they fail
instead, so a CI run cannot pass by skipping them.
"""

import asyncio
import os
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AbstractAsyncContextManager, AsyncExitStack
from datetime import datetime
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import make_url, text, update
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from app.copilot.fake import FakeModelClient, FakeStep
from app.core.config import BACKEND_DIR, get_settings
from app.db.session import get_session
from app.models import Loan

CONNECT_TIMEOUT_SECONDS = 5.0


def _test_database_url() -> URL:
    explicit = os.environ.get("TEST_DATABASE_URL")
    if explicit:
        return make_url(explicit)
    url = make_url(get_settings().database_url)
    return url.set(database=f"{url.database}_test")


async def _ensure_database(url: URL) -> None:
    """Creates the test database on the server if it does not exist yet."""
    server = create_async_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        async with asyncio.timeout(CONNECT_TIMEOUT_SECONDS), server.connect() as connection:
            exists = await connection.scalar(
                text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": url.database}
            )
            if not exists:
                await connection.execute(text(f'CREATE DATABASE "{url.database}"'))
    finally:
        await server.dispose()


def _migrate(url: URL) -> None:
    # A subprocess, because the migration environment runs its own event loop.
    env = {**os.environ, "DATABASE_URL": url.render_as_string(hide_password=False)}
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND_DIR,
        env=env,
        check=True,
        capture_output=True,
    )


@pytest.fixture(scope="session")
async def db_engine() -> AsyncIterator[AsyncEngine]:
    url = _test_database_url()
    try:
        await _ensure_database(url)
        _migrate(url)
        failure = None
    except subprocess.CalledProcessError as exc:
        failure = f"test database migration failed: {exc.stderr.decode(errors='replace')}"
    except Exception as exc:
        failure = f"database unreachable ({type(exc).__name__}: {exc})"

    if failure is not None:
        if os.environ.get("REQUIRE_DB") == "1":
            pytest.fail(f"{failure}; REQUIRE_DB=1 is set", pytrace=False)
        pytest.skip(failure)

    engine = create_async_engine(url)
    yield engine
    await engine.dispose()


@pytest.fixture
async def db_session(db_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """A session whose changes, including commits, are rolled back after the test.

    The test runs inside an outer transaction. Session commits only release a SAVEPOINT,
    and the outer transaction is rolled back at teardown.
    """
    async with db_engine.connect() as connection:
        transaction = await connection.begin()
        session = AsyncSession(
            bind=connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        try:
            yield session
        finally:
            await session.close()
            await transaction.rollback()


@pytest.fixture
async def empty_db(db_session: AsyncSession) -> AsyncSession:
    """The test session with every library table emptied, inside the rolled-back transaction,
    so tests see only their own data whatever the test database holds.
    """
    tables = (
        "copilot_proposals",
        "copilot_messages",
        "copilot_conversations",
        "activity_events",
        "sessions",
        "users",
        "renewals",
        "holds",
        "loans",
        "copies",
        "books",
        "members",
    )
    for table in tables:
        await db_session.execute(text(f"DELETE FROM {table}"))  # noqa: S608 (fixed names)
    # Moves the deletes into the outer transaction, so a later rollback in a service keeps them.
    await db_session.commit()
    return db_session


@pytest.fixture
def make_db_app(
    make_app: Callable[..., FastAPI], db_engine: AsyncEngine, empty_db: AsyncSession
) -> Callable[..., FastAPI]:
    """Builds an app whose requests all use the test session, so everything they write is rolled
    back. Keyword arguments override single settings.
    """

    database_url = db_engine.url.render_as_string(hide_password=False)

    def _make(**overrides: Any) -> FastAPI:
        app = make_app(database_url=database_url, **overrides)

        async def test_session() -> AsyncIterator[AsyncSession]:
            try:
                yield empty_db
            finally:
                # The next request starts with an empty identity map, like a fresh session.
                empty_db.expunge_all()

        app.dependency_overrides[get_session] = test_session
        return app

    return _make


@pytest.fixture
def app(make_db_app: Callable[..., FastAPI]) -> FastAPI:
    return make_db_app()


async def sign_in_as(http: AsyncClient, role: str) -> dict[str, Any]:
    """Signs the client in as the demo account of the role and returns the UserOut body."""
    response = await http.post("/api/auth/demo", json={"role": role})
    assert response.status_code == 200, response.text
    user: dict[str, Any] = response.json()
    return user


@pytest.fixture
def sign_in() -> Callable[[AsyncClient, str], Awaitable[dict[str, Any]]]:
    return sign_in_as


@pytest.fixture
async def client(
    app: FastAPI, serve: Callable[[FastAPI], AbstractAsyncContextManager[AsyncClient]]
) -> AsyncIterator[AsyncClient]:
    """A client signed in as the demo staff account. Most tests act as staff."""
    async with serve(app) as http:
        await sign_in_as(http, "staff")
        yield http


@pytest.fixture
async def open_client(app: FastAPI) -> AsyncIterator[Callable[..., Awaitable[AsyncClient]]]:
    """Opens more clients of the test app, each with its own cookies: signed in as the demo
    account of the role, or anonymous without one.
    """
    async with AsyncExitStack() as stack:

        async def _open(role: str | None = None) -> AsyncClient:
            transport = ASGITransport(app=app, raise_app_exceptions=False)
            http = await stack.enter_async_context(
                AsyncClient(transport=transport, base_url="http://test")
            )
            if role is not None:
                await sign_in_as(http, role)
            return http

        yield _open


@pytest.fixture
async def copilot(
    make_db_app: Callable[..., FastAPI],
    serve: Callable[[FastAPI], AbstractAsyncContextManager[AsyncClient]],
) -> AsyncIterator[Callable[..., Awaitable[tuple[AsyncClient, FakeModelClient]]]]:
    """Opens a client, signed in as the role, on an app whose model is a fake with this script.
    Keyword arguments override single settings.
    """
    async with AsyncExitStack() as stack:

        async def _open(
            *steps: FakeStep, role: str = "member", **settings: Any
        ) -> tuple[AsyncClient, FakeModelClient]:
            app = make_db_app(**settings)
            model = FakeModelClient(list(steps))
            app.state.copilot_model = model
            http = await stack.enter_async_context(serve(app))
            await sign_in_as(http, role)
            return http, model

        yield _open


@pytest.fixture
async def anonymous(open_client: Callable[..., Awaitable[AsyncClient]]) -> AsyncClient:
    return await open_client()


@pytest.fixture
async def member_client(open_client: Callable[..., Awaitable[AsyncClient]]) -> AsyncClient:
    """A client signed in as the demo member account."""
    return await open_client("member")


@pytest.fixture
def make_book(client: AsyncClient) -> Callable[..., Awaitable[dict[str, Any]]]:
    """Adds a book through the API and returns the BookDetail body."""

    async def _make(**fields: Any) -> dict[str, Any]:
        body = {"title": "Dune", "author": "Frank Herbert", **fields}
        response = await client.post("/api/books", json=body)
        assert response.status_code == 201, response.text
        book: dict[str, Any] = response.json()
        return book

    return _make


@pytest.fixture
def make_member(client: AsyncClient) -> Callable[..., Awaitable[dict[str, Any]]]:
    """Adds a member through the API and returns the MemberOut body."""

    async def _make(full_name: str = "Maya Hassan", email: str | None = None) -> dict[str, Any]:
        response = await client.post("/api/members", json={"full_name": full_name, "email": email})
        assert response.status_code == 201, response.text
        member: dict[str, Any] = response.json()
        return member

    return _make


@pytest.fixture
def borrow(client: AsyncClient) -> Callable[..., Awaitable[Response]]:
    """Posts a borrow and returns the raw response."""

    async def _borrow(copy_id: str, member_id: str, **fields: Any) -> Response:
        body = {"copy_id": copy_id, "member_id": member_id, **fields}
        return await client.post("/api/loans", json=body)

    return _borrow


@pytest.fixture
def move_loan(empty_db: AsyncSession) -> Callable[..., Awaitable[None]]:
    """Sets a loan's borrowed_at, due_at or returned_at directly, to place it in time.

    During a test the database's now() is when the test's transaction began, a moment before
    the test body runs. Times a minute or more from the present fall clearly on one side of it.
    """

    async def _move(loan_id: str, **times: datetime) -> None:
        await empty_db.execute(update(Loan).where(Loan.id == uuid.UUID(loan_id)).values(**times))
        await empty_db.commit()

    return _move
