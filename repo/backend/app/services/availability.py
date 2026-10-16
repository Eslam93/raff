"""The one rule for whether a copy is on the shelf, which every availability decision uses: the
catalog's counts and its available filter, the book page, the copy lookup, the first available
copy, the borrow's checks, the holds and the dashboard.

A copy is free when it is in the catalog, has no active loan, and is not set aside by a ready
hold whose pick-up time is later than the database clock. So a ready hold past its pick-up time
frees its copy with no write; settling the book's holds records the expiry later.

The subqueries use their own aliases of loans and holds, so they never correlate with a loan or
a hold that the enclosing query reads.
"""

from typing import Any

from sqlalchemy import ColumnElement, and_, exists, func
from sqlalchemy.orm import aliased

from app.models import Copy, Hold, Loan


def has_active_loan(copy_id: Any) -> ColumnElement[bool]:
    """True while the copy is lent out."""
    loan = aliased(Loan)
    return exists().where(loan.copy_id == copy_id, loan.returned_at.is_(None))


def is_live_ready(hold: Any = Hold) -> ColumnElement[bool]:
    """True for a ready hold whose copy is still set aside, by the database clock."""
    return and_(hold.status == "ready", hold.pickup_by > func.now())


def is_lapsed(hold: Any = Hold) -> ColumnElement[bool]:
    """True for a ready hold past its pick-up time: expired, whether or not that is written yet."""
    return and_(hold.status == "ready", hold.pickup_by <= func.now())


def is_held(copy_id: Any) -> ColumnElement[bool]:
    """True while a live ready hold sets the copy aside for a member."""
    hold = aliased(Hold)
    return exists().where(hold.copy_id == copy_id, is_live_ready(hold))


def is_held_for(copy_id: Any, member_id: Any) -> ColumnElement[bool]:
    """True while a live ready hold sets the copy aside for this member."""
    hold = aliased(Hold)
    return exists().where(hold.copy_id == copy_id, hold.member_id == member_id, is_live_ready(hold))


def is_free() -> ColumnElement[bool]:
    """True for a copy (the copies row of the enclosing query) that can be lent to anyone now."""
    return and_(Copy.archived_at.is_(None), ~has_active_loan(Copy.id), ~is_held(Copy.id))
