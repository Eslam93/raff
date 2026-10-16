"""Borrowing, returning and renewing copies, and reading loans: the loans list, overdue loans
and loans due soon, and a copy found by its code. A borrow can also be checked without being
made, for a proposal that is confirmed later.

Overdue is derived when reading, by the database clock. The database allows one active loan
per copy (a partial unique index). Borrowing checks first so the usual case gets a clean error,
and a borrow that loses a race at the index gets the same copy_unavailable conflict. A borrow
also takes a share lock on the book's row: archiving or deleting a book locks that row for
update, so the borrow waits for it and then sees the outcome, and the archive in turn waits for a
borrow in progress and then sees its loan. Borrows of the same book do not wait for each other
at the book's row; they do wait for each other's work on the book's holds (app.services.holds).

Holds: a borrow settles the book's holds before its checks, refuses a copy set aside for another
member (copy_held), and fulfils the borrower's own open hold on the book. A return settles the
book's holds after it, so the copy goes to the first member in line. A renewal is one
conditional update on the loan's id, its unreturned state and the due date that was read, so two
renewals at once cannot both count.
"""

import re
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from sqlalchemy import (
    ColumnElement,
    Date,
    ScalarSelect,
    Select,
    and_,
    case,
    cast,
    func,
    or_,
    select,
    update,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import DEFAULT_HOLD_PICKUP_DAYS, DEFAULT_MAX_RENEWALS
from app.core.exceptions import ConflictError, NotFoundError, ValidationFailedError
from app.db.errors import flush_or_raise
from app.models import ActivityVia, Book, Copy, Loan, Member, Renewal, User
from app.models.copy import format_copy_code
from app.models.loan import ACTIVE_LOAN_PER_COPY_INDEX
from app.schemas.common import Page
from app.schemas.loans import BookRef, CopyLookup, CopyRef, HeldFor, LoanListStatus, LoanOut
from app.schemas.members import MemberRef
from app.services import activity, availability, holds
from app.services.text_search import contains, search_term

MAX_DAYS_UNTIL_DUE = 90
# A loan is due at the end of its due date, in UTC.
_END_OF_DAY = time(23, 59, 59, tzinfo=UTC)
# A copy code as people type or scan it: "CP-0012", "cp12", or the number alone.
_COPY_NUMBER = re.compile(r"(?:CP-?)?0*(\d{1,9})", re.IGNORECASE)


def is_overdue() -> ColumnElement[bool]:
    """True for an active loan past its due time, by the database clock."""
    return and_(Loan.returned_at.is_(None), Loan.due_at < func.now())


def _utc_date(moment: Any) -> ColumnElement[date]:
    return cast(func.timezone("UTC", moment), Date)


def days_overdue() -> ColumnElement[int]:
    """Whole days from the due date to today (UTC) for an overdue loan, and at least 1, so an
    overdue loan never shows 0. 0 for any other loan. By the database clock, like is_overdue.
    """
    days = _utc_date(func.now()) - _utc_date(Loan.due_at)
    return case((is_overdue(), func.greatest(days, 1)), else_=0)


def is_due_soon(days: int) -> ColumnElement[bool]:
    """True for an active loan that is not overdue and is due by the end of the day `days` days
    from today (UTC). With 3: due today, tomorrow, or in two or three days.
    """
    return and_(
        Loan.returned_at.is_(None),
        Loan.due_at >= func.now(),
        _utc_date(Loan.due_at) <= _utc_date(func.now()) + days,
    )


def today_utc() -> date:
    return datetime.now(UTC).date()


def due_at_for(due_date: date | None, *, today: date, loan_period_days: int) -> datetime:
    """The due time for a new loan. Without a date, the loan period applies."""
    if due_date is None:
        due_date = today + timedelta(days=loan_period_days)
    elif due_date <= today:
        raise ValidationFailedError.for_field(
            "due_date", "Choose a due date after today.", "due_date_not_in_future"
        )
    elif due_date > today + timedelta(days=MAX_DAYS_UNTIL_DUE):
        raise ValidationFailedError.for_field(
            "due_date",
            f"Choose a due date at most {MAX_DAYS_UNTIL_DUE} days from today.",
            "due_date_too_far",
        )
    return datetime.combine(due_date, _END_OF_DAY)


def renewed_due_at(due_at: datetime, *, today: date, loan_period_days: int) -> datetime:
    """The due time after a renewal: the later of today and the current due date, plus the loan
    period, at most 90 days from today, at the end of that day (UTC).
    """
    start = max(today, due_at.astimezone(UTC).date())
    due_date = min(
        start + timedelta(days=loan_period_days), today + timedelta(days=MAX_DAYS_UNTIL_DUE)
    )
    return datetime.combine(due_date, _END_OF_DAY)


def _copy_unavailable(code: str) -> ConflictError:
    return ConflictError(f"Copy {code} is already on loan.", code="copy_unavailable")


def _copy_held(code: str, held: HeldFor) -> ConflictError:
    until = activity.format_short_day(held.pickup_by.astimezone(UTC).date())
    return ConflictError(
        f"Copy {code} is held for {held.member.full_name} until {until}.", code="copy_held"
    )


def _book_archived() -> ConflictError:
    return ConflictError("This book is archived.", code="book_archived")


def _loan_already_returned() -> ConflictError:
    return ConflictError("This loan was already returned.", code="loan_already_returned")


@dataclass(frozen=True)
class BorrowCheck:
    """A borrow that passed its checks: what it lends, to whom, and until when."""

    copy: Copy
    book: Book
    member: Member
    due_at: datetime


async def check_borrow(
    session: AsyncSession,
    *,
    copy_id: uuid.UUID,
    member_id: uuid.UUID,
    due_date: date | None = None,
    loan_period_days: int,
    lock_book: bool = False,
) -> BorrowCheck:
    """Everything a borrow checks, without writing anything, with the same errors: the due
    date, the copy and its book in the catalog, the member not archived, the copy not on loan
    (copy_unavailable), and the copy not set aside for another member's hold (copy_held).
    With lock_book, the book's row is share-locked until the transaction ends, so a change to the
    book in progress finishes first and the check sees its outcome.
    """
    due_at = due_at_for(due_date, today=today_utc(), loan_period_days=loan_period_days)

    statement = (
        select(Copy, Book)
        .join(Book, Book.id == Copy.book_id)
        .where(Copy.id == copy_id)
        .execution_options(populate_existing=True)
    )
    if lock_book:
        statement = statement.with_for_update(read=True, of=Book)
    found = (await session.execute(statement)).one_or_none()
    if found is None:
        raise NotFoundError("Copy not found.")
    copy, book = found._tuple()
    if book.archived_at is not None or copy.archived_at is not None:
        raise _book_archived()

    member = await session.get(Member, member_id)
    if member is None or member.archived_at is not None:
        raise NotFoundError("Member not found.")

    if await session.scalar(select(availability.has_active_loan(copy.id))):
        raise _copy_unavailable(copy.code)
    held = await holds.held_for(session, copy.id)
    if held is not None and held.member.id != member.id:
        raise _copy_held(copy.code, held)
    return BorrowCheck(copy=copy, book=book, member=member, due_at=due_at)


async def first_available_copy(
    session: AsyncSession, book_id: uuid.UUID, *, member_id: uuid.UUID | None = None
) -> uuid.UUID:
    """What a borrow of "the book" lends: with member_id, the copy set aside for that member's
    hold if there is one, otherwise the book's first free copy by code. no_copy_available when
    there is neither.
    """
    book = await session.get(Book, book_id, populate_existing=True)
    if book is None:
        raise NotFoundError("Book not found.")
    if book.archived_at is not None:
        raise _book_archived()
    statement = select(Copy.id).where(Copy.book_id == book.id, Copy.archived_at.is_(None))
    # CP-0999 before CP-1000 before CP-10000.
    by_code = (func.length(Copy.code), Copy.code)
    if member_id is None:
        statement = statement.where(availability.is_free()).order_by(*by_code)
    else:
        mine = availability.is_held_for(Copy.id, member_id)
        statement = statement.where(or_(availability.is_free(), mine)).order_by(
            case((mine, 0), else_=1), *by_code
        )
    copy_id = await session.scalar(statement.limit(1))
    if copy_id is None:
        raise ConflictError(f"No copy of {book.title} is available now.", code="no_copy_available")
    return copy_id


async def borrow(
    session: AsyncSession,
    *,
    copy_id: uuid.UUID,
    member_id: uuid.UUID,
    due_date: date | None = None,
    loan_period_days: int,
    hold_pickup_days: int = DEFAULT_HOLD_PICKUP_DAYS,
    max_renewals: int = DEFAULT_MAX_RENEWALS,
    via: ActivityVia = "ui",
    actor: User | None,
) -> LoanOut:
    """Lends the copy. The book's holds are settled first, so a ready hold past its pick-up time
    no longer keeps the copy aside; then the borrower's own open hold on the book is fulfilled.
    """
    book_id = await session.scalar(select(Copy.book_id).where(Copy.id == copy_id))
    # An unknown copy is reported by the checks, in their usual order.
    if book_id is not None:
        await holds.settle_book(
            session, book_id, hold_pickup_days=hold_pickup_days, via=via, actor=actor
        )
    checked = await check_borrow(
        session,
        copy_id=copy_id,
        member_id=member_id,
        due_date=due_date,
        loan_period_days=loan_period_days,
        lock_book=True,
    )
    copy, book, member, due_at = checked.copy, checked.book, checked.member, checked.due_at

    loan = Loan(copy_id=copy.id, member_id=member.id, due_at=due_at)
    session.add(loan)
    await flush_or_raise(session, {ACTIVE_LOAN_PER_COPY_INDEX: _copy_unavailable(copy.code)})
    activity.record(
        session,
        action="loan.borrowed",
        entity_type="loan",
        entity_id=loan.id,
        summary=activity.loan_borrowed(book.title, copy.code, member.full_name, due_at.date()),
        details={
            "book_id": str(book.id),
            "copy_id": str(copy.id),
            "member_id": str(member.id),
            "due_at": due_at.isoformat(),
        },
        via=via,
        actor=actor,
    )
    await holds.fulfil(
        session,
        book_id=book.id,
        member_id=member.id,
        loan_id=loan.id,
        copy_id=copy.id,
        hold_pickup_days=hold_pickup_days,
        via=via,
        actor=actor,
    )
    await session.commit()
    return await get_loan(session, loan.id, max_renewals=max_renewals)


async def return_loan(
    session: AsyncSession,
    loan_id: uuid.UUID,
    *,
    hold_pickup_days: int = DEFAULT_HOLD_PICKUP_DAYS,
    max_renewals: int = DEFAULT_MAX_RENEWALS,
    via: ActivityVia = "ui",
    actor: User | None,
) -> LoanOut:
    """Returns the copy, then settles the book's holds: the copy is set aside for the first
    member in line, if there is one.
    """
    book_id = await session.scalar(
        select(Copy.book_id).join(Loan, Loan.copy_id == Copy.id).where(Loan.id == loan_id)
    )
    if book_id is None:
        raise NotFoundError("Loan not found.")
    # Before the loan's row is locked, as every change to the book's holds does.
    await holds.lock_book_line(session, book_id)
    # One conditional update, so two simultaneous returns cannot both succeed.
    returned = await session.scalar(
        update(Loan)
        .where(Loan.id == loan_id, Loan.returned_at.is_(None))
        .values(returned_at=func.now())
        .returning(Loan.id)
        .execution_options(synchronize_session=False)
    )
    if returned is None:
        raise _loan_already_returned()

    loan = await get_loan(session, loan_id, max_renewals=max_renewals)
    activity.record(
        session,
        action="loan.returned",
        entity_type="loan",
        entity_id=loan.id,
        summary=activity.loan_returned(loan.book.title, loan.copy_ref.code, loan.member.full_name),
        details={
            "book_id": str(loan.book.id),
            "copy_id": str(loan.copy_ref.id),
            "member_id": str(loan.member.id),
        },
        via=via,
        actor=actor,
    )
    await holds.settle_book(
        session, book_id, hold_pickup_days=hold_pickup_days, via=via, actor=actor
    )
    await session.commit()
    return loan


async def renew(
    session: AsyncSession,
    loan_id: uuid.UUID,
    *,
    member_id: uuid.UUID | None = None,
    loan_period_days: int,
    max_renewals: int,
    via: ActivityVia = "ui",
    actor: User | None,
) -> LoanOut:
    """Moves an active loan's due date (see renewed_due_at) and records the renewal. With
    member_id, another member's loan is not found, like a missing one. Refused with
    loan_already_returned, renewal_limit_reached (renewed max_renewals times already),
    book_has_holds (a member is waiting for the book), and loan_changed (renewed or returned by
    someone else in the meantime). An overdue loan can be renewed.
    """
    conditions = [Loan.id == loan_id]
    if member_id is not None:
        conditions.append(Loan.member_id == member_id)
    found = (
        await session.execute(
            select(
                Loan.due_at,
                Loan.returned_at,
                _renewals_count(),
                holds.has_waiting_holds(Copy.book_id),
                Copy.book_id,
            )
            .join(Copy, Copy.id == Loan.copy_id)
            .where(*conditions)
        )
    ).one_or_none()
    if found is None:
        raise NotFoundError("Loan not found.")
    due_at, returned_at, renewals, book_has_holds, book_id = found._tuple()
    if not book_has_holds:
        # The book's line lock, then a second look: a hold placed at the same moment either
        # committed first and blocks this renewal, or waits until it is done.
        await holds.lock_book_line(session, book_id)
        book_has_holds = bool(await session.scalar(select(holds.has_waiting_holds(book_id))))
    if returned_at is not None:
        raise _loan_already_returned()
    if renewals >= max_renewals:
        noun = "renewal" if max_renewals == 1 else "renewals"
        raise ConflictError(
            f"This loan cannot be renewed again: the limit is {max_renewals} {noun}.",
            code="renewal_limit_reached",
        )
    if book_has_holds:
        raise ConflictError(
            "A member is waiting for this book, so the loan cannot be renewed.",
            code="book_has_holds",
        )

    new_due_at = renewed_due_at(due_at, today=today_utc(), loan_period_days=loan_period_days)
    if new_due_at <= due_at:
        raise ConflictError(
            f"This loan is already due as late as a loan can be: {MAX_DAYS_UNTIL_DUE} days ahead.",
            code="renewal_not_needed",
        )
    # Conditional on the due date that was read, so of two renewals at once only one counts, and
    # a loan returned in the meantime is not renewed.
    renewed = await session.scalar(
        update(Loan)
        .where(Loan.id == loan_id, Loan.returned_at.is_(None), Loan.due_at == due_at)
        .values(due_at=new_due_at)
        .returning(Loan.id)
        .execution_options(synchronize_session=False)
    )
    if renewed is None:
        raise ConflictError(
            "This loan changed while it was being renewed. Look at it again.",
            code="loan_changed",
        )
    session.add(Renewal(loan_id=loan_id, previous_due_at=due_at, new_due_at=new_due_at))

    loan = await get_loan(session, loan_id, max_renewals=max_renewals)
    activity.record(
        session,
        action="loan.renewed",
        entity_type="loan",
        entity_id=loan.id,
        summary=activity.loan_renewed(
            loan.book.title,
            loan.copy_ref.code,
            loan.member.full_name,
            due_at.astimezone(UTC).date(),
            new_due_at.date(),
        ),
        details={
            "book_id": str(loan.book.id),
            "copy_id": str(loan.copy_ref.id),
            "member_id": str(loan.member.id),
            "previous_due_at": due_at.isoformat(),
            "due_at": new_due_at.isoformat(),
        },
        via=via,
        actor=actor,
    )
    await session.commit()
    return loan


# Copies by code


def normalize_copy_code(code: str) -> str:
    """The stored form of a typed or scanned code. Letter case does not matter, and a number,
    with or without the CP prefix, means that copy number: "12" and "cp-12" are CP-0012.
    """
    text = code.strip()
    number = _COPY_NUMBER.fullmatch(text)
    return format_copy_code(int(number.group(1))) if number else text.upper()


async def find_copy_by_code(
    session: AsyncSession, code: str, *, max_renewals: int = DEFAULT_MAX_RENEWALS
) -> CopyLookup:
    """The copy with this code, its book, its active loan, and who it is set aside for while a
    ready hold holds it. Archived copies are found too, marked archived.
    """
    normalized = normalize_copy_code(code)
    found = (
        await session.execute(
            select(Copy, Book)
            .join(Book, Book.id == Copy.book_id)
            .where(Copy.code == normalized)
            .execution_options(populate_existing=True)
        )
    ).one_or_none()
    if found is None:
        raise NotFoundError(f"No copy has the code {normalized}.")
    copy, book = found._tuple()

    on_loan = await _loans(
        session,
        Loan.copy_id == copy.id,
        Loan.returned_at.is_(None),
        order=Loan.due_at.asc(),
        limit=1,
        max_renewals=max_renewals,
    )
    active_loan = on_loan[0] if on_loan else None
    held = None if active_loan is not None else await holds.held_for(session, copy.id)
    return CopyLookup(
        copy=CopyRef(id=copy.id, code=copy.code),
        book=BookRef(id=book.id, title=book.title, author=book.author),
        status="borrowed" if active_loan is not None else "held" if held else "available",
        archived=copy.archived_at is not None or book.archived_at is not None,
        active_loan=active_loan,
        held_for=held,
    )


# Reading loans


def _with_loan_parts[T: tuple[Any, ...]](statement: Select[T]) -> Select[T]:
    """Joins each loan's copy, book and member."""
    return (
        statement.join(Copy, Copy.id == Loan.copy_id)
        .join(Book, Book.id == Copy.book_id)
        .join(Member, Member.id == Loan.member_id)
    )


def _renewals_count() -> ScalarSelect[int]:
    """How many times the loan was renewed."""
    return select(func.count()).where(Renewal.loan_id == Loan.id).correlate(Loan).scalar_subquery()


def _loan_statement() -> Select[tuple[Loan, str, uuid.UUID, str, str, str, bool, int, int, bool]]:
    return _with_loan_parts(
        select(
            Loan,
            Copy.code,
            Book.id,
            Book.title,
            Book.author,
            Member.full_name,
            is_overdue().label("is_overdue"),
            days_overdue().label("days_overdue"),
            _renewals_count().label("renewals"),
            holds.has_waiting_holds(Copy.book_id).label("book_has_holds"),
        )
    ).execution_options(populate_existing=True)


async def _loans(
    session: AsyncSession,
    *conditions: ColumnElement[bool],
    order: ColumnElement[Any],
    limit: int,
    offset: int = 0,
    max_renewals: int,
) -> list[LoanOut]:
    rows = await session.execute(
        _loan_statement().where(*conditions).order_by(order, Loan.id).limit(limit).offset(offset)
    )
    return [_loan_out(*row, max_renewals=max_renewals) for row in rows.tuples()]


async def get_loan(
    session: AsyncSession, loan_id: uuid.UUID, *, max_renewals: int = DEFAULT_MAX_RENEWALS
) -> LoanOut:
    row = (await session.execute(_loan_statement().where(Loan.id == loan_id))).one_or_none()
    if row is None:
        raise NotFoundError("Loan not found.")
    return _loan_out(*row._tuple(), max_renewals=max_renewals)


def _status_filter(status: LoanListStatus) -> tuple[list[ColumnElement[bool]], ColumnElement[Any]]:
    """Which loans a status lists, and in what order."""
    if status == "active":
        return [Loan.returned_at.is_(None)], Loan.due_at.asc()
    if status == "overdue":
        return [is_overdue()], Loan.due_at.asc()
    if status == "returned":
        return [Loan.returned_at.is_not(None)], Loan.returned_at.desc()
    return [], Loan.borrowed_at.desc()


def _search_condition(q: str | None) -> ColumnElement[bool] | None:
    """Case-insensitive substring match on the book's title or author, the member's name or the
    copy code.
    """
    term = search_term(q)
    if term is None:
        return None
    columns = (Book.title, Book.author, Member.full_name, Copy.code)
    return or_(*(contains(column, term) for column in columns))


async def list_loans(
    session: AsyncSession,
    *,
    status: LoanListStatus,
    q: str | None = None,
    member_id: uuid.UUID | None = None,
    book_id: uuid.UUID | None = None,
    limit: int,
    offset: int,
    max_renewals: int = DEFAULT_MAX_RENEWALS,
) -> Page[LoanOut]:
    """active and overdue: due soonest first. returned: most recently returned first. all: most
    recently borrowed first.
    """
    conditions, order = _status_filter(status)
    search = _search_condition(q)
    if search is not None:
        conditions.append(search)
    if member_id is not None:
        conditions.append(Loan.member_id == member_id)
    if book_id is not None:
        conditions.append(Copy.book_id == book_id)

    total = await session.scalar(
        _with_loan_parts(select(func.count()).select_from(Loan)).where(*conditions)
    )
    items = await _loans(
        session, *conditions, order=order, limit=limit, offset=offset, max_renewals=max_renewals
    )
    return Page(items=items, total=total or 0, limit=limit, offset=offset)


async def overdue_loans(
    session: AsyncSession, *, limit: int, max_renewals: int = DEFAULT_MAX_RENEWALS
) -> list[LoanOut]:
    """Overdue loans, longest overdue first."""
    return await _loans(
        session, is_overdue(), order=Loan.due_at.asc(), limit=limit, max_renewals=max_renewals
    )


async def loans_due_soon(
    session: AsyncSession, *, days: int, limit: int, max_renewals: int = DEFAULT_MAX_RENEWALS
) -> list[LoanOut]:
    """Loans due within the next `days` days and not overdue (see is_due_soon), soonest first."""
    return await _loans(
        session,
        is_due_soon(days),
        order=Loan.due_at.asc(),
        limit=limit,
        max_renewals=max_renewals,
    )


def _loan_out(
    loan: Loan,
    code: str,
    book_id: uuid.UUID,
    title: str,
    author: str,
    member_name: str,
    overdue: bool,
    days_late: int,
    renewals: int,
    book_has_holds: bool,
    *,
    max_renewals: int,
) -> LoanOut:
    active = loan.returned_at is None
    return LoanOut(
        id=loan.id,
        copy=CopyRef(id=loan.copy_id, code=code),
        book=BookRef(id=book_id, title=title, author=author),
        member=MemberRef(id=loan.member_id, full_name=member_name),
        borrowed_at=loan.borrowed_at,
        due_at=loan.due_at,
        returned_at=loan.returned_at,
        is_overdue=overdue,
        days_overdue=days_late,
        renewals=renewals,
        can_renew=active and renewals < max_renewals and not book_has_holds,
    )
