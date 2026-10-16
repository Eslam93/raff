"""Member self-service: the signed-in member's own loans and holds.

Every route acts only on the signed-in member's own records: another member's loan or hold is
not found (404), never forbidden. An account without a member record gets 404 no_member_profile.
"""

import uuid

from fastapi import APIRouter, status

from app.api.deps import AppSettings, CurrentUser, PageLimit, PageOffset
from app.api.routers.holds import PLACE_CONFLICTS
from app.core.exceptions import NotFoundError
from app.db.session import DbSession
from app.models import User
from app.schemas.common import Page, error_responses
from app.schemas.holds import HoldListStatus, HoldOut, MyHoldCreate
from app.schemas.loans import LoanOut, LoanStatus
from app.services import circulation, holds

router = APIRouter(prefix="/me", tags=["me"])


def _member_id(user: User, records: str) -> uuid.UUID:
    """The signed-in user's member record. 404 no_member_profile for an account without one."""
    if user.member_id is None:
        raise NotFoundError(
            f"This account has no member record, so it has no {records}.",
            code="no_member_profile",
        )
    return user.member_id


@router.get("/loans", responses=error_responses(signed_in=True, not_found=True))
async def my_loans(
    session: DbSession,
    settings: AppSettings,
    user: CurrentUser,
    status: LoanStatus = "active",
    limit: PageLimit = 20,
    offset: PageOffset = 0,
) -> Page[LoanOut]:
    """active: loans not returned yet, due soonest first. returned: history, most recently
    returned first. 404 no_member_profile for an account without a member record.
    """
    return await circulation.list_loans(
        session,
        status=status,
        member_id=_member_id(user, "loans"),
        limit=limit,
        offset=offset,
        max_renewals=settings.max_renewals,
    )


@router.post(
    "/loans/{loan_id}/renew",
    responses=error_responses(
        signed_in=True,
        not_found=True,
        conflicts=[
            "loan_already_returned",
            "renewal_limit_reached",
            "book_has_holds",
            "renewal_not_needed",
            "loan_changed",
        ],
    ),
)
async def renew_my_loan(
    session: DbSession, settings: AppSettings, user: CurrentUser, loan_id: uuid.UUID
) -> LoanOut:
    """Renews one of the member's own active loans. Another member's loan is 404."""
    return await circulation.renew(
        session,
        loan_id,
        member_id=_member_id(user, "loans"),
        loan_period_days=settings.loan_period_days,
        max_renewals=settings.max_renewals,
        actor=user,
    )


@router.get("/holds", responses=error_responses(signed_in=True, not_found=True))
async def my_holds(
    session: DbSession,
    user: CurrentUser,
    status: HoldListStatus = "open",
    limit: PageLimit = 20,
    offset: PageOffset = 0,
) -> Page[HoldOut]:
    """The member's own holds. open (the default): waiting and ready, ready first. closed:
    fulfilled, cancelled and expired, the most recently closed first.
    """
    return await holds.list_holds(
        session, status=status, member_id=_member_id(user, "holds"), limit=limit, offset=offset
    )


@router.post(
    "/holds",
    status_code=status.HTTP_201_CREATED,
    responses=error_responses(signed_in=True, not_found=True, conflicts=PLACE_CONFLICTS),
)
async def place_my_hold(
    session: DbSession, settings: AppSettings, user: CurrentUser, body: MyHoldCreate
) -> HoldOut:
    """Puts the member in line for a book that has no copy on the shelf."""
    return await holds.place(
        session,
        book_id=body.book_id,
        member_id=_member_id(user, "holds"),
        max_open_holds=settings.max_open_holds,
        hold_pickup_days=settings.hold_pickup_days,
        actor=user,
    )


@router.post(
    "/holds/{hold_id}/cancel",
    responses=error_responses(signed_in=True, not_found=True, conflicts=["hold_closed"]),
)
async def cancel_my_hold(
    session: DbSession, settings: AppSettings, user: CurrentUser, hold_id: uuid.UUID
) -> HoldOut:
    """Cancels one of the member's own open holds. Another member's hold is 404."""
    return await holds.cancel(
        session,
        hold_id,
        member_id=_member_id(user, "holds"),
        hold_pickup_days=settings.hold_pickup_days,
        actor=user,
    )
