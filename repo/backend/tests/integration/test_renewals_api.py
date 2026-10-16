"""Renewing a loan: the new due date, the record of each renewal, the limits, and members
renewing their own loans.
"""

import uuid
from datetime import UTC, datetime, time, timedelta

import pytest
from sqlalchemy import func, select, update

from app.models import Loan, Renewal
from app.services.activity import format_day

pytestmark = pytest.mark.integration


def utc_today():
    return datetime.now(UTC).date()


def parse(timestamp: str) -> datetime:
    return datetime.fromisoformat(timestamp.replace("Z", "+00:00"))


def end_of(day) -> datetime:
    return datetime.combine(day, time(23, 59, 59, tzinfo=UTC))


def due_in(days: int) -> str:
    return (utc_today() + timedelta(days=days)).isoformat()


@pytest.fixture
async def maya(make_member):
    return await make_member("Maya Hassan")


@pytest.fixture
async def dune(make_book):
    return await make_book(title="Dune", author="Frank Herbert", copies=1)


@pytest.fixture
async def loan(dune, maya, borrow):
    """Maya's loan of Dune, due in 14 days."""
    response = await borrow(dune["copies"][0]["id"], maya["id"])
    assert response.status_code == 201, response.text
    return response.json()


async def renew(http, loan_id, *, own=False):
    path = f"/api/me/loans/{loan_id}/renew" if own else f"/api/loans/{loan_id}/renew"
    return await http.post(path)


def conflict_code(response):
    assert response.status_code == 409, response.text
    return response.json()["error"]["code"]


async def test_a_new_loan_can_be_renewed(loan):
    assert (loan["renewals"], loan["can_renew"]) == (0, True)


async def test_renewing_adds_the_loan_period_to_the_due_date_and_records_it(loan, client, empty_db):
    response = await renew(client, loan["id"])

    assert response.status_code == 200
    renewed = response.json()
    assert parse(renewed["due_at"]) == end_of(utc_today() + timedelta(days=28))
    assert (renewed["renewals"], renewed["can_renew"]) == (1, True)
    [record] = await empty_db.scalars(
        select(Renewal).where(Renewal.loan_id == uuid.UUID(loan["id"]))
    )
    assert record.previous_due_at == parse(loan["due_at"])
    assert record.new_due_at == parse(renewed["due_at"])
    listed = (await client.get("/api/loans")).json()["items"][0]
    assert (listed["renewals"], listed["due_at"]) == (1, renewed["due_at"])


async def test_an_overdue_loan_is_renewed_from_today(loan, client, empty_db):
    now = datetime.now(UTC)
    await empty_db.execute(
        update(Loan)
        .where(Loan.id == uuid.UUID(loan["id"]))
        .values(borrowed_at=now - timedelta(days=20), due_at=now - timedelta(days=6))
    )
    await empty_db.commit()

    response = await renew(client, loan["id"])

    assert response.status_code == 200
    renewed = response.json()
    assert parse(renewed["due_at"]) == end_of(utc_today() + timedelta(days=14))
    assert renewed["is_overdue"] is False


async def test_a_renewal_never_moves_the_due_date_past_90_days_from_today(
    dune, maya, borrow, client
):
    loan = (await borrow(dune["copies"][0]["id"], maya["id"], due_date=due_in(85))).json()

    renewed = (await renew(client, loan["id"])).json()

    assert parse(renewed["due_at"]) == end_of(utc_today() + timedelta(days=90))


async def test_a_third_renewal_is_renewal_limit_reached(loan, client):
    first = await renew(client, loan["id"])
    second = await renew(client, loan["id"])
    third = await renew(client, loan["id"])

    assert (first.status_code, second.status_code) == (200, 200)
    assert (second.json()["renewals"], second.json()["can_renew"]) == (2, False)
    assert conflict_code(third) == "renewal_limit_reached"
    assert parse(second.json()["due_at"]) == end_of(utc_today() + timedelta(days=42))


async def test_a_renewal_while_a_member_waits_for_the_book_is_book_has_holds(
    loan, dune, make_member, client
):
    omar = await make_member("Omar Farouk")
    await client.post("/api/holds", json={"book_id": dune["id"], "member_id": omar["id"]})

    response = await renew(client, loan["id"])

    assert conflict_code(response) == "book_has_holds"
    listed = (await client.get("/api/loans")).json()["items"][0]
    assert (listed["renewals"], listed["can_renew"]) == (0, False)


async def test_renewing_a_returned_loan_is_loan_already_returned(loan, client):
    returned = (await client.post(f"/api/loans/{loan['id']}/return")).json()

    response = await renew(client, loan["id"])

    assert returned["can_renew"] is False
    assert conflict_code(response) == "loan_already_returned"


async def test_renewing_an_unknown_loan_is_404(client):
    response = await renew(client, uuid.uuid4())

    assert response.status_code == 404


async def test_a_renewal_is_recorded_with_both_due_dates(loan, client):
    renewed = (await renew(client, loan["id"])).json()

    events = (await client.get("/api/activity")).json()

    event = next(event for event in events if event["action"] == "loan.renewed")
    previous, new = parse(loan["due_at"]).date(), parse(renewed["due_at"]).date()
    code = loan["copy"]["code"]
    assert event["summary"] == (
        f"Renewed Dune ({code}) for Maya Hassan, due {format_day(new)} "
        f"instead of {format_day(previous)}"
    )
    assert (event["entity_type"], event["entity_id"], event["via"]) == ("loan", loan["id"], "ui")


async def test_the_renewal_limit_and_loan_period_come_from_settings(make_db_app, serve, sign_in):
    app = make_db_app(max_renewals=1, loan_period_days=7)

    async with serve(app) as http:
        await sign_in(http, "staff")
        book = (await http.post("/api/books", json={"title": "Dune", "author": "F"})).json()
        member = (await http.post("/api/members", json={"full_name": "Maya"})).json()
        loan = (
            await http.post(
                "/api/loans", json={"copy_id": book["copies"][0]["id"], "member_id": member["id"]}
            )
        ).json()
        first = await renew(http, loan["id"])
        second = await renew(http, loan["id"])

    assert parse(first.json()["due_at"]) == end_of(utc_today() + timedelta(days=14))
    assert first.json()["can_renew"] is False
    assert conflict_code(second) == "renewal_limit_reached"
    assert second.json()["error"]["message"] == (
        "This loan cannot be renewed again: the limit is 1 renewal."
    )


async def test_a_loan_already_due_at_the_furthest_date_is_renewal_not_needed(
    dune, maya, borrow, client, empty_db
):
    response = await borrow(dune["copies"][0]["id"], maya["id"], due_date=due_in(90))
    assert response.status_code == 201, response.text
    loan = response.json()

    refused = await renew(client, loan["id"])

    assert conflict_code(refused) == "renewal_not_needed"
    assert parse(loan["due_at"]) == end_of(utc_today() + timedelta(days=90))
    count = await empty_db.scalar(
        select(func.count()).select_from(Renewal).where(Renewal.loan_id == uuid.UUID(loan["id"]))
    )
    assert count == 0


# Members


async def test_a_member_renews_their_own_loan(dune, borrow, member_client):
    me = (await member_client.get("/api/auth/me")).json()
    loan = (await borrow(dune["copies"][0]["id"], me["member_id"])).json()

    response = await renew(member_client, loan["id"], own=True)

    assert response.status_code == 200
    assert response.json()["renewals"] == 1
    [listed] = (await member_client.get("/api/me/loans")).json()["items"]
    assert (listed["renewals"], listed["can_renew"]) == (1, True)


async def test_a_member_cannot_renew_another_members_loan(loan, client, member_client):
    response = await renew(member_client, loan["id"], own=True)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
    unchanged = (await client.get("/api/loans")).json()["items"][0]
    assert (unchanged["renewals"], unchanged["due_at"]) == (0, loan["due_at"])


async def test_a_member_cannot_use_the_staff_renewal(loan, member_client):
    response = await renew(member_client, loan["id"])

    assert response.status_code == 403
