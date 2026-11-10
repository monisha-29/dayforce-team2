"""Exception endpoints for queue listing, detail retrieval, proposals, and escalations."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models.employee import EmployeeModel
from app.models.exception import ExceptionModel
from app.models.proposal import ProposalModel
from app.models.punch import PunchModel
from app.models.schedule import ScheduleModel
from app.rules.detectors.cross_day import split_duplicate_punches
from app.schemas import (
    AttendanceException,
    AuditEvent,
    ContextShift,
    DecisionResponse,
    Employee,
    EscalateRequest,
    ExceptionDetail,
    Proposal,
    PunchRecord,
    ScheduleWindow,
    Timecard,
    ValidatorResult,
)
from app.services.audit_service import (
    get_audit_events_for_exception,
    to_audit_event_schema,
)
from app.services.decision_service import escalate_exception_workflow
from app.services.proposal_service import generate_proposal_for_exception
from app.services.timecard import shift_context, shift_window

router = APIRouter(prefix="/exceptions", tags=["Exceptions"])

# Human-readable display mappings expected by Person 1's UI
TYPE_DISPLAY_MAP: dict[str, str] = {
    "missed_punch": "Missing Punch",
    "missing_punch": "Missing Punch",
    "overtime": "Overtime Risk",
    "schedule_conflict": "Schedule Conflict",
    "meal_break": "Meal Break Violation",
    "duplicate_punch": "Duplicate Punch",
    "rest_period": "Rest Period Violation",
    "consecutive_days": "Consecutive Days",
}

STATUS_DISPLAY_MAP: dict[str, str] = {
    "pending_review": "Pending Review",
    "ai_processing": "AI Processing",
    "awaiting_approval": "Awaiting Approval",
    "approved": "Approved",
    "rejected": "Rejected",
    "escalated": "Escalated",
    "open": "Pending Review",
}

SEVERITY_DISPLAY_MAP: dict[str, str] = {
    "low": "Low",
    "medium": "Medium",
    "high": "High",
    "critical": "Critical",
}


def format_type(val: str) -> str:
    """Format exception type to user-facing string or retain display title."""
    return TYPE_DISPLAY_MAP.get(val.strip().lower(), val)


def format_status(val: str) -> str:
    """Format status to user-facing display string."""
    return STATUS_DISPLAY_MAP.get(val.strip().lower(), val.title())


def format_severity(val: str) -> str:
    """Format severity to user-facing display string."""
    return SEVERITY_DISPLAY_MAP.get(val.strip().lower(), val.title())


def parse_timecard(data: Any) -> Timecard:
    """Safely extract Timecard schema from JSON storage (supports snake_case and camelCase)."""
    if isinstance(data, dict):
        check_in = data.get("check_in") or data.get("checkIn")
        check_out = data.get("check_out") or data.get("checkOut")
        meal_start = data.get("meal_start") or data.get("mealStart")
        meal_end = data.get("meal_end") or data.get("mealEnd")
        total_hours = data.get("total_hours") if "total_hours" in data else data.get("totalHours")
        return Timecard(
            check_in=str(check_in) if check_in is not None else None,
            check_out=str(check_out) if check_out is not None else None,
            meal_start=str(meal_start) if meal_start is not None else None,
            meal_end=str(meal_end) if meal_end is not None else None,
            total_hours=float(total_hours) if total_hours is not None else None,
        )
    return Timecard()


def to_proposal_schema(p_model: ProposalModel) -> Proposal:
    """Transform a ProposalModel into the Proposal response schema."""
    validator_results: list[ValidatorResult] = []
    for v in p_model.validators or []:
        if isinstance(v, dict):
            validator_results.append(
                ValidatorResult(
                    name=str(v.get("name", "")),
                    passed=bool(v.get("passed", False)),
                    reason=v.get("reason"),
                )
            )

    gen_at = (
        p_model.generated_at.isoformat()
        if hasattr(p_model.generated_at, "isoformat")
        else str(p_model.generated_at)
    )

    return Proposal(
        id=p_model.id,
        exception_id=p_model.exception_id,
        proposed=parse_timecard(p_model.proposed_timecard),
        changed_fields=p_model.changed_fields or [],
        detected_issue=p_model.detected_issue,
        reason=p_model.reason,
        policy_title=p_model.policy_title,
        policy_clause_id=p_model.policy_clause_id,
        policy_excerpt=p_model.policy_excerpt,
        recommendation=p_model.recommendation,
        confidence=p_model.confidence,
        missing_information=p_model.missing_information or [],
        validators=validator_results,
        blocked=p_model.blocked,
        generated_at=gen_at,
    )


def to_attendance_exception_schema(exc: ExceptionModel) -> AttendanceException:
    """Transform an ExceptionModel into the AttendanceException response schema."""
    emp = exc.employee
    employee_schema = (
        Employee(
            id=emp.id,
            name=emp.name,
            department=emp.department,
            shift=emp.shift,
            shift_start=emp.shift_start,
            shift_end=emp.shift_end,
        )
        if emp
        else Employee(
            id=exc.employee_id,
            name="Unknown",
            department="Unknown",
            shift="Unknown",
            shift_start="00:00",
            shift_end="00:00",
        )
    )

    det_at = (
        exc.detected_at.isoformat()
        if hasattr(exc.detected_at, "isoformat")
        else str(exc.detected_at)
    )

    return AttendanceException(
        id=exc.id,
        employee=employee_schema,
        type=format_type(exc.type),
        date=exc.date,
        severity=format_severity(exc.severity),
        status=format_status(exc.status),
        original=parse_timecard(exc.original_attendance),
        proposal_id=exc.proposal_id,
        detected_at=det_at,
    )


def to_exception_detail_schema(exc: ExceptionModel) -> ExceptionDetail:
    """Transform an ExceptionModel into the full ExceptionDetail response schema."""
    base = to_attendance_exception_schema(exc)
    proposal_schema: Proposal | None = None
    if exc.active_proposal is not None:
        proposal_schema = to_proposal_schema(exc.active_proposal)

    return ExceptionDetail(
        id=base.id,
        employee=base.employee,
        type=base.type,
        date=base.date,
        severity=base.severity,
        status=base.status,
        original=base.original,
        proposal_id=base.proposal_id,
        detected_at=base.detected_at,
        proposal=proposal_schema,
    )


def build_filter_candidates(val: str, mapping: dict[str, str]) -> list[str]:
    """Generate search candidates matching both snake_case and UI display values."""
    clean = val.strip().lower()
    candidates: set[str] = {val.strip(), clean, clean.replace(" ", "_")}
    for code, title in mapping.items():
        if clean in (code.lower(), title.lower(), code.replace("_", " ").lower()):
            candidates.add(code)
            candidates.add(title)
    return list(candidates)


@router.get(
    "",
    response_model=list[AttendanceException],
    summary="List Attendance Exceptions",
    description="Retrieve a list of attendance exceptions with optional filtering by search term, type, status, and severity.",
)
def list_exceptions(
    db: Annotated[Session, Depends(get_db)],
    search: Annotated[
        str | None,
        Query(description="Search employee name, employee ID, or exception ID"),
    ] = None,
    type: Annotated[str | None, Query(description="Filter by exception type")] = None,
    status_filter: Annotated[
        str | None,
        Query(alias="status", description="Filter by review status"),
    ] = None,
    severity: Annotated[str | None, Query(description="Filter by severity level")] = None,
) -> list[AttendanceException]:
    """Return all attendance exceptions matching the query filters."""
    query = (
        db.query(ExceptionModel)
        .outerjoin(EmployeeModel, ExceptionModel.employee_id == EmployeeModel.id)
        .options(
            joinedload(ExceptionModel.employee),
            joinedload(ExceptionModel.active_proposal),
        )
    )

    # Filter: search by employee name, employee ID, or exception ID
    if search and search.strip():
        term = f"%{search.strip()}%"
        query = query.filter(
            or_(
                ExceptionModel.id.ilike(term),
                EmployeeModel.id.ilike(term),
                EmployeeModel.name.ilike(term),
            )
        )

    # Filter: exception type
    if type and type.strip().lower() != "all":
        type_candidates = build_filter_candidates(type, TYPE_DISPLAY_MAP)
        query = query.filter(ExceptionModel.type.in_(type_candidates))

    # Filter: status
    if status_filter and status_filter.strip().lower() != "all":
        status_candidates = build_filter_candidates(status_filter, STATUS_DISPLAY_MAP)
        query = query.filter(ExceptionModel.status.in_(status_candidates))

    # Filter: severity
    if severity and severity.strip().lower() != "all":
        severity_candidates = build_filter_candidates(severity, SEVERITY_DISPLAY_MAP)
        query = query.filter(ExceptionModel.severity.in_(severity_candidates))

    # Order by date descending, then creation timestamp descending
    query = query.order_by(ExceptionModel.date.desc(), ExceptionModel.detected_at.desc())

    records = query.all()
    return [to_attendance_exception_schema(r) for r in records]


def load_shift_evidence(
    db: Session, exc: ExceptionModel
) -> tuple[list[PunchRecord], ScheduleWindow | None]:
    """The raw punches of the exception's shift (duplicates included) and its schedule."""
    rows = db.query(PunchModel).filter(PunchModel.employee_id == exc.employee_id).all()
    window = shift_window(rows, exc.date)
    _, duplicates = split_duplicate_punches(window)
    duplicate_ids = {d.id for d, _ in duplicates}
    punches = [
        PunchRecord(
            id=p.id,
            type=str(p.punch_type),
            date=p.timestamp.strftime("%Y-%m-%d"),
            time=p.timestamp.strftime("%H:%M"),
            source=p.source,
            notes=p.notes,
            is_duplicate=p.id in duplicate_ids,
        )
        for p in window
    ]
    sched = (
        db.query(ScheduleModel)
        .filter(ScheduleModel.employee_id == exc.employee_id, ScheduleModel.date == exc.date)
        .first()
    )
    window_schema = (
        ScheduleWindow(
            start=sched.start_time.strftime("%H:%M"), end=sched.end_time.strftime("%H:%M")
        )
        if sched
        else None
    )
    return punches, window_schema


@router.get(
    "/{id}",
    response_model=ExceptionDetail,
    summary="Get Exception Detail",
    description="Retrieve full details for an attendance exception, including employee data, original timecard, and active AI proposal.",
)
def get_exception(
    id: str,
    db: Annotated[Session, Depends(get_db)],
) -> ExceptionDetail:
    """Return single exception by ID."""
    exc = (
        db.query(ExceptionModel)
        .options(
            joinedload(ExceptionModel.employee),
            joinedload(ExceptionModel.active_proposal),
        )
        .filter(ExceptionModel.id == id)
        .first()
    )

    if exc is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Exception '{id}' not found.",
        )

    detail = to_exception_detail_schema(exc)
    detail.detected_issue = exc.description
    detail.punches, detail.schedule = load_shift_evidence(db, exc)
    rows = db.query(PunchModel).filter(PunchModel.employee_id == exc.employee_id).all()
    shifts, summary = shift_context(rows, exc.type, exc.date)
    detail.context_shifts = [ContextShift(**s) for s in shifts]
    detail.context_summary = summary
    return detail


@router.post(
    "/{id}/proposal",
    response_model=Proposal,
    summary="Generate Proposal",
    description="Trigger proposal generation (with policy retrieval, validation, retry, and fallback) for an exception.",
)
def generate_proposal(
    id: str,
    db: Annotated[Session, Depends(get_db)],
) -> Proposal:
    """Generate or regenerate a proposal for the specified exception."""
    try:
        prop_model = generate_proposal_for_exception(session=db, exception_id=id)
        return to_proposal_schema(prop_model)
    except ValueError as val_err:
        err_msg = str(val_err)
        if "not found" in err_msg.lower():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=err_msg,
            ) from val_err
        if "already" in err_msg.lower():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=err_msg,
            ) from val_err
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=err_msg,
        ) from val_err


@router.post(
    "/{id}/escalate",
    response_model=DecisionResponse,
    summary="Escalate Exception",
    description="Escalate an unresolved or contentious exception directly to HR operations/manager.",
)
def escalate_exception(
    id: str,
    request: EscalateRequest,
    db: Annotated[Session, Depends(get_db)],
) -> DecisionResponse:
    """Escalate exception to manager."""
    return escalate_exception_workflow(
        session=db,
        exception_id=id,
        note=request.note,
    )


@router.get(
    "/{id}/audit",
    response_model=list[AuditEvent],
    summary="Get Exception Audit Trail",
    description="Retrieve the chronological, append-only audit trail for a specific exception.",
)
def get_exception_audit(
    id: str,
    db: Annotated[Session, Depends(get_db)],
) -> list[AuditEvent]:
    """Return audit events for an exception."""
    events = get_audit_events_for_exception(session=db, exception_id=id)
    return [to_audit_event_schema(e) for e in events]
