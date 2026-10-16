"""The Copilot's parts that need no database: the number check, the faces and their tools, the
rate limit, the settings, the event format and the offline fake.
"""

import asyncio
import json
import re
import uuid

import httpx
import pytest
from pydantic import ValidationError

from app.copilot.clients import create_model_client
from app.copilot.faces import FACES, MEMBER_FACE, STAFF_FACE
from app.copilot.fake import FakeModelClient, reply
from app.copilot.model import ModelError
from app.copilot.numbers import allowed_runs, data_digit_runs, digit_runs, unsupported_numbers
from app.copilot.openrouter import OpenRouterClient
from app.copilot.rate_limit import RateLimiter
from app.copilot.sse import event_stream, format_event
from app.copilot.tools import BookHolds, GetMyLoans, MyHolds, PrepareBorrow, SearchCatalog
from app.core.config import DEFAULT_COPILOT_MODEL, Settings


def make_settings(**values):
    return Settings(_env_file=None, **{"openrouter_api_key": None, **values})


def schema_labels(schema) -> list[str]:
    """Every "title" label in a JSON schema, at any depth."""
    if isinstance(schema, dict):
        own = [value for key, value in schema.items() if key == "title" and isinstance(value, str)]
        return own + [label for value in schema.values() for label in schema_labels(value)]
    if isinstance(schema, list):
        return [label for value in schema for label in schema_labels(value)]
    return []


# The number check


def test_digit_runs_fold_thousands_commas_and_leading_zeros():
    assert digit_runs("4,120 loans on 2026-09-05, copy CP-0012") == {"4120", "2026", "9", "5", "12"}


def test_numbers_in_lookup_results_and_user_words_are_allowed():
    allowed = allowed_runs(
        [{"copies_total": 3, "due_on": "2026-10-02", "title": "Fahrenheit 451"}],
        ["Anything from 1965?"],
    )

    assert unsupported_numbers("Due on 2 October 2026; 3 copies of Fahrenheit 451.", allowed) == []
    assert unsupported_numbers("Books from 1965 are rare.", allowed) == []
    assert unsupported_numbers("It has 7 copies, due in 12 days.", allowed) == ["7", "12"]


def test_list_numbering_is_not_a_number():
    text = "1. Dune\n2) Emma\n - 3. Beloved\nWe have 4."

    assert unsupported_numbers(text, set()) == ["4"]


def test_ids_cannot_vouch_for_a_number():
    result = {"id": "5f0e7a12-0000-4000-8000-000000000042", "book_id": "123", "copies": [1]}

    assert data_digit_runs(result) == {"1"}


def test_booleans_and_nulls_add_nothing():
    assert data_digit_runs({"overdue": True, "isbn": None, "year": 1965}) == {"1965"}


# Faces and tools


def test_the_role_chooses_the_face_and_its_tools():
    assert [tool.name for tool in MEMBER_FACE.tools] == [
        "search_catalog",
        "list_categories",
        "get_book",
        "get_my_loans",
        "my_holds",
    ]
    assert [tool.name for tool in STAFF_FACE.tools] == [
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
    assert STAFF_FACE.tool("get_my_loans") is None


@pytest.mark.parametrize("face", FACES.values(), ids=lambda face: face.name)
def test_prompts_hold_no_digits_and_state_the_rules(face):
    assert not re.search(r"\d", face.prompt)
    for rule in ("Never state one from memory", "Every number you write", "ask one short question"):
        assert rule in face.prompt


def test_the_member_prompt_declines_features_that_do_not_exist():
    for feature in ("reserve", "renew", "fines", "contact staff"):
        assert feature in MEMBER_FACE.prompt


def test_the_staff_prompt_leaves_every_change_to_the_confirm():
    prompt = STAFF_FACE.prompt

    for rule in (
        "Preparing changes nothing",
        "list them briefly and ask which one",
        "Never prepare a borrow or a return for a member, a book or a copy you are not sure of",
        "Never say that the loan was made or the copy was returned",
        "Prepare one borrow or return at a time",
    ):
        assert rule in prompt
    for feature in ("reserve", "renew", "fines", "send messages", "change or delete member"):
        assert feature in prompt


@pytest.mark.parametrize("face", FACES.values(), ids=lambda face: face.name)
def test_the_prompts_know_holds_exist_and_leave_them_to_the_app_for_now(face):
    prompt = face.prompt

    # Holds and renewals exist now: no prompt may say the app has no such feature.
    assert "reserve or hold books" not in prompt
    assert "loans and holds) come only from lookups" in prompt
    assert "give counts and places in line exactly as the results give them" in prompt
    assert "Holds have no card" in prompt


def test_the_member_prompt_points_holds_and_renewals_to_the_books_page_and_my_loans():
    prompt = MEMBER_FACE.prompt

    for statement in (
        "The member places a hold on the book's page, cancels it there or in My loans, and "
        "renews a loan in My loans.",
        "You cannot do any of this for them yet",
        "point to the book's page or My loans",
        "never guess or describe who has a book or who is waiting for it",
    ):
        assert statement in prompt


def test_the_staff_prompt_points_holds_and_renewals_to_the_app():
    prompt = STAFF_FACE.prompt

    for statement in (
        "You cannot place or cancel holds or renew loans yet.",
        "a book's page places a hold for a member and cancels holds",
        "A copy set aside for a member's hold can be lent only to that member.",
        "who is waiting for it, in line order",
    ):
        assert statement in prompt


@pytest.mark.parametrize("face", FACES.values(), ids=lambda face: face.name)
def test_tool_descriptions_hold_no_digits(face):
    for definition in face.definitions():
        assert not re.search(r"\d", definition["function"]["description"])


def test_my_holds_has_no_identity_parameter():
    [definition] = [d for d in MEMBER_FACE.definitions() if d["function"]["name"] == "my_holds"]

    parameters = definition["function"]["parameters"]
    assert set(parameters["properties"]) == {"status"}
    assert parameters["properties"]["status"]["enum"] == ["open", "closed"]
    assert MyHolds.model_validate({}).status == "open"
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        MyHolds.model_validate({"member_id": "someone"})


def test_book_holds_needs_a_book_and_lists_open_or_closed_holds():
    book_id = str(uuid.uuid4())

    assert BookHolds.model_validate({"book_id": book_id}).status == "open"
    for arguments in ({}, {"book_id": book_id, "status": "all"}):
        with pytest.raises(ValidationError):
            BookHolds.model_validate(arguments)


def test_prepare_borrow_takes_exactly_one_of_a_book_or_a_copy():
    member = str(uuid.uuid4())

    assert PrepareBorrow.model_validate({"member_id": member, "copy_code": "217"}).book_id is None
    for arguments in ({}, {"book_id": str(uuid.uuid4()), "copy_code": "217"}):
        with pytest.raises(ValidationError, match="exactly one of book_id or copy_code"):
            PrepareBorrow.model_validate({"member_id": member, **arguments})


@pytest.mark.parametrize("face", FACES.values(), ids=lambda face: face.name)
def test_tool_definitions_are_closed_json_schemas(face):
    for definition in face.definitions():
        parameters = definition["function"]["parameters"]
        assert definition["type"] == "function"
        assert parameters["type"] == "object"
        assert parameters["additionalProperties"] is False
        assert schema_labels(parameters) == []


def test_my_loans_has_no_identity_parameter():
    [definition] = [d for d in MEMBER_FACE.definitions() if d["function"]["name"] == "get_my_loans"]

    assert set(definition["function"]["parameters"]["properties"]) == {"status"}
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        GetMyLoans.model_validate({"status": "active", "member_id": "someone"})


def test_search_returns_at_most_ten_books():
    with pytest.raises(ValidationError):
        SearchCatalog.model_validate({"limit": 11})


# Rate limit


def test_the_rate_limit_counts_per_user_in_a_sliding_minute():
    now = [0.0]
    limiter = RateLimiter(2, clock=lambda: now[0])

    assert [limiter.allow("maya"), limiter.allow("maya"), limiter.allow("maya")] == [
        True,
        True,
        False,
    ]
    assert limiter.allow("omar") is True
    now[0] = 59.9
    assert limiter.allow("maya") is False
    now[0] = 60.0
    assert limiter.allow("maya") is True


# Settings


def test_copilot_defaults():
    settings = make_settings()

    assert settings.copilot_model == DEFAULT_COPILOT_MODEL
    assert settings.openrouter_base_url == "https://openrouter.ai/api/v1"
    assert (settings.copilot_timeout_seconds, settings.copilot_max_tool_rounds) == (45, 6)
    assert settings.copilot_rate_per_minute == 20
    assert settings.copilot_key is None
    assert settings.copilot_fake_model is False


async def test_the_model_client_follows_the_settings():
    async with httpx.AsyncClient() as http:
        clients = [
            create_model_client(make_settings(**values), http)
            for values in ({}, {"openrouter_api_key": ""}, {"openrouter_api_key": "k"})
        ]
        fake = create_model_client(make_settings(copilot_fake_model=True), http)

    assert clients[:2] == [None, None]
    assert isinstance(clients[2], OpenRouterClient)
    assert isinstance(fake, FakeModelClient)


def test_production_refuses_the_fake_model():
    with pytest.raises(ValidationError, match="COPILOT_FAKE_MODEL"):
        make_settings(app_env="production", session_secret="k" * 40, copilot_fake_model=True)


def test_the_key_is_hidden_in_the_settings_repr():
    settings = make_settings(openrouter_api_key="secret-value")

    assert "secret-value" not in repr(settings)
    assert settings.copilot_key == "secret-value"


# Events and the offline fake


def test_an_event_is_a_named_line_with_compact_json():
    assert format_event("status", {"text": "Searching"}) == (
        'event: status\ndata: {"text":"Searching"}\n\n'
    )


async def test_a_quiet_stream_sends_keepalive_comments():
    async def produce(emit):
        await asyncio.sleep(0.05)
        await emit("done", {})

    response = event_stream(produce, keepalive_seconds=0.01)
    chunks = [chunk async for chunk in response.body_iterator]

    assert ": keepalive\n\n" in chunks
    assert chunks[-1] == "event: done\ndata: {}\n\n"


async def test_the_turn_is_cancelled_when_the_client_goes_away():
    cancelled = asyncio.Event()

    async def produce(emit):
        await emit("status", {"text": "Working"})
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            cancelled.set()
            raise

    body = event_stream(produce).body_iterator
    first = await anext(body)
    await body.aclose()

    assert first.startswith("event: status")
    await asyncio.wait_for(cancelled.wait(), timeout=1)


async def test_the_offline_fake_searches_then_answers():
    model = FakeModelClient()
    tools = STAFF_FACE.definitions()

    first = await model.complete(
        [{"role": "user", "content": "Anything by Frank Herbert?"}],
        tools=tools,
        tool_choice="auto",
        timeout=1,
    )
    [call] = first.tool_calls
    second = await model.complete(
        [{"role": "tool", "tool_call_id": call.id, "content": '{"books": [{"title": "Dune"}]}'}],
        tools=tools,
        tool_choice="auto",
        timeout=1,
    )

    assert (call.name, json.loads(call.arguments)) == (
        "search_catalog",
        {"query": "frank herbert", "available_only": False},
    )
    assert second.text == "Here is what I found."


@pytest.mark.parametrize(
    ("face", "tool"), [(STAFF_FACE, "get_overdue_loans"), (MEMBER_FACE, "get_my_loans")]
)
async def test_the_offline_fake_lists_overdue_loans_for_staff_and_own_loans_for_members(face, tool):
    model = FakeModelClient()

    first = await model.complete(
        [{"role": "user", "content": "Show everything overdue"}],
        tools=face.definitions(),
        tool_choice="auto",
        timeout=1,
    )

    [call] = first.tool_calls
    assert call.name == tool


@pytest.mark.parametrize(
    ("face", "tool"), [(MEMBER_FACE, "my_holds"), (STAFF_FACE, "search_catalog")]
)
async def test_the_offline_fake_looks_up_a_members_own_holds(face, tool):
    model = FakeModelClient()

    first = await model.complete(
        [{"role": "user", "content": "Where am I in line for my holds?"}],
        tools=face.definitions(),
        tool_choice="auto",
        timeout=1,
    )
    [call] = first.tool_calls
    second = await model.complete(
        [{"role": "tool", "tool_call_id": call.id, "content": '{"holds": []}'}],
        tools=face.definitions(),
        tool_choice="auto",
        timeout=1,
    )

    assert call.name == tool
    assert second.text == "I found nothing that matches."


async def test_a_script_that_runs_out_is_a_model_error():
    model = FakeModelClient([reply("Only one.")])
    await model.complete([], tools=[], tool_choice="auto", timeout=1)

    with pytest.raises(ModelError):
        await model.complete([], tools=[], tool_choice="auto", timeout=1)
