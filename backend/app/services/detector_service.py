"""Detector integration service connecting database records with Person 3's rules engine.

This module forms the clean integration boundary for attendance exception detection:
- Converts SQLAlchemy PunchModel/ScheduleModel records to detector Pydantic models.
- Invokes detect_all_exceptions (or an injected detector callable).
- Converts detected exceptions to SQLAlchemy ExceptionModel instances.
- Guarantees deterministic exception IDs to prevent duplicates.
- Maps detector lifecycle status 'open' to backend status 'pending_review'.
- Commits new exceptions in a safe database transaction.
"""

import uuid
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.models.exception import ExceptionModel
from app.models.punch import PunchModel
from app.models.schedule import ScheduleModel
from app.schemas.common import Punch as SchemaPunch
from app.schemas.common import Schedule as SchemaSchedule

# Dynamic import boundary for Person 3's rules module.
# Person 3's code currently resides on branch `origin/feature/rules-validation`.
# When merged, these imports resolve directly without code changes.
try:
    from app.rules.detectors import (  # type: ignore[import-not-found]
        detect_all_exceptions as person3_detect_all_exceptions,
    )
    from app.rules.models.exception import (  # type: ignore[import-not-found]
        Punch as RulePunch,
    )
    from app.rules.models.exception import (
        Schedule as RuleSchedule,
    )
    from app.rules.models.exception import (
        TimecardException as RuleTimecardException,
    )

    RULES_MODULE_AVAILABLE = True
except ImportError:
    person3_detect_all_exceptions = None  # type: ignore[assignment]
    RulePunch = None  # type: ignore[assignment, misc]
    RuleSchedule = None  # type: ignore[assignment, misc]
    RuleTimecardException = None  # type: ignore[assignment, misc]
    RULES_MODULE_AVAILABLE = False


# Standard namespace UUID matching Person 3's BaseDetector.generate_exception_id
DETECTOR_NAMESPACE = uuid.UUID("12345678-1234-5678-1234-567812345678")

# Callable type representing Person 3's detect_all_exceptions
DetectorFunction = Callable[[Sequence[Any], Sequence[Any]], Sequence[Any]]


class RulesModuleNotAvailableError(RuntimeError):
    """Raised when detection is requested but Person 3's rules module is not available on this branch."""


class DetectionSummary(BaseModel):
    """Structured report returned by the detection pipeline."""

    detected_count: int = Field(..., description="Total exceptions returned by the detector engine")
    newly_saved_count: int = Field(
        ..., description="Number of new exceptions written to the database"
    )
    duplicate_skipped_count: int = Field(
        ..., description="Number of duplicate exceptions already present in the database"
    )


def generate_deterministic_exception_id(
    employee_id: str,
    date_str: str,
    exception_type: str,
    sub_type: str = "",
) -> str:
    """Generate a reproducible, deterministic exception ID.

    Matches Person 3's UUIDv5 naming scheme to ensure identical IDs for identical violations.
    """
    clean_type = exception_type.strip().lower()
    suffix = f"_{sub_type}" if sub_type else ""
    name = f"{employee_id}_{date_str}_{clean_type}{suffix}"
    return f"EXC-{uuid.uuid5(DETECTOR_NAMESPACE, name).hex[:12].upper()}"


def to_detector_punch(punch: Any) -> Any:
    """Convert an SQLAlchemy PunchModel or Punch object to the detector Punch Pydantic model.

    Uses Person 3's RulePunch when available, otherwise uses the compatible SchemaPunch.
    """
    target_cls = RulePunch if RULES_MODULE_AVAILABLE and RulePunch is not None else SchemaPunch
    if isinstance(punch, target_cls):
        return punch
    return target_cls(
        id=getattr(punch, "id", None),
        employee_id=str(punch.employee_id),
        timestamp=punch.timestamp,
        punch_type=str(getattr(punch.punch_type, "value", punch.punch_type)),
        source=str(getattr(punch, "source", "terminal")),
        notes=getattr(punch, "notes", None),
    )


def to_detector_schedule(schedule: Any) -> Any:
    """Convert an SQLAlchemy ScheduleModel or Schedule object to the detector Schedule Pydantic model.

    Uses Person 3's RuleSchedule when available, otherwise uses the compatible SchemaSchedule.
    """
    target_cls = (
        RuleSchedule if RULES_MODULE_AVAILABLE and RuleSchedule is not None else SchemaSchedule
    )
    if isinstance(schedule, target_cls):
        return schedule
    return target_cls(
        id=getattr(schedule, "id", None),
        employee_id=str(schedule.employee_id),
        date=str(schedule.date),
        start_time=schedule.start_time,
        end_time=schedule.end_time,
        department_id=getattr(schedule, "department_id", None),
        scheduled_break_minutes=int(getattr(schedule, "scheduled_break_minutes", 30)),
    )


def convert_detector_exception_to_model(detector_exc: Any) -> ExceptionModel:
    """Convert a detector TimecardException instance into an unattached SQLAlchemy ExceptionModel.

    Handles enum unwrapping, status mapping (open -> pending_review), and JSON extraction.
    """
    # 1. Extract identifier or generate deterministically
    raw_id = getattr(detector_exc, "exception_id", None) or getattr(detector_exc, "id", None)
    employee_id = str(getattr(detector_exc, "employee_id", ""))
    date_str = str(getattr(detector_exc, "date", ""))

    raw_type = getattr(detector_exc, "exception_type", None) or getattr(detector_exc, "type", "")
    type_str = str(getattr(raw_type, "value", raw_type))

    exc_id = (
        str(raw_id)
        if raw_id
        else generate_deterministic_exception_id(employee_id, date_str, type_str)
    )

    # 2. Extract and normalize severity
    raw_sev = getattr(detector_exc, "severity", "medium")
    severity_str = str(getattr(raw_sev, "value", raw_sev))
    severity_clean = severity_str.strip().lower()

    # 3. Map status: Person 3's detector outputs 'open', which maps to backend 'pending_review'
    raw_status = getattr(detector_exc, "status", "pending_review")
    status_str = str(getattr(raw_status, "value", raw_status))
    status_clean = status_str.strip().lower()
    if status_clean in ("open", "detected", "new"):
        status_clean = "pending_review"

    # 4. Extract description and policy reference
    description = str(getattr(detector_exc, "description", ""))
    policy_reference = str(getattr(detector_exc, "policy_reference", ""))

    # 5. Extract original attendance payload
    original_att = getattr(detector_exc, "original_attendance", {})
    if hasattr(original_att, "model_dump"):
        attendance_dict = original_att.model_dump(mode="json")
    elif isinstance(original_att, dict):
        attendance_dict = dict(original_att)
    else:
        attendance_dict = {}

    # 6. Extract detected timestamp
    detected_at = (
        getattr(detector_exc, "created_at", None)
        or getattr(detector_exc, "detected_at", None)
        or datetime.now(UTC)
    )

    return ExceptionModel(
        id=exc_id,
        employee_id=employee_id,
        type=type_str,
        date=date_str,
        severity=severity_clean,
        status=status_clean,
        description=description,
        original_attendance=attendance_dict,
        policy_reference=policy_reference,
        detected_at=detected_at,
        proposal_id=None,
    )


def run_detection_pipeline(
    session: Session,
    punches: Sequence[PunchModel] | None = None,
    schedules: Sequence[ScheduleModel] | None = None,
    detector_fn: DetectorFunction | None = None,
) -> DetectionSummary:
    """Execute the detection pipeline and persist newly detected exceptions.

    1. Loads punches and schedules from the database if not explicitly provided.
    2. Converts database models to detector Pydantic models.
    3. Executes the detector function (injected or from app.rules).
    4. Deduplicates against existing database records using deterministic IDs.
    5. Saves new exceptions within a single transactional commit.
    6. Returns a DetectionSummary of counts.
    """
    # 1. Resolve records from session if omitted
    input_punches = list(punches) if punches is not None else list(session.query(PunchModel).all())
    input_schedules = (
        list(schedules) if schedules is not None else list(session.query(ScheduleModel).all())
    )

    # 2. Convert to detector Pydantic models
    detector_punches = [to_detector_punch(p) for p in input_punches]
    detector_schedules = [to_detector_schedule(s) for s in input_schedules]

    # 3. Resolve detector implementation
    active_detector = detector_fn or person3_detect_all_exceptions
    if active_detector is None:
        raise RulesModuleNotAvailableError(
            "Person 3's rules engine ('app.rules.detectors') is not available on branch 'backend-development'. "
            "Pass an injected detector_fn or merge 'origin/feature/rules-validation'."
        )

    # 4. Run detection
    raw_exceptions = active_detector(detector_punches, detector_schedules)

    # 5. Deduplicate and insert new exceptions
    newly_saved_count = 0
    duplicate_skipped_count = 0
    seen_in_batch: set[str] = set()

    for item in raw_exceptions:
        model = convert_detector_exception_to_model(item)

        # Check in-batch deduplication
        if model.id in seen_in_batch:
            duplicate_skipped_count += 1
            continue
        seen_in_batch.add(model.id)

        # Check database deduplication
        existing = session.get(ExceptionModel, model.id)
        if existing is not None:
            duplicate_skipped_count += 1
            continue

        session.add(model)
        newly_saved_count += 1

    # 6. Commit transaction
    if newly_saved_count > 0:
        session.commit()

    return DetectionSummary(
        detected_count=len(raw_exceptions),
        newly_saved_count=newly_saved_count,
        duplicate_skipped_count=duplicate_skipped_count,
    )
