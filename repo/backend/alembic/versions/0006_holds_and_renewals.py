"""holds and renewals

Holds, with the partial unique indexes that allow one open hold per member and book and one
ready hold per copy, and the index the line for a book is read from. Renewals, one row per
renewal of a loan.

Revision ID: 0006
Revises: 0005
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> list[sa.Column[Any]]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    ]


def _uuid_pk() -> sa.Column[Any]:
    return sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False)


def upgrade() -> None:
    op.create_table(
        "holds",
        _uuid_pk(),
        sa.Column("book_id", sa.Uuid(), nullable=False),
        sa.Column("member_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column(
            "placed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("copy_id", sa.Uuid(), nullable=True),
        sa.Column("ready_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("pickup_by", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("loan_id", sa.Uuid(), nullable=True),
        *_timestamps(),
        sa.CheckConstraint(
            "status IN ('waiting', 'ready', 'fulfilled', 'cancelled', 'expired')",
            name=op.f("ck_holds_status_allowed"),
        ),
        sa.CheckConstraint(
            "status <> 'ready' OR (copy_id IS NOT NULL AND ready_at IS NOT NULL "
            "AND pickup_by IS NOT NULL)",
            name=op.f("ck_holds_ready_has_copy"),
        ),
        sa.CheckConstraint(
            "(status IN ('waiting', 'ready')) = (closed_at IS NULL)",
            name=op.f("ck_holds_closed_at_when_closed"),
        ),
        sa.ForeignKeyConstraint(
            ["book_id"], ["books.id"], name=op.f("fk_holds_book_id_books"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["member_id"], ["members.id"], name=op.f("fk_holds_member_id_members")
        ),
        sa.ForeignKeyConstraint(
            ["copy_id"], ["copies.id"], name=op.f("fk_holds_copy_id_copies"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["loan_id"], ["loans.id"], name=op.f("fk_holds_loan_id_loans")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_holds")),
    )
    op.create_index(op.f("ix_holds_book_id"), "holds", ["book_id"])
    op.create_index(op.f("ix_holds_member_id"), "holds", ["member_id"])
    # One open hold per member and book: two simultaneous holds cannot both be placed.
    op.create_index(
        "uq_holds_member_id_book_id_open",
        "holds",
        ["member_id", "book_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('waiting', 'ready')"),
    )
    # One ready hold per copy: a copy is set aside for one member at a time.
    op.create_index(
        "uq_holds_copy_id_ready",
        "holds",
        ["copy_id"],
        unique=True,
        postgresql_where=sa.text("status = 'ready'"),
    )
    # The line for a book: its waiting holds, oldest first.
    op.create_index(
        "ix_holds_book_id_placed_at_waiting",
        "holds",
        ["book_id", "placed_at"],
        postgresql_where=sa.text("status = 'waiting'"),
    )

    op.create_table(
        "renewals",
        _uuid_pk(),
        sa.Column("loan_id", sa.Uuid(), nullable=False),
        sa.Column(
            "renewed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("previous_due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("new_due_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "new_due_at >= previous_due_at", name=op.f("ck_renewals_new_due_not_earlier")
        ),
        sa.ForeignKeyConstraint(["loan_id"], ["loans.id"], name=op.f("fk_renewals_loan_id_loans")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_renewals")),
    )
    op.create_index(op.f("ix_renewals_loan_id"), "renewals", ["loan_id"])


def downgrade() -> None:
    # Dropping a table drops its indexes and constraints with it.
    op.drop_table("renewals")
    op.drop_table("holds")
