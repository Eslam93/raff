"""The holds sweep: one failing book does not stop the others, and the loop keeps going after a
failed sweep until it is cancelled.

The sweep runs in the test's session here, so everything it writes is rolled back afterwards.
"""

import asyncio
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update

from app.models import Hold
from app.services import holds

pytestmark = pytest.mark.integration

WAIT_SECONDS = 5.0


class RecordingLog:
    """Stands in for the holds service's logger and keeps what it was told."""

    def __init__(self):
        self.errors = []

    def error(self, event, **fields):
        self.errors.append((event, fields))

    def info(self, event, **fields):
        pass


@pytest.fixture
def recorded(monkeypatch):
    log = RecordingLog()
    monkeypatch.setattr(holds, "log", log)
    return log


@pytest.fixture
def lapsed_hold(make_book, make_member, borrow, client, empty_db):
    """A book whose only copy is set aside for a member, with the pick-up time passed."""

    async def _make(title: str) -> dict:
        book = await make_book(title=title, copies=1)
        sara = await make_member(f"Sara for {title}")
        maya = await make_member(f"Maya for {title}")
        loan = (await borrow(book["copies"][0]["id"], sara["id"])).json()
        hold = (
            await client.post("/api/holds", json={"book_id": book["id"], "member_id": maya["id"]})
        ).json()
        await client.post(f"/api/loans/{loan['id']}/return")
        await empty_db.execute(
            update(Hold)
            .where(Hold.id == uuid.UUID(hold["id"]))
            .values(pickup_by=datetime.now(UTC) - timedelta(hours=1))
        )
        await empty_db.commit()
        return {"book_id": uuid.UUID(book["id"]), "hold_id": uuid.UUID(hold["id"])}

    return _make


async def stored_status(session, hold_id) -> str | None:
    return await session.scalar(select(Hold.status).where(Hold.id == hold_id))


async def test_a_failure_for_one_book_is_logged_and_the_other_books_are_still_settled(
    lapsed_hold, empty_db, recorded, monkeypatch
):
    broken = await lapsed_hold("Broken")
    fine = await lapsed_hold("Fine")
    settle = holds.settle_book

    async def settle_or_fail(session, book_id, **options):
        if book_id == broken["book_id"]:
            raise RuntimeError("the database refused")
        await settle(session, book_id, **options)

    monkeypatch.setattr(holds, "settle_book", settle_or_fail)

    settled = await holds.sweep(empty_db, hold_pickup_days=3)

    assert settled == 1
    assert await stored_status(empty_db, fine["hold_id"]) == "expired"
    assert await stored_status(empty_db, broken["hold_id"]) == "ready"
    assert recorded.errors == [("hold_sweep_book_failed", recorded.errors[0][1])]
    assert recorded.errors[0][1]["book_id"] == str(broken["book_id"])


async def test_the_loop_sweeps_again_after_a_failed_sweep(lapsed_hold, empty_db, recorded):
    hold = await lapsed_hold("Dune")
    calls = 0
    swept = asyncio.Event()

    @asynccontextmanager
    async def sessions():
        """The first sweep cannot reach the database, the second can, and any later one waits
        until the loop is cancelled, so only one task uses the test's session at a time.
        """
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ConnectionError("the database is unreachable")
        if calls > 2:
            await asyncio.Event().wait()
        yield empty_db
        swept.set()

    loop = asyncio.create_task(holds.run_sweeps(sessions, every_seconds=0.01, hold_pickup_days=3))
    try:
        async with asyncio.timeout(WAIT_SECONDS):
            await swept.wait()
    finally:
        loop.cancel()

    with pytest.raises(asyncio.CancelledError):
        await loop
    assert await stored_status(empty_db, hold["hold_id"]) == "expired"
    assert [event for event, _ in recorded.errors] == ["hold_sweep_failed"]
