"""Request and response shapes for holds."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.hold import HoldStatus
from app.schemas.loans import BookRef, CopyRef
from app.schemas.members import MemberRef

# What a hold list can show: waiting, ready, open (both, the default), closed (fulfilled,
# cancelled or expired), or all.
HoldListStatus = Literal["waiting", "ready", "open", "closed", "all"]


class HoldCreate(BaseModel):
    """Staff place a hold for a member."""

    book_id: UUID
    member_id: UUID


class MyHoldCreate(BaseModel):
    """A member places a hold for themselves."""

    book_id: UUID


class HoldOut(BaseModel):
    id: UUID
    # A ready hold past its pick-up time reads as expired, before anything writes that.
    status: HoldStatus
    book: BookRef
    member: MemberRef
    # The copy set aside, once the hold is ready. "copy" would shadow BaseModel.copy.
    copy_ref: CopyRef | None = Field(alias="copy")
    placed_at: datetime
    ready_at: datetime | None
    # The end of the last day to pick the copy up (UTC), once the hold is ready.
    pickup_by: datetime | None
    closed_at: datetime | None
    # Place in line, 1 for the next member to get a copy. Only while waiting; null otherwise.
    position: int | None
