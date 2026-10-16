"""The activity record: one event per change, added to the same transaction as the change.

The summary sentences live here so the services and the development seed word them the same.
"""

import uuid
from collections.abc import Sequence
from datetime import date, datetime
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ActivityEvent, ActivityVia, User
from app.schemas.activity import ActivityOut

ActivityAction = Literal[
    "book.created",
    "book.updated",
    "book.archived",
    "book.deleted",
    "copy.added",
    "member.created",
    "loan.borrowed",
    "loan.returned",
    "loan.renewed",
    "hold.placed",
    "hold.ready",
    "hold.expired",
    "hold.cancelled",
    "hold.fulfilled",
]
EntityType = Literal["book", "member", "loan", "hold"]

_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def record(
    session: AsyncSession,
    *,
    action: ActivityAction,
    entity_type: EntityType,
    entity_id: uuid.UUID | None,
    summary: str,
    details: dict[str, Any] | None = None,
    via: ActivityVia = "ui",
    actor: User | None = None,
    occurred_at: datetime | None = None,
) -> None:
    """Adds an event to the session. The caller's commit writes it together with the change.

    The actor is the signed-in user who acted; the event keeps their name as it was then. None
    means the system acted, such as the development seed.
    """
    event = ActivityEvent(
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        summary=summary,
        details=details or {},
        via=via,
        actor=actor.display_name if actor else None,
        actor_user_id=actor.id if actor else None,
    )
    if occurred_at is not None:
        event.occurred_at = occurred_at
    session.add(event)


async def list_recent(session: AsyncSession, *, limit: int) -> list[ActivityOut]:
    events = await session.scalars(
        select(ActivityEvent)
        .order_by(ActivityEvent.occurred_at.desc(), ActivityEvent.id.desc())
        .limit(limit)
    )
    return [ActivityOut.model_validate(event, from_attributes=True) for event in events]


# Summary sentences


def format_day(value: date) -> str:
    """3 Oct 2026, in English whatever the server locale."""
    return f"{value.day} {_MONTHS[value.month - 1]} {value.year}"


def format_short_day(value: date) -> str:
    """3 Oct, for a date in the next few days, in English whatever the server locale."""
    return f"{value.day} {_MONTHS[value.month - 1]}"


def format_month(value: date) -> str:
    """Oct 2026, in English whatever the server locale."""
    return f"{_MONTHS[value.month - 1]} {value.year}"


def _copies_phrase(codes: Sequence[str]) -> str:
    noun = "copy" if len(codes) == 1 else "copies"
    return f"{len(codes)} {noun} ({', '.join(codes)})"


def book_created(title: str, author: str, codes: Sequence[str]) -> str:
    return f"Added {title} by {author} with {_copies_phrase(codes)}"


def book_updated(title: str, fields: Sequence[str]) -> str:
    labels = {"isbn": "ISBN", "published_year": "year"}
    return f"Edited {title}: {', '.join(labels.get(field, field) for field in fields)}"


def book_archived(title: str) -> str:
    return f"Archived {title}; its loan history is kept"


def book_deleted(title: str) -> str:
    return f"Deleted {title}"


def copies_added(title: str, codes: Sequence[str]) -> str:
    return f"Added {_copies_phrase(codes)} of {title}"


def member_created(full_name: str) -> str:
    return f"Added member {full_name}"


def member_joined(full_name: str) -> str:
    return f"{full_name} joined by signing in with Google"


def loan_borrowed(title: str, code: str, member_name: str, due: date) -> str:
    return f"Borrowed {title} ({code}) to {member_name}, due {format_day(due)}"


def loan_returned(title: str, code: str, member_name: str) -> str:
    return f"Returned {title} ({code}) from {member_name}"


def loan_renewed(title: str, code: str, member_name: str, previous_due: date, due: date) -> str:
    return (
        f"Renewed {title} ({code}) for {member_name}, due {format_day(due)} "
        f"instead of {format_day(previous_due)}"
    )


def hold_placed(title: str, member_name: str, position: int) -> str:
    return f"Placed a hold on {title} for {member_name}, number {position} in line"


def hold_ready(title: str, code: str, member_name: str, pickup_by: date) -> str:
    return f"Set {title} ({code}) aside for {member_name}, to pick up by {format_day(pickup_by)}"


def hold_expired(title: str, code: str, member_name: str) -> str:
    return f"The hold of {member_name} on {title} expired: {code} was not picked up in time"


def hold_cancelled(title: str, member_name: str) -> str:
    return f"Cancelled the hold of {member_name} on {title}"


def hold_fulfilled(title: str, code: str, member_name: str) -> str:
    return f"{member_name} borrowed {title} ({code}), which fulfils their hold"
