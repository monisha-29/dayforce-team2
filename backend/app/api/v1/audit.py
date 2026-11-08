"""Audit endpoints for global timeline access."""

from fastapi import APIRouter

from app.schemas import AuditEvent

router = APIRouter(prefix="/audit", tags=["Audit"])


@router.get(
    "",
    response_model=list[AuditEvent],
    summary="List All Audit Events",
    description="Retrieve the global chronological audit log across all exceptions and actions.",
)
async def list_all_audits() -> list[AuditEvent]:
    """Return all audit events."""
    # Phase 0 route definition for OpenAPI generation. Audit query will be connected in Phase 1.
    return []
