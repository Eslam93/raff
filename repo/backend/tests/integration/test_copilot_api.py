"""The Copilot's API with a scripted fake model: the stream, the tools as the signed-in user, the
number check, the limits and the stored conversation. Nothing here reaches the network.
"""

import json
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from copilot_stream import chat, data_of, names, tool_results
from sqlalchemy import select

from app.copilot.engine import FALLBACK_INTRO
from app.copilot.fake import FakeStep, call, call_raw, reply
from app.copilot.model import ModelError, ModelUnavailableError
from app.models import CopilotConversation, CopilotMessage
from app.schemas.books import BookSummary
from app.services.activity import format_day

pytestmark = pytest.mark.integration


def due_in(days: int) -> str:
    return (datetime.now(UTC).date() + timedelta(days=days)).isoformat()


def day_in(days: int) -> str:
    """The date `days` from today as the tools write it for the model: "3 Oct 2026"."""
    return format_day(datetime.now(UTC).date() + timedelta(days=days))


@pytest.fixture
async def demo_member(member_client) -> dict[str, Any]:
    """The demo member account's UserOut; the account exists once member_client signed in."""
    return (await member_client.get("/api/auth/me")).json()


# Configuration and availability


@pytest.mark.parametrize("role", ["member", "staff"])
async def test_without_a_key_the_copilot_is_unavailable_and_chat_is_503(role, open_client):
    http = await open_client(role)

    config = (await http.get("/api/copilot/config")).json()
    response = await http.post("/api/copilot/chat", json={"message": "Hello"})

    assert config["available"] is False
    assert config["face"] == role
    assert config["reason"]
    assert 3 <= len(config["examples"]) <= 4
    assert response.status_code == 503
    assert response.headers["content-type"] == "application/json"
    assert response.json()["error"]["code"] == "copilot_unavailable"


async def test_with_a_model_the_copilot_is_available(copilot):
    http, _ = await copilot()

    config = (await http.get("/api/copilot/config")).json()

    assert config == {
        "available": True,
        "face": "member",
        "reason": None,
        "examples": config["examples"],
    }


async def test_the_message_must_be_1_to_2000_characters(copilot):
    http, _ = await copilot()

    empty = await http.post("/api/copilot/chat", json={"message": "   "})
    long = await http.post("/api/copilot/chat", json={"message": "x" * 2001})

    assert (empty.status_code, long.status_code) == (422, 422)


# The stream


async def test_member_search_streams_book_cards_then_the_reply(
    make_book, make_member, borrow, copilot
):
    dune = await make_book(title="Dune", category="Science Fiction", copies=2)
    await make_book(title="Sapiens", author="Yuval Noah Harari", category="History")
    out = await make_book(title="Neuromancer", author="William Gibson", category="Science Fiction")
    await borrow(out["copies"][0]["id"], (await make_member())["id"])
    http, model = await copilot(
        call("search_catalog", category="science fiction", available_only=True),
        reply("Dune is available now."),
    )

    events = await chat(http, "Show me available science fiction")

    assert names(events) == ["conversation", "status", "result", "message", "done"]
    [conversation] = data_of(events, "conversation")
    assert uuid.UUID(conversation["conversation_id"])
    assert data_of(events, "status") == [{"text": "Searching the catalog"}]
    [result] = data_of(events, "result")
    assert result["tool"] == "search_catalog"
    assert result["display"]["kind"] == "books"
    [card] = result["display"]["items"]
    assert card["id"] == dune["id"]
    assert (card["availability"], card["copies_available"], card["copies_total"]) == (
        "available",
        2,
        2,
    )
    assert set(card) == set(BookSummary.model_fields)
    assert data_of(events, "message") == [{"text": "Dune is available now."}]
    assert data_of(events, "done") == [{}]
    [found] = tool_results(model, 1)
    assert found["matches"] == 1
    assert [book["title"] for book in found["books"]] == ["Dune"]


async def test_availability_is_answered_with_the_lookup_numbers(
    make_book, make_member, borrow, copilot
):
    dune = await make_book(title="Dune", copies=2)
    omar = await make_member("Omar Farouk")
    await borrow(dune["copies"][0]["id"], omar["id"], due_date=due_in(5))
    answer = "Two copies exist and 1 of 2 is available now."
    http, model = await copilot(
        call("search_catalog", query="Dune"),
        call("get_book", book_id=dune["id"]),
        reply(answer),
    )

    events = await chat(http, "Can I borrow Dune?")

    assert names(events) == [
        "conversation",
        "status",
        "result",
        "status",
        "result",
        "message",
        "done",
    ]
    assert data_of(events, "message") == [{"text": answer}]
    book = tool_results(model, 2)[1]
    assert (book["copies_available"], book["copies_total"]) == (1, 2)
    assert [copy["status"] for copy in book["copies"]] == ["borrowed", "available"]
    assert book["copies"][0]["due_back"] == day_in(5)


# Tools act as the signed-in user


async def test_my_loans_takes_no_member_id_and_reads_only_the_signed_in_members_loans(
    make_book, make_member, borrow, demo_member, copilot
):
    book = await make_book(title="Dune", copies=2)
    omar = await make_member("Omar Farouk")
    await borrow(book["copies"][0]["id"], omar["id"])
    mine = (await borrow(book["copies"][1]["id"], demo_member["member_id"])).json()
    http, model = await copilot(
        call("get_my_loans", status="active", member_id=omar["id"]),
        call("get_my_loans", status="active"),
        reply("You have Dune."),
    )

    events = await chat(http, "What do I have on loan?")

    rejected = tool_results(model, 1)[0]
    assert rejected["error"] == "invalid_arguments"
    assert rejected["problems"] == [
        {"field": "member_id", "problem": "Extra inputs are not permitted"}
    ]
    loans = tool_results(model, 2)[1]
    assert [loan["copy_code"] for loan in loans["loans"]] == [mine["copy"]["code"]]
    assert loans["today"] == day_in(0)
    [result] = data_of(events, "result")
    assert result["display"]["kind"] == "loans"
    assert [loan["id"] for loan in result["display"]["items"]] == [mine["id"]]
    assert result["display"]["items"][0]["copy"]["code"] == mine["copy"]["code"]
    everything = json.dumps(events) + json.dumps([r.messages for r in model.requests])
    assert "Omar Farouk" not in everything


async def test_a_member_never_sees_who_has_a_book(make_book, make_member, borrow, copilot):
    book = await make_book(title="Dune")
    omar = await make_member("Omar Farouk")
    await borrow(book["copies"][0]["id"], omar["id"], due_date=due_in(9))
    http, model = await copilot(call("get_book", book_id=book["id"]), reply("It is out."))

    events = await chat(http, "Who has Dune?")

    [result] = data_of(events, "result")
    [copy] = result["display"]["book"]["copies"]
    assert (copy["status"], copy["active_loan"]) == ("borrowed", None)
    [seen] = tool_results(model, 1)[0]["copies"]
    assert seen == {"code": book["copies"][0]["code"], "status": "borrowed", "due_back": day_in(9)}
    everything = json.dumps(events) + json.dumps([r.messages for r in model.requests])
    assert "Omar Farouk" not in everything
    assert omar["id"] not in everything


async def test_the_staff_face_has_staff_tools_and_sees_borrowers(
    make_book, make_member, borrow, copilot
):
    book = await make_book(title="Dune")
    omar = await make_member("Omar Farouk")
    await borrow(book["copies"][0]["id"], omar["id"])
    http, model = await copilot(
        call("get_my_loans"),
        call("get_book", book_id=book["id"]),
        reply("Omar Farouk has it."),
        role="staff",
    )

    events = await chat(http, "Who has Dune?")

    assert model.requests[0].tool_names == [
        "search_catalog",
        "list_categories",
        "get_book",
        "search_members",
        "get_member_loans",
        "get_book_loans",
        "book_holds",
        "get_overdue_loans",
        "lookup_copy",
        "prepare_borrow",
        "prepare_return",
        "forecast_metric",
        "describe_metrics",
        "query_metrics",
    ]
    assert tool_results(model, 1)[0]["error"] == "unknown_tool"
    [copy] = tool_results(model, 2)[1]["copies"]
    assert (copy["borrower"], copy["overdue"]) == ("Omar Farouk", False)
    [result] = data_of(events, "result")
    assert result["display"]["book"]["copies"][0]["active_loan"]["member"]["id"] == omar["id"]
    assert "You are the Staff Copilot" in model.requests[0].messages[0]["content"]


async def test_invalid_tool_arguments_go_back_to_the_model(copilot):
    http, model = await copilot(
        call("search_catalog", limit=50),
        call_raw("get_book", "not json"),
        call("get_book", book_id="dune"),
        reply("Which book do you mean?"),
    )

    events = await chat(http, "Show me Dune")

    too_many = tool_results(model, 1)[0]
    assert too_many["error"] == "invalid_arguments"
    assert [problem["field"] for problem in too_many["problems"]] == ["limit"]
    assert tool_results(model, 2)[1] == {
        "error": "invalid_arguments",
        "message": "The arguments must be a JSON object.",
    }
    assert tool_results(model, 3)[2]["problems"][0]["field"] == "book_id"
    # Rejected calls run nothing, so the panel shows no status or cards for them.
    assert names(events) == ["conversation", "message", "done"]


async def test_a_book_that_does_not_exist_is_reported_to_the_model(copilot):
    http, model = await copilot(
        call("get_book", book_id=str(uuid.uuid4())), reply("I could not find it.")
    )

    await chat(http, "Show me that book")

    assert tool_results(model, 1)[0] == {"error": "not_found", "message": "Book not found."}


# The number check


async def test_an_invented_number_gets_one_retry_then_the_plain_results(make_book, copilot):
    await make_book(title="Dune", copies=2)
    http, model = await copilot(
        call("search_catalog", query="Dune"),
        reply("We have 7 copies of Dune."),
        reply("There are still 7 copies."),
    )

    events = await chat(http, "How many copies of Dune are there?")

    [message] = data_of(events, "message")
    assert message["text"] == "\n\n".join(
        [FALLBACK_INTRO, "Books in the catalog:\n- Dune by Frank Herbert: 2 of 2 copies available"]
    )
    assert len(model.requests) == 3
    retry = model.requests[2]
    assert retry.tool_choice == "none"
    assert retry.messages[-2] == {"role": "assistant", "content": "We have 7 copies of Dune."}
    assert retry.messages[-1]["role"] == "user"
    assert ": 7." in retry.messages[-1]["content"]


async def test_a_corrected_reply_is_sent(make_book, copilot):
    await make_book(title="Dune", copies=2)
    corrected = "Dune has 2 copies, and 2 are available."
    http, _ = await copilot(
        call("search_catalog", query="Dune"), reply("Dune has 3 copies."), reply(corrected)
    )

    events = await chat(http, "How many copies of Dune are there?")

    assert data_of(events, "message") == [{"text": corrected}]


async def test_an_empty_reply_gets_one_nudge_that_can_still_make_lookups(make_book, copilot):
    # The real model sometimes stops between the lookups of a task of several steps, with
    # neither an answer nor the next lookup. The nudge must leave the tools on offer, or the
    # task cannot finish.
    await make_book(title="Dune", category="Science Fiction", copies=2)
    http, model = await copilot(
        call("list_categories"),
        reply(""),
        call("search_catalog", query="Dune"),
        reply("Dune is available."),
    )

    events = await chat(http, "Is Dune available?")

    assert data_of(events, "message") == [{"text": "Dune is available."}]
    assert [data["tool"] for data in data_of(events, "result")] == [
        "list_categories",
        "search_catalog",
    ]
    nudge = model.requests[2]
    assert nudge.tool_choice == "auto"
    assert nudge.messages[-1]["role"] == "user"


async def test_a_second_empty_reply_ends_with_the_plain_results(make_book, copilot):
    await make_book(title="Dune", category="Science Fiction")
    http, model = await copilot(call("list_categories"), reply(""), reply(""))

    events = await chat(http, "What categories are there?")

    assert data_of(events, "message") == [
        {"text": f"{FALLBACK_INTRO}\n\nCategories: Science Fiction."}
    ]
    assert len(model.requests) == 3


async def test_numbers_from_the_users_words_and_list_numbering_pass(copilot):
    text = "1. Books from 1965 would need a search.\n2. Try the catalog."
    http, model = await copilot(reply(text))

    events = await chat(http, "Anything from 1965?")

    assert data_of(events, "message") == [{"text": text}]
    assert len(model.requests) == 1


# Limits and failures


async def test_the_round_limit_ends_the_turn_with_the_plain_results(make_book, copilot):
    await make_book(title="Dune", category="Science Fiction")
    http, model = await copilot(
        call("list_categories"),
        call("list_categories"),
        call("list_categories"),
        copilot_max_tool_rounds=2,
    )

    events = await chat(http, "What categories are there?")

    assert names(events) == [
        "conversation",
        "status",
        "result",
        "status",
        "result",
        "message",
        "done",
    ]
    assert data_of(events, "message") == [
        {"text": f"{FALLBACK_INTRO}\n\nCategories: Science Fiction."}
    ]
    assert len(model.requests) == 3


async def test_a_turn_that_runs_out_of_time_ends_with_copilot_timeout(copilot):
    http, _ = await copilot(FakeStep(delay=10), copilot_timeout_seconds=0.3)

    started = time.monotonic()
    events = await chat(http, "Hello")

    assert time.monotonic() - started < 5
    assert names(events) == ["conversation", "error", "done"]
    assert data_of(events, "error")[0]["code"] == "copilot_timeout"
    assert data_of(events, "error")[0]["message"]


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (ModelUnavailableError("refused"), "copilot_unavailable"),
        (ModelError("bad answer"), "copilot_failed"),
    ],
)
async def test_a_model_error_ends_the_turn_with_an_error_event(error, code, copilot):
    http, _ = await copilot(FakeStep(error=error))

    events = await chat(http, "Hello")

    assert names(events) == ["conversation", "error", "done"]
    assert data_of(events, "error")[0]["code"] == code


async def test_too_many_messages_are_refused_with_copilot_rate_limited(copilot):
    http, model = await copilot(reply("Hello."), reply("Again."), copilot_rate_per_minute=1)

    first = await chat(http, "Hello")
    second = await chat(http, "Hello again")

    assert names(first)[-2:] == ["message", "done"]
    assert names(second) == ["error", "done"]
    assert data_of(second, "error")[0]["code"] == "copilot_rate_limited"
    assert len(model.requests) == 1


# Conversations


async def test_a_follow_up_gets_the_earlier_messages(make_book, copilot, empty_db):
    await make_book(title="Dune", copies=2)
    http, model = await copilot(
        call("search_catalog", query="Dune"),
        reply("Dune is on the shelf."),
        # 2 comes from the first turn's lookup, so the number check lets it through.
        reply("Both of its 2 copies are available."),
    )

    first = await chat(http, "Is Dune in?")
    conversation_id = data_of(first, "conversation")[0]["conversation_id"]
    second = await chat(http, "How many copies?", conversation_id)

    assert data_of(second, "conversation") == [{"conversation_id": conversation_id}]
    assert data_of(second, "message") == [{"text": "Both of its 2 copies are available."}]
    sent = model.requests[2].messages
    assert [m["role"] for m in sent] == ["system", "user", "assistant", "tool", "assistant", "user"]
    assert [sent[1]["content"], sent[4]["content"], sent[5]["content"]] == [
        "Is Dune in?",
        "Dune is on the shelf.",
        "How many copies?",
    ]
    assert sent[2]["tool_calls"][0]["id"] == sent[3]["tool_call_id"]

    conversation = await empty_db.scalar(select(CopilotConversation))
    assert conversation is not None
    assert (str(conversation.id), conversation.face) == (conversation_id, "member")
    stored = await empty_db.scalars(select(CopilotMessage.role).order_by(CopilotMessage.id))
    assert stored.all() == ["user", "assistant", "tool", "assistant", "user", "assistant"]


async def test_only_the_latest_messages_are_sent(copilot):
    steps = [reply(f"Answer {n}.") for n in range(12)]
    http, model = await copilot(*steps)

    conversation_id = None
    for n in range(12):
        events = await chat(http, f"Question {n}", conversation_id)
        conversation_id = data_of(events, "conversation")[0]["conversation_id"]

    sent = model.requests[11].messages
    # The system prompt, the latest 20 stored messages, then the new question.
    assert len(sent) == 22
    assert sent[1]["content"] == "Question 1"
    assert sent[-1]["content"] == "Question 11"


async def test_another_users_conversation_is_not_found(copilot):
    member, _ = await copilot(reply("Hello."))
    staff, _ = await copilot(reply("Hello."), role="staff")
    events = await chat(member, "Hello")
    conversation_id = data_of(events, "conversation")[0]["conversation_id"]

    theirs = await staff.post(
        "/api/copilot/chat", json={"message": "Hi", "conversation_id": conversation_id}
    )
    unknown = await member.post(
        "/api/copilot/chat", json={"message": "Hi", "conversation_id": str(uuid.uuid4())}
    )

    assert (theirs.status_code, unknown.status_code) == (404, 404)
    assert theirs.json()["error"]["code"] == "not_found"
