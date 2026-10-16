"""The catalog: books and their copies. Everyone signed in reads it; only staff change it."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.deps import (
    AppSettings,
    CurrentUser,
    PageLimit,
    PageOffset,
    SearchQuery,
    StaffUser,
)
from app.db.session import DbSession
from app.schemas.books import (
    BookCreate,
    BookDetail,
    BookSort,
    BookSummary,
    BookUpdate,
    CopiesCreate,
    DeleteResult,
)
from app.schemas.common import Page, error_responses
from app.services import catalog

router = APIRouter(prefix="/books", tags=["books"])


CategoryFilter = Annotated[
    str | None, Query(max_length=100, description="A whole category name, in any letter case")
]


@router.get("", responses=error_responses(signed_in=True))
async def list_books(
    session: DbSession,
    _: CurrentUser,
    q: SearchQuery = None,
    category: CategoryFilter = None,
    available_only: bool = False,
    sort: BookSort = "title",
    limit: PageLimit = 20,
    offset: PageOffset = 0,
) -> Page[BookSummary]:
    """Books in the catalog. q matches title, author or part of the ISBN. available_only keeps
    books with a copy that can be borrowed now. sort: title (the default) and author A to Z,
    year_desc the newest publication year first (books without one last), or recent the books
    added most recently first; ties go by title.
    """
    return await catalog.list_books(
        session,
        q=q,
        category=category,
        available_only=available_only,
        sort=sort,
        limit=limit,
        offset=offset,
    )


# Declared before /{book_id}, which would otherwise read "categories" as an id.
@router.get("/categories", responses=error_responses(signed_in=True))
async def list_categories(session: DbSession, _: CurrentUser) -> list[str]:
    """The categories of the books in the catalog, A to Z, for the catalog's filter."""
    return await catalog.list_categories(session)


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    responses=error_responses(staff=True, conflicts=["isbn_taken"]),
)
async def create_book(session: DbSession, user: StaffUser, body: BookCreate) -> BookDetail:
    """Adds a book together with its first copies."""
    return await catalog.create_book(session, body, actor=user)


@router.get("/{book_id}", responses=error_responses(signed_in=True, not_found=True))
async def get_book(session: DbSession, user: CurrentUser, book_id: uuid.UUID) -> BookDetail:
    """For members, a borrowed copy shows when it is due back but not who has it
    (active_loan is null), and a held copy shows as held but not for whom (held_for is null).
    my_hold is the signed-in member's open hold on the book; null for staff.
    """
    return await catalog.get_book_detail(
        session, book_id, show_borrowers=user.is_staff, member_id=user.member_id
    )


@router.patch(
    "/{book_id}",
    responses=error_responses(
        staff=True, not_found=True, conflicts=["isbn_taken", "book_archived"]
    ),
)
async def update_book(
    session: DbSession, user: StaffUser, book_id: uuid.UUID, body: BookUpdate
) -> BookDetail:
    return await catalog.update_book(session, book_id, body, actor=user)


@router.delete(
    "/{book_id}",
    responses=error_responses(staff=True, not_found=True, conflicts=["book_has_active_loans"]),
)
async def delete_book(session: DbSession, user: StaffUser, book_id: uuid.UUID) -> DeleteResult:
    """Deletes the book if it never had a loan, otherwise archives it."""
    return DeleteResult(outcome=await catalog.delete_book(session, book_id, actor=user))


@router.post(
    "/{book_id}/copies",
    status_code=status.HTTP_201_CREATED,
    responses=error_responses(staff=True, not_found=True, conflicts=["book_archived"]),
)
async def add_copies(
    session: DbSession,
    settings: AppSettings,
    user: StaffUser,
    book_id: uuid.UUID,
    body: CopiesCreate,
) -> BookDetail:
    """New copies are set aside for the members waiting for the book, oldest hold first."""
    return await catalog.add_copies(
        session, book_id, body.count, hold_pickup_days=settings.hold_pickup_days, actor=user
    )
