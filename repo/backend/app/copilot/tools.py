"""The Copilot's tools: typed lookups that call the product's own services as the signed-in user,
and for staff, preparing a borrow or a return that only the user's confirm makes.

Each tool's parameters are a pydantic model that rejects unknown fields, so the model can add
neither an identity nor a filter the tool does not offer. Who is asking always comes from the
session (ToolContext.user), and the services apply the web app's own rules: a member sees when a
borrowed copy is due back, never who has it, that a copy is set aside for a hold, never for whom,
and only their own loans and holds.

A tool returns what the model reads (plain JSON, with dates and no times) and what the panel
shows (a display in the product's API shapes), and can put its data in plain sentences for the
fallback reply. Dates for the model are written like "3 Oct 2026": the prompts hold no digits,
so the data is what shows the model the form to answer in. The holds lookups have no display:
the panel has no card for a hold yet, so the reply says what the answer needs.
"""

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.copilot import proposals
from app.core.exceptions import NotFoundError
from app.models import User
from app.schemas.books import BookDetail, BookSummary, CopyOut
from app.schemas.copilot import (
    BookDisplay,
    BooksDisplay,
    CategoriesDisplay,
    CopyDisplay,
    Display,
    LoansDisplay,
    MembersDisplay,
    ProposalDisplay,
    ProposalOut,
)
from app.schemas.holds import HoldOut
from app.schemas.loans import CopyLookup, LoanOut, LoanStatus
from app.schemas.members import MemberOut
from app.services import activity, catalog, circulation, holds, members

MAX_SEARCH_RESULTS = 10
MAX_MEMBER_RESULTS = 10
MAX_LOANS = 20
MAX_HOLDS = 20
MAX_COPY_CODE_LENGTH = 20
# Book descriptions are cut to this length for the model.
MAX_DESCRIPTION_CHARS = 600

Data = dict[str, Any]


class ToolParams(BaseModel):
    model_config = ConfigDict(extra="forbid")


@dataclass(frozen=True)
class ToolContext:
    session: AsyncSession
    user: User
    # The turn's conversation, which a proposal tells its outcome to.
    conversation_id: uuid.UUID | None
    # The loan period from the settings, for a borrow without a due date.
    loan_period_days: int
    # The renewal limit from the settings, which decides whether a loan can be renewed.
    max_renewals: int


@dataclass(frozen=True)
class ToolOutput:
    data: Data
    # What the panel shows. None when there is nothing to show, such as an empty search.
    display: Display | None = None


@dataclass(frozen=True)
class Tool[P: ToolParams]:
    name: str
    description: str
    params: type[P]
    # Shown in the panel while the lookup runs.
    status: str
    run: Callable[[ToolContext, P], Awaitable[ToolOutput]]
    # The data in plain sentences, for the fallback reply.
    render: Callable[[Data], str]

    def definition(self) -> dict[str, Any]:
        """The tool as the model sees it, in the OpenAI-compatible format."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": _without_titles(_inlined(self.params.model_json_schema())),
            },
        }


def _inlined(schema: dict[str, Any]) -> dict[str, Any]:
    """The JSON schema with each nested model written out where it is used, instead of as a
    reference to a shared definition, which not every model provider reads.
    """
    definitions = schema.pop("$defs", {})

    def resolve(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                target = definitions[node["$ref"].rsplit("/", 1)[-1]]
                siblings = {key: value for key, value in node.items() if key != "$ref"}
                return resolve({**target, **siblings})
            return {key: resolve(value) for key, value in node.items()}
        if isinstance(node, list):
            return [resolve(value) for value in node]
        return node

    resolved: dict[str, Any] = resolve(schema)
    return resolved


def _without_titles(schema: Any) -> Any:
    """The JSON schema without pydantic's generated "title" labels, which the model does not
    need. A property that happens to be named title is kept.
    """
    if isinstance(schema, dict):
        return {
            key: _without_titles(value)
            for key, value in schema.items()
            if not (key == "title" and isinstance(value, str))
        }
    if isinstance(schema, list):
        return [_without_titles(value) for value in schema]
    return schema


def _day(moment: Any) -> str | None:
    return activity.format_day(moment.date()) if moment is not None else None


def _today() -> str:
    return activity.format_day(circulation.today_utc())


def _count(number: int, noun: str) -> str:
    return f"{number} {noun}" + ("" if number == 1 else "s")


def _copies_text(available: int, total: int) -> str:
    if total == 0:
        return "no copies"
    return f"{available} of {total} {'copy' if total == 1 else 'copies'} available"


# Holds, as every lookup that mentions one gives it. What a hold says depends on its status: its
# place in line while waiting, the copy set aside and the day to pick it up by while ready, and
# the day it closed once fulfilled, cancelled or expired.

# How a closed hold ended, in words.
_HOLD_ENDINGS = {"fulfilled": "picked up", "cancelled": "cancelled", "expired": "expired"}


def _hold_state(hold: HoldOut) -> Data:
    data: Data = {"status": hold.status, "placed_on": _day(hold.placed_at)}
    if hold.position is not None:
        data["place_in_line"] = hold.position
    if hold.copy_ref is not None:
        data["copy_code"] = hold.copy_ref.code
    if hold.status == "ready":
        data["pick_up_by"] = _day(hold.pickup_by)
    elif hold.status in _HOLD_ENDINGS:
        # A ready hold past its pick-up time reads as expired before anything writes closed_at.
        data["closed_on"] = _day(hold.closed_at or hold.pickup_by)
    return data


def _hold_data(hold: HoldOut) -> Data:
    return {
        "book_id": str(hold.book.id),
        "title": hold.book.title,
        "author": hold.book.author,
        **_hold_state(hold),
    }


def _availability_holds(holds_waiting: int, my_hold: HoldOut | None, *, is_member: bool) -> Data:
    """The holds part of a book's availability: how many members are in line for it, and for an
    account with a member record, its own open hold on the book (null when it has none).
    """
    data: Data = {"holds_waiting": holds_waiting}
    if is_member:
        data["my_hold"] = _hold_state(my_hold) if my_hold is not None else None
    return data


def _hold_text(hold: Data, *, yours: bool) -> str:
    status = hold["status"]
    if status == "ready":
        for_whom = " for you" if yours else ""
        return f"copy {hold['copy_code']} is set aside{for_whom} until {hold['pick_up_by']}"
    if status == "waiting":
        return ("you are " if yours else "") + f"number {hold['place_in_line']} in line"
    return f"{_HOLD_ENDINGS[status]} on {hold['closed_on']}"


def _availability_text(book: Data) -> str:
    """How many copies are available, then the line and the member's own hold, if any."""
    text = _copies_text(book["copies_available"], book["copies_total"])
    if book["holds_waiting"]:
        text += f", {_count(book['holds_waiting'], 'member')} waiting"
    if book.get("my_hold") is not None:
        text += f", {_hold_text(book['my_hold'], yours=True)}"
    return text


# search_catalog


class SearchCatalog(ToolParams):
    query: str = Field(
        default="",
        max_length=200,
        description="Words from a book's title or its author's name, or part of an ISBN. "
        "Empty to browse.",
    )
    category: str = Field(
        default="",
        max_length=100,
        description="A category name exactly as list_categories gives it. Empty for all.",
    )
    available_only: bool = Field(
        default=False, description="Only books with a copy that can be borrowed now."
    )
    limit: int = Field(
        default=5, ge=1, le=MAX_SEARCH_RESULTS, description="How many books to return."
    )


def _book_brief(book: BookSummary) -> Data:
    return {
        "id": str(book.id),
        "title": book.title,
        "author": book.author,
        "category": book.category,
        "published_year": book.published_year,
        "copies_total": book.copies_total,
        "copies_available": book.copies_available,
    }


async def _search_catalog(context: ToolContext, params: SearchCatalog) -> ToolOutput:
    session, member_id = context.session, context.user.member_id
    page = await catalog.list_books(
        session,
        q=params.query,
        category=params.category,
        available_only=params.available_only,
        limit=params.limit,
        offset=0,
    )
    books = []
    for book in page.items:
        my_hold = None
        if member_id is not None:
            my_hold = await holds.open_hold(session, book_id=book.id, member_id=member_id)
        waiting = await holds.waiting_count(session, book.id)
        books.append(
            {
                **_book_brief(book),
                **_availability_holds(waiting, my_hold, is_member=member_id is not None),
            }
        )
    data = {"matches": page.total, "books": books}
    return ToolOutput(data, BooksDisplay(items=page.items) if page.items else None)


def _render_books(data: Data) -> str:
    if not data["books"]:
        return "No books in the catalog match that."
    lines = [
        f"- {book['title']} by {book['author']}: {_availability_text(book)}"
        for book in data["books"]
    ]
    return "\n".join(["Books in the catalog:", *lines])


# list_categories


class ListCategories(ToolParams):
    pass


async def _list_categories(context: ToolContext, _: ListCategories) -> ToolOutput:
    categories = await catalog.list_categories(context.session)
    display = CategoriesDisplay(items=categories) if categories else None
    return ToolOutput({"categories": categories}, display)


def _render_categories(data: Data) -> str:
    if not data["categories"]:
        return "The catalog has no categories yet."
    return "Categories: " + ", ".join(data["categories"]) + "."


# get_book


class GetBook(ToolParams):
    book_id: uuid.UUID = Field(description="The id of a book from search results.")


def _copy_data(copy: CopyOut) -> Data:
    data: Data = {"code": copy.code, "status": copy.status}
    if copy.due_at is not None:
        data["due_back"] = _day(copy.due_at)
    # Only staff get the active loan, and who a held copy is set aside for; for members both are
    # always empty.
    if copy.active_loan is not None:
        data["borrower"] = copy.active_loan.member.full_name
        data["overdue"] = copy.active_loan.is_overdue
    if copy.held_for is not None:
        data["held_for"] = copy.held_for.member.full_name
        data["pick_up_by"] = _day(copy.held_for.pickup_by)
    return data


def _book_data(book: BookDetail, *, is_member: bool) -> Data:
    description = book.description
    if description is not None and len(description) > MAX_DESCRIPTION_CHARS:
        description = description[:MAX_DESCRIPTION_CHARS].rstrip() + "..."
    data: Data = {
        **_book_brief(book),
        **_availability_holds(book.holds_waiting, book.my_hold, is_member=is_member),
        "isbn": book.isbn,
        "description": description,
        "copies": [_copy_data(copy) for copy in book.copies],
    }
    if book.archived:
        data["archived"] = True
    return data


async def _get_book(context: ToolContext, params: GetBook) -> ToolOutput:
    # As the book's page: staff see who has a copy or who it is held for, and an account with a
    # member record gets its own hold on the book.
    member_id = context.user.member_id
    book = await catalog.get_book_detail(
        context.session, params.book_id, show_borrowers=context.user.is_staff, member_id=member_id
    )
    return ToolOutput(_book_data(book, is_member=member_id is not None), BookDisplay(book=book))


def _render_book(data: Data) -> str:
    lines = [f"{data['title']} by {data['author']}: {_availability_text(data)}."]
    my_hold = data.get("my_hold")
    for copy in data["copies"]:
        if copy["status"] == "held":
            if "held_for" in copy:
                lines.append(
                    f"- Copy {copy['code']} is set aside for {copy['held_for']} until "
                    f"{copy['pick_up_by']}."
                )
            # A copy set aside for the member asking is already in the first line.
            elif my_hold is None or my_hold.get("copy_code") != copy["code"]:
                lines.append(f"- Copy {copy['code']} is set aside for a member's hold.")
            continue
        if copy["status"] != "borrowed":
            continue
        line = f"- Copy {copy['code']} is due back on {copy['due_back']}"
        if "borrower" in copy:
            line += f", borrowed by {copy['borrower']}"
            line += ", overdue" if copy["overdue"] else ""
        lines.append(line + ".")
    return "\n".join(lines)


# get_my_loans


class GetMyLoans(ToolParams):
    status: LoanStatus = Field(
        default="active",
        description="active: loans not returned yet, due soonest first. returned: past loans, "
        "most recently returned first.",
    )


def _loan_data(loan: LoanOut) -> Data:
    data: Data = {
        "book_id": str(loan.book.id),
        "title": loan.book.title,
        "author": loan.book.author,
        "copy_code": loan.copy_ref.code,
        "borrowed_on": _day(loan.borrowed_at),
        "due_on": _day(loan.due_at),
        "overdue": loan.is_overdue,
    }
    if loan.is_overdue:
        data["days_overdue"] = loan.days_overdue
    if loan.returned_at is not None:
        data["returned_on"] = _day(loan.returned_at)
    return data


async def _get_my_loans(context: ToolContext, params: GetMyLoans) -> ToolOutput:
    # Always the signed-in member: the parameters have no member id to change it.
    member_id = context.user.member_id
    if member_id is None:
        raise NotFoundError("This account has no member record, so it has no loans.")
    page = await circulation.list_loans(
        context.session,
        status=params.status,
        member_id=member_id,
        limit=MAX_LOANS,
        offset=0,
        max_renewals=context.max_renewals,
    )
    data = {
        "today": _today(),
        "status": params.status,
        "total": page.total,
        "loans": [_loan_data(loan) for loan in page.items],
    }
    return ToolOutput(data, LoansDisplay(items=page.items) if page.items else None)


def _render_loans(data: Data) -> str:
    loans = data["loans"]
    if data["status"] == "returned":
        if not loans:
            return "You have no past loans."
        lines = [f"- {loan['title']}, returned on {loan['returned_on']}" for loan in loans]
        return "\n".join(["Your past loans:", *lines])
    if not loans:
        return "You have no books on loan."
    lines = [
        f"- {loan['title']} (copy {loan['copy_code']}), due {loan['due_on']}"
        + (", overdue" if loan["overdue"] else "")
        for loan in loans
    ]
    return "\n".join(["Your loans:", *lines])


# my_holds

# What a holds lookup can list: open holds (waiting, or with a copy set aside) or closed ones.
HoldsShown = Literal["open", "closed"]


class MyHolds(ToolParams):
    status: HoldsShown = Field(
        default="open",
        description="open: holds still in line or with a copy set aside, those with a copy set "
        "aside first. closed: past holds, picked up, cancelled or expired, the most recently "
        "closed first.",
    )


async def _my_holds(context: ToolContext, params: MyHolds) -> ToolOutput:
    # Always the signed-in member: the parameters have no member id to change it.
    member_id = context.user.member_id
    if member_id is None:
        raise NotFoundError(
            "This account has no member record, so it has no holds.", code="no_member_profile"
        )
    page = await holds.list_holds(
        context.session, status=params.status, member_id=member_id, limit=MAX_HOLDS, offset=0
    )
    data = {
        "today": _today(),
        "status": params.status,
        "total": page.total,
        "holds": [_hold_data(hold) for hold in page.items],
    }
    return ToolOutput(data)


def _render_my_holds(data: Data) -> str:
    held = data["holds"]
    if data["status"] == "closed":
        if not held:
            return "You have no past holds."
        heading = "Your past holds:"
    else:
        if not held:
            return "You have no open holds."
        heading = "Your holds:"
    lines = [f"- {hold['title']}: {_hold_text(hold, yours=True)}" for hold in held]
    return "\n".join([heading, *lines])


# Staff lookups. A loan as staff see it also says who has it.


def _staff_loan_data(loan: LoanOut) -> Data:
    return {**_loan_data(loan), "member": loan.member.full_name, "member_id": str(loan.member.id)}


def _loans_output(data: Data, items: list[LoanOut]) -> ToolOutput:
    return ToolOutput(data, LoansDisplay(items=items) if items else None)


def _staff_loan_line(loan: Data, *, with_title: bool = True, with_member: bool = True) -> str:
    code = loan["copy_code"]
    line = f"- {loan['title']} (copy {code})" if with_title else f"- Copy {code}"
    if with_member:
        line += f", {loan['member']}"
    if "returned_on" in loan:
        return line + f", returned on {loan['returned_on']}"
    return line + f", due {loan['due_on']}" + (", overdue" if loan["overdue"] else "")


# search_members


class SearchMembers(ToolParams):
    query: str = Field(
        min_length=1, max_length=200, description="Part of a member's name or email address."
    )
    limit: int = Field(
        default=5, ge=1, le=MAX_MEMBER_RESULTS, description="How many members to return."
    )


def _member_data(member: MemberOut) -> Data:
    return {
        "id": str(member.id),
        "full_name": member.full_name,
        "email": member.email,
        "active_loans": member.active_loans,
    }


async def _search_members(context: ToolContext, params: SearchMembers) -> ToolOutput:
    page = await members.list_members(context.session, q=params.query, limit=params.limit, offset=0)
    data = {"matches": page.total, "members": [_member_data(member) for member in page.items]}
    return ToolOutput(data, MembersDisplay(items=page.items) if page.items else None)


def _render_members(data: Data) -> str:
    if not data["members"]:
        return "No members match that."
    lines = [
        f"- {member['full_name']}"
        + (f" ({member['email']})" if member["email"] else "")
        + f": {_count(member['active_loans'], 'active loan')}"
        for member in data["members"]
    ]
    return "\n".join(["Members:", *lines])


# get_member_loans


class GetMemberLoans(ToolParams):
    member_id: uuid.UUID = Field(description="The id of a member from search_members.")
    status: LoanStatus = Field(
        default="active",
        description="active: loans not returned yet, due soonest first. returned: past loans, "
        "most recently returned first.",
    )


async def _get_member_loans(context: ToolContext, params: GetMemberLoans) -> ToolOutput:
    member = await members.get_member(context.session, params.member_id)
    page = await circulation.list_loans(
        context.session,
        status=params.status,
        member_id=member.id,
        limit=MAX_LOANS,
        offset=0,
        max_renewals=context.max_renewals,
    )
    data = {
        "today": _today(),
        "member": member.full_name,
        "status": params.status,
        "total": page.total,
        "loans": [_staff_loan_data(loan) for loan in page.items],
    }
    return _loans_output(data, page.items)


def _render_member_loans(data: Data) -> str:
    member, loans = data["member"], data["loans"]
    if data["status"] == "returned":
        if not loans:
            return f"{member} has no past loans."
        heading = f"Past loans of {member}:"
    else:
        if not loans:
            return f"{member} has no books on loan."
        heading = f"Loans of {member}:"
    return "\n".join([heading, *(_staff_loan_line(loan, with_member=False) for loan in loans)])


# get_book_loans


class GetBookLoans(ToolParams):
    book_id: uuid.UUID = Field(description="The id of a book from search results.")
    status: LoanStatus = Field(
        default="active",
        description="active: copies on loan now, due soonest first. returned: past loans, most "
        "recently returned first.",
    )


async def _get_book_loans(context: ToolContext, params: GetBookLoans) -> ToolOutput:
    book = await catalog.get_book_detail(context.session, params.book_id)
    page = await circulation.list_loans(
        context.session,
        status=params.status,
        book_id=book.id,
        limit=MAX_LOANS,
        offset=0,
        max_renewals=context.max_renewals,
    )
    data = {
        "today": _today(),
        "title": book.title,
        "status": params.status,
        "total": page.total,
        "loans": [_staff_loan_data(loan) for loan in page.items],
    }
    return _loans_output(data, page.items)


def _render_book_loans(data: Data) -> str:
    title, loans = data["title"], data["loans"]
    if data["status"] == "returned":
        if not loans:
            return f"{title} has no past loans."
        heading = f"Past loans of {title}:"
    else:
        if not loans:
            return f"No copy of {title} is on loan."
        heading = f"Copies of {title} on loan:"
    return "\n".join([heading, *(_staff_loan_line(loan, with_title=False) for loan in loans)])


# book_holds


class BookHolds(ToolParams):
    book_id: uuid.UUID = Field(description="The id of a book from search results.")
    status: HoldsShown = Field(
        default="open",
        description="open: who has a copy set aside, the soonest pick-up first, then who is "
        "waiting, in line order. closed: past holds, picked up, cancelled or expired, the most "
        "recently closed first.",
    )


async def _book_holds(context: ToolContext, params: BookHolds) -> ToolOutput:
    book = await catalog.get_book_detail(context.session, params.book_id)
    page = await holds.list_holds(
        context.session, status=params.status, book_id=book.id, limit=MAX_HOLDS, offset=0
    )
    data = {
        "today": _today(),
        "title": book.title,
        "holds_waiting": book.holds_waiting,
        "status": params.status,
        "total": page.total,
        "holds": [
            {**_hold_data(hold), "member": hold.member.full_name, "member_id": str(hold.member.id)}
            for hold in page.items
        ],
    }
    return ToolOutput(data)


def _render_book_holds(data: Data) -> str:
    title, held = data["title"], data["holds"]
    if data["status"] == "closed":
        if not held:
            return f"{title} has no past holds."
        heading = f"Past holds on {title}:"
    else:
        if not held:
            return f"Nobody is waiting for {title}."
        heading = f"Holds on {title}:"
    lines = [f"- {hold['member']}: {_hold_text(hold, yours=False)}" for hold in held]
    return "\n".join([heading, *lines])


# get_overdue_loans


class GetOverdueLoans(ToolParams):
    limit: int = Field(default=10, ge=1, le=MAX_LOANS, description="How many loans to return.")


async def _get_overdue_loans(context: ToolContext, params: GetOverdueLoans) -> ToolOutput:
    # Due soonest first is longest overdue first.
    page = await circulation.list_loans(
        context.session,
        status="overdue",
        limit=params.limit,
        offset=0,
        max_renewals=context.max_renewals,
    )
    data = {
        "today": _today(),
        "total": page.total,
        "loans": [_staff_loan_data(loan) for loan in page.items],
    }
    return _loans_output(data, page.items)


def _render_overdue_loans(data: Data) -> str:
    if not data["loans"]:
        return "No loans are overdue."
    return "\n".join(["Overdue loans:", *(_staff_loan_line(loan) for loan in data["loans"])])


# lookup_copy


class LookupCopy(ToolParams):
    code: str = Field(
        min_length=1,
        max_length=MAX_COPY_CODE_LENGTH,
        description="The code on the copy's label, with or without the CP- prefix and the "
        "leading zeros.",
    )


def _copy_lookup_data(lookup: CopyLookup) -> Data:
    data: Data = {
        "code": lookup.copy_ref.code,
        "title": lookup.book.title,
        "author": lookup.book.author,
        "book_id": str(lookup.book.id),
        "status": lookup.status,
        "archived": lookup.archived,
    }
    loan = lookup.active_loan
    if loan is not None:
        data["borrower"] = loan.member.full_name
        data["member_id"] = str(loan.member.id)
        data["due_on"] = _day(loan.due_at)
        data["overdue"] = loan.is_overdue
        if loan.is_overdue:
            data["days_overdue"] = loan.days_overdue
    held = lookup.held_for
    if held is not None:
        data["held_for"] = held.member.full_name
        data["member_id"] = str(held.member.id)
        data["pick_up_by"] = _day(held.pickup_by)
    return data


async def _lookup_copy(context: ToolContext, params: LookupCopy) -> ToolOutput:
    lookup = await circulation.find_copy_by_code(
        context.session, params.code, max_renewals=context.max_renewals
    )
    return ToolOutput(_copy_lookup_data(lookup), CopyDisplay(lookup=lookup))


def _render_copy(data: Data) -> str:
    text = f"Copy {data['code']} of {data['title']} by {data['author']}"
    if "borrower" in data:
        text += f" is on loan to {data['borrower']}, due back on {data['due_on']}"
        text += ", overdue." if data["overdue"] else "."
    elif "held_for" in data:
        text += f" is set aside for {data['held_for']}, to pick up by {data['pick_up_by']}."
    else:
        text += " is available."
    if data["archived"]:
        text += " It is no longer in the catalog."
    return text


# prepare_borrow and prepare_return


BORROW_NOTE = (
    "Nothing has changed yet. The loan is made only when the staff member presses Confirm on "
    "the card in the panel."
)
RETURN_NOTE = (
    "Nothing has changed yet. The copy is returned only when the staff member presses Confirm "
    "on the card in the panel."
)


class PrepareBorrow(ToolParams):
    member_id: uuid.UUID = Field(
        description="The id of the member who borrows, from search_members."
    )
    book_id: uuid.UUID | None = Field(
        default=None,
        description="The book to lend; the copy set aside for the member's hold is chosen, or "
        "else the book's first available copy. Give this or copy_code, not both.",
    )
    copy_code: str | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_COPY_CODE_LENGTH,
        description="The code of a particular copy to lend. Give this or book_id, not both.",
    )
    due_date: date | None = Field(
        default=None,
        description="Only when the staff member asks for a due date. Left out, the library's "
        "usual loan period applies.",
    )

    @model_validator(mode="after")
    def _one_book_or_copy(self) -> Self:
        if (self.book_id is None) == (self.copy_code is None):
            raise ValueError("Give exactly one of book_id or copy_code.")
        return self


class PrepareReturn(ToolParams):
    copy_code: str = Field(
        min_length=1,
        max_length=MAX_COPY_CODE_LENGTH,
        description="The code of the copy being returned, from the member's loans or the "
        "copy's label.",
    )


def _proposal_data(proposal: ProposalOut) -> Data:
    return {
        "proposal": "waiting_for_confirmation",
        "action": proposal.action,
        "title": proposal.book.title,
        "author": proposal.book.author,
        "copy_code": proposal.copy_ref.code,
        "member": proposal.member.full_name,
    }


async def _prepare_borrow(context: ToolContext, params: PrepareBorrow) -> ToolOutput:
    proposal = await proposals.prepare_borrow(
        context.session,
        user=context.user,
        conversation_id=context.conversation_id,
        member_id=params.member_id,
        book_id=params.book_id,
        copy_code=params.copy_code,
        due_date=params.due_date,
        loan_period_days=context.loan_period_days,
    )
    data = {**_proposal_data(proposal), "due_on": _day(proposal.due_at), "note": BORROW_NOTE}
    return ToolOutput(data, ProposalDisplay(proposal=proposal))


async def _prepare_return(context: ToolContext, params: PrepareReturn) -> ToolOutput:
    proposal = await proposals.prepare_return(
        context.session,
        user=context.user,
        conversation_id=context.conversation_id,
        copy_code=params.copy_code,
    )
    data = {
        **_proposal_data(proposal),
        "borrowed_on": _day(proposal.borrowed_at),
        "due_on": _day(proposal.due_at),
        "overdue": proposal.is_overdue,
        "note": RETURN_NOTE,
    }
    return ToolOutput(data, ProposalDisplay(proposal=proposal))


def _render_proposal(data: Data) -> str:
    copy = f"{data['title']} (copy {data['copy_code']})"
    if data["action"] == "borrow":
        text = f"A borrow is ready to confirm: {copy} for {data['member']}, due {data['due_on']}."
    else:
        text = f"A return is ready to confirm: {copy} from {data['member']}."
    return f"{text} {data['note']}"


SEARCH_CATALOG = Tool(
    name="search_catalog",
    description="Search the library's catalog by title, author, ISBN, category and "
    "availability. Returns the number of matches and the matching books, each with how many "
    "copies the library has, how many can be borrowed now and how many members are waiting in "
    "line for it, and for a member, their own hold on it.",
    params=SearchCatalog,
    status="Searching the catalog",
    run=_search_catalog,
    render=_render_books,
)

LIST_CATEGORIES = Tool(
    name="list_categories",
    description="List the categories of the books in the catalog.",
    params=ListCategories,
    status="Looking at the categories",
    run=_list_categories,
    render=_render_categories,
)

GET_BOOK_MEMBER_VIEW = Tool(
    name="get_book",
    description="Show one book: its details, each copy's status with the date a borrowed copy "
    "is due back, how many members are waiting in line for it, and the asking member's own "
    "hold on it: their place in line, or the copy set aside for them and the day to pick it up "
    "by.",
    params=GetBook,
    status="Opening the book",
    run=_get_book,
    render=_render_book,
)

GET_BOOK_STAFF_VIEW = Tool(
    name="get_book",
    description="Show one book: its details, each copy's status, and how many members are "
    "waiting in line for it. For a borrowed copy, who has it, when it is due back and whether "
    "it is overdue. For a copy set aside for a hold, who it is for and the day to pick it up "
    "by.",
    params=GetBook,
    status="Opening the book",
    run=_get_book,
    render=_render_book,
)

GET_MY_LOANS = Tool(
    name="get_my_loans",
    description="The loans of the member who is asking: current loans with due dates and "
    "overdue marks, or past loans. Includes today's date.",
    params=GetMyLoans,
    status="Checking your loans",
    run=_get_my_loans,
    render=_render_loans,
)

MY_HOLDS = Tool(
    name="my_holds",
    description="The holds of the member who is asking: open holds, each with its place in "
    "line, or the copy set aside for them and the day to pick it up by; or past holds and how "
    "each ended. Includes today's date.",
    params=MyHolds,
    status="Checking your holds",
    run=_my_holds,
    render=_render_my_holds,
)

SEARCH_MEMBERS = Tool(
    name="search_members",
    description="Find members by part of their name or email address. Returns the number of "
    "matches and the matching members, each with how many books they have on loan.",
    params=SearchMembers,
    status="Looking up members",
    run=_search_members,
    render=_render_members,
)

GET_MEMBER_LOANS = Tool(
    name="get_member_loans",
    description="One member's loans: current loans with due dates and overdue marks, or past "
    "loans. Includes today's date.",
    params=GetMemberLoans,
    status="Checking the member's loans",
    run=_get_member_loans,
    render=_render_member_loans,
)

GET_BOOK_LOANS = Tool(
    name="get_book_loans",
    description="One book's loans: who has its copies now, with due dates and overdue marks, "
    "or its past loans. Includes today's date.",
    params=GetBookLoans,
    status="Checking the book's loans",
    run=_get_book_loans,
    render=_render_book_loans,
)

BOOK_HOLDS = Tool(
    name="book_holds",
    description="One book's holds: who has a copy set aside and the day to pick it up by, then "
    "who is waiting, in line order, and how many members are waiting; or its past holds and "
    "how each ended. Includes today's date.",
    params=BookHolds,
    status="Checking the book's holds",
    run=_book_holds,
    render=_render_book_holds,
)

GET_OVERDUE_LOANS = Tool(
    name="get_overdue_loans",
    description="The overdue loans, longest overdue first, with who has each copy, and how "
    "many loans are overdue in total. Includes today's date.",
    params=GetOverdueLoans,
    status="Checking overdue loans",
    run=_get_overdue_loans,
    render=_render_overdue_loans,
)

LOOKUP_COPY = Tool(
    name="lookup_copy",
    description="Look up one copy by its code: its book, whether it is on loan, and if so to "
    "whom and until when, or whether it is set aside for a member's hold, and if so for whom "
    "and until when.",
    params=LookupCopy,
    status="Looking up the copy",
    run=_lookup_copy,
    render=_render_copy,
)

PREPARE_BORROW = Tool(
    name="prepare_borrow",
    description="Prepare lending a copy to a member, for the staff member to confirm. Checks "
    "that the loan can be made and shows a card with Confirm and Cancel. Changes nothing: the "
    "loan is made only if the staff member presses Confirm.",
    params=PrepareBorrow,
    status="Preparing the borrow",
    run=_prepare_borrow,
    render=_render_proposal,
)

PREPARE_RETURN = Tool(
    name="prepare_return",
    description="Prepare the return of a copy on loan, for the staff member to confirm. Finds "
    "the copy's loan and shows a card with Confirm and Cancel. Changes nothing: the copy is "
    "returned only if the staff member presses Confirm.",
    params=PrepareReturn,
    status="Preparing the return",
    run=_prepare_return,
    render=_render_proposal,
)
