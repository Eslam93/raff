"""The Copilot and holds, with a scripted fake model: the member's own holds and place in line,
the line and the copies set aside in the staff face's lookups, borrows prepared for a copy set
aside, and the renewal limit in loan cards. Nothing here reaches the network.

During a test the database's now() is when the test's transaction began, so a ready hold is
made to lapse by moving its pick-up time into the past.
"""

import json
import uuid
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

import pytest
from copilot_stream import chat, data_of, names, tool_results
from sqlalchemy import select, update

from app.copilot import proposals
from app.copilot.engine import FALLBACK_INTRO
from app.copilot.fake import call, calls, reply
from app.models import Hold, User
from app.services.activity import format_day, format_short_day

pytestmark = pytest.mark.integration


def today() -> date:
    return datetime.now(UTC).date()


def day_in(days: int) -> str:
    """The date as the tools write it for the model: "3 Oct 2026"."""
    return format_day(today() + timedelta(days=days))


def end_of_day_in(days: int) -> datetime:
    return datetime.combine(today() + timedelta(days=days), time(23, 59, 59, tzinfo=UTC))


@pytest.fixture
async def me(member_client) -> dict[str, Any]:
    """The demo member account's UserOut; the account exists once member_client signed in."""
    return (await member_client.get("/api/auth/me")).json()


@pytest.fixture
async def sara(make_member) -> dict[str, Any]:
    return await make_member("Sara Ali")


@pytest.fixture
def lent_book(make_book, borrow, sara):
    """Adds a book and lends each of its copies to Sara Ali, so no copy is on the shelf. Returns
    the book and its loans, in copy order.
    """

    async def _lent(**fields: Any) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        book = await make_book(**fields)
        loans = [(await borrow(copy["id"], sara["id"])).json() for copy in book["copies"]]
        return book, loans

    return _lent


async def place(client, book: dict[str, Any], member_id: str) -> dict[str, Any]:
    """Staff place a hold for the member."""
    response = await client.post("/api/holds", json={"book_id": book["id"], "member_id": member_id})
    assert response.status_code == 201, response.text
    hold: dict[str, Any] = response.json()
    return hold


async def give_back(client, loan: dict[str, Any]) -> None:
    response = await client.post(f"/api/loans/{loan['id']}/return")
    assert response.status_code == 200, response.text


def everything(events, model) -> str:
    return json.dumps(events) + json.dumps([request.messages for request in model.requests])


# The member face


async def test_my_holds_gives_the_place_in_line_and_the_copy_set_aside(
    lent_book, make_member, client, me, copilot
):
    maya = await make_member("Maya Hassan")
    dune, _ = await lent_book(title="Dune")
    emma, [emma_loan] = await lent_book(title="Emma", author="Jane Austen")
    await place(client, dune, maya["id"])
    await place(client, dune, me["member_id"])
    await place(client, emma, me["member_id"])
    # The return sets Emma's copy aside for the member, the only one in line.
    await give_back(client, emma_loan)
    code = emma["copies"][0]["code"]
    answer = (
        f"You are number 2 in line for Dune, and copy {code} of Emma is waiting for you until "
        f"{day_in(3)}."
    )
    http, model = await copilot(call("my_holds"), reply(answer))

    events = await chat(http, "Where am I in line?")

    # The answer passes the number check: the place in line and the date are in the lookup.
    assert data_of(events, "message") == [{"text": answer}]
    # Holds have no card in the panel.
    assert names(events) == ["conversation", "status", "message", "done"]
    assert data_of(events, "status") == [{"text": "Checking your holds"}]
    assert tool_results(model, 1) == [
        {
            "today": day_in(0),
            "status": "open",
            "total": 2,
            "holds": [
                {
                    "book_id": emma["id"],
                    "title": "Emma",
                    "author": "Jane Austen",
                    "status": "ready",
                    "placed_on": day_in(0),
                    "copy_code": code,
                    "pick_up_by": day_in(3),
                },
                {
                    "book_id": dune["id"],
                    "title": "Dune",
                    "author": "Frank Herbert",
                    "status": "waiting",
                    "placed_on": day_in(0),
                    "place_in_line": 2,
                },
            ],
        }
    ]
    seen = everything(events, model)
    assert "Maya Hassan" not in seen
    assert maya["id"] not in seen


async def test_a_place_in_line_the_lookup_does_not_give_is_sent_back(
    lent_book, make_member, client, me, copilot
):
    dune, _ = await lent_book(title="Dune")
    await place(client, dune, (await make_member("Maya Hassan"))["id"])
    await place(client, dune, me["member_id"])
    # No day of a month and no place in line here can be 40.
    http, model = await copilot(
        call("my_holds"),
        reply("You are number 40 in line for Dune."),
        reply("You are number 2 in line for Dune."),
    )

    events = await chat(http, "Where am I in line for Dune?")

    assert data_of(events, "message") == [{"text": "You are number 2 in line for Dune."}]
    retry = model.requests[2]
    assert retry.tool_choice == "none"
    assert ": 40." in retry.messages[-1]["content"]


async def test_my_holds_takes_no_member_id_and_lists_past_holds(
    lent_book, make_member, client, me, copilot
):
    maya = await make_member("Maya Hassan")
    dune, _ = await lent_book(title="Dune")
    await place(client, dune, maya["id"])
    mine = await place(client, dune, me["member_id"])
    cancelled = await client.post(f"/api/holds/{mine['id']}/cancel")
    assert cancelled.status_code == 200, cancelled.text
    http, model = await copilot(
        call("my_holds", member_id=maya["id"]),
        call("my_holds", status="closed"),
        call("my_holds"),
        reply("You cancelled your hold on Dune."),
    )

    events = await chat(http, "What happened to my hold?")

    rejected = tool_results(model, 1)[0]
    assert rejected["error"] == "invalid_arguments"
    assert rejected["problems"] == [
        {"field": "member_id", "problem": "Extra inputs are not permitted"}
    ]
    closed, still_open = tool_results(model, 3)[1:]
    assert (closed["status"], closed["total"]) == ("closed", 1)
    assert closed["holds"] == [
        {
            "book_id": dune["id"],
            "title": "Dune",
            "author": "Frank Herbert",
            "status": "cancelled",
            "placed_on": day_in(0),
            "closed_on": day_in(0),
        }
    ]
    # Maya's open hold on the same book is not the member's.
    assert (still_open["total"], still_open["holds"]) == (0, [])
    assert "Maya Hassan" not in everything(events, model)


async def test_a_members_book_lookups_include_the_line_and_their_own_hold(
    lent_book, make_book, make_member, client, me, copilot
):
    maya = await make_member("Maya Hassan")
    dune, _ = await lent_book(title="Dune")
    emma, [emma_loan] = await lent_book(title="Emma", author="Jane Austen")
    await make_book(title="Sapiens", author="Yuval Noah Harari")
    await place(client, dune, maya["id"])
    await place(client, dune, me["member_id"])
    await place(client, emma, me["member_id"])
    await give_back(client, emma_loan)
    code = emma["copies"][0]["code"]
    http, model = await copilot(
        calls(
            call("search_catalog"),
            call("get_book", book_id=dune["id"]),
            call("get_book", book_id=emma["id"]),
        ),
        reply("You are number 2 in line for Dune, and Emma is waiting for you."),
    )

    events = await chat(http, "What about my books?")

    found, dune_seen, emma_seen = tool_results(model, 1)
    waiting = {"status": "waiting", "placed_on": day_in(0), "place_in_line": 2}
    ready = {"status": "ready", "placed_on": day_in(0), "copy_code": code, "pick_up_by": day_in(3)}
    assert [
        (book["title"], book["copies_available"], book["holds_waiting"], book["my_hold"])
        for book in found["books"]
    ] == [("Dune", 0, 2, waiting), ("Emma", 0, 0, ready), ("Sapiens", 1, 0, None)]
    assert (dune_seen["holds_waiting"], dune_seen["my_hold"]) == (2, waiting)
    assert (emma_seen["holds_waiting"], emma_seen["my_hold"]) == (0, ready)
    # A member sees that a copy is held, never for whom, as on the book's page.
    assert emma_seen["copies"] == [{"code": code, "status": "held"}]
    displays = [data["display"] for data in data_of(events, "result")]
    [emma_card] = displays[2]["book"]["copies"]
    assert (emma_card["status"], emma_card["held_for"]) == ("held", None)
    assert displays[2]["book"]["my_hold"]["copy"]["code"] == code
    seen = everything(events, model)
    for other in ("Maya Hassan", "Sara Ali"):
        assert other not in seen


async def test_the_plain_reply_gives_the_line_and_the_copy_set_aside_for_the_member(
    lent_book, make_member, client, me, copilot
):
    dune, [dune_loan] = await lent_book(title="Dune")
    emma, [emma_loan] = await lent_book(title="Emma", author="Jane Austen")
    await place(client, dune, (await make_member("Maya Hassan"))["id"])
    await place(client, dune, me["member_id"])
    await place(client, emma, me["member_id"])
    await give_back(client, emma_loan)
    code = emma["copies"][0]["code"]
    # A second round of lookups goes past the limit, so the reply is the lookups in plain words.
    http, _ = await copilot(
        calls(
            call("search_catalog"),
            call("get_book", book_id=dune["id"]),
            call("get_book", book_id=emma["id"]),
        ),
        call("list_categories"),
        copilot_max_tool_rounds=1,
    )

    events = await chat(http, "What about my books?")

    due = format_day(datetime.fromisoformat(dune_loan["due_at"]).date())
    set_aside = f"copy {code} is set aside for you until {day_in(3)}"
    [message] = data_of(events, "message")
    assert message["text"] == "\n\n".join(
        [
            FALLBACK_INTRO,
            "Books in the catalog:\n"
            "- Dune by Frank Herbert: 0 of 1 copy available, 2 members waiting, you are number "
            "2 in line\n"
            f"- Emma by Jane Austen: 0 of 1 copy available, {set_aside}",
            "Dune by Frank Herbert: 0 of 1 copy available, 2 members waiting, you are number 2 "
            f"in line.\n- Copy {dune['copies'][0]['code']} is due back on {due}.",
            f"Emma by Jane Austen: 0 of 1 copy available, {set_aside}.",
        ]
    )


# The staff face


async def test_book_holds_lists_the_copy_set_aside_then_the_line(
    lent_book, make_member, client, copilot
):
    maya, omar, lina = [await make_member(name) for name in ("Maya", "Omar", "Lina")]
    dune, [loan] = await lent_book(title="Dune")
    for member in (maya, omar, lina):
        await place(client, dune, member["id"])
    await give_back(client, loan)
    code = dune["copies"][0]["code"]
    answer = f"Copy {code} is set aside for Maya until {day_in(3)}. Omar is next, then Lina."
    http, model = await copilot(call("book_holds", book_id=dune["id"]), reply(answer), role="staff")

    events = await chat(http, "Who is waiting for Dune?")

    assert data_of(events, "message") == [{"text": answer}]
    assert names(events) == ["conversation", "status", "message", "done"]
    assert data_of(events, "status") == [{"text": "Checking the book's holds"}]
    book = {"book_id": dune["id"], "title": "Dune", "author": "Frank Herbert"}
    assert tool_results(model, 1) == [
        {
            "today": day_in(0),
            "title": "Dune",
            "holds_waiting": 2,
            "status": "open",
            "total": 3,
            "holds": [
                {
                    **book,
                    "status": "ready",
                    "placed_on": day_in(0),
                    "copy_code": code,
                    "pick_up_by": day_in(3),
                    "member": "Maya",
                    "member_id": maya["id"],
                },
                {
                    **book,
                    "status": "waiting",
                    "placed_on": day_in(0),
                    "place_in_line": 1,
                    "member": "Omar",
                    "member_id": omar["id"],
                },
                {
                    **book,
                    "status": "waiting",
                    "placed_on": day_in(0),
                    "place_in_line": 2,
                    "member": "Lina",
                    "member_id": lina["id"],
                },
            ],
        }
    ]


async def test_past_holds_say_how_each_ended(lent_book, make_member, client, empty_db, copilot):
    maya, omar = await make_member("Maya Hassan"), await make_member("Omar Farouk")
    dune, [loan] = await lent_book(title="Dune")
    ready = await place(client, dune, maya["id"])
    cancelled = await place(client, dune, omar["id"])
    assert (await client.post(f"/api/holds/{cancelled['id']}/cancel")).status_code == 200
    await give_back(client, loan)
    # Maya did not pick the copy up by yesterday noon: her hold reads as expired, before anything
    # writes that.
    yesterday_noon = datetime.combine(today() - timedelta(days=1), time(12, tzinfo=UTC))
    await empty_db.execute(
        update(Hold).where(Hold.id == uuid.UUID(ready["id"])).values(pickup_by=yesterday_noon)
    )
    await empty_db.commit()
    http, model = await copilot(
        calls(
            call("book_holds", book_id=dune["id"], status="closed"),
            call("book_holds", book_id=dune["id"]),
        ),
        call("list_categories"),
        role="staff",
        copilot_max_tool_rounds=1,
    )

    events = await chat(http, "What happened to the holds on Dune?")

    closed, still_open = tool_results(model, 1)
    assert [
        (hold["member"], hold["status"], hold["closed_on"], hold.get("copy_code"))
        for hold in closed["holds"]
    ] == [
        ("Omar Farouk", "cancelled", day_in(0), None),
        ("Maya Hassan", "expired", day_in(-1), dune["copies"][0]["code"]),
    ]
    assert (still_open["total"], still_open["holds_waiting"]) == (0, 0)
    [message] = data_of(events, "message")
    assert message["text"] == "\n\n".join(
        [
            FALLBACK_INTRO,
            "Past holds on Dune:\n"
            f"- Omar Farouk: cancelled on {day_in(0)}\n"
            f"- Maya Hassan: expired on {day_in(-1)}",
            "Nobody is waiting for Dune.",
        ]
    )


async def test_staff_lookups_say_who_a_held_copy_is_set_aside_for(
    lent_book, make_member, client, copilot
):
    maya, lina = await make_member("Maya Hassan"), await make_member("Lina Saleh")
    dune, [first_loan, second_loan] = await lent_book(title="Dune", copies=2)
    await place(client, dune, maya["id"])
    await place(client, dune, lina["id"])
    await give_back(client, second_loan)
    on_loan, held = dune["copies"]
    http, model = await copilot(
        calls(
            call("search_catalog", query="Dune"),
            call("get_book", book_id=dune["id"]),
            call("lookup_copy", code=held["code"]),
        ),
        call("list_categories"),
        role="staff",
        copilot_max_tool_rounds=1,
    )

    events = await chat(http, "Where is Dune?")

    found, book, lookup = tool_results(model, 1)
    [brief] = found["books"]
    assert (brief["copies_available"], brief["holds_waiting"]) == (0, 1)
    # Staff have no member record, so no hold of their own.
    assert "my_hold" not in brief
    assert "my_hold" not in book
    due = format_day(datetime.fromisoformat(first_loan["due_at"]).date())
    assert book["holds_waiting"] == 1
    assert book["copies"] == [
        {
            "code": on_loan["code"],
            "status": "borrowed",
            "due_back": due,
            "borrower": "Sara Ali",
            "overdue": False,
        },
        {
            "code": held["code"],
            "status": "held",
            "held_for": "Maya Hassan",
            "pick_up_by": day_in(3),
        },
    ]
    assert lookup == {
        "code": held["code"],
        "title": "Dune",
        "author": "Frank Herbert",
        "book_id": dune["id"],
        "status": "held",
        "archived": False,
        "held_for": "Maya Hassan",
        "member_id": maya["id"],
        "pick_up_by": day_in(3),
    }
    displays = [data["display"] for data in data_of(events, "result")]
    assert displays[1]["book"]["copies"][1]["held_for"]["member"]["id"] == maya["id"]
    assert displays[2]["lookup"]["held_for"]["member"]["id"] == maya["id"]
    [message] = data_of(events, "message")
    assert message["text"] == "\n\n".join(
        [
            FALLBACK_INTRO,
            "Books in the catalog:\n- Dune by Frank Herbert: 0 of 2 copies available, 1 member "
            "waiting",
            "Dune by Frank Herbert: 0 of 2 copies available, 1 member waiting.\n"
            f"- Copy {on_loan['code']} is due back on {due}, borrowed by Sara Ali.\n"
            f"- Copy {held['code']} is set aside for Maya Hassan until {day_in(3)}.",
            f"Copy {held['code']} of Dune by Frank Herbert is set aside for Maya Hassan, to pick "
            f"up by {day_in(3)}.",
        ]
    )


async def test_each_face_has_only_its_own_holds_tool(lent_book, make_member, client, copilot):
    dune, _ = await lent_book(title="Dune")
    await place(client, dune, (await make_member("Maya Hassan"))["id"])
    member, member_model = await copilot(
        call("book_holds", book_id=dune["id"]), reply("I cannot say who is waiting.")
    )
    staff, staff_model = await copilot(
        calls(call("my_holds"), call("book_holds", book_id=str(uuid.uuid4()))),
        reply("I could not find that book."),
        role="staff",
    )

    member_events = await chat(member, "Who is waiting for Dune?")
    await chat(staff, "Who is waiting?")

    assert tool_results(member_model, 1)[0]["error"] == "unknown_tool"
    assert "Maya Hassan" not in everything(member_events, member_model)
    assert tool_results(staff_model, 1) == [
        {
            "error": "unknown_tool",
            "message": "There is no tool named 'my_holds'. Use only the tools given.",
        },
        {"error": "not_found", "message": "Book not found."},
    ]


# Borrows and returns prepared by the staff face


async def test_a_borrow_prepared_from_the_book_takes_the_copy_set_aside_for_the_member(
    lent_book, make_member, client, copilot
):
    maya, lina = await make_member("Maya Hassan"), await make_member("Lina Saleh")
    dune, [_, second_loan] = await lent_book(title="Dune", copies=2)
    await place(client, dune, maya["id"])
    await place(client, dune, lina["id"])
    await give_back(client, second_loan)
    held = dune["copies"][1]
    http, model = await copilot(
        calls(
            call("prepare_borrow", member_id=lina["id"], book_id=dune["id"]),
            call("prepare_borrow", member_id=lina["id"], copy_code=held["code"]),
        ),
        call("prepare_borrow", member_id=maya["id"], book_id=dune["id"]),
        reply("The card is ready to confirm."),
        role="staff",
    )

    events = await chat(http, "Lend Dune to Maya Hassan")

    until = format_short_day(today() + timedelta(days=3))
    assert tool_results(model, 1) == [
        {"error": "no_copy_available", "message": "No copy of Dune is available now."},
        {
            "error": "copy_held",
            "message": f"Copy {held['code']} is held for Maya Hassan until {until}.",
        },
    ]
    [result] = data_of(events, "result")
    proposal = result["display"]["proposal"]
    assert proposal["copy"] == {"id": held["id"], "code": held["code"]}

    confirmed = await http.post(f"/api/copilot/proposals/{proposal['id']}/confirm")

    assert confirmed.status_code == 200, confirmed.text
    loan = confirmed.json()["loan"]
    assert (loan["copy"]["code"], loan["member"]["id"]) == (held["code"], maya["id"])
    line = (await client.get("/api/holds", params={"book_id": dune["id"], "status": "all"})).json()
    assert [(hold["member"]["full_name"], hold["status"]) for hold in line["items"]] == [
        ("Lina Saleh", "waiting"),
        ("Maya Hassan", "fulfilled"),
    ]
    activity = (await client.get("/api/activity", params={"limit": 200})).json()
    assert [(event["action"], event["via"]) for event in activity][:2] == [
        ("hold.fulfilled", "copilot"),
        ("loan.borrowed", "copilot"),
    ]


async def test_a_return_confirmed_through_the_copilot_sets_the_copy_aside_for_the_line(
    lent_book, make_member, client, copilot
):
    maya = await make_member("Maya Hassan")
    dune, [loan] = await lent_book(title="Dune")
    await place(client, dune, maya["id"])
    http, _ = await copilot(
        call("prepare_return", copy_code=dune["copies"][0]["code"]),
        reply("The card is ready to confirm."),
        role="staff",
    )
    events = await chat(http, "Sara is returning Dune")
    [result] = data_of(events, "result")

    confirmed = await http.post(
        f"/api/copilot/proposals/{result['display']['proposal']['id']}/confirm"
    )

    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["loan"]["id"] == loan["id"]
    [hold] = (await client.get("/api/holds", params={"book_id": dune["id"]})).json()["items"]
    assert (hold["status"], hold["copy"]["code"]) == ("ready", dune["copies"][0]["code"])
    assert datetime.fromisoformat(hold["pickup_by"]) == end_of_day_in(3)
    activity = (await client.get("/api/activity", params={"limit": 200})).json()
    assert [(event["action"], event["via"]) for event in activity][:2] == [
        ("hold.ready", "copilot"),
        ("loan.returned", "copilot"),
    ]


async def test_the_confirm_route_passes_the_apps_pick_up_days_and_renewal_limit(
    lent_book, make_book, make_member, client, copilot
):
    maya, omar = await make_member("Maya Hassan"), await make_member("Omar Farouk")
    dune, _ = await lent_book(title="Dune")
    await place(client, dune, maya["id"])
    hobbit = await make_book(title="The Hobbit")
    http, _ = await copilot(
        calls(
            call("prepare_return", copy_code=dune["copies"][0]["code"]),
            call("prepare_borrow", member_id=omar["id"], book_id=hobbit["id"]),
        ),
        reply("Both cards are ready to confirm."),
        role="staff",
        hold_pickup_days=5,
        max_renewals=0,
    )
    events = await chat(http, "Return Dune and lend The Hobbit to Omar")
    returned, lent = (data["display"]["proposal"]["id"] for data in data_of(events, "result"))

    confirmed_return = await http.post(f"/api/copilot/proposals/{returned}/confirm")
    confirmed_borrow = await http.post(f"/api/copilot/proposals/{lent}/confirm")
    read_back = await http.get(f"/api/copilot/proposals/{lent}")

    assert confirmed_return.status_code == 200, confirmed_return.text
    [hold] = (await client.get("/api/holds", params={"book_id": dune["id"]})).json()["items"]
    assert datetime.fromisoformat(hold["pickup_by"]) == end_of_day_in(5)
    # An active loan that could be renewed under the default limit cannot under a limit of 0.
    assert confirmed_borrow.status_code == 200, confirmed_borrow.text
    assert confirmed_borrow.json()["loan"]["can_renew"] is False
    assert read_back.json()["loan"]["can_renew"] is False


async def test_confirm_applies_the_pick_up_days_and_renewal_limit_it_is_given(
    lent_book, make_book, make_member, client, copilot, empty_db
):
    maya, omar = await make_member("Maya Hassan"), await make_member("Omar Farouk")
    dune, [loan] = await lent_book(title="Dune")
    await place(client, dune, maya["id"])
    hobbit = await make_book(title="The Hobbit")
    http, _ = await copilot(
        calls(
            call("prepare_return", copy_code=dune["copies"][0]["code"]),
            call("prepare_borrow", member_id=omar["id"], book_id=hobbit["id"]),
        ),
        reply("Both cards are ready to confirm."),
        role="staff",
    )
    events = await chat(http, "Return Dune and lend The Hobbit to Omar")
    returned, lent = (
        uuid.UUID(data["display"]["proposal"]["id"]) for data in data_of(events, "result")
    )
    staff = await empty_db.scalar(select(User).where(User.role == "staff", User.is_demo))
    assert staff is not None

    await proposals.confirm(
        empty_db, returned, user=staff, loan_period_days=14, hold_pickup_days=5, max_renewals=0
    )
    borrowed = await proposals.confirm(
        empty_db, lent, user=staff, loan_period_days=14, hold_pickup_days=5, max_renewals=0
    )

    [hold] = (await client.get("/api/holds", params={"book_id": dune["id"]})).json()["items"]
    assert datetime.fromisoformat(hold["pickup_by"]) == end_of_day_in(5)
    assert borrowed.loan is not None
    assert (borrowed.loan.renewals, borrowed.loan.can_renew) == (0, False)
    # The same loan read with the app's settings can be renewed.
    active = (await client.get("/api/loans", params={"status": "active", "limit": 100})).json()
    [same] = [item for item in active["items"] if item["id"] == str(borrowed.loan.id)]
    assert same["can_renew"] is True
    returned_loan = await client.get("/api/loans", params={"status": "returned"})
    assert [item["id"] for item in returned_loan.json()["items"]] == [loan["id"]]


# Loan cards


async def test_loan_cards_follow_the_renewal_limit_in_the_settings(
    make_book, make_member, borrow, me, copilot
):
    maya = await make_member("Maya Hassan")
    dune = await make_book(title="Dune")
    emma = await make_book(title="Emma", author="Jane Austen")
    await borrow(dune["copies"][0]["id"], maya["id"])
    await borrow(emma["copies"][0]["id"], me["member_id"])
    staff, _ = await copilot(
        calls(
            call("get_member_loans", member_id=maya["id"]),
            call("get_book_loans", book_id=dune["id"]),
            call("lookup_copy", code=dune["copies"][0]["code"]),
        ),
        reply("Maya Hassan has Dune."),
        role="staff",
        max_renewals=0,
    )
    member, _ = await copilot(call("get_my_loans"), reply("You have Emma."), max_renewals=0)

    staff_events = await chat(staff, "Who has Dune?")
    member_events = await chat(member, "What do I have?")

    member_loans, book_loans, lookup = (data["display"] for data in data_of(staff_events, "result"))
    [my_loans] = (data["display"] for data in data_of(member_events, "result"))
    cards = [
        *member_loans["items"],
        *book_loans["items"],
        lookup["lookup"]["active_loan"],
        *my_loans["items"],
    ]
    assert [(card["renewals"], card["can_renew"]) for card in cards] == [(0, False)] * 4
