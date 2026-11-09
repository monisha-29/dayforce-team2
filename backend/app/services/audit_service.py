"""Audit logging service for the append-only timecard exception trail.

Records every significant workflow step:
- Exception detected
- Policy retrieved
- AI proposal generated
- Validation completed
- Retry attempted
- Fallback triggered
- Escalated
- Manager approved
- Manager edited
- Manager rejected
- Timecard updated

Generates unique trace IDs, ensures credentials/secrets are never recorded,
and provides query functions for exception and global audit streams.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.models.audit_log import AuditEventModel
from app.schemas.audit import AuditEvent


def generate_trace_id() -> str:
    """Generate a lightweight trace ID matching frontend format ('tr-<hex>')."""
    return f"tr-{uuid.uuid4().hex[:6]}"


def generate_audit_id() -> str:
    """Generate a unique audit event identifier."""
    return f"AUD-{uuid.uuid4().hex[:12].upper()}"


def sanitize_audit_text(text: str | None) -> str | None:
    """Strip potential sensitive tokens or secrets before audit persistence."""
    if not text:
        return text
    # Mask common sensitive key patterns
    sensitive_markers = ("password", "api_key", "secret", "token", "bearer ")
    lower = text.lower()
    for marker in sensitive_markers:
        if marker in lower:
            return "[REDACTED SENSITIVE DATA]"
    return text


def log_audit_event(
    session: Session,
    action: str,
    user: str,
    status: str,
    trace_id: str,
    exception_id: str | None = None,
    detail: str | None = None,
    flags: list[str] | None = None,
    timestamp: datetime | None = None,
) -> AuditEventModel:
    """Append a structured audit event to the audit_log table.

    Never stores credentials, passwords, or secrets.
    """
    event_time = timestamp or datetime.now(UTC).replace(tzinfo=None)
    event = AuditEventModel(
        id=generate_audit_id(),
        exception_id=exception_id,
        timestamp=event_time,
        action=action,
        user=user,
        status=status.lower(),
        trace_id=trace_id,
        detail=sanitize_audit_text(detail),
        flags=flags or [],
    )
    session.add(event)
    return event


def get_audit_events_for_exception(
    session: Session,
    exception_id: str,
) -> list[AuditEventModel]:
    """Retrieve chronological audit trail for a specific exception."""
    return (
        session.query(AuditEventModel)
        .filter(AuditEventModel.exception_id == exception_id)
        .order_by(AuditEventModel.timestamp.asc())
        .all()
    )


def get_all_audit_events(
    session: Session,
    limit: int = 200,
) -> list[AuditEventModel]:
    """Retrieve reverse-chronological global audit stream across all exceptions."""
    return (
        session.query(AuditEventModel)
        .order_by(AuditEventModel.timestamp.desc())
        .limit(limit)
        .all()
    )


def to_audit_event_schema(model: AuditEventModel) -> AuditEvent:
    """Convert an AuditEventModel to the API AuditEvent schema."""
    ts_str = (
        model.timestamp.isoformat()
        if isinstance(model.timestamp, datetime)
        else str(model.timestamp)
    )
    return AuditEvent(
        id=model.id,
        exception_id=model.exception_id or "",
        timestamp=ts_str,
        action=model.action,
        user=model.user,
        status=model.status,
        trace_id=model.trace_id,
        detail=model.detail,
        flags=model.flags or [],
    )
