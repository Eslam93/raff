"""Holds: a member's place in line for a book with no copy on the shelf.

A hold is waiting until a copy comes free for it, then ready: the copy is set aside for the
member until the end of the pick-up day. Borrowing any copy of the book fulfils the member's open
hold, a ready hold not picked up in time expires, and the member or staff can cancel an open hold.
Place in line is derived when reading: the waiting holds on the same book placed earlier (ties by
id), plus one. A ready hold past its pick-up time reads as expired, and its copy as free
(app.services.availability), before anything writes that.

settle_book keeps a book's holds in step with its copies: it expires ready holds past their
pick-up time, then sets free copies aside for the oldest waiting holds. It runs inside every
change that frees or takes a copy of the book (borrow, return, adding copies, placing and
cancelling a hold) and in the sweep, which the app runs every HOLD_SWEEP_SECONDS.

Every change to a book's holds first takes a transaction-level advisory lock keyed on the book,
before any row lock, so changes to one book's line run one at a time and cannot deadlock with the
borrow's share lock on the book's row. The partial unique indexes still have the last word: one
open hold per member and book, and one ready hold per copy.
"""

import asyncio
import uuid
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from typing import Any, cast

from sqlalchemy import (
    ColumnElement,
    Select,
    case,
    exists,
    func,
    literal,
    null,
    or_,
    select,
    tuple_,
    union,
    update,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.exceptions import ConflictError, NotFoundError
from app.core.logging import get_logger
from app.db.errors import flush_or_raise
from app.models import ActivityVia, Book, Copy, Hold, HoldStatus, Loan, Member, User
from app.models.hold import OPEN_HOLD_PER_MEMBER_INDEX, OPEN_HOLD_STATUSES
from app.schemas.common import Page
from app.schemas.holds import HoldListStatus, HoldOut
from app.schemas.loans import BookRef, CopyRef, HeldFor
from app.schemas.members import MemberRef
from app.services import activity, availability

log = get_logger(__name__)

# Advisory lock keys are shared by the whole database. The first of the two keys names the holds'
# locks ("hold" in ASCII), the second is taken from the book's id.
_LOCK_CLASS = 0x686F6C64
# A hold is picked up by the end of its pick-up day, in UTC, as a loan is due at the end of its
# due day.
_END_OF_DAY = time(23, 59, 59, tzinfo=UTC)
_CLOSED_STATUSES = ("fulfilled", "cancelled", "expired")


def _book_archived() -> ConflictError:
    return ConflictError("This book is archived.", code="book_archived")


def _hold_exists(member_name: str, title: str) -> ConflictError:
    return ConflictError(f"{member_name} already has a hold on {title}.", code="hold_exists")


# Locking


def _lock_key(book_id: uuid.UUID) -> int:
    """32 bits of the book's id. Two books that share them only wait for each other."""
    return int.from_bytes(book_id.bytes[:4], "big", signed=True)


async def lock_book_line(session: AsyncSession, book_id: uuid.UUID) -> None:
    """Takes the lock on the book's line until the transaction ends. Callers take it before any
    row lock. Taking it again in the same transaction returns at once.
    """
    await session.execute(select(func.pg_advisory_xact_lock(_LOCK_CLASS, _lock_key(book_id))))


# Expressions


def _status() -> ColumnElement[str]:
    """The status as people see it: a ready hold past its pick-up time is expired."""
    return case((availability.is_lapsed(), literal("expired")), else_=Hold.status)


def _is_open() -> ColumnElement[bool]:
    """Waiting, or ready with the copy still set aside."""
    return or_(Hold.status == "waiting", availability.is_live_ready())


def _position() -> ColumnElement[int | None]:
    """Place in line for a waiting hold, 1 for the next; null for any other hold."""
    earlier = aliased(Hold)
    ahead = (
        select(func.count())
        .where(
            earlier.book_id == Hold.book_id,
            earlier.status == "waiting",
            tuple_(earlier.placed_at, earlier.id) < tuple_(Hold.placed_at, Hold.id),
        )
        .correlate(Hold)
        .scalar_subquery()
    )
    return case((Hold.status == "waiting", ahead + 1), else_=null())


def has_waiting_holds(book_id: Any) -> ColumnElement[bool]:
    """True while a member is in line for the book."""
    hold = aliased(Hold)
    return exists().where(hold.book_id == book_id, hold.status == "waiting")


# Reading


def _hold_statement() -> Select[tuple[Hold, str, int | None, str, str, str, str]]:
    """Each hold with its shown status, place in line, book, member, and the code of its copy
    (null until the hold is ready, through the outer join).
    """
    return (
        select(
            Hold,
            _status().label("shown_status"),
            _position().label("position"),
            Book.title,
            Book.author,
            Member.full_name,
            Copy.code,
        )
        .join(Book, Book.id == Hold.book_id)
        .join(Member, Member.id == Hold.member_id)
        .outerjoin(Copy, Copy.id == Hold.copy_id)
        .execution_options(populate_existing=True)
    )


def _hold_out(
    hold: Hold,
    status: str,
    position: int | None,
    title: str,
    author: str,
    member_name: str,
    code: str | None,
) -> HoldOut:
    copy = CopyRef(id=hold.copy_id, code=code) if hold.copy_id and code is not None else None
    return HoldOut(
        id=hold.id,
        status=cast(HoldStatus, status),
        book=BookRef(id=hold.book_id, title=title, author=author),
        member=MemberRef(id=hold.member_id, full_name=member_name),
        copy=copy,
        placed_at=hold.placed_at,
        ready_at=hold.ready_at,
        pickup_by=hold.pickup_by,
        closed_at=hold.closed_at,
        position=position,
    )


async def get_hold(
    session: AsyncSession, hold_id: uuid.UUID, *, member_id: uuid.UUID | None = None
) -> HoldOut:
    """With member_id, another member's hold is not found, like a missing one."""
    statement = _hold_statement().where(Hold.id == hold_id)
    if member_id is not None:
        statement = statement.where(Hold.member_id == member_id)
    row = (await session.execute(statement)).one_or_none()
    if row is None:
        raise NotFoundError("Hold not found.")
    return _hold_out(*row._tuple())


def _status_filter(status: HoldListStatus) -> list[ColumnElement[bool]]:
    if status == "waiting":
        return [Hold.status == "waiting"]
    if status == "ready":
        return [availability.is_live_ready()]
    if status == "open":
        return [_is_open()]
    if status == "closed":
        return [or_(Hold.status.in_(_CLOSED_STATUSES), availability.is_lapsed())]
    return []


def _order() -> list[ColumnElement[Any]]:
    """Ready holds first, the soonest pick-up first; then waiting holds in line order; then
    closed holds, the most recently closed first.
    """
    rank = case((availability.is_live_ready(), 0), (Hold.status == "waiting", 1), else_=2)
    open_order = case(
        (availability.is_live_ready(), Hold.pickup_by), (Hold.status == "waiting", Hold.placed_at)
    )
    closed_order = func.coalesce(Hold.closed_at, Hold.pickup_by)
    return [rank, open_order.asc(), closed_order.desc(), Hold.id.expression]


async def list_holds(
    session: AsyncSession,
    *,
    status: HoldListStatus,
    book_id: uuid.UUID | None = None,
    member_id: uuid.UUID | None = None,
    limit: int,
    offset: int,
) -> Page[HoldOut]:
    conditions = _status_filter(status)
    if book_id is not None:
        conditions.append(Hold.book_id == book_id)
    if member_id is not None:
        conditions.append(Hold.member_id == member_id)

    total = await session.scalar(select(func.count()).select_from(Hold).where(*conditions))
    rows = await session.execute(
        _hold_statement().where(*conditions).order_by(*_order()).limit(limit).offset(offset)
    )
    items = [_hold_out(*row) for row in rows.tuples()]
    return Page(items=items, total=total or 0, limit=limit, offset=offset)


async def open_hold(
    session: AsyncSession, *, book_id: uuid.UUID, member_id: uuid.UUID
) -> HoldOut | None:
    """The member's open hold on the book, or None."""
    row = (
        await session.execute(
            _hold_statement().where(
                Hold.book_id == book_id, Hold.member_id == member_id, _is_open()
            )
        )
    ).one_or_none()
    return _hold_out(*row._tuple()) if row is not None else None


async def waiting_count(session: AsyncSession, book_id: uuid.UUID) -> int:
    """How many members are in line for the book."""
    count = await session.scalar(
        select(func.count()).where(Hold.book_id == book_id, Hold.status == "waiting")
    )
    return count or 0


async def held_for(session: AsyncSession, copy_id: uuid.UUID) -> HeldFor | None:
    """Who the copy is set aside for and until when, while a ready hold sets it aside."""
    row = (
        await session.execute(
            select(Hold.member_id, Member.full_name, Hold.pickup_by)
            .join(Member, Member.id == Hold.member_id)
            .where(Hold.copy_id == copy_id, availability.is_live_ready())
        )
    ).one_or_none()
    if row is None:
        return None
    member_id, full_name, pickup_by = row._tuple()
    if pickup_by is None:
        return None
    return HeldFor(member=MemberRef(id=member_id, full_name=full_name), pickup_by=pickup_by)


# Activity


@dataclass(frozen=True)
class _HoldFacts:
    """What an activity event about a hold names."""

    id: uuid.UUID
    book_id: uuid.UUID
    member_id: uuid.UUID
    copy_id: uuid.UUID | None
    title: str
    member_name: str
    code: str | None


async def _facts(session: AsyncSession, hold_id: uuid.UUID) -> _HoldFacts:
    row = (
        await session.execute(
            select(
                Hold.id,
                Hold.book_id,
                Hold.member_id,
                Hold.copy_id,
                Book.title,
                Member.full_name,
                Copy.code,
            )
            .join(Book, Book.id == Hold.book_id)
            .join(Member, Member.id == Hold.member_id)
            .outerjoin(Copy, Copy.id == Hold.copy_id)
            .where(Hold.id == hold_id)
        )
    ).one()
    return _HoldFacts(*row._tuple())


def _record(
    session: AsyncSession,
    action: activity.ActivityAction,
    facts: _HoldFacts,
    summary: str,
    *,
    via: ActivityVia,
    actor: User | None,
    **details: Any,
) -> None:
    activity.record(
        session,
        action=action,
        entity_type="hold",
        entity_id=facts.id,
        summary=summary,
        details={
            "book_id": str(facts.book_id),
            "member_id": str(facts.member_id),
            "copy_id": str(facts.copy_id) if facts.copy_id else None,
            **details,
        },
        via=via,
        actor=actor,
    )


# Settling a book's line


def pickup_by_for(hold_pickup_days: int) -> datetime:
    """The end of the UTC day hold_pickup_days from today."""
    today = datetime.now(UTC).date()
    return datetime.combine(today + timedelta(days=hold_pickup_days), _END_OF_DAY)


async def settle_book(
    session: AsyncSession,
    book_id: uuid.UUID,
    *,
    hold_pickup_days: int,
    via: ActivityVia = "ui",
    actor: User | None,
) -> None:
    """Brings the book's holds in step with its copies, in the caller's transaction: ready holds
    past their pick-up time expire, then each free copy, lowest code first, is set aside for the
    oldest waiting hold. The caller commits.
    """
    await lock_book_line(session, book_id)

    expired = await session.scalars(
        update(Hold)
        .where(Hold.book_id == book_id, availability.is_lapsed())
        .values(status="expired", closed_at=func.now())
        .returning(Hold.id)
        .execution_options(synchronize_session=False)
    )
    for hold_id in expired.all():
        facts = await _facts(session, hold_id)
        _record(
            session,
            "hold.expired",
            facts,
            activity.hold_expired(facts.title, facts.code or "", facts.member_name),
            via=via,
            actor=actor,
        )

    pickup_by = pickup_by_for(hold_pickup_days)
    while True:
        next_hold = await session.scalar(
            select(Hold.id)
            .where(Hold.book_id == book_id, Hold.status == "waiting")
            .order_by(Hold.placed_at, Hold.id)
            .limit(1)
        )
        if next_hold is None:
            return
        free_copy = await session.scalar(
            select(Copy.id)
            .where(Copy.book_id == book_id, availability.is_free())
            # CP-0999 before CP-1000 before CP-10000.
            .order_by(func.length(Copy.code), Copy.code)
            .limit(1)
        )
        if free_copy is None:
            return
        await session.execute(
            update(Hold)
            .where(Hold.id == next_hold)
            .values(status="ready", copy_id=free_copy, ready_at=func.now(), pickup_by=pickup_by)
            .execution_options(synchronize_session=False)
        )
        facts = await _facts(session, next_hold)
        _record(
            session,
            "hold.ready",
            facts,
            activity.hold_ready(facts.title, facts.code or "", facts.member_name, pickup_by.date()),
            via=via,
            actor=actor,
            pickup_by=pickup_by.isoformat(),
        )


async def fulfil(
    session: AsyncSession,
    *,
    book_id: uuid.UUID,
    member_id: uuid.UUID,
    loan_id: uuid.UUID,
    copy_id: uuid.UUID,
    hold_pickup_days: int,
    via: ActivityVia = "ui",
    actor: User | None,
) -> None:
    """Closes the member's open hold on the book, if any, as fulfilled by the loan. When the hold
    was ready on another copy than the one borrowed, that copy goes to the next in line. Runs
    inside a borrow, after settle_book, so the book's line is locked; the caller commits.
    """
    fulfilled = (
        await session.execute(
            update(Hold)
            .where(
                Hold.book_id == book_id,
                Hold.member_id == member_id,
                Hold.status.in_(OPEN_HOLD_STATUSES),
            )
            .values(status="fulfilled", loan_id=loan_id, closed_at=func.now())
            .returning(Hold.id, Hold.copy_id)
            .execution_options(synchronize_session=False)
        )
    ).one_or_none()
    if fulfilled is None:
        return
    hold_id, held_copy = fulfilled._tuple()

    facts = await _facts(session, hold_id)
    code = await session.scalar(select(Copy.code).where(Copy.id == copy_id))
    _record(
        session,
        "hold.fulfilled",
        facts,
        activity.hold_fulfilled(facts.title, code or "", facts.member_name),
        via=via,
        actor=actor,
        loan_id=str(loan_id),
    )
    if held_copy is not None and held_copy != copy_id:
        await settle_book(session, book_id, hold_pickup_days=hold_pickup_days, via=via, actor=actor)


# Placing and cancelling


async def place(
    session: AsyncSession,
    *,
    book_id: uuid.UUID,
    member_id: uuid.UUID,
    max_open_holds: int,
    hold_pickup_days: int,
    via: ActivityVia = "ui",
    actor: User | None,
) -> HoldOut:
    """Puts the member at the end of the book's line. Refused, in this order: book not found
    (404), book_archived, member not found (404), already_borrowed (the member has a copy of the
    book on loan), hold_exists (they already have an open hold on it), copy_available (a copy is
    on the shelf: borrow it instead), hold_limit_reached (they have max_open_holds open holds).
    """
    await lock_book_line(session, book_id)
    book = await session.get(Book, book_id, populate_existing=True)
    if book is None:
        raise NotFoundError("Book not found.")
    if book.archived_at is not None:
        raise _book_archived()
    # Locked until commit, so the same member's holds on other books are counted one at a time.
    member = await session.get(
        Member, member_id, populate_existing=True, with_for_update={"key_share": True}
    )
    if member is None or member.archived_at is not None:
        raise NotFoundError("Member not found.")
    title, member_name = book.title, member.full_name

    await settle_book(session, book_id, hold_pickup_days=hold_pickup_days, via=via, actor=actor)

    on_loan = (
        select(Loan.id)
        .join(Copy, Copy.id == Loan.copy_id)
        .where(Copy.book_id == book_id, Loan.member_id == member_id, Loan.returned_at.is_(None))
        .exists()
    )
    if await session.scalar(select(on_loan)):
        raise ConflictError(f"{member_name} already has {title} on loan.", code="already_borrowed")
    already_held = exists().where(
        Hold.book_id == book_id,
        Hold.member_id == member_id,
        Hold.status.in_(OPEN_HOLD_STATUSES),
    )
    if await session.scalar(select(already_held)):
        raise _hold_exists(member_name, title)
    free = exists().where(Copy.book_id == book_id, availability.is_free())
    if await session.scalar(select(free)):
        raise ConflictError(
            f"A copy of {title} is on the shelf now: borrow it instead of placing a hold.",
            code="copy_available",
        )
    open_holds = await session.scalar(
        # Open as people see it: a ready hold past its pick-up time no longer counts.
        select(func.count()).where(Hold.member_id == member_id, _is_open())
    )
    if (open_holds or 0) >= max_open_holds:
        raise ConflictError(
            f"{member_name} already has {open_holds} open holds, the most allowed.",
            code="hold_limit_reached",
        )

    # Placed at the moment of the insert rather than the transaction's start, so holds placed one
    # after another under the book's lock keep that order.
    hold = Hold(
        book_id=book_id, member_id=member_id, status="waiting", placed_at=func.clock_timestamp()
    )
    session.add(hold)
    await flush_or_raise(session, {OPEN_HOLD_PER_MEMBER_INDEX: _hold_exists(member_name, title)})
    placed = await get_hold(session, hold.id)
    _record(
        session,
        "hold.placed",
        await _facts(session, hold.id),
        activity.hold_placed(title, member_name, placed.position or 1),
        via=via,
        actor=actor,
    )
    await session.commit()
    return placed


async def cancel(
    session: AsyncSession,
    hold_id: uuid.UUID,
    *,
    member_id: uuid.UUID | None = None,
    hold_pickup_days: int,
    via: ActivityVia = "ui",
    actor: User | None,
) -> HoldOut:
    """Cancels an open hold, and a copy it set aside goes to the next in line. With member_id,
    another member's hold is not found, like a missing one. hold_closed when the hold is already
    fulfilled, cancelled or expired, including a ready hold past its pick-up time.
    """
    conditions = [Hold.id == hold_id]
    if member_id is not None:
        conditions.append(Hold.member_id == member_id)
    book_id = await session.scalar(select(Hold.book_id).where(*conditions))
    if book_id is None:
        raise NotFoundError("Hold not found.")

    await lock_book_line(session, book_id)
    # One conditional update, so a cancel and a fulfilment or an expiry cannot both happen.
    cancelled = await session.scalar(
        update(Hold)
        .where(Hold.id == hold_id, _is_open())
        .values(status="cancelled", closed_at=func.now())
        .returning(Hold.id)
        .execution_options(synchronize_session=False)
    )
    if cancelled is None:
        raise ConflictError("This hold is already closed.", code="hold_closed")

    facts = await _facts(session, hold_id)
    _record(
        session,
        "hold.cancelled",
        facts,
        activity.hold_cancelled(facts.title, facts.member_name),
        via=via,
        actor=actor,
    )
    await settle_book(session, book_id, hold_pickup_days=hold_pickup_days, via=via, actor=actor)
    await session.commit()
    return await get_hold(session, hold_id)


async def cancel_open_holds_of_book(
    session: AsyncSession, book_id: uuid.UUID, *, via: ActivityVia = "ui", actor: User | None
) -> None:
    """Cancels every open hold on a book that leaves the catalog. The caller holds the book's
    lock and commits.
    """
    cancelled = await session.scalars(
        update(Hold)
        .where(Hold.book_id == book_id, Hold.status.in_(OPEN_HOLD_STATUSES))
        .values(status="cancelled", closed_at=func.now())
        .returning(Hold.id)
        .execution_options(synchronize_session=False)
    )
    for hold_id in cancelled.all():
        facts = await _facts(session, hold_id)
        _record(
            session,
            "hold.cancelled",
            facts,
            activity.hold_cancelled(facts.title, facts.member_name),
            via=via,
            actor=actor,
            reason="book_removed",
        )


# The sweep


async def books_to_settle(session: AsyncSession) -> list[uuid.UUID]:
    """Books with a ready hold past its pick-up time, or with a waiting hold and a free copy."""
    lapsed = select(Hold.book_id).where(availability.is_lapsed())
    free_copy = exists().where(Copy.book_id == Hold.book_id, availability.is_free())
    promotable = select(Hold.book_id).where(Hold.status == "waiting", free_copy)
    return list(await session.scalars(union(lapsed, promotable)))


async def sweep(session: AsyncSession, *, hold_pickup_days: int) -> int:
    """Settles every book that needs it, each in its own transaction, as the system. A failure
    for one book is logged and rolled back, and the other books are still settled. Returns how
    many books were settled.
    """
    book_ids = await books_to_settle(session)
    await session.commit()
    settled = 0
    for book_id in book_ids:
        try:
            await settle_book(
                session, book_id, hold_pickup_days=hold_pickup_days, via="system", actor=None
            )
            await session.commit()
        except Exception as exc:
            await session.rollback()
            log.error("hold_sweep_book_failed", book_id=str(book_id), exc_info=exc)
            continue
        settled += 1
    return settled


async def run_sweeps(
    sessions: Callable[[], AbstractAsyncContextManager[AsyncSession]],
    *,
    every_seconds: float,
    hold_pickup_days: int,
) -> None:
    """Sweeps every every_seconds until cancelled, each time in a new session. A sweep that fails
    as a whole, such as while the database is unreachable, is logged and tried again next time.
    """
    while True:
        await asyncio.sleep(every_seconds)
        try:
            async with sessions() as session:
                settled = await sweep(session, hold_pickup_days=hold_pickup_days)
        except Exception as exc:
            log.error("hold_sweep_failed", exc_info=exc)
            continue
        if settled:
            log.info("hold_sweep", books_settled=settled)
