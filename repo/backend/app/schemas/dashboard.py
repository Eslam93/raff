"""Response shape for the staff dashboard."""

from pydantic import BaseModel

from app.schemas.activity import ActivityOut
from app.schemas.loans import LoanOut


class DashboardCounts(BaseModel):
    """The library right now. Archived books and copies are not counted."""

    titles: int
    copies: int
    # Copies in circulation that are on the shelf (free to borrow), and those on loan. A copy set
    # aside for a member's hold is in neither, so the two add up to copies only without holds.
    available: int
    on_loan: int
    overdue: int
    members: int
    # Members who borrowed at least once in the last 90 days.
    active_members_90d: int


class DashboardOut(BaseModel):
    counts: DashboardCounts
    # Longest overdue first.
    overdue: list[LoanOut]
    # Due in the next few days and not overdue yet, soonest first.
    due_soon: list[LoanOut]
    # Newest first.
    recent_activity: list[ActivityOut]
