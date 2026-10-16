"""Request and response shapes for loans."""

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.members import MemberRef

# available: on the shelf. borrowed: lent out. held: set aside for a member's ready hold.
CopyStatus = Literal["available", "borrowed", "held"]
# active: not returned yet. returned: history.
LoanStatus = Literal["active", "returned"]
# What staff can list: the same, plus overdue (active and past due) and all loans.
LoanListStatus = Literal["active", "overdue", "returned", "all"]


class LoanCreate(BaseModel):
    copy_id: UUID
    member_id: UUID
    # Defaults to today plus the loan period. The loan is due at the end of this day (UTC).
    due_date: date | None = None


class CopyRef(BaseModel):
    id: UUID
    code: str


class BookRef(BaseModel):
    id: UUID
    title: str
    author: str


class LoanOut(BaseModel):
    id: UUID
    # "copy" would shadow BaseModel.copy, so the attribute has another name.
    copy_ref: CopyRef = Field(alias="copy")
    book: BookRef
    member: MemberRef
    borrowed_at: datetime
    due_at: datetime
    returned_at: datetime | None
    is_overdue: bool
    # Whole days since the due date while overdue, at least 1; 0 for any other loan.
    days_overdue: int
    # How many times the loan was renewed.
    renewals: int
    # Whether it can be renewed now: active, renewed fewer times than allowed, and nobody
    # waiting for the book.
    can_renew: bool


class HeldFor(BaseModel):
    """Who a copy is set aside for, and until when."""

    member: MemberRef
    pickup_by: datetime


class CopyLookup(BaseModel):
    """A copy found by its code: its book, whether it is on loan and to whom, and whether it is
    set aside for a member's hold.
    """

    copy_ref: CopyRef = Field(alias="copy")
    book: BookRef
    status: CopyStatus
    # The copy or its book left the catalog. Its history is still readable.
    archived: bool
    active_loan: LoanOut | None
    # Who the copy is set aside for while it is held.
    held_for: HeldFor | None
