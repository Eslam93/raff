"""Holds: placing one, the line, a returned copy set aside for the first in line, borrowing a held
copy, expiry, cancelling, and what members see and may do.

During a test the database's now() is when the test's transaction began, so a ready hold is
made to lapse by moving its pick-up time an hour into the past.
"""

import uuid
from datetime import UTC, datetime, time, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select, update

from app.models import ActivityEvent, Hold
from app.services import circulation, holds
from app.services.activity import format_day, format_short_day

pytestmark = pytest.mark.integration

HOLD_FIELDS = {
    "id",
    "status",
    "book",
    "member",
    "copy",
    "placed_at",
    "ready_at",
    "pickup_by",
    "closed_at",
    "position",
}


def utc_today():
    return datetime.now(UTC).date()


def parse(timestamp: str) -> datetime:
    return datetime.fromisoformat(timestamp.replace("Z", "+00:00"))


def pickup_day(days: int = 3):
    """The pick-up date of a hold made ready today."""
    return utc_today() + timedelta(days=days)


@pytest.fixture
async def maya(make_member):
    return await make_member("Maya Hassan")


@pytest.fixture
async def omar(make_member):
    return await make_member("Omar Farouk")


@pytest.fixture
async def lina(make_member):
    return await make_member("Lina Saleh")


@pytest.fixture
async def out_book(make_book, make_member, borrow):
    """Dune with one copy, lent to Sara Ali: no copy of it is on the shelf."""
    book = await make_book(title="Dune", author="Frank Herbert", copies=1)
    sara = await make_member("Sara Ali")
    loan = (await borrow(book["copies"][0]["id"], sara["id"])).json()
    return SimpleNamespace(id=book["id"], copy=book["copies"][0], loan=loan, borrower=sara)


@pytest.fixture
async def me(member_client):
    """The demo member account's UserOut, signed in on member_client."""
    return (await member_client.get("/api/auth/me")).json()


async def place(http, book_id, member_id=None):
    """Staff place a hold for the member; without a member, the signed-in member places one."""
    if member_id is None:
        return await http.post("/api/me/holds", json={"book_id": book_id})
    return await http.post("/api/holds", json={"book_id": book_id, "member_id": member_id})


async def placed(http, book_id, member_id=None):
    response = await place(http, book_id, member_id)
    assert response.status_code == 201, response.text
    return response.json()


async def holds_by_id(client, **params):
    response = await client.get("/api/holds", params={"status": "all", "limit": 100, **params})
    assert response.status_code == 200, response.text
    return {hold["id"]: hold for hold in response.json()["items"]}


async def return_loan(client, loan):
    response = await client.post(f"/api/loans/{loan['id']}/return")
    assert response.status_code == 200, response.text
    return response.json()


def conflict_code(response):
    assert response.status_code == 409, response.text
    return response.json()["error"]["code"]


@pytest.fixture
def lapse(empty_db):
    """Moves a ready hold's pick-up time an hour into the past, as if the days had gone by."""

    async def _lapse(hold_id: str) -> None:
        await empty_db.execute(
            update(Hold)
            .where(Hold.id == uuid.UUID(hold_id))
            .values(pickup_by=datetime.now(UTC) - timedelta(hours=1))
        )
        await empty_db.commit()

    return _lapse


async def actions(client):
    """The activity record, oldest first, as (action, summary, via)."""
    events = (await client.get("/api/activity", params={"limit": 200})).json()
    return [(event["action"], event["summary"], event["via"]) for event in reversed(events)]


# Placing a hold


async def test_a_hold_on_a_book_with_every_copy_out_waits_with_its_place_in_line(
    out_book, maya, omar, client
):
    response = await place(client, out_book.id, maya["id"])
    second = await placed(client, out_book.id, omar["id"])

    assert response.status_code == 201
    first = response.json()
    assert set(first) == HOLD_FIELDS
    assert first["status"] == "waiting"
    assert first["book"] == {"id": out_book.id, "title": "Dune", "author": "Frank Herbert"}
    assert first["member"] == {"id": maya["id"], "full_name": "Maya Hassan"}
    assert (first["copy"], first["ready_at"], first["pickup_by"], first["closed_at"]) == (
        None,
        None,
        None,
        None,
    )
    assert first["position"] == 1
    assert second["position"] == 2
    listed = (await client.get("/api/holds", params={"book_id": out_book.id})).json()
    assert [(hold["id"], hold["position"]) for hold in listed["items"]] == [
        (first["id"], 1),
        (second["id"], 2),
    ]
    detail = (await client.get(f"/api/books/{out_book.id}")).json()
    assert detail["holds_waiting"] == 2


async def test_a_second_hold_by_the_same_member_on_the_same_book_is_hold_exists(
    out_book, maya, client
):
    await placed(client, out_book.id, maya["id"])

    response = await place(client, out_book.id, maya["id"])

    assert conflict_code(response) == "hold_exists"
    assert response.json()["error"]["message"] == "Maya Hassan already has a hold on Dune."


async def test_a_hold_while_a_copy_is_on_the_shelf_is_copy_available(make_book, maya, client):
    book = await make_book(copies=1)

    response = await place(client, book["id"], maya["id"])

    assert conflict_code(response) == "copy_available"


async def test_a_hold_on_a_book_the_member_has_borrowed_is_already_borrowed(out_book, client):
    response = await place(client, out_book.id, out_book.borrower["id"])

    assert conflict_code(response) == "already_borrowed"


async def test_a_sixth_open_hold_is_hold_limit_reached(
    make_book, make_member, borrow, maya, client
):
    sara = await make_member("Sara Ali")
    books = []
    for number in range(6):
        book = await make_book(title=f"Book {number}", copies=1)
        await borrow(book["copies"][0]["id"], sara["id"])
        books.append(book)
    for book in books[:5]:
        await placed(client, book["id"], maya["id"])

    response = await place(client, books[5]["id"], maya["id"])

    assert conflict_code(response) == "hold_limit_reached"
    assert response.json()["error"]["message"] == (
        "Maya Hassan already has 5 open holds, the most allowed."
    )


async def test_a_ready_hold_past_its_pick_up_time_does_not_count_toward_the_limit(
    make_book, make_member, borrow, maya, client, lapse
):
    sara = await make_member("Sara Ali")
    books, loans = [], []
    for number in range(6):
        book = await make_book(title=f"Book {number}", copies=1)
        loans.append((await borrow(book["copies"][0]["id"], sara["id"])).json())
        books.append(book)
    held = [await placed(client, book["id"], maya["id"]) for book in books[:5]]
    await return_loan(client, loans[0])
    await lapse(held[0]["id"])

    response = await place(client, books[5]["id"], maya["id"])

    assert response.status_code == 201, response.text


async def test_the_open_hold_limit_comes_from_settings(make_db_app, serve, sign_in):
    app = make_db_app(max_open_holds=1)

    async with serve(app) as http:
        await sign_in(http, "staff")
        sara = (await http.post("/api/members", json={"full_name": "Sara"})).json()
        maya = (await http.post("/api/members", json={"full_name": "Maya"})).json()
        ids = []
        for title in ("One", "Two"):
            book = (await http.post("/api/books", json={"title": title, "author": "A"})).json()
            await http.post(
                "/api/loans", json={"copy_id": book["copies"][0]["id"], "member_id": sara["id"]}
            )
            ids.append(book["id"])
        first = await place(http, ids[0], maya["id"])
        second = await place(http, ids[1], maya["id"])

    assert first.status_code == 201
    assert conflict_code(second) == "hold_limit_reached"


async def test_a_hold_on_an_archived_book_is_book_archived(out_book, maya, client):
    await return_loan(client, out_book.loan)
    await client.delete(f"/api/books/{out_book.id}")

    response = await place(client, out_book.id, maya["id"])

    assert conflict_code(response) == "book_archived"


async def test_a_hold_for_an_unknown_book_or_member_is_404(out_book, maya, client):
    unknown_book = await place(client, str(uuid.uuid4()), maya["id"])
    unknown_member = await place(client, out_book.id, str(uuid.uuid4()))

    assert unknown_book.status_code == 404
    assert unknown_book.json()["error"]["message"] == "Book not found."
    assert unknown_member.status_code == 404
    assert unknown_member.json()["error"]["message"] == "Member not found."


async def test_refusals_come_in_the_agreed_order(make_book, make_member, borrow, maya, client):
    # already_borrowed before copy_available: the borrower of one copy, with another free.
    two_copies = await make_book(title="Two copies", copies=2)
    sara = await make_member("Sara Ali")
    await borrow(two_copies["copies"][0]["id"], sara["id"])
    # hold_exists before copy_available: Maya's hold is ready on one new copy, another is free.
    one_copy = await make_book(title="One copy", copies=1)
    await borrow(one_copy["copies"][0]["id"], sara["id"])
    await placed(client, one_copy["id"], maya["id"])
    await client.post(f"/api/books/{one_copy['id']}/copies", json={"count": 2})

    borrowed_and_free = await place(client, two_copies["id"], sara["id"])
    held_and_free = await place(client, one_copy["id"], maya["id"])

    assert conflict_code(borrowed_and_free) == "already_borrowed"
    assert conflict_code(held_and_free) == "hold_exists"


async def test_placing_a_hold_is_recorded_with_the_place_in_line(out_book, maya, omar, client):
    await placed(client, out_book.id, maya["id"])
    await placed(client, out_book.id, omar["id"])

    recorded = [entry for entry in await actions(client) if entry[0] == "hold.placed"]

    assert recorded == [
        ("hold.placed", "Placed a hold on Dune for Maya Hassan, number 1 in line", "ui"),
        ("hold.placed", "Placed a hold on Dune for Omar Farouk, number 2 in line", "ui"),
    ]


# A copy comes back


async def test_a_returned_copy_is_set_aside_for_the_oldest_waiting_hold(
    out_book, maya, omar, client
):
    first = await placed(client, out_book.id, maya["id"])
    second = await placed(client, out_book.id, omar["id"])

    await return_loan(client, out_book.loan)

    found = await holds_by_id(client, book_id=out_book.id)
    ready, waiting = found[first["id"]], found[second["id"]]
    assert ready["status"] == "ready"
    assert ready["copy"] == {"id": out_book.copy["id"], "code": out_book.copy["code"]}
    assert ready["ready_at"] is not None
    assert parse(ready["pickup_by"]) == datetime.combine(pickup_day(), time(23, 59, 59, tzinfo=UTC))
    assert ready["position"] is None
    assert (waiting["status"], waiting["position"]) == ("waiting", 1)
    summary = (
        f"Set Dune ({out_book.copy['code']}) aside for Maya Hassan, "
        f"to pick up by {format_day(pickup_day())}"
    )
    assert ("hold.ready", summary, "ui") in await actions(client)


async def test_a_held_copy_counts_as_unavailable_everywhere(out_book, maya, client, member_client):
    await placed(client, out_book.id, maya["id"])
    await return_loan(client, out_book.loan)
    code = out_book.copy["code"]

    as_staff = (await client.get(f"/api/books/{out_book.id}")).json()
    as_member = (await member_client.get(f"/api/books/{out_book.id}")).json()
    [summary] = (await client.get("/api/books")).json()["items"]
    shelf = (await client.get("/api/books", params={"available_only": True})).json()
    lookup = (await client.get(f"/api/copies/by-code/{code}")).json()
    counts = (await client.get("/api/dashboard")).json()["counts"]

    assert (as_staff["copies_available"], as_staff["availability"]) == (0, "all_borrowed")
    [copy] = as_staff["copies"]
    held_for = {
        "member": {"id": maya["id"], "full_name": "Maya Hassan"},
        "pickup_by": copy["held_for"]["pickup_by"],
    }
    assert (copy["status"], copy["due_at"], copy["active_loan"]) == ("held", None, None)
    assert copy["held_for"] == held_for
    assert parse(held_for["pickup_by"]).date() == pickup_day()
    assert as_member["copies"][0]["status"] == "held"
    assert as_member["copies"][0]["held_for"] is None
    assert "Maya Hassan" not in str(as_member)
    assert summary["copies_available"] == 0
    assert shelf["items"] == []
    assert (lookup["status"], lookup["active_loan"], lookup["held_for"]) == ("held", None, held_for)
    assert (counts["copies"], counts["available"], counts["on_loan"]) == (1, 0, 0)


async def test_a_return_with_nobody_waiting_puts_the_copy_back_on_the_shelf(out_book, client):
    await return_loan(client, out_book.loan)

    lookup = (await client.get(f"/api/copies/by-code/{out_book.copy['code']}")).json()

    assert (lookup["status"], lookup["held_for"]) == ("available", None)


async def test_new_copies_are_set_aside_for_the_members_in_line(out_book, maya, omar, client):
    first = await placed(client, out_book.id, maya["id"])
    second = await placed(client, out_book.id, omar["id"])

    response = await client.post(f"/api/books/{out_book.id}/copies", json={"count": 1})

    assert response.status_code == 201
    detail = response.json()
    new_copy = detail["copies"][1]
    assert new_copy["status"] == "held"
    assert new_copy["held_for"]["member"]["id"] == maya["id"]
    assert (detail["copies_available"], detail["holds_waiting"]) == (0, 1)
    found = await holds_by_id(client, book_id=out_book.id)
    assert found[first["id"]]["copy"]["id"] == new_copy["id"]
    assert (found[second["id"]]["status"], found[second["id"]]["position"]) == ("waiting", 1)


# Borrowing a held copy


async def test_only_the_member_a_copy_is_held_for_can_borrow_it(
    out_book, maya, omar, borrow, client
):
    hold = await placed(client, out_book.id, maya["id"])
    await return_loan(client, out_book.loan)
    copy = out_book.copy

    refused = await borrow(copy["id"], omar["id"])
    lent = await borrow(copy["id"], maya["id"])

    assert conflict_code(refused) == "copy_held"
    assert refused.json()["error"]["message"] == (
        f"Copy {copy['code']} is held for Maya Hassan until {format_short_day(pickup_day())}."
    )
    assert lent.status_code == 201, lent.text
    assert lent.json()["member"]["id"] == maya["id"]
    fulfilled = (await holds_by_id(client))[hold["id"]]
    assert fulfilled["status"] == "fulfilled"
    assert fulfilled["closed_at"] is not None
    detail = (await client.get(f"/api/books/{out_book.id}")).json()
    assert detail["copies"][0]["status"] == "borrowed"
    assert detail["holds_waiting"] == 0
    assert (
        "hold.fulfilled",
        f"Maya Hassan borrowed Dune ({copy['code']}), which fulfils their hold",
        "ui",
    ) in await actions(client)


async def test_borrowing_another_copy_fulfils_the_hold_and_frees_the_copy_it_kept(
    make_book, make_member, borrow, maya, client
):
    book = await make_book(copies=2)
    kept, other = book["copies"]
    sara, ali = await make_member("Sara Ali"), await make_member("Ali Nasser")
    first = (await borrow(kept["id"], sara["id"])).json()
    second = (await borrow(other["id"], ali["id"])).json()
    hold = await placed(client, book["id"], maya["id"])
    await return_loan(client, first)
    await return_loan(client, second)

    lent = await borrow(other["id"], maya["id"])

    assert lent.status_code == 201, lent.text
    assert (await holds_by_id(client))[hold["id"]]["status"] == "fulfilled"
    detail = (await client.get(f"/api/books/{book['id']}")).json()
    assert [copy["status"] for copy in detail["copies"]] == ["available", "borrowed"]
    assert detail["copies_available"] == 1


async def test_borrowing_the_book_picks_the_copy_held_for_the_member_first(
    make_book, make_member, borrow, maya, omar, client, empty_db
):
    book = await make_book(copies=2)
    free, held = book["copies"]
    sara, ali = await make_member("Sara Ali"), await make_member("Ali Nasser")
    on_free = (await borrow(free["id"], sara["id"])).json()
    on_held = (await borrow(held["id"], ali["id"])).json()
    await placed(client, book["id"], maya["id"])
    await return_loan(client, on_held)
    await return_loan(client, on_free)
    book_id = uuid.UUID(book["id"])

    for_maya = await circulation.first_available_copy(
        empty_db, book_id, member_id=uuid.UUID(maya["id"])
    )
    for_omar = await circulation.first_available_copy(
        empty_db, book_id, member_id=uuid.UUID(omar["id"])
    )
    for_anyone = await circulation.first_available_copy(empty_db, book_id)

    assert str(for_maya) == held["id"]
    assert str(for_omar) == str(for_anyone) == free["id"]


# Expiry


async def test_a_lapsed_hold_reads_as_expired_and_frees_its_copy_before_anything_writes(
    out_book, maya, client, lapse, empty_db
):
    hold = await placed(client, out_book.id, maya["id"])
    await return_loan(client, out_book.loan)

    await lapse(hold["id"])

    shown = (await holds_by_id(client))[hold["id"]]
    stored = await empty_db.scalar(select(Hold.status).where(Hold.id == uuid.UUID(hold["id"])))
    detail = (await client.get(f"/api/books/{out_book.id}")).json()
    lookup = (await client.get(f"/api/copies/by-code/{out_book.copy['code']}")).json()
    assert (shown["status"], stored) == ("expired", "ready")
    assert detail["copies_available"] == 1
    assert detail["copies"][0]["status"] == "available"
    assert lookup["status"] == "available"
    open_holds = (await client.get("/api/holds", params={"book_id": out_book.id})).json()
    assert open_holds["items"] == []


async def test_the_sweep_expires_a_lapsed_hold_and_gives_the_copy_to_the_next_in_line(
    out_book, maya, omar, client, lapse, empty_db
):
    first = await placed(client, out_book.id, maya["id"])
    second = await placed(client, out_book.id, omar["id"])
    await return_loan(client, out_book.loan)
    await lapse(first["id"])

    settled = await holds.sweep(empty_db, hold_pickup_days=3)

    assert settled == 1
    found = await holds_by_id(client)
    assert found[first["id"]]["status"] == "expired"
    assert found[first["id"]]["closed_at"] is not None
    assert found[second["id"]]["status"] == "ready"
    assert found[second["id"]]["copy"]["id"] == out_book.copy["id"]
    lookup = (await client.get(f"/api/copies/by-code/{out_book.copy['code']}")).json()
    assert lookup["held_for"]["member"]["id"] == omar["id"]
    code = out_book.copy["code"]
    recorded = [entry for entry in await actions(client) if entry[2] == "system"]
    assert recorded == [
        (
            "hold.expired",
            f"The hold of Maya Hassan on Dune expired: {code} was not picked up in time",
            "system",
        ),
        (
            "hold.ready",
            f"Set Dune ({code}) aside for Omar Farouk, to pick up by {format_day(pickup_day())}",
            "system",
        ),
    ]
    system_events = await empty_db.scalars(
        select(ActivityEvent).where(ActivityEvent.via == "system")
    )
    assert all(event.actor is None for event in system_events)


async def test_the_sweep_puts_the_copy_of_a_lapsed_hold_back_on_the_shelf(
    out_book, maya, client, lapse, empty_db
):
    hold = await placed(client, out_book.id, maya["id"])
    await return_loan(client, out_book.loan)
    await lapse(hold["id"])

    await holds.sweep(empty_db, hold_pickup_days=3)

    assert (await holds_by_id(client))[hold["id"]]["status"] == "expired"
    stored = await empty_db.scalar(select(Hold.status).where(Hold.id == uuid.UUID(hold["id"])))
    assert stored == "expired"
    lookup = (await client.get(f"/api/copies/by-code/{out_book.copy['code']}")).json()
    assert (lookup["status"], lookup["held_for"]) == ("available", None)


async def test_a_borrow_settles_the_book_first_so_the_next_in_line_keeps_their_turn(
    out_book, maya, omar, lina, borrow, client, lapse, empty_db
):
    first = await placed(client, out_book.id, maya["id"])
    second = await placed(client, out_book.id, omar["id"])
    await return_loan(client, out_book.loan)
    await lapse(first["id"])

    # Maya's hold has lapsed, so the copy is free by the rule until something writes. A borrow
    # settles the book before its checks: the copy goes to Omar, next in line, not to Lina.
    jumped = await borrow(out_book.copy["id"], lina["id"])
    lent = await borrow(out_book.copy["id"], omar["id"])

    assert conflict_code(jumped) == "copy_held"
    assert "held for Omar Farouk" in jumped.json()["error"]["message"]
    assert lent.status_code == 201, lent.text
    found = await holds_by_id(client)
    assert found[first["id"]]["status"] == "expired"
    assert found[second["id"]]["status"] == "fulfilled"
    stored = await empty_db.scalar(select(Hold.status).where(Hold.id == uuid.UUID(first["id"])))
    assert stored == "expired"


# Cancelling


async def test_cancelling_a_waiting_hold_moves_the_line_up(out_book, maya, omar, lina, client):
    first = await placed(client, out_book.id, maya["id"])
    second = await placed(client, out_book.id, omar["id"])
    third = await placed(client, out_book.id, lina["id"])

    response = await client.post(f"/api/holds/{second['id']}/cancel")

    assert response.status_code == 200
    cancelled = response.json()
    assert (cancelled["status"], cancelled["position"]) == ("cancelled", None)
    assert cancelled["closed_at"] is not None
    found = await holds_by_id(client)
    assert (found[first["id"]]["position"], found[third["id"]]["position"]) == (1, 2)
    assert ("hold.cancelled", "Cancelled the hold of Omar Farouk on Dune", "ui") in await actions(
        client
    )


async def test_cancelling_a_ready_hold_gives_the_copy_to_the_next_in_line(
    out_book, maya, omar, client
):
    first = await placed(client, out_book.id, maya["id"])
    second = await placed(client, out_book.id, omar["id"])
    await return_loan(client, out_book.loan)

    response = await client.post(f"/api/holds/{first['id']}/cancel")

    assert response.json()["status"] == "cancelled"
    next_in_line = (await holds_by_id(client))[second["id"]]
    assert next_in_line["status"] == "ready"
    assert next_in_line["copy"]["id"] == out_book.copy["id"]


async def test_cancelling_a_closed_hold_is_hold_closed(out_book, maya, omar, client, lapse):
    cancelled = await placed(client, out_book.id, omar["id"])
    await client.post(f"/api/holds/{cancelled['id']}/cancel")
    lapsed = await placed(client, out_book.id, maya["id"])
    await return_loan(client, out_book.loan)
    await lapse(lapsed["id"])

    again = await client.post(f"/api/holds/{cancelled['id']}/cancel")
    expired = await client.post(f"/api/holds/{lapsed['id']}/cancel")
    unknown = await client.post(f"/api/holds/{uuid.uuid4()}/cancel")

    assert conflict_code(again) == "hold_closed"
    assert conflict_code(expired) == "hold_closed"
    assert unknown.status_code == 404


async def test_a_book_that_leaves_the_catalog_cancels_its_open_holds(out_book, maya, omar, client):
    first = await placed(client, out_book.id, maya["id"])
    second = await placed(client, out_book.id, omar["id"])
    await return_loan(client, out_book.loan)

    deleted = await client.delete(f"/api/books/{out_book.id}")

    assert deleted.json() == {"outcome": "archived"}
    found = await holds_by_id(client)
    assert {found[first["id"]]["status"], found[second["id"]]["status"]} == {"cancelled"}


# The holds list


async def test_the_list_shows_ready_holds_first_then_the_line(
    make_book, make_member, borrow, maya, omar, lina, client
):
    book = await make_book(copies=2)
    sara = await make_member("Sara Ali")
    loans = [(await borrow(copy["id"], sara["id"])).json() for copy in book["copies"]]
    first = await placed(client, book["id"], maya["id"])
    second = await placed(client, book["id"], omar["id"])
    third = await placed(client, book["id"], lina["id"])
    await return_loan(client, loans[0])
    await client.post(f"/api/holds/{third['id']}/cancel")

    async def ids(**params):
        listed = (await client.get("/api/holds", params=params)).json()
        return [hold["id"] for hold in listed["items"]], listed["total"]

    assert await ids() == ([first["id"], second["id"]], 2)
    assert await ids(status="ready") == ([first["id"]], 1)
    assert await ids(status="waiting") == ([second["id"]], 1)
    assert await ids(status="closed") == ([third["id"]], 1)
    assert await ids(status="all") == ([first["id"], second["id"], third["id"]], 3)
    assert await ids(member_id=omar["id"]) == ([second["id"]], 1)
    assert await ids(status="all", limit=1, offset=1) == ([second["id"]], 3)


async def test_the_list_status_must_be_one_of_the_agreed_values(client):
    response = await client.get("/api/holds", params={"status": "lost"})

    assert response.status_code == 422


# Members


async def test_a_member_places_a_hold_and_sees_their_place_in_line(
    out_book, maya, me, client, member_client
):
    await placed(client, out_book.id, maya["id"])

    response = await place(member_client, out_book.id)

    assert response.status_code == 201
    mine = response.json()
    assert mine["member"] == {"id": me["member_id"], "full_name": me["display_name"]}
    assert (mine["status"], mine["position"]) == ("waiting", 2)
    listed = (await member_client.get("/api/me/holds")).json()
    assert [hold["id"] for hold in listed["items"]] == [mine["id"]]
    detail = (await member_client.get(f"/api/books/{out_book.id}")).json()
    assert detail["my_hold"]["id"] == mine["id"]
    assert detail["my_hold"]["position"] == 2
    assert detail["holds_waiting"] == 2
    as_staff = (await client.get(f"/api/books/{out_book.id}")).json()
    assert as_staff["my_hold"] is None


async def test_a_member_sees_the_copy_waiting_for_them(out_book, me, client, member_client):
    await placed(member_client, out_book.id)
    await return_loan(client, out_book.loan)

    [mine] = (await member_client.get("/api/me/holds")).json()["items"]
    detail = (await member_client.get(f"/api/books/{out_book.id}")).json()

    assert mine["status"] == "ready"
    assert parse(mine["pickup_by"]).date() == pickup_day()
    assert detail["my_hold"]["status"] == "ready"
    assert detail["my_hold"]["copy"]["code"] == out_book.copy["code"]


async def test_a_member_cancels_their_own_hold(out_book, me, member_client):
    mine = await placed(member_client, out_book.id)

    response = await member_client.post(f"/api/me/holds/{mine['id']}/cancel")

    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"
    assert (await member_client.get("/api/me/holds")).json()["items"] == []
    closed = (await member_client.get("/api/me/holds", params={"status": "closed"})).json()
    assert [hold["id"] for hold in closed["items"]] == [mine["id"]]


async def test_a_member_cannot_see_or_cancel_another_members_hold(
    out_book, maya, client, member_client
):
    theirs = await placed(client, out_book.id, maya["id"])

    cancel = await member_client.post(f"/api/me/holds/{theirs['id']}/cancel")
    listed = (await member_client.get("/api/me/holds", params={"status": "all"})).json()

    assert cancel.status_code == 404
    assert cancel.json()["error"]["code"] == "not_found"
    assert listed["items"] == []
    assert (await holds_by_id(client))[theirs["id"]]["status"] == "waiting"


async def test_a_member_places_holds_only_for_themselves(out_book, maya, me, member_client):
    response = await member_client.post(
        "/api/me/holds", json={"book_id": out_book.id, "member_id": maya["id"]}
    )

    assert response.status_code == 201
    assert response.json()["member"]["id"] == me["member_id"]


async def test_a_member_is_named_as_the_actor_of_their_own_hold(
    out_book, me, member_client, client
):
    await placed(member_client, out_book.id)

    events = (await client.get("/api/activity")).json()

    placed_event = next(event for event in events if event["action"] == "hold.placed")
    assert (placed_event["actor"], placed_event["via"]) == (me["display_name"], "ui")


async def test_a_members_own_holds_are_refused_with_the_same_codes(
    out_book, make_book, borrow, me, member_client
):
    on_the_shelf = await make_book(title="On the shelf", copies=1)
    mine = await make_book(title="Mine", copies=1)
    await borrow(mine["copies"][0]["id"], me["member_id"])
    await placed(member_client, out_book.id)

    again = await place(member_client, out_book.id)
    free = await place(member_client, on_the_shelf["id"])
    borrowed = await place(member_client, mine["id"])

    assert conflict_code(again) == "hold_exists"
    assert conflict_code(free) == "copy_available"
    assert conflict_code(borrowed) == "already_borrowed"


async def test_my_holds_for_an_account_without_a_member_record_is_404(client):
    response = await client.get("/api/me/holds")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "no_member_profile"
