import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import update

from app.models import Loan

pytestmark = pytest.mark.integration

LOAN_FIELDS = {
    "id",
    "copy",
    "book",
    "member",
    "borrowed_at",
    "due_at",
    "returned_at",
    "is_overdue",
    "days_overdue",
    "renewals",
    "can_renew",
}


def utc_today() -> date:
    return datetime.now(UTC).date()


def parse(timestamp: str) -> datetime:
    return datetime.fromisoformat(timestamp.replace("Z", "+00:00"))


@pytest.fixture
async def dune(make_book):
    return await make_book(title="Dune", author="Frank Herbert", copies=2)


@pytest.fixture
async def maya(make_member):
    return await make_member("Maya Hassan")


# Borrow


async def test_borrow_creates_an_active_loan_due_after_the_loan_period(dune, maya, borrow, client):
    copy = dune["copies"][0]

    response = await borrow(copy["id"], maya["id"])

    assert response.status_code == 201
    loan = response.json()
    assert set(loan) == LOAN_FIELDS
    assert loan["copy"] == {"id": copy["id"], "code": copy["code"]}
    assert loan["book"] == {"id": dune["id"], "title": "Dune", "author": "Frank Herbert"}
    assert loan["member"] == {"id": maya["id"], "full_name": "Maya Hassan"}
    assert loan["returned_at"] is None
    assert loan["is_overdue"] is False
    due_at = parse(loan["due_at"])
    assert due_at.date() == utc_today() + timedelta(days=14)
    assert (due_at.hour, due_at.minute, due_at.second) == (23, 59, 59)
    assert due_at.utcoffset() == timedelta(0)


async def test_borrowed_copy_shows_as_unavailable(dune, maya, borrow, client):
    copy = dune["copies"][0]
    await borrow(copy["id"], maya["id"])

    detail = (await client.get(f"/api/books/{dune['id']}")).json()
    summary = (await client.get("/api/books")).json()["items"][0]

    assert (detail["copies_total"], detail["copies_available"]) == (2, 1)
    assert detail["availability"] == "available"
    borrowed = next(c for c in detail["copies"] if c["id"] == copy["id"])
    assert borrowed["status"] == "borrowed"
    assert borrowed["due_at"] == borrowed["active_loan"]["due_at"]
    assert borrowed["active_loan"]["member"] == {"id": maya["id"], "full_name": "Maya Hassan"}
    assert borrowed["active_loan"]["is_overdue"] is False
    assert detail["has_loan_history"] is True
    assert summary["copies_available"] == 1


async def test_book_with_every_copy_borrowed_is_all_borrowed(make_book, maya, borrow, client):
    book = await make_book(copies=1)
    await borrow(book["copies"][0]["id"], maya["id"])

    [summary] = (await client.get("/api/books")).json()["items"]

    assert summary["availability"] == "all_borrowed"
    assert summary["copies_available"] == 0


async def test_borrowing_a_copy_on_loan_is_409(dune, maya, make_member, borrow):
    copy_id = dune["copies"][0]["id"]
    await borrow(copy_id, maya["id"])
    omar = await make_member("Omar Farouk")

    response = await borrow(copy_id, omar["id"])

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "copy_unavailable"


async def test_borrowing_a_copy_of_an_archived_book_is_409(dune, maya, borrow, client):
    loan = (await borrow(dune["copies"][0]["id"], maya["id"])).json()
    await client.post(f"/api/loans/{loan['id']}/return")
    await client.delete(f"/api/books/{dune['id']}")

    response = await borrow(dune["copies"][1]["id"], maya["id"])

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "book_archived"


async def test_borrowing_an_unknown_copy_or_member_is_404(dune, maya, borrow):
    unknown_copy = await borrow(str(uuid.uuid4()), maya["id"])
    unknown_member = await borrow(dune["copies"][0]["id"], str(uuid.uuid4()))

    assert unknown_copy.status_code == 404
    assert unknown_copy.json()["error"]["message"] == "Copy not found."
    assert unknown_member.status_code == 404
    assert unknown_member.json()["error"]["message"] == "Member not found."


async def test_borrow_needs_copy_and_member(client):
    response = await client.post("/api/loans", json={})

    locations = {tuple(e["location"]) for e in response.json()["error"]["details"]["errors"]}
    assert response.status_code == 422
    assert locations == {("body", "copy_id"), ("body", "member_id")}


# Due dates


@pytest.mark.parametrize("days_ahead", [1, 30, 90])
async def test_chosen_due_date_is_kept_and_due_at_the_end_of_that_day(
    dune, maya, borrow, days_ahead
):
    due_date = utc_today() + timedelta(days=days_ahead)

    response = await borrow(dune["copies"][0]["id"], maya["id"], due_date=due_date.isoformat())

    assert response.status_code == 201
    due_at = parse(response.json()["due_at"])
    assert due_at.date() == due_date
    assert due_at.hour == 23


@pytest.mark.parametrize(
    ("days_ahead", "error_type"),
    [(0, "due_date_not_in_future"), (-3, "due_date_not_in_future"), (91, "due_date_too_far")],
)
async def test_due_date_must_be_after_today_and_within_90_days(
    dune, maya, borrow, days_ahead, error_type
):
    due_date = utc_today() + timedelta(days=days_ahead)

    response = await borrow(dune["copies"][0]["id"], maya["id"], due_date=due_date.isoformat())

    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "validation_failed"
    [error] = body["error"]["details"]["errors"]
    assert set(error) == {"location", "message", "type"}
    assert error["location"] == ["body", "due_date"]
    assert error["type"] == error_type
    assert "due date" in error["message"]


async def test_loan_period_comes_from_settings(make_db_app, serve, sign_in):
    app = make_db_app(loan_period_days=7)

    async with serve(app) as http:
        await sign_in(http, "staff")
        book = (await http.post("/api/books", json={"title": "Dune", "author": "F"})).json()
        member = (await http.post("/api/members", json={"full_name": "Maya"})).json()
        response = await http.post(
            "/api/loans", json={"copy_id": book["copies"][0]["id"], "member_id": member["id"]}
        )

    assert parse(response.json()["due_at"]).date() == utc_today() + timedelta(days=7)


# Overdue


async def test_active_loan_past_its_due_time_is_overdue(dune, maya, borrow, client, empty_db):
    loan = (await borrow(dune["copies"][0]["id"], maya["id"])).json()
    await empty_db.execute(
        update(Loan)
        .where(Loan.id == uuid.UUID(loan["id"]))
        .values(
            borrowed_at=datetime.now(UTC) - timedelta(days=20),
            due_at=datetime.now(UTC) - timedelta(days=6),
        )
    )
    await empty_db.commit()

    detail = (await client.get(f"/api/books/{dune['id']}")).json()
    returned = (await client.post(f"/api/loans/{loan['id']}/return")).json()

    borrowed = next(c for c in detail["copies"] if c["status"] == "borrowed")
    assert borrowed["active_loan"]["is_overdue"] is True
    # A returned loan is no longer overdue.
    assert returned["is_overdue"] is False


# Return


async def test_return_closes_the_loan_and_frees_the_copy(dune, maya, borrow, client):
    copy_id = dune["copies"][0]["id"]
    loan = (await borrow(copy_id, maya["id"])).json()

    response = await client.post(f"/api/loans/{loan['id']}/return")

    assert response.status_code == 200
    returned = response.json()
    assert set(returned) == LOAN_FIELDS
    assert returned["returned_at"] is not None
    assert parse(returned["returned_at"]) >= parse(returned["borrowed_at"])
    detail = (await client.get(f"/api/books/{dune['id']}")).json()
    assert detail["copies_available"] == 2
    assert all(c["status"] == "available" for c in detail["copies"])


async def test_returned_copy_can_be_borrowed_again(dune, maya, borrow, client):
    copy_id = dune["copies"][0]["id"]
    loan = (await borrow(copy_id, maya["id"])).json()
    await client.post(f"/api/loans/{loan['id']}/return")

    again = await borrow(copy_id, maya["id"])

    assert again.status_code == 201


async def test_returning_twice_is_409(dune, maya, borrow, client):
    loan = (await borrow(dune["copies"][0]["id"], maya["id"])).json()
    await client.post(f"/api/loans/{loan['id']}/return")

    response = await client.post(f"/api/loans/{loan['id']}/return")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "loan_already_returned"


async def test_returning_an_unknown_loan_is_404(client):
    response = await client.post(f"/api/loans/{uuid.uuid4()}/return")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
