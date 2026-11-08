"""Proposal endpoints for submitting manager review decisions."""

from fastapi import APIRouter, HTTPException, status

from app.schemas import DecisionRequest, DecisionResponse

router = APIRouter(prefix="/proposals", tags=["Proposals"])


@router.post(
    "/{id}/decision",
    response_model=DecisionResponse,
    summary="Submit Proposal Decision",
    description="Submit manager review action (approve, edit, or reject) for a proposed timecard correction.",
)
async def submit_decision(id: str, request: DecisionRequest) -> DecisionResponse:
    """Record manager review decision and update timecard if approved."""
    # Phase 0 route definition for OpenAPI generation. Decision logic will be connected in Phase 1.
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail=f"Submitting decisions for proposal '{id}' will be available in Phase 1.",
    )
