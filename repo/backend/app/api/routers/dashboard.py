"""The staff dashboard. Staff only."""

from fastapi import APIRouter, Depends

from app.api.deps import AppSettings, require_staff
from app.db.session import DbSession
from app.schemas.common import error_responses
from app.schemas.dashboard import DashboardOut
from app.services import dashboard

router = APIRouter(prefix="/dashboard", tags=["dashboard"], dependencies=[Depends(require_staff)])


@router.get("", responses=error_responses(staff=True))
async def get_dashboard(session: DbSession, settings: AppSettings) -> DashboardOut:
    """Counts of titles, copies, copies on the shelf (neither on loan nor held for a member) and
    on loan, overdue loans, members and members who borrowed in the last 90 days (archived books
    and copies are not counted); up to 8 overdue loans, longest overdue first; up to 8 loans due
    within 3 days and not overdue, soonest first; and the 10 latest activity events.
    """
    return await dashboard.get_dashboard(session, max_renewals=settings.max_renewals)
