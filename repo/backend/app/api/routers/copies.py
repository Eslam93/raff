"""Copies found by their code, as staff type or scan it at the desk. Staff only."""

from typing import Annotated

from fastapi import APIRouter, Depends, Path

from app.api.deps import AppSettings, require_staff
from app.db.session import DbSession
from app.schemas.common import error_responses
from app.schemas.loans import CopyLookup
from app.services import circulation

router = APIRouter(prefix="/copies", tags=["copies"], dependencies=[Depends(require_staff)])


@router.get("/by-code/{code}", responses=error_responses(staff=True, not_found=True))
async def get_copy_by_code(
    session: DbSession, settings: AppSettings, code: Annotated[str, Path(max_length=40)]
) -> CopyLookup:
    """Letter case does not matter, and a number means that copy number: "12" and "cp-12" find
    CP-0012. active_loan is the loan while the copy is borrowed; held_for names the member a
    held copy is set aside for, and until when.
    """
    return await circulation.find_copy_by_code(session, code, max_renewals=settings.max_renewals)
