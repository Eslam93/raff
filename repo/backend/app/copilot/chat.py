"""One chat message, from the request to the stream's last event.

The events, in order: conversation (the conversation the turn belongs to), then status and
result while lookups run, then message (the reply) or error, and done last, always. The user's
message is stored when the turn starts. The finished lookups and the reply are stored when it
ends, also after a timeout or a model error, so a follow-up has the same context.

One log line per turn records the face, rounds, tools, latency, token usage and outcome. It never
holds message text.
"""

import asyncio
import time
import uuid
from dataclasses import dataclass

from sqlalchemy.exc import StatementError
from sqlalchemy.ext.asyncio import AsyncSession

from app.copilot import conversations
from app.copilot.engine import TurnError, TurnResult, run_turn
from app.copilot.faces import Face
from app.copilot.model import ModelClient
from app.copilot.rate_limit import RateLimiter
from app.copilot.sse import Emit
from app.copilot.tools import ToolContext
from app.core.config import Settings
from app.core.logging import get_logger
from app.models import User

log = get_logger(__name__)

RATE_LIMITED_MESSAGE = (
    "You are sending messages faster than the assistant can answer. Wait a minute and try again."
)
ERROR_MESSAGES: dict[TurnError, str] = {
    "copilot_timeout": "The assistant took too long to answer. Try again.",
    "copilot_unavailable": "The assistant is not available right now.",
    "copilot_failed": "The assistant could not answer. Try again.",
}


@dataclass(frozen=True)
class ChatTurn:
    session: AsyncSession
    user: User
    face: Face
    model: ModelClient
    settings: Settings
    limiter: RateLimiter
    # The conversation to continue; None starts a new one.
    conversation_id: uuid.UUID | None
    text: str

    async def run(self, emit: Emit) -> None:
        started = time.monotonic()
        result = TurnResult(outcome="failed")
        try:
            if self.limiter.allow(self.user.id):
                result = await self._converse(emit)
            else:
                result.outcome = "rate_limited"
                await _error(emit, "copilot_rate_limited", RATE_LIMITED_MESSAGE)
        except asyncio.CancelledError:
            result.outcome = "cancelled"
            raise
        except Exception as exc:
            # A database error's message can include the statement's parameters, which hold
            # message text, so only its type is logged.
            log.error(
                "copilot_turn_failed",
                error=type(exc).__name__,
                exc_info=not isinstance(exc, StatementError),
            )
            await _error(emit, "copilot_failed", ERROR_MESSAGES["copilot_failed"])
        finally:
            await emit("done", {})
            log.info(
                "copilot_turn",
                face=self.face.name,
                outcome=result.outcome,
                rounds=result.rounds,
                model_calls=result.model_calls,
                tools=result.tools,
                prompt_tokens=result.usage.prompt_tokens,
                completion_tokens=result.usage.completion_tokens,
                latency_ms=round((time.monotonic() - started) * 1000),
            )

    async def _converse(self, emit: Emit) -> TurnResult:
        session = self.session
        conversation_id = self.conversation_id
        if conversation_id is None:
            conversation = await conversations.start(session, user=self.user, face=self.face.name)
            conversation_id = conversation.id
        history = await conversations.history(session, conversation_id)
        await conversations.add(session, conversation_id, [{"role": "user", "content": self.text}])
        await session.commit()
        await emit("conversation", {"conversation_id": str(conversation_id)})

        result = await run_turn(
            self.model,
            self.face,
            ToolContext(
                session=session,
                user=self.user,
                conversation_id=conversation_id,
                loan_period_days=self.settings.loan_period_days,
                max_renewals=self.settings.max_renewals,
            ),
            history=history,
            user_text=self.text,
            timeout_seconds=self.settings.copilot_timeout_seconds,
            max_tool_rounds=self.settings.copilot_max_tool_rounds,
            emit=emit,
        )
        if result.error is not None:
            # A lookup cut short by the deadline can leave the transaction unusable.
            await session.rollback()
        if result.messages:
            await conversations.add(session, conversation_id, result.messages)
            await session.commit()

        if result.error is not None:
            await _error(emit, result.error, ERROR_MESSAGES[result.error])
        else:
            await emit("message", {"text": result.reply or ""})
        return result


async def _error(emit: Emit, code: str, message: str) -> None:
    await emit("error", {"code": code, "message": message})
