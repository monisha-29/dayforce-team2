"""Exception endpoints for queue listing, detail retrieval, proposals, and escalations."""

from fastapi import APIRouter, HTTPException, Query, status

from app.schemas import (
    AttendanceException,
    AuditEvent,
    DecisionResponse,
    EscalateRequest,
    ExceptionDetail,
    Proposal,
)

router = APIRouter(prefix="/exceptions", tags=["Exceptions"])


@router.get(
    "",
    response_model=list[AttendanceException],
    summary="List Attendance Exceptions",
    description="Retrieve a list of attendance exceptions with optional filtering by search term, type, status, and severity.",
)
async def list_exceptions(
    search: str | None = Query(
        default=None, description="Search employee name, employee ID, or exception ID"
    ),
    type: str | None = Query(default=None, description="Filter by exception type"),
    status: str | None = Query(default=None, description="Filter by review status"),
    severity: str | None = Query(default=None, description="Filter by severity level"),
) -> list[AttendanceException]:
    """Return all attendance exceptions matching the query filters."""
    # Phase 0 route definition for OpenAPI generation. Database query will be connected in Phase 1.
    return []


@router.get(
    "/{id}",
    response_model=ExceptionDetail,
    summary="Get Exception Detail",
    description="Retrieve full details for an attendance exception, including employee data, original timecard, and active AI proposal.",
)
async def get_exception(id: str) -> ExceptionDetail:
    """Return single exception by ID."""
    # Phase 0 route definition for OpenAPI generation. Database query will be connected in Phase 1.
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Exception '{id}' not found.",
    )


@router.post(
    "/{id}/proposal",
    response_model=Proposal,
    summary="Generate Proposal",
    description="Trigger AI proposal generation (with retrieval, validation, retry, and fallback) for an exception.",
)
async def generate_proposal(id: str) -> Proposal:
    """Generate or regenerate a proposal for the specified exception."""
    # Phase 0 route definition for OpenAPI generation. AI orchestration will be connected in Phase 2.
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail=f"Proposal generation for exception '{id}' will be available in Phase 2.",
    )


@router.post(
    "/{id}/escalate",
    response_model=DecisionResponse,
    summary="Escalate Exception",
    description="Escalate an unresolved or contentious exception directly to HR operations/manager.",
)
async def escalate_exception(id: str, request: EscalateRequest) -> DecisionResponse:
    """Escalate exception to manager."""
    # Phase 0 route definition for OpenAPI generation. Escalation workflow will be connected in Phase 1.
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail=f"Escalation for exception '{id}' will be available in Phase 1.",
    )


@router.get(
    "/{id}/audit",
    response_model=list[AuditEvent],
    summary="Get Exception Audit Trail",
    description="Retrieve the chronological, append-only audit trail for a specific exception.",
)
async def get_exception_audit(id: str) -> list[AuditEvent]:
    """Return audit events for an exception."""
    # Phase 0 route definition for OpenAPI generation. Audit query will be connected in Phase 1.
    return []
