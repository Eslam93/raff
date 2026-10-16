"""A stand-in for the language model that never reaches the network.

Tests give it a script: one step per model call, each a reply, lookups to request, an error to
raise or a delay. It records every request it receives, so tests can check what the model was
shown. Without a script it runs a simple offline mode for development without a key (the
COPILOT_FAKE_MODEL setting, which production refuses): it lists the overdue loans for staff,
forecasts staff's loans when asked for a forecast, counts staff's loans by month or by category
when asked what is borrowed most or per month, looks up the member's holds or loans or searches
the catalog for the words of the message, then says it found something.
"""

import asyncio
import copy
import json
import re
from collections import deque
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from app.copilot.model import Message, ModelError, ModelReply, ToolCall, ToolChoice, Usage

_LOAN_WORDS = re.compile(r"\b(loans?|due|overdue|borrowed|my books?)\b")
_HOLD_WORDS = re.compile(r"\b(holds?|in line|reserved?|reservations?)\b")
_FIGURE_WORDS = re.compile(r"\b(most|per month|by month)\b")
# Words the offline mode leaves out of a search.
_FILLER = frozenset(
    {
        "a", "an", "and", "any", "anything", "are", "available", "book", "books", "borrow",
        "by", "can", "do", "find", "for", "have", "i", "is", "me", "of", "please", "show",
        "some", "the", "to", "what", "which", "you",
    }
)  # fmt: skip


@dataclass(frozen=True)
class FakeStep:
    text: str = ""
    # (tool name, arguments as JSON text) for each lookup requested.
    tool_calls: tuple[tuple[str, str], ...] = ()
    error: Exception | None = None
    # Seconds to wait before answering, to run into a timeout.
    delay: float = 0.0


def reply(text: str) -> FakeStep:
    return FakeStep(text=text)


def call(name: str, **arguments: Any) -> FakeStep:
    return FakeStep(tool_calls=((name, json.dumps(arguments)),))


def calls(*steps: FakeStep) -> FakeStep:
    """Several lookups in one model reply."""
    return FakeStep(tool_calls=tuple(pair for step in steps for pair in step.tool_calls))


def call_raw(name: str, arguments: str) -> FakeStep:
    """A lookup whose arguments are exactly this text, valid JSON or not."""
    return FakeStep(tool_calls=((name, arguments),))


@dataclass(frozen=True)
class FakeRequest:
    messages: list[Message]
    tool_names: list[str]
    tool_choice: ToolChoice
    timeout: float


@dataclass
class FakeModelClient:
    script: Iterable[FakeStep] | None = None
    requests: list[FakeRequest] = field(default_factory=list)

    def __post_init__(self) -> None:
        self._steps = deque(self.script) if self.script is not None else None

    async def complete(
        self,
        messages: Sequence[Message],
        *,
        tools: Sequence[Message],
        tool_choice: ToolChoice,
        timeout: float,
    ) -> ModelReply:
        tool_names = [tool["function"]["name"] for tool in tools]
        self.requests.append(
            FakeRequest(copy.deepcopy(list(messages)), tool_names, tool_choice, timeout)
        )
        if self._steps is None:
            step = _offline_step(messages, tool_names)
        elif self._steps:
            step = self._steps.popleft()
        else:
            raise ModelError("the fake model's script has no more steps")

        if step.delay:
            await asyncio.sleep(step.delay)
        if step.error is not None:
            raise step.error
        return _reply(step, call_number=len(self.requests))


def _reply(step: FakeStep, *, call_number: int) -> ModelReply:
    tool_calls = tuple(
        ToolCall(id=f"call_{call_number}_{index}", name=name, arguments=arguments)
        for index, (name, arguments) in enumerate(step.tool_calls)
    )
    message: Message = {"role": "assistant", "content": step.text or None}
    if tool_calls:
        message["tool_calls"] = [
            {"id": c.id, "type": "function", "function": {"name": c.name, "arguments": c.arguments}}
            for c in tool_calls
        ]
    usage = Usage(prompt_tokens=10 * call_number, completion_tokens=len(step.text.split()))
    return ModelReply(text=step.text, tool_calls=tool_calls, message=message, usage=usage)


def _offline_step(messages: Sequence[Message], tool_names: list[str]) -> FakeStep:
    last = messages[-1]
    if last["role"] == "tool":
        result = json.loads(last["content"])
        lists = ("books", "loans", "holds", "rows")
        empty = "error" in result or any(result.get(key) == [] for key in lists)
        return reply("I found nothing that matches." if empty else "Here is what I found.")

    text = str(last.get("content") or "").lower()
    if "get_overdue_loans" in tool_names and "overdue" in text:
        return call("get_overdue_loans")
    if "forecast_metric" in tool_names and "forecast" in text:
        return call("forecast_metric", metric="loans")
    if "query_metrics" in tool_names and _FIGURE_WORDS.search(text):
        if "month" in text:
            return call("query_metrics", metric="loans", group_by="month")
        return call(
            "query_metrics", metric="loans", group_by="category", period={"preset": "this_quarter"}
        )
    if "my_holds" in tool_names and _HOLD_WORDS.search(text):
        return call("my_holds")
    if "get_my_loans" in tool_names and _LOAN_WORDS.search(text):
        return call("get_my_loans", status="active")
    if "categor" in text:
        return call("list_categories")
    words = [word for word in re.findall(r"[\w'-]+", text) if word not in _FILLER]
    return call("search_catalog", query=" ".join(words), available_only="available" in text)
