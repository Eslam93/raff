"""Two holds by one member on one book, or two renewals of one loan, at the same moment, through
separate database connections.

These tests cannot run inside the rolled-back test transaction, because each connection must
see the other's committed work. They commit their own data and remove it afterwards.
"""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import delete, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.core.exceptions import ConflictError
from app.models import ActivityEvent, Book, Copy, Hold, Loan, Member, Renewal, User
from app.services import circulation, holds
from app.services.catalog import allocate_copy_codes

pytestmark = pytest.mark.integration

LOCK_WAIT_TIMEOUT_SECONDS = 5.0


@pytest.fixture
def app(make_app, db_engine):
    """The real app: every request gets its own session and connection from the pool."""
    return make_app(database_url=db_engine.url.render_as_string(hide_password=False))


@pytest.fixture
async def client(app, serve, sign_in, db_engine):
    """Signed in as demo staff. The account is committed for real, so it is removed afterwards
    together with its sessions.
    """
    async with serve(app) as http:
        staff = await sign_in(http, "staff")
        yield http

    async with db_engine.begin() as connection:
        await connection.execute(delete(User).where(User.id == uuid.UUID(staff["id"])))


@pytest.fixture
async def line(db_engine):
    """A book whose only copy is lent out, the member who has it, and a member who wants it,
    committed so every connection sees them.
    """
    sessions = async_sessionmaker(db_engine, expire_on_commit=False)
    async with sessions() as session:
        book = Book(title="Holds race probe", author="Test Suite")
        session.add(book)
        await session.flush()
        [code] = await allocate_copy_codes(session, 1)
        copy = Copy(book_id=book.id, code=code)
        borrower, holder = Member(full_name="Race Borrower"), Member(full_name="Race Holder")
        session.add_all([copy, borrower, holder])
        await session.flush()
        loan = Loan(
            copy_id=copy.id,
            member_id=borrower.id,
            due_at=datetime.now(UTC) + timedelta(days=14),
        )
        session.add(loan)
        await session.commit()

    yield SimpleNamespace(book=book, copy=copy, loan=loan, borrower=borrower, holder=holder)

    async with sessions() as session:
        hold_ids = select(Hold.id).where(Hold.book_id == book.id)
        loan_ids = select(Loan.id).where(Loan.copy_id == copy.id)
        await session.execute(
            delete(ActivityEvent).where(
                or_(ActivityEvent.entity_id.in_(hold_ids), ActivityEvent.entity_id.in_(loan_ids))
            )
        )
        await session.execute(delete(Renewal).where(Renewal.loan_id.in_(loan_ids)))
        await session.execute(delete(Hold).where(Hold.book_id == book.id))
        await session.execute(delete(Loan).where(Loan.copy_id == copy.id))
        await session.execute(delete(Book).where(Book.id == book.id))
        await session.execute(delete(Member).where(Member.id.in_([borrower.id, holder.id])))
        await session.commit()


async def open_holds(engine: AsyncEngine, book_id) -> int:
    async with engine.connect() as connection:
        count = await connection.scalar(
            select(func.count())
            .select_from(Hold)
            .where(Hold.book_id == book_id, Hold.status.in_(("waiting", "ready")))
        )
    return count or 0


async def renewals_of(engine: AsyncEngine, loan_id) -> int:
    async with engine.connect() as connection:
        count = await connection.scalar(
            select(func.count()).select_from(Renewal).where(Renewal.loan_id == loan_id)
        )
    return count or 0


async def wait_until_waiting_on_a_lock(engine: AsyncEngine, pid: int) -> None:
    query = text("SELECT wait_event_type FROM pg_stat_activity WHERE pid = :pid")
    async with asyncio.timeout(LOCK_WAIT_TIMEOUT_SECONDS), engine.connect() as connection:
        while await connection.scalar(query, {"pid": pid}) != "Lock":
            await asyncio.sleep(0.02)


async def test_two_simultaneous_holds_by_one_member_on_one_book_make_one_hold_and_one_409(
    client, line, db_engine
):
    body = {"book_id": str(line.book.id), "member_id": str(line.holder.id)}

    responses = await asyncio.gather(
        client.post("/api/holds", json=body), client.post("/api/holds", json=body)
    )

    assert sorted(response.status_code for response in responses) == [201, 409]
    conflict = next(response for response in responses if response.status_code == 409)
    assert conflict.json()["error"]["code"] == "hold_exists"
    assert await open_holds(db_engine, line.book.id) == 1


async def test_a_hold_that_loses_the_race_at_the_database_is_hold_exists(line, db_engine):
    sessions = async_sessionmaker(db_engine, expire_on_commit=False)
    async with sessions() as winner, sessions() as loser:
        # The winner's hold is written but not committed, without the book's lock, so the loser's
        # checks cannot see it and the loser's insert has to wait on the unique index.
        winner.add(Hold(book_id=line.book.id, member_id=line.holder.id, status="waiting"))
        await winner.flush()
        loser_pid = await loser.scalar(text("SELECT pg_backend_pid()"))
        attempt = asyncio.create_task(
            holds.place(
                loser,
                book_id=line.book.id,
                member_id=line.holder.id,
                max_open_holds=5,
                hold_pickup_days=3,
                actor=None,
            )
        )
        await wait_until_waiting_on_a_lock(db_engine, loser_pid)
        await winner.commit()

        with pytest.raises(ConflictError) as caught:
            await attempt

    assert caught.value.code == "hold_exists"
    assert await open_holds(db_engine, line.book.id) == 1


async def test_two_simultaneous_renewals_of_one_loan_count_once(line, db_engine):
    sessions = async_sessionmaker(db_engine, expire_on_commit=False)
    async with sessions() as blocker, sessions() as first, sessions() as second:
        # The blocker holds the loan's row, so both renewals read the same due date, pass their
        # checks, and wait at their conditional update until the blocker lets go.
        await blocker.execute(select(Loan.id).where(Loan.id == line.loan.id).with_for_update())
        renewers = (first, second)
        pids = [await renewer.scalar(text("SELECT pg_backend_pid()")) for renewer in renewers]
        attempts = [
            asyncio.create_task(
                circulation.renew(
                    renewer, line.loan.id, loan_period_days=14, max_renewals=2, actor=None
                )
            )
            for renewer in renewers
        ]
        for pid in pids:
            await wait_until_waiting_on_a_lock(db_engine, pid)
        await blocker.commit()

        results = await asyncio.gather(*attempts, return_exceptions=True)

    refused = [result for result in results if isinstance(result, ConflictError)]
    renewed = [result for result in results if not isinstance(result, BaseException)]
    assert len(renewed) == 1
    assert [error.code for error in refused] == ["loan_changed"]
    assert renewed[0].renewals == 1
    assert await renewals_of(db_engine, line.loan.id) == 1
