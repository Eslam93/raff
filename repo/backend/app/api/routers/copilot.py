"""The Copilot: its configuration for the signed-in user; chat, one message per request,
answered as a stream of server-sent events; and the borrows and returns it proposes, which staff
read, confirm or cancel.
"""

import uuid
from typing import Any

from fastapi import APIRouter, Request, status
from fastapi.responses import StreamingResponse

from app.api.deps import AppSettings, CurrentUser, StaffUser
from app.copilot import conversations, proposals
from app.copilot.chat import ChatTurn
from app.copilot.faces import face_for
from app.copilot.model import ModelClient
from app.copilot.rate_limit import RateLimiter
from app.copilot.sse import event_stream
from app.core.exceptions import AppError
from app.db.session import DbSession
from app.schemas.common import ErrorResponse, error_responses
from app.schemas.copilot import ChatRequest, CopilotConfigOut, ProposalOut

router = APIRouter(prefix="/copilot", tags=["copilot"])

UNAVAILABLE_REASON = "The assistant is not set up on this server. Everything else works as usual."

_CHAT_RESPONSES: dict[int | str, dict[str, Any]] = {
    **error_responses(signed_in=True, not_found=True),
    200: {
        "description": "text/event-stream. Events, each with JSON data: conversation "
        "{conversation_id}; status {text}; result {tool, display}, where display.kind is books, "
        "book, loans, categories, members, copy, proposal or table; message {text}; error {code, "
        "message} with code copilot_timeout, copilot_unavailable, copilot_rate_limited or "
        "copilot_failed; done {} last.",
        "content": {"text/event-stream": {"schema": {"type": "string"}}},
    },
    503: {"model": ErrorResponse, "description": "copilot_unavailable: no model is configured"},
}


class CopilotUnavailableError(AppError):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    code = "copilot_unavailable"
    message = "The assistant is not available on this server."


def _model(request: Request) -> ModelClient | None:
    model: ModelClient | None = request.app.state.copilot_model
    return model


@router.get("/config", responses=error_responses(signed_in=True))
async def copilot_config(request: Request, user: CurrentUser) -> CopilotConfigOut:
    """Whether the assistant is available, which face the user gets, and example prompts."""
    face = face_for(user)
    available = _model(request) is not None
    return CopilotConfigOut(
        available=available,
        face=face.name,
        reason=None if available else UNAVAILABLE_REASON,
        examples=list(face.examples),
    )


@router.post("/chat", response_class=StreamingResponse, responses=_CHAT_RESPONSES)
async def chat(
    request: Request,
    session: DbSession,
    settings: AppSettings,
    user: CurrentUser,
    body: ChatRequest,
) -> StreamingResponse:
    """Sends one message and streams the turn. Without conversation_id a new conversation
    starts; the conversation event names it. 503 copilot_unavailable when no model is
    configured and 404 for a conversation that is not the user's, both before the stream starts.
    """
    model = _model(request)
    if model is None:
        raise CopilotUnavailableError()
    face = face_for(user)
    conversation_id = None
    if body.conversation_id is not None:
        conversation = await conversations.find(
            session, body.conversation_id, user=user, face=face.name
        )
        conversation_id = conversation.id
    limiter: RateLimiter = request.app.state.copilot_rate_limiter
    turn = ChatTurn(
        session=session,
        user=user,
        face=face,
        model=model,
        settings=settings,
        limiter=limiter,
        conversation_id=conversation_id,
        text=body.message,
    )
    return event_stream(turn.run)


# Proposals: staff only, and each one only for the user it was prepared for.


@router.get("/proposals/{proposal_id}", responses=error_responses(staff=True, not_found=True))
async def get_proposal(
    session: DbSession, settings: AppSettings, user: StaffUser, proposal_id: uuid.UUID
) -> ProposalOut:
    """A proposal the Copilot prepared for this user. A pending proposal past expires_at reads
    as expired. 404 for another user's proposal, like a missing one.
    """
    return await proposals.get(
        session, proposal_id, user_id=user.id, max_renewals=settings.max_renewals
    )


@router.post(
    "/proposals/{proposal_id}/confirm",
    responses=error_responses(
        staff=True,
        not_found=True,
        conflicts=[
            "proposal_resolved",
            "proposal_expired",
            "copy_unavailable",
            "loan_already_returned",
            "book_archived",
            "proposal_failed",
        ],
    ),
)
async def confirm_proposal(
    session: DbSession, settings: AppSettings, user: StaffUser, proposal_id: uuid.UUID
) -> ProposalOut:
    """Makes the proposed borrow or return, recorded in the activity history as via the Copilot
    with this user as the actor, and returns the proposal with its loan. Once only:
    proposal_resolved when it is no longer pending, proposal_expired past expires_at. When the
    change is refused the proposal is marked failed: copy_unavailable, loan_already_returned and
    book_archived come back as they are, anything else as proposal_failed with the reason.
    """
    return await proposals.confirm(
        session,
        proposal_id,
        user=user,
        loan_period_days=settings.loan_period_days,
        hold_pickup_days=settings.hold_pickup_days,
        max_renewals=settings.max_renewals,
    )


@router.post(
    "/proposals/{proposal_id}/cancel",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=error_responses(
        staff=True, not_found=True, conflicts=["proposal_resolved", "proposal_expired"]
    ),
)
async def cancel_proposal(session: DbSession, user: StaffUser, proposal_id: uuid.UUID) -> None:
    """Declines the proposal; nothing changes. proposal_resolved when it is no longer pending,
    proposal_expired past expires_at.
    """
    await proposals.cancel(session, proposal_id, user=user)
