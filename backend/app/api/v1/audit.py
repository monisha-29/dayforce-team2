"""Audit endpoints for global timeline access."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import AuditEvent
from app.services.audit_service import get_all_audit_events, to_audit_event_schema

router = APIRouter(prefix="/audit", tags=["Audit"])


@router.get(
    "",
    response_model=list[AuditEvent],
    summary="List All Audit Events",
    description="Retrieve the global chronological audit log across all exceptions and actions.",
)
def list_all_audits(
    db: Annotated[Session, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=500, description="Max audit entries to retrieve")] = 200,
) -> list[AuditEvent]:
    """Return all audit events."""
    events = get_all_audit_events(session=db, limit=limit)
    return [to_audit_event_schema(e) for e in events]
