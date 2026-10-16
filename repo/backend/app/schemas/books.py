"""Request and response shapes for books and their copies."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator
from pydantic_core import PydanticCustomError

from app.schemas.fields import (
    AuthorName,
    BookTitle,
    Category,
    Description,
    Isbn,
    PublishedYear,
)
from app.schemas.holds import HoldOut
from app.schemas.loans import CopyStatus, HeldFor
from app.schemas.members import MemberRef

MAX_COPIES_PER_REQUEST = 20

# all_borrowed: the book has copies and none is on the shelf (each is lent out or held).
Availability = Literal["available", "all_borrowed", "no_copies"]
# The catalog's orders: title and author A to Z, the newest publication year first, or the book
# added to the catalog most recently first.
BookSort = Literal["title", "author", "year_desc", "recent"]


class BookCreate(BaseModel):
    title: BookTitle
    author: AuthorName
    isbn: Isbn = None
    category: Category = None
    published_year: PublishedYear = None
    description: Description = None
    # How many copies to create with the book.
    copies: int = Field(default=1, ge=1, le=MAX_COPIES_PER_REQUEST)


class BookUpdate(BaseModel):
    """Any subset of the book fields. An omitted field keeps its value; null clears an optional
    field. Title and author cannot be cleared.
    """

    title: BookTitle | None = None
    author: AuthorName | None = None
    isbn: Isbn = None
    category: Category = None
    published_year: PublishedYear = None
    description: Description = None

    @field_validator("title", "author")
    @classmethod
    def _not_null(cls, value: str | None) -> str:
        if value is None:
            raise PydanticCustomError("missing", "Field required")
        return value


class CopiesCreate(BaseModel):
    count: int = Field(default=1, ge=1, le=MAX_COPIES_PER_REQUEST)


class LoanBrief(BaseModel):
    id: UUID
    member: MemberRef
    borrowed_at: datetime
    due_at: datetime
    is_overdue: bool


class CopyOut(BaseModel):
    id: UUID
    code: str
    status: CopyStatus
    # When a borrowed copy is due back. Everyone signed in sees this.
    due_at: datetime | None
    # Who has the copy. Staff only: null for members, always.
    active_loan: LoanBrief | None
    # Who a held copy is set aside for, and until when. Staff only: null for members, always.
    held_for: HeldFor | None


class BookSummary(BaseModel):
    id: UUID
    title: str
    author: str
    isbn: str | None
    category: str | None
    published_year: int | None
    copies_total: int
    copies_available: int
    availability: Availability


class BookDetail(BookSummary):
    description: str | None
    has_loan_history: bool
    archived: bool
    created_at: datetime
    updated_at: datetime
    copies: list[CopyOut]
    # Members in line for the book: its waiting holds.
    holds_waiting: int
    # The signed-in member's open hold on the book, or null. Null for an account without a
    # member record, such as staff.
    my_hold: HoldOut | None


class IsbnLookupOut(BaseModel):
    """A book found by its ISBN, to fill the add-book form. The category stays manual."""

    # Normalized: digits, and a final X for an ISBN-10.
    isbn: str
    title: str
    # The first author named.
    author: str
    # Null when unknown, or outside the years the catalog accepts.
    published_year: int | None


class DeleteResult(BaseModel):
    """deleted: the book never had a loan and is gone. archived: it has loan history, so it
    left the catalog but its record and history are kept.
    """

    outcome: Literal["deleted", "archived"]
