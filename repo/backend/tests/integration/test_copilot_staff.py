"""The Copilot's staff face with a scripted fake model: the lookups, and borrows and returns that
the Copilot only prepares and the staff member confirms or cancels. Nothing here reaches the
network.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

import pytest
from copilot_stream import chat, data_of, names, tool_results
from httpx import AsyncClient
from sqlalchemy import func, select, update

from app.api.cookies import SESSION_COOKIE
from app.copilot import proposals
from app.copilot.fake import FakeModelClient, FakeStep, call, calls, reply
from app.copilot.tools import BORROW_NOTE, RETURN_NOTE
from app.models import ActivityEvent, CopilotMessage, CopilotProposal, Loan, User
from app.schemas.members import MemberOut
from app.services import auth
from app.services.activity import format_day

pytestmark = pytest.mark.integration


def today() -> date:
    return datetime.now(UTC).date()


def iso_in(days: int) -> str:
    return (today() + timedelta(days=days)).isoformat()


def day_in(days: int) -> str:
    """The date as the tools write it for the model: "3 Oct 2026"."""
    return format_day(today() + timedelta(days=days))


def end_of_day_in(days: int) -> datetime:
    """When a loan due that day is due: the end of the day, in UTC."""
    return datetime.combine(today() + timedelta(days=days), time(23, 59, 59, tzinfo=UTC))


def url(proposal: dict[str, Any], action: str = "") -> str:
    return f"/api/copilot/proposals/{proposal['id']}" + (f"/{action}" if action else "")


@dataclass
class Prepared:
    http: AsyncClient
    model: FakeModelClient
    proposal: dict[str, Any]
    conversation_id: str


async def prepare(copilot, tool: str, *after: FakeStep, **arguments: Any) -> Prepared:
    """Prepares a borrow or a return in a staff chat turn. `after` scripts later turns."""
    http, model = await copilot(
        call(tool, **arguments), reply("The card is ready to confirm."), *after, role="staff"
    )
    events = await chat(http, "Prepare it, please")
    [result] = data_of(events, "result")
    assert result["display"]["kind"] == "proposal"
    conversation_id = data_of(events, "conversation")[0]["conversation_id"]
    return Prepared(http, model, result["display"]["proposal"], conversation_id)


async def count(session, model, *conditions) -> int:
    return await session.scalar(select(func.count()).select_from(model).where(*conditions)) or 0


async def last_note(session, conversation_id: str) -> dict[str, Any]:
    message = await session.scalar(
        select(CopilotMessage)
        .where(CopilotMessage.conversation_id == uuid.UUID(conversation_id))
        .order_by(CopilotMessage.id.desc())
        .limit(1)
    )
    return {"role": message.role, **message.content}


async def stored_proposal(session) -> CopilotProposal:
    return await session.scalar(select(CopilotProposal).execution_options(populate_existing=True))


# Lookups


async def test_search_members_shows_the_matches_with_their_active_loans(
    make_book, make_member, borrow, copilot
):
    maya = await make_member("Maya Hassan", "maya.hassan@example.com")
    await make_member("Maya Stone")
    await make_member("Omar Farouk")
    book = await make_book(title="Dune")
    await borrow(book["copies"][0]["id"], maya["id"])
    http, model = await copilot(
        call("search_members", query="maya"),
        reply("Two members match. Which one do you mean?"),
        role="staff",
    )

    events = await chat(http, "Which books does Maya have?")

    found = tool_results(model, 1)[0]
    assert found["matches"] == 2
    assert [member["full_name"] for member in found["members"]] == ["Maya Hassan", "Maya Stone"]
    assert found["members"][0] == {
        "id": maya["id"],
        "full_name": "Maya Hassan",
        "email": "maya.hassan@example.com",
        "active_loans": 1,
    }
    assert data_of(events, "status") == [{"text": "Looking up members"}]
    [result] = data_of(events, "result")
    assert result["display"]["kind"] == "members"
    items = result["display"]["items"]
    assert [item["full_name"] for item in items] == ["Maya Hassan", "Maya Stone"]
    assert set(items[0]) == set(MemberOut.model_fields)
    assert items[0]["active_loans"] == 1


async def test_member_loans_carry_the_member_and_dates_written_out(
    make_book, make_member, borrow, copilot
):
    maya = await make_member("Maya Hassan")
    dune = await make_book(title="Dune")
    loan = (await borrow(dune["copies"][0]["id"], maya["id"], due_date=iso_in(5))).json()
    http, model = await copilot(
        call("get_member_loans", member_id=maya["id"]), reply("Maya has Dune."), role="staff"
    )

    events = await chat(http, "Which books does Maya have?")

    assert tool_results(model, 1)[0] == {
        "today": day_in(0),
        "member": "Maya Hassan",
        "status": "active",
        "total": 1,
        "loans": [
            {
                "book_id": dune["id"],
                "title": "Dune",
                "author": "Frank Herbert",
                "copy_code": dune["copies"][0]["code"],
                "borrowed_on": day_in(0),
                "due_on": day_in(5),
                "overdue": False,
                "member": "Maya Hassan",
                "member_id": maya["id"],
            }
        ],
    }
    [result] = data_of(events, "result")
    assert result["display"]["kind"] == "loans"
    [item] = result["display"]["items"]
    # The display keeps the API's own shape, with ISO date-times.
    assert (item["id"], item["due_at"]) == (loan["id"], loan["due_at"])


async def test_book_loans_say_who_has_each_copy_now_and_who_had_it(
    make_book, make_member, borrow, client, copilot
):
    maya, omar = await make_member("Maya Hassan"), await make_member("Omar Farouk")
    dune = await make_book(title="Dune", copies=2)
    first, second = dune["copies"]
    earlier = (await borrow(first["id"], maya["id"])).json()
    await client.post(f"/api/loans/{earlier['id']}/return")
    await borrow(first["id"], omar["id"], due_date=iso_in(9))
    await borrow(second["id"], maya["id"], due_date=iso_in(4))
    http, model = await copilot(
        calls(
            call("get_book_loans", book_id=dune["id"]),
            call("get_book_loans", book_id=dune["id"], status="returned"),
        ),
        reply("Maya Hassan and Omar Farouk have Dune."),
        role="staff",
    )

    events = await chat(http, "Who has Dune?")

    active, returned = tool_results(model, 1)
    assert (active["today"], active["title"], active["status"], active["total"]) == (
        day_in(0),
        "Dune",
        "active",
        2,
    )
    assert [(loan["member"], loan["copy_code"], loan["due_on"]) for loan in active["loans"]] == [
        ("Maya Hassan", second["code"], day_in(4)),
        ("Omar Farouk", first["code"], day_in(9)),
    ]
    assert [(loan["member"], loan["returned_on"]) for loan in returned["loans"]] == [
        ("Maya Hassan", day_in(0))
    ]
    assert [data["display"]["kind"] for data in data_of(events, "result")] == ["loans", "loans"]


async def test_overdue_loans_come_longest_overdue_first(
    make_book, make_member, borrow, move_loan, copilot
):
    maya, omar = await make_member("Maya Hassan"), await make_member("Omar Farouk")
    book = await make_book(title="Dune", copies=3)
    loans = [
        (await borrow(copy["id"], member["id"])).json()
        for copy, member in zip(book["copies"], [maya, omar, maya], strict=True)
    ]
    now = datetime.now(UTC)
    await move_loan(
        loans[0]["id"], borrowed_at=now - timedelta(days=20), due_at=now - timedelta(days=3)
    )
    await move_loan(
        loans[1]["id"], borrowed_at=now - timedelta(days=30), due_at=now - timedelta(days=10)
    )
    http, model = await copilot(
        call("get_overdue_loans"), reply("Two loans are overdue."), role="staff"
    )

    events = await chat(http, "Show everything overdue")

    overdue = tool_results(model, 1)[0]
    assert (overdue["today"], overdue["total"]) == (day_in(0), 2)
    assert [
        (loan["member"], loan["due_on"], loan["overdue"], loan["days_overdue"])
        for loan in overdue["loans"]
    ] == [("Omar Farouk", day_in(-10), True, 10), ("Maya Hassan", day_in(-3), True, 3)]
    [result] = data_of(events, "result")
    assert [item["id"] for item in result["display"]["items"]] == [loans[1]["id"], loans[0]["id"]]


async def test_lookup_copy_finds_a_copy_by_its_number_and_says_who_has_it(
    make_book, make_member, borrow, copilot
):
    maya = await make_member("Maya Hassan")
    dune = await make_book(title="Dune", copies=2)
    on_loan, free = dune["copies"]
    await borrow(on_loan["id"], maya["id"], due_date=iso_in(6))
    number = str(int(on_loan["code"].removeprefix("CP-")))
    http, model = await copilot(
        calls(call("lookup_copy", code=number), call("lookup_copy", code=free["code"].lower())),
        reply("Maya Hassan has it."),
        role="staff",
    )

    events = await chat(http, f"What is copy {number}?")

    borrowed, available = tool_results(model, 1)
    book = {"title": "Dune", "author": "Frank Herbert", "book_id": dune["id"], "archived": False}
    assert borrowed == {
        "code": on_loan["code"],
        **book,
        "status": "borrowed",
        "borrower": "Maya Hassan",
        "member_id": maya["id"],
        "due_on": day_in(6),
        "overdue": False,
    }
    assert available == {"code": free["code"], **book, "status": "available"}
    displays = [data["display"] for data in data_of(events, "result")]
    assert [display["kind"] for display in displays] == ["copy", "copy"]
    assert displays[0]["lookup"]["copy"]["code"] == on_loan["code"]
    assert displays[0]["lookup"]["active_loan"]["member"]["id"] == maya["id"]
    assert displays[1]["lookup"]["active_loan"] is None


async def test_the_member_face_keeps_its_own_tools_and_loan_data(make_book, borrow, copilot):
    http, model = await copilot(
        call("search_members", query="Maya"),
        call("get_my_loans"),
        reply("You have Dune."),
    )
    me = (await http.get("/api/auth/me")).json()
    dune = await make_book(title="Dune")
    await borrow(dune["copies"][0]["id"], me["member_id"], due_date=iso_in(5))

    await chat(http, "What do I have?")

    assert model.requests[0].tool_names == [
        "search_catalog",
        "list_categories",
        "get_book",
        "get_my_loans",
        "my_holds",
    ]
    assert tool_results(model, 1)[0]["error"] == "unknown_tool"
    [loan] = tool_results(model, 2)[1]["loans"]
    assert loan == {
        "book_id": dune["id"],
        "title": "Dune",
        "author": "Frank Herbert",
        "copy_code": dune["copies"][0]["code"],
        "borrowed_on": day_in(0),
        "due_on": day_in(5),
        "overdue": False,
    }


# Preparing


async def test_prepare_borrow_stores_a_pending_proposal_and_changes_nothing(
    make_book, make_member, copilot, empty_db
):
    maya = await make_member("Maya Hassan")
    hobbit = await make_book(title="The Hobbit", author="J. R. R. Tolkien", copies=2)
    first_copy = hobbit["copies"][0]
    http, model = await copilot(
        call("prepare_borrow", member_id=maya["id"], book_id=hobbit["id"]),
        reply("The card is ready to confirm."),
        role="staff",
    )

    events = await chat(http, "Borrow The Hobbit for Maya Hassan")

    assert names(events) == ["conversation", "status", "result", "message", "done"]
    assert data_of(events, "status") == [{"text": "Preparing the borrow"}]
    [result] = data_of(events, "result")
    assert (result["tool"], result["display"]["kind"]) == ("prepare_borrow", "proposal")
    proposal = result["display"]["proposal"]
    assert proposal == {
        "id": proposal["id"],
        "action": "borrow",
        "status": "pending",
        "book": {"id": hobbit["id"], "title": "The Hobbit", "author": "J. R. R. Tolkien"},
        "copy": {"id": first_copy["id"], "code": first_copy["code"]},
        "member": {"id": maya["id"], "full_name": "Maya Hassan"},
        "due_at": proposal["due_at"],
        "borrowed_at": None,
        "is_overdue": False,
        "created_at": proposal["created_at"],
        "expires_at": proposal["expires_at"],
        "resolved_at": None,
        "loan": None,
        "error": None,
    }
    assert datetime.fromisoformat(proposal["due_at"]) == end_of_day_in(14)
    created, expires = (
        datetime.fromisoformat(proposal[key]) for key in ("created_at", "expires_at")
    )
    assert expires - created == timedelta(minutes=10)
    assert tool_results(model, 1)[0] == {
        "proposal": "waiting_for_confirmation",
        "action": "borrow",
        "title": "The Hobbit",
        "author": "J. R. R. Tolkien",
        "copy_code": first_copy["code"],
        "member": "Maya Hassan",
        "due_on": day_in(14),
        "note": BORROW_NOTE,
    }

    stored = await stored_proposal(empty_db)
    staff = (await http.get("/api/auth/me")).json()
    conversation_id = data_of(events, "conversation")[0]["conversation_id"]
    assert (str(stored.id), stored.status, str(stored.user_id), str(stored.conversation_id)) == (
        proposal["id"],
        "pending",
        staff["id"],
        conversation_id,
    )
    assert stored.params == {
        "copy_id": first_copy["id"],
        "member_id": maya["id"],
        "due_date": iso_in(14),
    }
    assert await count(empty_db, Loan) == 0
    assert await count(empty_db, ActivityEvent, ActivityEvent.action.like("loan.%")) == 0


async def test_prepare_borrow_of_a_particular_copy_keeps_the_due_date_asked_for(
    make_book, make_member, copilot
):
    maya = await make_member("Maya Hassan")
    hobbit = await make_book(title="The Hobbit", copies=2)
    second = hobbit["copies"][1]

    prepared = await prepare(
        copilot,
        "prepare_borrow",
        member_id=maya["id"],
        copy_code=second["code"].lower(),
        due_date=iso_in(7),
    )

    assert prepared.proposal["copy"] == {"id": second["id"], "code": second["code"]}
    assert datetime.fromisoformat(prepared.proposal["due_at"]) == end_of_day_in(7)
    assert tool_results(prepared.model, 1)[0]["due_on"] == day_in(7)


async def test_prepare_refuses_what_the_borrow_or_the_return_would_refuse(
    make_book, make_member, borrow, client, copilot, empty_db
):
    maya, omar = await make_member("Maya Hassan"), await make_member("Omar Farouk")
    hobbit = await make_book(title="The Hobbit")
    dune = await make_book(title="Dune")
    await borrow(dune["copies"][0]["id"], omar["id"])
    old = await make_book(title="Old Book")
    old_loan = (await borrow(old["copies"][0]["id"], omar["id"])).json()
    await client.post(f"/api/loans/{old_loan['id']}/return")
    assert (await client.delete(f"/api/books/{old['id']}")).json() == {"outcome": "archived"}
    member, free_code = maya["id"], hobbit["copies"][0]["code"]
    http, model = await copilot(
        calls(
            call("prepare_borrow", member_id=member, copy_code=dune["copies"][0]["code"]),
            call("prepare_borrow", member_id=member, book_id=dune["id"]),
            call("prepare_borrow", member_id=member, book_id=old["id"]),
            call("prepare_borrow", member_id=str(uuid.uuid4()), book_id=hobbit["id"]),
            call("prepare_borrow", member_id=member, book_id=hobbit["id"], due_date=iso_in(0)),
            call("prepare_borrow", member_id=member, book_id=hobbit["id"], copy_code=free_code),
            call("prepare_borrow", member_id=member),
            call("prepare_return", copy_code=free_code),
        ),
        reply("Nothing could be prepared."),
        role="staff",
    )

    events = await chat(http, "Borrow them all")

    results = tool_results(model, 1)
    assert [result["error"] for result in results] == [
        "copy_unavailable",
        "no_copy_available",
        "book_archived",
        "not_found",
        "due_date_not_in_future",
        "invalid_arguments",
        "invalid_arguments",
        "copy_not_on_loan",
    ]
    assert results[1]["message"] == "No copy of Dune is available now."
    assert results[4]["message"] == "Choose a due date after today."
    assert results[7]["message"] == f"Copy {free_code} is not on loan."
    assert data_of(events, "result") == []
    assert await count(empty_db, CopilotProposal) == 0


# Confirming


async def test_confirm_lends_the_copy_once_via_the_copilot_as_the_staff_user(
    make_book, make_member, copilot, empty_db
):
    maya = await make_member("Maya Hassan")
    hobbit = await make_book(title="The Hobbit")
    prepared = await prepare(copilot, "prepare_borrow", member_id=maya["id"], book_id=hobbit["id"])
    http, proposal = prepared.http, prepared.proposal

    confirmed = await http.post(url(proposal, "confirm"))
    again = await http.post(url(proposal, "confirm"))

    assert confirmed.status_code == 200, confirmed.text
    body = confirmed.json()
    assert (body["status"], body["error"]) == ("confirmed", None)
    assert body["resolved_at"] is not None
    loan = body["loan"]
    assert (loan["copy"]["code"], loan["member"]["id"], loan["returned_at"]) == (
        hobbit["copies"][0]["code"],
        maya["id"],
        None,
    )
    assert loan["due_at"] == proposal["due_at"]
    assert (again.status_code, again.json()["error"]["code"]) == (409, "proposal_resolved")
    assert (await http.get(url(proposal))).json() == body

    events = [e for e in (await http.get("/api/activity")).json() if e["action"] == "loan.borrowed"]
    assert [(e["via"], e["actor"], e["entity_id"]) for e in events] == [
        ("copilot", "Demo Staff", loan["id"])
    ]
    staff = (await http.get("/api/auth/me")).json()
    recorded = await empty_db.scalar(
        select(ActivityEvent.actor_user_id).where(ActivityEvent.action == "loan.borrowed")
    )
    assert str(recorded) == staff["id"]
    assert await count(empty_db, Loan) == 1


async def test_the_conversation_is_told_the_outcome(make_book, make_member, copilot, empty_db):
    maya = await make_member("Maya Hassan")
    hobbit = await make_book(title="The Hobbit")
    code = hobbit["copies"][0]["code"]
    prepared = await prepare(
        copilot,
        "prepare_borrow",
        reply("Yes, it is lent."),
        member_id=maya["id"],
        book_id=hobbit["id"],
    )
    await prepared.http.post(url(prepared.proposal, "confirm"))

    await chat(prepared.http, "Is it done?", prepared.conversation_id)

    note = f"Confirmed: The Hobbit (copy {code}) was lent to Maya Hassan, due {day_in(14)}."
    sent = prepared.model.requests[-1].messages
    assert sent[-2:] == [
        {"role": "assistant", "content": note},
        {"role": "user", "content": "Is it done?"},
    ]


async def test_another_users_proposal_is_not_found(
    make_book, make_member, copilot, open_client, empty_db
):
    maya = await make_member("Maya Hassan")
    hobbit = await make_book(title="The Hobbit")
    prepared = await prepare(copilot, "prepare_borrow", member_id=maya["id"], book_id=hobbit["id"])
    other = User(email="second.staff@example.com", display_name="Second Staff", role="staff")
    empty_db.add(other)
    await empty_db.flush()
    token = await auth.start_session(empty_db, other, lifetime=timedelta(hours=1))
    stranger = await open_client()
    cookie = {"Cookie": f"{SESSION_COOKIE}={token}"}
    assert (await stranger.get("/api/auth/me", headers=cookie)).json()["role"] == "staff"

    responses = [
        await stranger.get(url(prepared.proposal), headers=cookie),
        await stranger.post(url(prepared.proposal, "confirm"), headers=cookie),
        await stranger.post(url(prepared.proposal, "cancel"), headers=cookie),
        await prepared.http.get(url({"id": uuid.uuid4()})),
    ]

    assert [response.status_code for response in responses] == [404, 404, 404, 404]
    assert {response.json()["error"]["code"] for response in responses} == {"not_found"}
    assert (await prepared.http.get(url(prepared.proposal))).json()["status"] == "pending"
    assert await count(empty_db, Loan) == 0


async def test_a_proposal_past_its_expiry_reads_as_expired_and_cannot_be_confirmed(
    make_book, make_member, copilot, empty_db
):
    maya = await make_member("Maya Hassan")
    hobbit = await make_book(title="The Hobbit")
    prepared = await prepare(copilot, "prepare_borrow", member_id=maya["id"], book_id=hobbit["id"])
    http, proposal = prepared.http, prepared.proposal
    past = datetime.now(UTC) - timedelta(minutes=10)
    await empty_db.execute(update(CopilotProposal).values(expires_at=past))
    await empty_db.commit()

    read = await http.get(url(proposal))
    still_stored_as = (await stored_proposal(empty_db)).status
    confirmed = await http.post(url(proposal, "confirm"))
    cancelled = await http.post(url(proposal, "cancel"))

    assert (read.json()["status"], still_stored_as) == ("expired", "pending")
    assert (confirmed.status_code, confirmed.json()["error"]["code"]) == (409, "proposal_expired")
    assert (cancelled.status_code, cancelled.json()["error"]["code"]) == (409, "proposal_expired")
    stored = await stored_proposal(empty_db)
    assert stored.status == "expired"
    assert stored.resolved_at is not None
    assert await count(empty_db, Loan) == 0
    assert (await last_note(empty_db, prepared.conversation_id))["content"].startswith(
        "Expired: nothing changed."
    )


async def test_a_copy_borrowed_elsewhere_before_the_confirm_fails_the_proposal(
    make_book, make_member, borrow, copilot, empty_db
):
    maya, omar = await make_member("Maya Hassan"), await make_member("Omar Farouk")
    hobbit = await make_book(title="The Hobbit")
    code = hobbit["copies"][0]["code"]
    prepared = await prepare(copilot, "prepare_borrow", member_id=maya["id"], copy_code=code)
    http, proposal = prepared.http, prepared.proposal
    elsewhere = (await borrow(hobbit["copies"][0]["id"], omar["id"])).json()

    response = await http.post(url(proposal, "confirm"))

    refusal = f"Copy {code} is already on loan."
    assert response.status_code == 409
    assert response.json()["error"] == {
        "code": "copy_unavailable",
        "message": refusal,
        "details": {},
    }
    read = (await http.get(url(proposal))).json()
    assert (read["status"], read["loan"]) == ("failed", None)
    assert read["error"] == {"code": "copy_unavailable", "message": refusal}
    assert read["resolved_at"] is not None
    loans = await empty_db.scalars(select(Loan.id))
    assert [str(loan_id) for loan_id in loans] == [elsewhere["id"]]
    assert await count(empty_db, ActivityEvent, ActivityEvent.via == "copilot") == 0
    assert await last_note(empty_db, prepared.conversation_id) == {
        "role": "assistant",
        "content": "Failed: nothing changed. The staff member confirmed the borrow of The Hobbit "
        f"(copy {code}) for Maya Hassan, but it was refused: {refusal}",
    }


async def test_any_other_refusal_fails_the_proposal_with_the_reason(
    make_book, make_member, client, copilot
):
    maya = await make_member("Maya Hassan")
    hobbit = await make_book(title="The Hobbit")
    prepared = await prepare(copilot, "prepare_borrow", member_id=maya["id"], book_id=hobbit["id"])
    # A book that was never lent is deleted with its copies.
    assert (await client.delete(f"/api/books/{hobbit['id']}")).json() == {"outcome": "deleted"}

    response = await prepared.http.post(url(prepared.proposal, "confirm"))

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "proposal_failed"
    assert response.json()["error"]["message"] == "Copy not found."
    read = (await prepared.http.get(url(prepared.proposal))).json()
    assert (read["status"], read["error"]) == (
        "failed",
        {"code": "proposal_failed", "message": "Copy not found."},
    )


async def test_a_return_is_prepared_from_the_copy_code_and_made_on_confirm(
    make_book, make_member, borrow, move_loan, copilot
):
    maya = await make_member("Maya Hassan")
    hobbit = await make_book(title="The Hobbit")
    code = hobbit["copies"][0]["code"]
    loan = (await borrow(hobbit["copies"][0]["id"], maya["id"])).json()
    now = datetime.now(UTC)
    await move_loan(
        loan["id"], borrowed_at=now - timedelta(days=20), due_at=now - timedelta(days=2)
    )

    prepared = await prepare(copilot, "prepare_return", copy_code=code)
    http, proposal = prepared.http, prepared.proposal
    confirmed = await http.post(url(proposal, "confirm"))
    again = await http.post(url(proposal, "confirm"))

    assert (proposal["action"], proposal["status"], proposal["is_overdue"]) == (
        "return",
        "pending",
        True,
    )
    assert (proposal["copy"]["code"], proposal["member"]["id"]) == (code, maya["id"])
    assert proposal["borrowed_at"] is not None
    assert tool_results(prepared.model, 1)[0] == {
        "proposal": "waiting_for_confirmation",
        "action": "return",
        "title": "The Hobbit",
        "author": "Frank Herbert",
        "copy_code": code,
        "member": "Maya Hassan",
        "borrowed_on": day_in(-20),
        "due_on": day_in(-2),
        "overdue": True,
        "note": RETURN_NOTE,
    }
    assert confirmed.status_code == 200, confirmed.text
    body = confirmed.json()
    assert (body["status"], body["loan"]["id"]) == ("confirmed", loan["id"])
    assert body["loan"]["returned_at"] is not None
    assert (again.status_code, again.json()["error"]["code"]) == (409, "proposal_resolved")
    events = [e for e in (await http.get("/api/activity")).json() if e["action"] == "loan.returned"]
    assert [(e["via"], e["actor"], e["entity_id"]) for e in events] == [
        ("copilot", "Demo Staff", loan["id"])
    ]
    assert (await http.get(f"/api/copies/by-code/{code}")).json()["status"] == "available"


async def test_a_loan_returned_elsewhere_before_the_confirm_fails_the_return(
    make_book, make_member, borrow, client, copilot
):
    maya = await make_member("Maya Hassan")
    hobbit = await make_book(title="The Hobbit")
    loan = (await borrow(hobbit["copies"][0]["id"], maya["id"])).json()
    prepared = await prepare(copilot, "prepare_return", copy_code=hobbit["copies"][0]["code"])
    await client.post(f"/api/loans/{loan['id']}/return")

    response = await prepared.http.post(url(prepared.proposal, "confirm"))

    assert (response.status_code, response.json()["error"]["code"]) == (
        409,
        "loan_already_returned",
    )
    read = (await prepared.http.get(url(prepared.proposal))).json()
    assert (read["status"], read["error"]["code"]) == ("failed", "loan_already_returned")


# Cancelling


async def test_cancel_declines_the_proposal_and_changes_nothing(
    make_book, make_member, copilot, empty_db
):
    maya = await make_member("Maya Hassan")
    hobbit = await make_book(title="The Hobbit")
    code = hobbit["copies"][0]["code"]
    prepared = await prepare(copilot, "prepare_borrow", member_id=maya["id"], book_id=hobbit["id"])
    http, proposal = prepared.http, prepared.proposal

    cancelled = await http.post(url(proposal, "cancel"))
    read = (await http.get(url(proposal))).json()
    confirmed = await http.post(url(proposal, "confirm"))
    again = await http.post(url(proposal, "cancel"))

    assert (cancelled.status_code, cancelled.content) == (204, b"")
    assert (read["status"], read["loan"], read["error"]) == ("cancelled", None, None)
    assert read["resolved_at"] is not None
    assert [(r.status_code, r.json()["error"]["code"]) for r in (confirmed, again)] == [
        (409, "proposal_resolved"),
        (409, "proposal_resolved"),
    ]
    assert await count(empty_db, Loan) == 0
    assert await last_note(empty_db, prepared.conversation_id) == {
        "role": "assistant",
        "content": "Cancelled: nothing changed. The staff member cancelled the borrow of The "
        f"Hobbit (copy {code}) for Maya Hassan.",
    }


async def test_preparing_deletes_the_users_proposals_that_ended_over_a_week_ago(
    make_book, make_member, client, empty_db
):
    maya = await make_member("Maya Hassan")
    hobbit = await make_book(title="The Hobbit")
    staff = await empty_db.scalar(select(User).where(User.role == "staff", User.is_demo))
    colleague = User(email="omar@staff.local", display_name="Omar Farouk", role="staff")
    empty_db.add(colleague)
    await empty_db.commit()

    async def prepared(user: User, **times: Any) -> uuid.UUID:
        proposal = await proposals.prepare_borrow(
            empty_db,
            user=user,
            conversation_id=None,
            member_id=uuid.UUID(maya["id"]),
            book_id=uuid.UUID(hobbit["id"]),
            loan_period_days=14,
        )
        if times:
            await empty_db.execute(
                update(CopilotProposal).where(CopilotProposal.id == proposal.id).values(**times)
            )
            await empty_db.commit()
        return proposal.id

    now = datetime.now(UTC)
    cancelled = {"status": "cancelled"}
    ended = {
        "resolved_8_days_ago": await prepared(staff, **cancelled, resolved_at=now - timedelta(8)),
        "resolved_6_days_ago": await prepared(staff, **cancelled, resolved_at=now - timedelta(6)),
        "expired_8_days_ago": await prepared(staff, expires_at=now - timedelta(8)),
        "expired_6_days_ago": await prepared(staff, expires_at=now - timedelta(6)),
        "pending": await prepared(staff),
        "colleagues_old": await prepared(colleague, **cancelled, resolved_at=now - timedelta(30)),
    }

    newest = await prepared(staff)

    kept = set(await empty_db.scalars(select(CopilotProposal.id)))
    assert kept == {
        ended["resolved_6_days_ago"],
        ended["expired_6_days_ago"],
        ended["pending"],
        ended["colleagues_old"],
        newest,
    }
