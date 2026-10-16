"""Holds: who is in line for a book, and who has a copy set aside. Staff only."""

import uuid

from fastapi import APIRouter, Depends, status

from app.api.deps import AppSettings, PageLimit, PageOffset, StaffUser, require_staff
from app.db.session import DbSession
from app.schemas.common import Page, error_responses
from app.schemas.holds import HoldCreate, HoldListStatus, HoldOut
from app.services import holds

router = APIRouter(prefix="/holds", tags=["holds"], dependencies=[Depends(require_staff)])

PLACE_CONFLICTS = [
    "book_archived",
    "already_borrowed",
    "hold_exists",
    "copy_available",
    "hold_limit_reached",
]


@router.get("", responses=error_responses(staff=True))
async def list_holds(
    session: DbSession,
    status: HoldListStatus = "open",
    book_id: uuid.UUID | None = None,
    member_id: uuid.UUID | None = None,
    limit: PageLimit = 20,
    offset: PageOffset = 0,
) -> Page[HoldOut]:
    """open (the default): waiting and ready holds. Ready holds come first, the soonest pick-up
    first, then waiting holds in line order, then closed holds, the most recently closed first.
    A ready hold past its pick-up time counts as closed and reads as expired. book_id and
    member_id narrow the list to one book or one member.
    """
    return await holds.list_holds(
        session, status=status, book_id=book_id, member_id=member_id, limit=limit, offset=offset
    )


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    responses=error_responses(staff=True, not_found=True, conflicts=PLACE_CONFLICTS),
)
async def place_hold(
    session: DbSession, settings: AppSettings, user: StaffUser, body: HoldCreate
) -> HoldOut:
    """Puts a member in line for a book that has no copy on the shelf."""
    return await holds.place(
        session,
        book_id=body.book_id,
        member_id=body.member_id,
        max_open_holds=settings.max_open_holds,
        hold_pickup_days=settings.hold_pickup_days,
        actor=user,
    )


@router.post(
    "/{hold_id}/cancel",
    responses=error_responses(staff=True, not_found=True, conflicts=["hold_closed"]),
)
async def cancel_hold(
    session: DbSession, settings: AppSettings, user: StaffUser, hold_id: uuid.UUID
) -> HoldOut:
    """Cancels a waiting or ready hold. A copy set aside for it goes to the next in line."""
    return await holds.cancel(
        session, hold_id, hold_pickup_days=settings.hold_pickup_days, actor=user
    )
