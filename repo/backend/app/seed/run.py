"""Stores a simulated history in the database, and keeps the demo sign-in accounts working.

Rows are written with bulk inserts, so a full library takes seconds. Copy codes come from the
same sequence the application uses, in the order the copies arrived, and every change has its
activity event, written by the member of staff on duty through the web app.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, time
from typing import Any

from sqlalchemy import ColumnElement, delete, exists, func, insert, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ActivityEvent, Book, Copy, Loan, Member, User
from app.seed.simulation import DEMO_MEMBER, GeneratorOptions, History, simulate
from app.services import activity, auth
from app.services.catalog import allocate_copy_codes


@dataclass(frozen=True)
class SeedSummary:
    titles: int
    copies: int
    members: int
    loans: int
    active: int
    overdue: int
    isbns: int
    demo_member: str


async def seed(
    session: AsyncSession, options: GeneratorOptions, *, reset: bool = False
) -> SeedSummary | None:
    """Generates the library and ensures the demo accounts, and commits. Without reset it only
    fills a library that has no books or members yet (the demo accounts' own records do not
    count) and returns None otherwise. With reset it first deletes the library's data.
    """
    if not reset and await session.scalar(select(_has_library_data())):
        await ensure_demo_accounts(session)
        return None

    history = simulate(options)
    previous_demo_record = await _reset_library(session) if reset else None
    await _store(session, history)
    await session.commit()
    await ensure_demo_accounts(session)
    if previous_demo_record is not None:
        await _delete_if_unused(session, previous_demo_record)
        await session.commit()
    return _summary(history)


async def ensure_demo_accounts(session: AsyncSession) -> None:
    """The demo sign-in accounts. The member account signs in as the generated demo member when
    that record exists and no one signs in as it yet, also when the account was created earlier
    with a member record of its own.
    """
    await auth.ensure_demo_user(session, "staff")
    demo_member = await session.scalar(
        select(Member).where(
            func.lower(Member.email) == str(DEMO_MEMBER.email),
            ~exists().where(User.member_id == Member.id),
        )
    )
    account = await auth.ensure_demo_user(session, "member", member=demo_member)
    if demo_member is not None and account.member_id != demo_member.id:
        account.member_id = demo_member.id
        account.display_name = demo_member.full_name
        await session.commit()


def _has_library_data() -> ColumnElement[bool]:
    # A demo sign-in before the seed gives the demo member a record of its own; that is not data.
    demo_records = select(User.member_id).where(User.is_demo, User.member_id.is_not(None))
    return (
        select(Book.id).exists() | select(Member.id).where(Member.id.not_in(demo_records)).exists()
    )


async def _reset_library(session: AsyncSession) -> uuid.UUID | None:
    """Deletes the activity, holds, loans and their renewals, copies, books and every member
    nobody signs in as, and restarts the copy codes at CP-0001. Users and their sessions stay.

    Returns the member record the demo member account signs in as. Its address is cleared so the
    new demo member can take it; once the account has moved over, the old record is deleted. When
    the new demo member has the same id, storing it overwrites the record instead.
    """
    await session.execute(
        text("TRUNCATE activity_events, renewals, holds, loans, copies, books RESTART IDENTITY")
    )
    signed_in = select(User.member_id).where(User.member_id.is_not(None))
    await session.execute(delete(Member).where(Member.id.not_in(signed_in)))
    await session.execute(text("ALTER SEQUENCE copy_code_seq RESTART WITH 1"))
    demo_record: uuid.UUID | None = await session.scalar(
        select(User.member_id).where(User.is_demo, User.role == "member")
    )
    if demo_record is not None:
        await session.execute(update(Member).where(Member.id == demo_record).values(email=None))
    return demo_record


async def _delete_if_unused(session: AsyncSession, member_id: uuid.UUID) -> None:
    await session.execute(
        delete(Member).where(
            Member.id == member_id,
            ~exists().where(User.member_id == Member.id),
            ~exists().where(Loan.member_id == Member.id),
        )
    )


async def _store(session: AsyncSession, history: History) -> None:
    copy_count = sum(len(book.copy_ids) for book in history.books)
    codes = iter(await allocate_copy_codes(session, copy_count))
    code_of: dict[uuid.UUID, str] = {}
    books: list[dict[str, Any]] = []
    copies: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []

    for book in history.books:
        entry = book.entry
        book_codes = [next(codes) for _ in book.copy_ids]
        code_of.update(zip(book.copy_ids, book_codes, strict=True))
        books.append(
            {
                "id": book.id,
                "title": entry.title,
                "author": entry.author,
                "isbn": entry.isbn,
                "category": entry.category,
                "published_year": entry.published_year,
                "created_at": book.added_at,
                "updated_at": book.added_at,
            }
        )
        copies.extend(
            {
                "id": copy_id,
                "book_id": book.id,
                "code": code,
                "created_at": book.added_at,
                "updated_at": book.added_at,
            }
            for copy_id, code in zip(book.copy_ids, book_codes, strict=True)
        )
        events.append(
            _event(
                book.added_at,
                book.added_by,
                "book.created",
                "book",
                book.id,
                activity.book_created(entry.title, entry.author, book_codes),
                {"isbn": entry.isbn, "copies": book_codes},
            )
        )

    members: list[dict[str, Any]] = []
    for member in history.members:
        members.append(
            {
                "id": member.id,
                "full_name": member.full_name,
                "email": member.email,
                "joined_on": member.joined_at.date(),
                "created_at": member.joined_at,
                "updated_at": member.joined_at,
            }
        )
        events.append(
            _event(
                member.joined_at,
                member.added_by,
                "member.created",
                "member",
                member.id,
                activity.member_created(member.full_name),
                {"email": member.email},
            )
        )

    loans: list[dict[str, Any]] = []
    for loan in history.loans:
        code, title = code_of[loan.copy_id], loan.book.entry.title
        loans.append(
            {
                "id": loan.id,
                "copy_id": loan.copy_id,
                "member_id": loan.member.id,
                "borrowed_at": loan.borrowed_at,
                "due_at": loan.due_at,
                "returned_at": loan.returned_at,
                "created_at": loan.borrowed_at,
                "updated_at": loan.returned_at or loan.borrowed_at,
            }
        )
        ids = {
            "book_id": str(loan.book.id),
            "copy_id": str(loan.copy_id),
            "member_id": str(loan.member.id),
        }
        events.append(
            _event(
                loan.borrowed_at,
                loan.borrowed_by,
                "loan.borrowed",
                "loan",
                loan.id,
                activity.loan_borrowed(title, code, loan.member.full_name, loan.due_at.date()),
                {**ids, "due_at": loan.due_at.isoformat()},
            )
        )
        if loan.returned_at is not None and loan.returned_by is not None:
            events.append(
                _event(
                    loan.returned_at,
                    loan.returned_by,
                    "loan.returned",
                    "loan",
                    loan.id,
                    activity.loan_returned(title, code, loan.member.full_name),
                    ids,
                )
            )

    # The event ids follow the order in which things happened.
    events.sort(key=lambda event: event["occurred_at"])
    await session.execute(insert(Book), books)
    await session.execute(insert(Copy), copies)
    # The same seed gives the same ids, so after a reset the record the demo member account
    # still signs in as can be one of these members; it is overwritten, not added again.
    upsert = pg_insert(Member)
    fields = {name: upsert.excluded[name] for name in members[0] if name != "id"}
    await session.execute(
        upsert.on_conflict_do_update(
            index_elements=[Member.id], set_={**fields, "archived_at": None}
        ),
        members,
    )
    if loans:
        await session.execute(insert(Loan), loans)
    await session.execute(insert(ActivityEvent), events)


def _event(
    occurred_at: datetime,
    actor: str,
    action: activity.ActivityAction,
    entity_type: activity.EntityType,
    entity_id: uuid.UUID,
    summary: str,
    details: dict[str, Any],
) -> dict[str, Any]:
    """An activity event as recorded at the desk: a member of staff, through the web app."""
    return {
        "occurred_at": occurred_at,
        "actor": actor,
        "action": action,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "summary": summary,
        "details": details,
        "via": "ui",
    }


def _summary(history: History) -> SeedSummary:
    start_of_today = datetime.combine(history.today, time(tzinfo=UTC))
    active = [loan for loan in history.loans if loan.returned_at is None]
    return SeedSummary(
        titles=len(history.books),
        copies=sum(len(book.copy_ids) for book in history.books),
        members=len(history.members),
        loans=len(history.loans),
        active=len(active),
        overdue=sum(1 for loan in active if loan.due_at < start_of_today),
        isbns=history.isbns_kept,
        demo_member=history.demo_member.full_name,
    )
