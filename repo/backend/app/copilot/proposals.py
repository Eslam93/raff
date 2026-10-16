"""Borrow and return proposals: the Copilot prepares a change, and only the user's confirm makes it.

Preparing checks what the change itself will check, without writing a loan, and stores the
proposal: bound to the user who asked, one-time, and pending for ten minutes. It is committed
before the tool returns, so a card never points at an unsaved proposal. Preparing also deletes
the user's proposals that were resolved, or that expired, more than a week ago.

Confirming locks the proposal's row, so of two confirms at once only one finds it pending. It
marks the proposal confirmed and makes the change through the circulation service, as the user
and via the Copilot, so the status change commits with the loan. When the service refuses,
nothing it did is kept: the proposal is marked failed with the error. After a confirm, a cancel,
a failure or an expiry, a note in the proposal's conversation tells the model the outcome, so a
follow-up question gets it right.

A pending proposal past its expiry reads as expired everywhere, by the database clock, before
anything writes that status.
"""

import uuid
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import ColumnElement, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.copilot import conversations
from app.core.config import DEFAULT_HOLD_PICKUP_DAYS, DEFAULT_MAX_RENEWALS
from app.core.exceptions import (
    AppError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ValidationFailedError,
)
from app.models import CopilotProposal, ProposalAction, User
from app.schemas.copilot import ProposalOut
from app.schemas.loans import BookRef, CopyRef, LoanOut
from app.schemas.members import MemberRef
from app.services import activity, circulation

PROPOSAL_LIFETIME = timedelta(minutes=10)
# How long a proposal is kept once it was resolved or expired, for its card to still show it.
PROPOSAL_KEPT = timedelta(days=7)
# Refusals of the circulation service that a failed confirm answers with as they are. Any other
# refusal becomes proposal_failed with the service's message.
PASSED_THROUGH = frozenset({"copy_unavailable", "loan_already_returned", "book_archived"})


# Preparing


async def prepare_borrow(
    session: AsyncSession,
    *,
    user: User,
    conversation_id: uuid.UUID | None,
    member_id: uuid.UUID,
    book_id: uuid.UUID | None = None,
    copy_code: str | None = None,
    due_date: date | None = None,
    loan_period_days: int,
) -> ProposalOut:
    """Checks a borrow as circulation.borrow will, and stores it as a pending proposal with its
    concrete due date. With a book, the copy chosen is the one set aside for the member's hold,
    or else the book's first available copy by code, as the web app's borrow of a book chooses.
    The errors are the borrow's own (copy_held among them), a refused due date named by its
    rule, and no_copy_available.
    """
    _require_staff(user)
    try:
        if book_id is not None:
            copy_id = await circulation.first_available_copy(session, book_id, member_id=member_id)
        elif copy_code is not None:
            copy_id = (await circulation.find_copy_by_code(session, copy_code)).copy_ref.id
        else:
            raise ValueError("a borrow needs a book id or a copy code")
        checked = await circulation.check_borrow(
            session,
            copy_id=copy_id,
            member_id=member_id,
            due_date=due_date,
            loan_period_days=loan_period_days,
        )
    except ValidationFailedError as exc:
        code, message = _plain(exc)
        raise ValidationFailedError(message, code=code) from exc

    book, copy, member = checked.book, checked.copy, checked.member
    return await _store(
        session,
        user=user,
        conversation_id=conversation_id,
        action="borrow",
        params={
            "copy_id": str(copy.id),
            "member_id": str(member.id),
            "due_date": checked.due_at.date().isoformat(),
        },
        summary=_summary(
            BookRef(id=book.id, title=book.title, author=book.author),
            CopyRef(id=copy.id, code=copy.code),
            MemberRef(id=member.id, full_name=member.full_name),
            due_at=checked.due_at,
        ),
    )


async def prepare_return(
    session: AsyncSession,
    *,
    user: User,
    conversation_id: uuid.UUID | None,
    copy_code: str,
) -> ProposalOut:
    """Finds the active loan of the copy and stores its return as a pending proposal.
    copy_not_on_loan when the copy is not borrowed.
    """
    _require_staff(user)
    lookup = await circulation.find_copy_by_code(session, copy_code)
    loan = lookup.active_loan
    if loan is None:
        raise ConflictError(f"Copy {lookup.copy_ref.code} is not on loan.", code="copy_not_on_loan")
    return await _store(
        session,
        user=user,
        conversation_id=conversation_id,
        action="return",
        params={"loan_id": str(loan.id)},
        summary=_summary(
            loan.book,
            loan.copy_ref,
            loan.member,
            due_at=loan.due_at,
            borrowed_at=loan.borrowed_at,
            is_overdue=loan.is_overdue,
        ),
    )


def _require_staff(user: User) -> None:
    # The staff face is the only one with these tools; this keeps the rule next to the write.
    if not user.is_staff:
        raise ForbiddenError("Only staff can borrow and return copies.")


def _summary(
    book: BookRef,
    copy: CopyRef,
    member: MemberRef,
    *,
    due_at: datetime,
    borrowed_at: datetime | None = None,
    is_overdue: bool = False,
) -> dict[str, Any]:
    """What the card shows, as it was when the proposal was prepared."""
    return {
        "book": book.model_dump(mode="json"),
        "copy": copy.model_dump(mode="json"),
        "member": member.model_dump(mode="json"),
        "due_at": due_at.isoformat(),
        "borrowed_at": borrowed_at.isoformat() if borrowed_at is not None else None,
        "is_overdue": is_overdue,
    }


async def _store(
    session: AsyncSession,
    *,
    user: User,
    conversation_id: uuid.UUID | None,
    action: ProposalAction,
    params: dict[str, Any],
    summary: dict[str, Any],
) -> ProposalOut:
    # The end of a proposal is when it was resolved, or when it expired if nobody resolved it.
    ended = func.coalesce(CopilotProposal.resolved_at, CopilotProposal.expires_at)
    await session.execute(
        delete(CopilotProposal)
        .where(CopilotProposal.user_id == user.id, ended < func.now() - PROPOSAL_KEPT)
        .execution_options(synchronize_session=False)
    )
    proposal = CopilotProposal(
        user_id=user.id,
        conversation_id=conversation_id,
        action=action,
        params=params,
        summary=summary,
        status="pending",
        expires_at=func.now() + PROPOSAL_LIFETIME,
    )
    session.add(proposal)
    await session.commit()
    return await get(session, proposal.id, user_id=user.id)


# Reading


def _lapsed() -> ColumnElement[bool]:
    """True once the proposal's time is up, by the database clock."""
    return CopilotProposal.expires_at <= func.now()


async def _find(
    session: AsyncSession, proposal_id: uuid.UUID, *, user_id: uuid.UUID, lock: bool = False
) -> tuple[CopilotProposal, bool]:
    """The user's proposal and whether its time is up. Another user's is not found, like a
    missing one. With lock, the row stays locked until the transaction ends.
    """
    statement = (
        select(CopilotProposal, _lapsed())
        .where(CopilotProposal.id == proposal_id, CopilotProposal.user_id == user_id)
        .execution_options(populate_existing=True)
    )
    if lock:
        statement = statement.with_for_update(of=CopilotProposal)
    found = (await session.execute(statement)).one_or_none()
    if found is None:
        raise NotFoundError("Proposal not found.")
    proposal, lapsed = found._tuple()
    return proposal, lapsed


def _status(proposal: CopilotProposal, lapsed: bool) -> str:
    return "expired" if proposal.status == "pending" and lapsed else proposal.status


async def get(
    session: AsyncSession,
    proposal_id: uuid.UUID,
    *,
    user_id: uuid.UUID,
    max_renewals: int = DEFAULT_MAX_RENEWALS,
) -> ProposalOut:
    """max_renewals decides whether the proposal's loan, once made, can be renewed."""
    proposal, lapsed = await _find(session, proposal_id, user_id=user_id)
    result = proposal.result or {}
    loan_id = result.get("loan_id")
    loan = (
        await circulation.get_loan(session, uuid.UUID(loan_id), max_renewals=max_renewals)
        if loan_id
        else None
    )
    return ProposalOut.model_validate(
        {
            **proposal.summary,
            "id": proposal.id,
            "action": proposal.action,
            "status": _status(proposal, lapsed),
            "created_at": proposal.created_at,
            "expires_at": proposal.expires_at,
            "resolved_at": proposal.resolved_at,
            "loan": loan,
            "error": result.get("error"),
        }
    )


# Confirming and cancelling


async def confirm(
    session: AsyncSession,
    proposal_id: uuid.UUID,
    *,
    user: User,
    loan_period_days: int,
    hold_pickup_days: int = DEFAULT_HOLD_PICKUP_DAYS,
    max_renewals: int = DEFAULT_MAX_RENEWALS,
) -> ProposalOut:
    """Makes the proposed change as the user, via the Copilot, and returns the proposal with
    its loan. proposal_resolved when it is no longer pending, proposal_expired past its expiry.
    A refused change marks the proposal failed and raises the service's conflict, or
    proposal_failed with the service's message. The change settles the book's holds as the
    web app's own borrow and return do, with hold_pickup_days for a copy set aside.
    """
    # A rollback expires every loaded object, so the user's id is read before anything runs.
    user_id = user.id
    proposal, lapsed = await _find(session, proposal_id, user_id=user_id, lock=True)
    await _ensure_pending(session, proposal, lapsed)

    proposal.status = "confirmed"
    proposal.resolved_at = func.now()
    await _tell_conversation(session, proposal, _confirmed_note(proposal))
    try:
        # The service commits, and with it the status change and the note.
        loan = await _make_change(
            session,
            proposal,
            user=user,
            loan_period_days=loan_period_days,
            hold_pickup_days=hold_pickup_days,
            max_renewals=max_renewals,
        )
    except AppError as exc:
        await session.rollback()
        raise await _fail(session, proposal_id, user_id=user_id, error=exc) from exc

    # The service makes the loan's id, so it is stored with a second commit.
    proposal.result = {"loan_id": str(loan.id)}
    await session.commit()
    return await get(session, proposal_id, user_id=user_id, max_renewals=max_renewals)


async def cancel(session: AsyncSession, proposal_id: uuid.UUID, *, user: User) -> None:
    """proposal_resolved when it is no longer pending, proposal_expired past its expiry."""
    proposal, lapsed = await _find(session, proposal_id, user_id=user.id, lock=True)
    await _ensure_pending(session, proposal, lapsed)
    proposal.status = "cancelled"
    proposal.resolved_at = func.now()
    await _tell_conversation(
        session,
        proposal,
        f"Cancelled: nothing changed. The staff member cancelled {_describe(proposal)}.",
    )
    await session.commit()


async def _ensure_pending(session: AsyncSession, proposal: CopilotProposal, lapsed: bool) -> None:
    """Refuses a proposal that can no longer be confirmed or cancelled. A pending one past its
    expiry is marked expired first.
    """
    if proposal.status == "pending" and lapsed:
        proposal.status = "expired"
        proposal.resolved_at = func.now()
        await _tell_conversation(
            session,
            proposal,
            f"Expired: nothing changed. The staff member did not confirm {_describe(proposal)} "
            "in time.",
        )
        await session.commit()
    if proposal.status == "expired":
        raise ConflictError(
            "This proposal has expired. Ask the assistant to prepare it again.",
            code="proposal_expired",
        )
    if proposal.status != "pending":
        raise ConflictError(
            f"This proposal was already {proposal.status}.", code="proposal_resolved"
        )


async def _make_change(
    session: AsyncSession,
    proposal: CopilotProposal,
    *,
    user: User,
    loan_period_days: int,
    hold_pickup_days: int,
    max_renewals: int,
) -> LoanOut:
    params = proposal.params
    if proposal.action == "borrow":
        return await circulation.borrow(
            session,
            copy_id=uuid.UUID(params["copy_id"]),
            member_id=uuid.UUID(params["member_id"]),
            due_date=date.fromisoformat(params["due_date"]),
            loan_period_days=loan_period_days,
            hold_pickup_days=hold_pickup_days,
            max_renewals=max_renewals,
            via="copilot",
            actor=user,
        )
    return await circulation.return_loan(
        session,
        uuid.UUID(params["loan_id"]),
        hold_pickup_days=hold_pickup_days,
        max_renewals=max_renewals,
        via="copilot",
        actor=user,
    )


async def _fail(
    session: AsyncSession, proposal_id: uuid.UUID, *, user_id: uuid.UUID, error: AppError
) -> AppError:
    """Marks the proposal failed with the error the confirm answers with, and returns that
    error. The proposal is read again under a lock, because the rollback released it.
    """
    code, message = _plain(error)
    answer = error if code in PASSED_THROUGH else ConflictError(message, code="proposal_failed")
    proposal, _ = await _find(session, proposal_id, user_id=user_id, lock=True)
    if proposal.status == "pending":
        proposal.status = "failed"
        proposal.resolved_at = func.now()
        proposal.result = {"error": {"code": answer.code, "message": answer.message}}
        await _tell_conversation(
            session,
            proposal,
            f"Failed: nothing changed. The staff member confirmed {_describe(proposal)}, but it "
            f"was refused: {answer.message}",
        )
        await session.commit()
    return answer


def _plain(error: AppError) -> tuple[str, str]:
    """The error's code and message, with a refused field named by its own rule and sentence
    (due_date_not_in_future, "Choose a due date after today.") rather than the general
    validation_failed.
    """
    errors = error.details.get("errors")
    if isinstance(error, ValidationFailedError) and errors:
        return str(errors[0]["type"]), str(errors[0]["message"])
    return error.code, error.message


# Conversation notes


def _describe(proposal: CopilotProposal) -> str:
    summary = proposal.summary
    title, code = summary["book"]["title"], summary["copy"]["code"]
    member = summary["member"]["full_name"]
    if proposal.action == "borrow":
        return f"the borrow of {title} (copy {code}) for {member}"
    return f"the return of {title} (copy {code}) from {member}"


def _confirmed_note(proposal: CopilotProposal) -> str:
    summary = proposal.summary
    title, code = summary["book"]["title"], summary["copy"]["code"]
    member = summary["member"]["full_name"]
    if proposal.action == "borrow":
        due = activity.format_day(datetime.fromisoformat(summary["due_at"]).date())
        return f"Confirmed: {title} (copy {code}) was lent to {member}, due {due}."
    return f"Confirmed: {title} (copy {code}) was returned from {member}."


async def _tell_conversation(session: AsyncSession, proposal: CopilotProposal, note: str) -> None:
    """Adds the note to the proposal's conversation, while it exists, as an assistant message.
    The caller commits.
    """
    if proposal.conversation_id is not None:
        await conversations.add(
            session, proposal.conversation_id, [{"role": "assistant", "content": note}]
        )
