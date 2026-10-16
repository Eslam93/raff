"""Every endpoint, called anonymously, as a member and as staff.

Public: health, auth config, demo sign-in, logout and the Google routes (404 here, because the
test settings do not configure Google). Signed-in: reading the catalog and its categories, the
current user, My loans and My holds with renewing one's own loan and placing and cancelling one's
own holds (404 no_member_profile for staff, who have no member record) and the Copilot (503
copilot_unavailable, because the test settings configure no model). Everything else is staff
only, including the dashboard, the loans list, renewing any loan, the holds list, placing and
cancelling holds for members, copy lookup, member detail, the ISBN lookup (503
isbn_lookup_unavailable for staff, because the test settings turn it off) and the Copilot's
proposals: 401 unauthorized when signed out, 403 forbidden for members.
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pytest
from sqlalchemy import select

from app.copilot import proposals
from app.models import User

pytestmark = pytest.mark.integration

World = dict[str, str]


@dataclass(frozen=True)
class Endpoint:
    method: str
    # Placeholders name values from the world fixture: {book}, {spare_book}, {loan}, ...
    path: str
    anonymous: int
    member: int
    staff: int
    body: Callable[[World], dict[str, Any]] | None = None


ENDPOINTS = [
    Endpoint("GET", "/api/health", 200, 200, 200),
    Endpoint("GET", "/api/auth/config", 200, 200, 200),
    Endpoint("POST", "/api/auth/demo", 200, 200, 200, lambda _: {"role": "member"}),
    Endpoint("GET", "/api/auth/google/login", 404, 404, 404),
    Endpoint("GET", "/api/auth/google/callback", 404, 404, 404),
    Endpoint("GET", "/api/auth/me", 401, 200, 200),
    Endpoint("POST", "/api/auth/logout", 204, 204, 204),
    Endpoint("GET", "/api/me/loans", 401, 200, 404),
    Endpoint("POST", "/api/me/loans/{my_loan}/renew", 401, 200, 404),
    Endpoint("GET", "/api/me/holds", 401, 200, 404),
    Endpoint("POST", "/api/me/holds", 401, 201, 404, lambda world: {"book_id": world["out_book"]}),
    Endpoint("POST", "/api/me/holds/{my_hold}/cancel", 401, 200, 404),
    Endpoint("GET", "/api/dashboard", 401, 403, 200),
    Endpoint("GET", "/api/books", 401, 200, 200),
    Endpoint("GET", "/api/books/categories", 401, 200, 200),
    Endpoint("GET", "/api/books/{book}", 401, 200, 200),
    Endpoint("POST", "/api/books", 401, 403, 201, lambda _: {"title": "New", "author": "A"}),
    Endpoint("PATCH", "/api/books/{book}", 401, 403, 200, lambda _: {"category": "SF"}),
    Endpoint("DELETE", "/api/books/{spare_book}", 401, 403, 200),
    Endpoint("POST", "/api/books/{book}/copies", 401, 403, 201, lambda _: {"count": 1}),
    # The test settings turn the lookup off, so staff get 503 and nothing reaches the network.
    Endpoint("GET", "/api/isbn/{isbn}", 401, 403, 503),
    Endpoint("GET", "/api/copies/by-code/{copy_code}", 401, 403, 200),
    Endpoint("GET", "/api/members", 401, 403, 200),
    Endpoint("POST", "/api/members", 401, 403, 201, lambda _: {"full_name": "New Member"}),
    Endpoint("GET", "/api/members/{member}", 401, 403, 200),
    Endpoint("GET", "/api/loans", 401, 403, 200),
    Endpoint(
        "POST",
        "/api/loans",
        401,
        403,
        201,
        lambda world: {"copy_id": world["free_copy"], "member_id": world["member"]},
    ),
    Endpoint("POST", "/api/loans/{loan}/return", 401, 403, 200),
    Endpoint("POST", "/api/loans/{loan}/renew", 401, 403, 200),
    Endpoint("GET", "/api/holds", 401, 403, 200),
    Endpoint(
        "POST",
        "/api/holds",
        401,
        403,
        201,
        lambda world: {"book_id": world["out_book"], "member_id": world["demo_member"]},
    ),
    Endpoint("POST", "/api/holds/{my_hold}/cancel", 401, 403, 200),
    Endpoint("GET", "/api/activity", 401, 403, 200),
    Endpoint("GET", "/api/copilot/config", 401, 200, 200),
    # The test settings configure no model, so signed-in users get 503 before any stream.
    Endpoint("POST", "/api/copilot/chat", 401, 503, 503, lambda _: {"message": "Hello"}),
    Endpoint("GET", "/api/copilot/proposals/{proposal}", 401, 403, 200),
    Endpoint("POST", "/api/copilot/proposals/{proposal}/confirm", 401, 403, 200),
    Endpoint("POST", "/api/copilot/proposals/{proposal}/cancel", 401, 403, 204),
]

ROLES = ["anonymous", "member", "staff"]


@pytest.fixture
async def world(make_book, make_member, borrow, client, empty_db, open_client) -> World:
    """A book with one copy on loan and one free, a book without loans, a member, and a
    proposal to lend the free copy, prepared for the demo staff account. For the demo member
    account: a loan of their own, a hold of their own on a book whose only copy is out, and a
    second book whose only copy is out, which they have no hold on.
    """
    book = await make_book(copies=2)
    spare = await make_book(title="Spare", author="Nobody")
    member = await make_member()
    loan = (await borrow(book["copies"][0]["id"], member["id"])).json()
    staff = await empty_db.scalar(select(User).where(User.role == "staff", User.is_demo))
    proposal = await proposals.prepare_borrow(
        empty_db,
        user=staff,
        conversation_id=None,
        member_id=uuid.UUID(member["id"]),
        copy_code=book["copies"][1]["code"],
        loan_period_days=14,
    )
    demo_member = (await (await open_client("member")).get("/api/auth/me")).json()["member_id"]
    held_book = await make_book(title="Held", author="Nobody")
    await borrow(held_book["copies"][0]["id"], member["id"])
    hold = await client.post(
        "/api/holds", json={"book_id": held_book["id"], "member_id": demo_member}
    )
    out_book = await make_book(title="Out", author="Nobody")
    await borrow(out_book["copies"][0]["id"], member["id"])
    own_book = await make_book(title="Own", author="Nobody")
    my_loan = (await borrow(own_book["copies"][0]["id"], demo_member)).json()
    return {
        "book": book["id"],
        "spare_book": spare["id"],
        "free_copy": book["copies"][1]["id"],
        "copy_code": book["copies"][0]["code"],
        "member": member["id"],
        "loan": loan["id"],
        "proposal": str(proposal.id),
        "isbn": "9780547928227",
        "demo_member": demo_member,
        "my_loan": my_loan["id"],
        "my_hold": hold.json()["id"],
        "out_book": out_book["id"],
    }


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("endpoint", ENDPOINTS, ids=lambda e: f"{e.method} {e.path}")
async def test_endpoint_answers_each_role_as_the_permissions_say(
    endpoint, role, world, open_client
):
    http = await open_client(None if role == "anonymous" else role)
    body = endpoint.body(world) if endpoint.body else None

    response = await http.request(endpoint.method, endpoint.path.format(**world), json=body)

    assert response.status_code == getattr(endpoint, role), response.text
    if response.status_code == 401:
        assert response.json()["error"]["code"] == "unauthorized"
    if response.status_code == 403:
        assert response.json()["error"]["code"] == "forbidden"


def test_the_matrix_covers_every_api_route(make_app):
    """A new route fails this test until it is added to the matrix above."""

    def shape(path: str) -> str:
        """/api/books/{book_id} and /api/books/{book} both become /api/books/{}."""
        return "/".join("{}" if part.startswith("{") else part for part in path.split("/"))

    paths = make_app().openapi()["paths"]
    routes = {
        (method.upper(), shape(path)) for path, methods in paths.items() for method in methods
    }
    covered = {(endpoint.method, shape(endpoint.path)) for endpoint in ENDPOINTS}

    assert routes == covered
