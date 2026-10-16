"""A member's place in line for a book that has no copy on the shelf.

A hold is waiting until a copy comes free for it, then ready: that copy is set aside for the
member until pickup_by. It closes as fulfilled (the member borrowed the book), cancelled, or
expired (not picked up in time). Place in line is derived when reading, never stored, and so is
the expiry of a ready hold past pickup_by until something writes it (app.services.holds).
"""

import uuid
from datetime import datetime
from typing import Literal, get_args

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin

HoldStatus = Literal["waiting", "ready", "fulfilled", "cancelled", "expired"]
# A hold is open while the member is still in line or a copy is waiting for them.
OPEN_HOLD_STATUSES: tuple[HoldStatus, ...] = ("waiting", "ready")
_STATUS_SQL_LIST = ", ".join(f"'{value}'" for value in get_args(HoldStatus))
_OPEN_SQL_LIST = ", ".join(f"'{value}'" for value in OPEN_HOLD_STATUSES)

# The database allows one open hold per member and book, and one ready hold per copy. The holds
# service turns a violation of the first into a hold_exists conflict.
OPEN_HOLD_PER_MEMBER_INDEX = "uq_holds_member_id_book_id_open"
READY_HOLD_PER_COPY_INDEX = "uq_holds_copy_id_ready"


class Hold(TimestampMixin, Base):
    __tablename__ = "holds"
    __table_args__ = (
        CheckConstraint(f"status IN ({_STATUS_SQL_LIST})", name="status_allowed"),
        # A ready hold names the copy set aside and the time it waits until.
        CheckConstraint(
            "status <> 'ready' OR (copy_id IS NOT NULL AND ready_at IS NOT NULL "
            "AND pickup_by IS NOT NULL)",
            name="ready_has_copy",
        ),
        # Open holds have no closing time; closed holds have one.
        CheckConstraint(
            f"(status IN ({_OPEN_SQL_LIST})) = (closed_at IS NULL)", name="closed_at_when_closed"
        ),
        Index(
            OPEN_HOLD_PER_MEMBER_INDEX,
            "member_id",
            "book_id",
            unique=True,
            postgresql_where=text(f"status IN ({_OPEN_SQL_LIST})"),
        ),
        Index(
            READY_HOLD_PER_COPY_INDEX,
            "copy_id",
            unique=True,
            postgresql_where=text("status = 'ready'"),
        ),
        # The line for a book: its waiting holds, oldest first.
        Index(
            "ix_holds_book_id_placed_at_waiting",
            "book_id",
            "placed_at",
            postgresql_where=text("status = 'waiting'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()")
    )
    book_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("books.id", ondelete="CASCADE"), index=True
    )
    member_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("members.id"), index=True)
    status: Mapped[str] = mapped_column(Text)
    placed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # The copy set aside, from the moment the hold is ready. Kept once the hold closes.
    copy_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("copies.id", ondelete="CASCADE"))
    ready_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    pickup_by: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # The loan that fulfilled the hold.
    loan_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("loans.id"))
