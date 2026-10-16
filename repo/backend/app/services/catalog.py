"""Books and their copies: search, detail, add, edit, delete or archive, and adding copies.

Availability is counted when reading, never stored, by the one free-copy rule
(app.services.availability): a copy on loan or set aside for a member's hold is not available.
Archived books and archived copies are out of circulation: they are not listed or counted.
"""

import uuid
from typing import Any, Literal

from sqlalchemy import ColumnElement, Label, and_, exists, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.config import DEFAULT_HOLD_PICKUP_DAYS
from app.core.exceptions import ConflictError, NotFoundError
from app.db.errors import flush_or_raise
from app.models import COPY_CODE_SEQUENCE, ActivityVia, Book, Copy, Hold, Loan, Member, User
from app.models.book import ACTIVE_ISBN_INDEX
from app.models.copy import format_copy_code
from app.schemas.books import (
    Availability,
    BookCreate,
    BookDetail,
    BookSort,
    BookSummary,
    BookUpdate,
    CopyOut,
    LoanBrief,
)
from app.schemas.common import Page
from app.schemas.loans import HeldFor
from app.schemas.members import MemberRef
from app.services import activity, availability, holds
from app.services.circulation import is_overdue
from app.services.isbn import isbn_search_fragment
from app.services.text_search import contains, search_term

DeleteOutcome = Literal["deleted", "archived"]


def _isbn_taken() -> ConflictError:
    return ConflictError("Another book in the catalog already has this ISBN.", code="isbn_taken")


def _book_archived() -> ConflictError:
    return ConflictError("This book is archived and cannot be changed.", code="book_archived")


def _book_has_active_loans() -> ConflictError:
    return ConflictError(
        "A copy of this book is on loan. Return it before deleting the book.",
        code="book_has_active_loans",
    )


# Queries


def _in_circulation() -> ColumnElement[bool]:
    return and_(Copy.book_id == Book.id, Copy.archived_at.is_(None))


def _has_available_copy() -> ColumnElement[bool]:
    return exists().where(_in_circulation(), availability.is_free()).correlate(Book)


def _availability_columns() -> tuple[Label[int], Label[int]]:
    """Counts of the book's copies in circulation, and of those free to borrow now."""
    total = select(func.count()).where(_in_circulation()).correlate(Book).scalar_subquery()
    available = (
        select(func.count())
        .where(_in_circulation(), availability.is_free())
        .correlate(Book)
        .scalar_subquery()
    )
    return total.label("copies_total"), available.label("copies_available")


def _book_has_loans(book_id: Any) -> ColumnElement[bool]:
    return (
        select(Loan.id).join(Copy, Copy.id == Loan.copy_id).where(Copy.book_id == book_id).exists()
    )


def _search_condition(q: str | None) -> ColumnElement[bool] | None:
    """Case-insensitive substring match on title or author, or a match inside the ISBN when
    the term looks like part of one ("978-0441" matches 9780441172719).
    """
    term = search_term(q)
    if term is None:
        return None
    conditions = [contains(Book.title, term), contains(Book.author, term)]
    fragment = isbn_search_fragment(term)
    if fragment is not None:
        conditions.append(Book.isbn.contains(fragment, autoescape=True))
    return or_(*conditions)


def _order(sort: BookSort) -> list[ColumnElement[Any]]:
    """Each order ends with the title and the id, so ties and pages are stable."""
    ties = [func.lower(Book.title), Book.id.expression]
    if sort == "author":
        return [func.lower(Book.author), *ties]
    if sort == "year_desc":
        return [Book.published_year.desc().nulls_last(), *ties]
    if sort == "recent":
        return [Book.created_at.desc(), *ties]
    return ties


def availability_of(copies_total: int, copies_available: int) -> Availability:
    if copies_total == 0:
        return "no_copies"
    return "available" if copies_available > 0 else "all_borrowed"


def _summary(book: Book, copies_total: int, copies_available: int) -> BookSummary:
    return BookSummary(
        id=book.id,
        title=book.title,
        author=book.author,
        isbn=book.isbn,
        category=book.category,
        published_year=book.published_year,
        copies_total=copies_total,
        copies_available=copies_available,
        availability=availability_of(copies_total, copies_available),
    )


async def list_books(
    session: AsyncSession,
    *,
    q: str | None,
    category: str | None = None,
    available_only: bool = False,
    sort: BookSort = "title",
    limit: int,
    offset: int,
) -> Page[BookSummary]:
    """category matches the whole category name, ignoring letter case. available_only keeps
    books with at least one copy on the shelf: neither on loan nor held for a member. recent puts
    the books added most recently first.
    """
    conditions: list[ColumnElement[bool]] = [Book.archived_at.is_(None)]
    search = _search_condition(q)
    if search is not None:
        conditions.append(search)
    category = search_term(category)
    if category is not None:
        conditions.append(func.lower(Book.category) == category.lower())
    if available_only:
        conditions.append(_has_available_copy())

    total = await session.scalar(select(func.count()).select_from(Book).where(*conditions))
    rows = await session.execute(
        select(Book, *_availability_columns())
        .where(*conditions)
        .order_by(*_order(sort))
        .limit(limit)
        .offset(offset)
        .execution_options(populate_existing=True)
    )
    items = [_summary(*row._tuple()) for row in rows]
    return Page(items=items, total=total or 0, limit=limit, offset=offset)


async def list_categories(session: AsyncSession) -> list[str]:
    """The categories of the books in the catalog, alphabetically."""
    rows = await session.scalars(
        select(Book.category)
        .where(Book.archived_at.is_(None), Book.category.is_not(None))
        .distinct()
        .order_by(Book.category)
    )
    return [category for category in rows if category]


async def get_book_detail(
    session: AsyncSession,
    book_id: uuid.UUID,
    *,
    show_borrowers: bool = True,
    member_id: uuid.UUID | None = None,
) -> BookDetail:
    """Archived books stay readable here, marked archived. Without show_borrowers, a borrowed
    copy shows only when it is due back, and a held copy only that it is held, never who has it
    or who it is set aside for (what members see). With member_id, my_hold is that member's
    open hold on the book.
    """
    found = (
        await session.execute(
            select(
                Book,
                *_availability_columns(),
                _book_has_loans(Book.id).label("has_loan_history"),
            )
            .where(Book.id == book_id)
            .execution_options(populate_existing=True)
        )
    ).one_or_none()
    if found is None:
        raise NotFoundError("Book not found.")
    book, copies_total, copies_available, has_loan_history = found._tuple()

    ready = aliased(Hold)
    holder = aliased(Member)
    copy_rows = await session.execute(
        select(Copy, Loan, Member.full_name, is_overdue(), ready, holder.full_name)
        .outerjoin(Loan, and_(Loan.copy_id == Copy.id, Loan.returned_at.is_(None)))
        .outerjoin(Member, Member.id == Loan.member_id)
        .outerjoin(ready, and_(ready.copy_id == Copy.id, availability.is_live_ready(ready)))
        .outerjoin(holder, holder.id == ready.member_id)
        .where(Copy.book_id == book.id, Copy.archived_at.is_(None))
        # CP-0999 before CP-1000 before CP-10000.
        .order_by(func.length(Copy.code), Copy.code)
        .execution_options(populate_existing=True)
    )
    copies = [
        _copy_out(
            copy,
            loan,
            member_name,
            bool(overdue),
            _held_for(hold, holder_name),
            show_borrower=show_borrowers,
        )
        for copy, loan, member_name, overdue, hold, holder_name in copy_rows.tuples()
    ]
    my_hold = None
    if member_id is not None:
        my_hold = await holds.open_hold(session, book_id=book.id, member_id=member_id)
    return BookDetail(
        **_summary(book, copies_total, copies_available).model_dump(),
        description=book.description,
        has_loan_history=has_loan_history,
        archived=book.archived_at is not None,
        created_at=book.created_at,
        updated_at=book.updated_at,
        copies=copies,
        holds_waiting=await holds.waiting_count(session, book.id),
        my_hold=my_hold,
    )


def _held_for(hold: Hold | None, member_name: str | None) -> HeldFor | None:
    if hold is None or member_name is None or hold.pickup_by is None:
        return None
    return HeldFor(
        member=MemberRef(id=hold.member_id, full_name=member_name), pickup_by=hold.pickup_by
    )


def _copy_out(
    copy: Copy,
    loan: Loan | None,
    member_name: str | None,
    overdue: bool,
    held: HeldFor | None,
    *,
    show_borrower: bool,
) -> CopyOut:
    if loan is None or member_name is None:
        if held is not None:
            return CopyOut(
                id=copy.id,
                code=copy.code,
                status="held",
                due_at=None,
                active_loan=None,
                held_for=held if show_borrower else None,
            )
        return CopyOut(
            id=copy.id,
            code=copy.code,
            status="available",
            due_at=None,
            active_loan=None,
            held_for=None,
        )
    brief = LoanBrief(
        id=loan.id,
        member=MemberRef(id=loan.member_id, full_name=member_name),
        borrowed_at=loan.borrowed_at,
        due_at=loan.due_at,
        is_overdue=overdue,
    )
    return CopyOut(
        id=copy.id,
        code=copy.code,
        status="borrowed",
        due_at=loan.due_at,
        active_loan=brief if show_borrower else None,
        held_for=None,
    )


# Changes


async def _ensure_isbn_free(
    session: AsyncSession, isbn: str, *, except_book_id: uuid.UUID | None = None
) -> None:
    taken = exists().where(Book.isbn == isbn, Book.archived_at.is_(None))
    if except_book_id is not None:
        taken = taken.where(Book.id != except_book_id)
    if await session.scalar(select(taken)):
        raise _isbn_taken()


async def _get_book_for_change(session: AsyncSession, book_id: uuid.UUID) -> Book:
    """Loads the book and locks its row until commit, so changes to one book run one at a time."""
    book = await session.get(Book, book_id, with_for_update=True, populate_existing=True)
    if book is None:
        raise NotFoundError("Book not found.")
    return book


async def allocate_copy_codes(session: AsyncSession, count: int) -> list[str]:
    """Takes the next numbers from the copy code sequence: CP-0001, CP-0002, ..."""
    numbers = await session.scalars(
        select(COPY_CODE_SEQUENCE.next_value()).select_from(func.generate_series(1, count))
    )
    return [format_copy_code(number) for number in sorted(numbers)]


async def _add_copies(session: AsyncSession, book_id: uuid.UUID, count: int) -> list[str]:
    codes = await allocate_copy_codes(session, count)
    session.add_all(Copy(book_id=book_id, code=code) for code in codes)
    return codes


async def create_book(
    session: AsyncSession,
    data: BookCreate,
    *,
    via: ActivityVia = "ui",
    actor: User | None,
) -> BookDetail:
    """Adds the book together with its first copies."""
    if data.isbn is not None:
        await _ensure_isbn_free(session, data.isbn)

    book = Book(**data.model_dump(exclude={"copies"}))
    session.add(book)
    await flush_or_raise(session, {ACTIVE_ISBN_INDEX: _isbn_taken()})
    codes = await _add_copies(session, book.id, data.copies)
    activity.record(
        session,
        action="book.created",
        entity_type="book",
        entity_id=book.id,
        summary=activity.book_created(book.title, book.author, codes),
        details={"isbn": book.isbn, "copies": codes},
        via=via,
        actor=actor,
    )
    await session.commit()
    return await get_book_detail(session, book.id)


async def update_book(
    session: AsyncSession,
    book_id: uuid.UUID,
    data: BookUpdate,
    *,
    via: ActivityVia = "ui",
    actor: User | None,
) -> BookDetail:
    """Applies the fields present in the request. An edit that changes nothing records nothing."""
    book = await _get_book_for_change(session, book_id)
    if book.archived_at is not None:
        raise _book_archived()

    changes = {
        field: {"from": getattr(book, field), "to": value}
        for field, value in data.model_dump(exclude_unset=True).items()
        if getattr(book, field) != value
    }
    if not changes:
        await session.commit()
        return await get_book_detail(session, book.id)

    new_isbn = changes.get("isbn", {}).get("to")
    if new_isbn is not None:
        await _ensure_isbn_free(session, new_isbn, except_book_id=book.id)
    for field, change in changes.items():
        setattr(book, field, change["to"])
    await flush_or_raise(session, {ACTIVE_ISBN_INDEX: _isbn_taken()})
    activity.record(
        session,
        action="book.updated",
        entity_type="book",
        entity_id=book.id,
        summary=activity.book_updated(book.title, list(changes)),
        details={"changes": changes},
        via=via,
        actor=actor,
    )
    await session.commit()
    return await get_book_detail(session, book.id)


async def delete_book(
    session: AsyncSession,
    book_id: uuid.UUID,
    *,
    via: ActivityVia = "ui",
    actor: User | None,
) -> DeleteOutcome:
    """Deletes a book that never had a loan, archives one with loan history, and refuses while
    a copy is on loan. Deleting an archived book again changes nothing. Open holds on a book that
    leaves the catalog are cancelled.
    """
    # Before the book's row is locked, as every change to the book's holds does.
    await holds.lock_book_line(session, book_id)
    book = await _get_book_for_change(session, book_id)
    if book.archived_at is not None:
        await session.commit()
        return "archived"

    book_copies = select(Copy.id).where(Copy.book_id == book.id)
    on_loan = exists().where(Loan.copy_id.in_(book_copies), Loan.returned_at.is_(None))
    if await session.scalar(select(on_loan)):
        raise _book_has_active_loans()

    title, isbn = book.title, book.isbn
    await holds.cancel_open_holds_of_book(session, book.id, via=via, actor=actor)
    if await session.scalar(select(_book_has_loans(book.id))):
        book.archived_at = func.now()
        await session.execute(
            update(Copy)
            .where(Copy.book_id == book.id, Copy.archived_at.is_(None))
            .values(archived_at=func.now())
            .execution_options(synchronize_session=False)
        )
        outcome: DeleteOutcome = "archived"
        action: activity.ActivityAction = "book.archived"
        summary = activity.book_archived(title)
    else:
        # Its copies go with it (ON DELETE CASCADE). A loan that started in the meantime makes
        # the database refuse, which is reported as the copy being on loan.
        await session.delete(book)
        outcome, action, summary = "deleted", "book.deleted", activity.book_deleted(title)

    await flush_or_raise(session, {"fk_loans_copy_id_copies": _book_has_active_loans()})
    activity.record(
        session,
        action=action,
        entity_type="book",
        entity_id=book_id,
        summary=summary,
        details={"title": title, "isbn": isbn},
        via=via,
        actor=actor,
    )
    await session.commit()
    return outcome


async def add_copies(
    session: AsyncSession,
    book_id: uuid.UUID,
    count: int,
    *,
    hold_pickup_days: int = DEFAULT_HOLD_PICKUP_DAYS,
    via: ActivityVia = "ui",
    actor: User | None,
) -> BookDetail:
    """Adds copies, then settles the book's holds: the new copies are set aside for the members
    in line, oldest hold first.
    """
    # Before the book's row is locked, as every change to the book's holds does.
    await holds.lock_book_line(session, book_id)
    book = await _get_book_for_change(session, book_id)
    if book.archived_at is not None:
        raise _book_archived()

    codes = await _add_copies(session, book.id, count)
    activity.record(
        session,
        action="copy.added",
        entity_type="book",
        entity_id=book.id,
        summary=activity.copies_added(book.title, codes),
        details={"copies": codes},
        via=via,
        actor=actor,
    )
    await session.flush()
    await holds.settle_book(
        session, book.id, hold_pickup_days=hold_pickup_days, via=via, actor=actor
    )
    await session.commit()
    return await get_book_detail(session, book.id)
