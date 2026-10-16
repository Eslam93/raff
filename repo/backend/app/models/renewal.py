"""One renewal of a loan: the due date it had and the one it got. The loan keeps its current due
date, so overdue, due soon and the metrics read it as before. A loan's renewal count is its
number of rows here.
"""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Renewal(Base):
    __tablename__ = "renewals"
    __table_args__ = (CheckConstraint("new_due_at >= previous_due_at", name="new_due_not_earlier"),)

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()")
    )
    loan_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("loans.id"), index=True)
    renewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    previous_due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    new_due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
