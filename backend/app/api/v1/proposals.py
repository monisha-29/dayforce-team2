"""Proposal endpoints for submitting manager review decisions."""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import DecisionRequest, DecisionResponse
from app.services.decision_service import record_decision

router = APIRouter(prefix="/proposals", tags=["Proposals"])


@router.post(
    "/{id}/decision",
    response_model=DecisionResponse,
    summary="Submit Proposal Decision",
    description="Submit manager review action (approve, edit, or reject) for a proposed timecard correction.",
)
def submit_decision(
    id: str,
    request: DecisionRequest,
    db: Annotated[Session, Depends(get_db)],
) -> DecisionResponse:
    """Record manager review decision and update timecard if approved."""
    return record_decision(
        session=db,
        proposal_id=id,
        request=request,
    )
