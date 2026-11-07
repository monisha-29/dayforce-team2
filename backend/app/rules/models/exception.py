"""Data models for timecard exceptions, punches, and schedules."""

from datetime import date, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class PunchType(str, Enum):
    """Supported punch types."""

    IN = "IN"
    OUT = "OUT"
    BREAK_START = "BREAK_START"
    BREAK_END = "BREAK_END"


class ExceptionType(str, Enum):
    """The four core exception types required by project specifications."""

    MISSED_PUNCH = "missed_punch"
    OVERTIME = "overtime"
    SCHEDULE_CONFLICT = "schedule_conflict"
    MEAL_BREAK = "meal_break"


class Severity(str, Enum):
    """Exception severity levels."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Punch(BaseModel):
    """An individual punch recorded in the system."""

    id: str | None = None
    employee_id: str
    timestamp: datetime
    punch_type: PunchType
    source: str = "terminal"
    notes: str | None = None

    @field_validator("punch_type", mode="before")
    @classmethod
    def normalize_punch_type(cls, v: Any) -> PunchType:
        if isinstance(v, PunchType):
            return v
        if isinstance(v, str):
            clean = v.strip().upper()
            if clean in ("CLOCK_IN", "IN"):
                return PunchType.IN
            if clean in ("CLOCK_OUT", "OUT"):
                return PunchType.OUT
            if clean in ("BREAK_START", "MEAL_START", "MEAL_OUT"):
                return PunchType.BREAK_START
            if clean in ("BREAK_END", "MEAL_END", "MEAL_IN"):
                return PunchType.BREAK_END
            try:
                return PunchType(clean)
            except ValueError:
                pass
        raise ValueError(f"Unsupported punch_type: {v}")


class Schedule(BaseModel):
    """Assigned shift schedule for an employee."""

    id: str | None = None
    employee_id: str
    date: str  # YYYY-MM-DD
    start_time: datetime
    end_time: datetime
    department_id: str | None = None
    scheduled_break_minutes: int = 30

    @field_validator("date", mode="before")
    @classmethod
    def validate_date_str(cls, v: Any) -> str:
        if isinstance(v, date):
            return v.isoformat()
        if isinstance(v, datetime):
            return v.date().isoformat()
        if isinstance(v, str):
            # Validate YYYY-MM-DD format
            date.fromisoformat(v)
            return v
        raise ValueError(f"Invalid date: {v}")


class TimecardException(BaseModel):
    """Consistent structured exception object produced by all four detectors.

    Matches required fields:
    - Exception ID
    - Employee ID
    - Exception type
    - Date
    - Severity
    - Description
    - Original attendance information
    - Relevant rule or policy reference
    """

    exception_id: str
    employee_id: str
    exception_type: ExceptionType
    date: str  # YYYY-MM-DD
    severity: Severity = Severity.MEDIUM
    description: str
    original_attendance: dict[str, Any] = Field(default_factory=dict)
    policy_reference: str
    status: str = "open"  # open, pending_review, resolved, escalated
    created_at: datetime = Field(default_factory=datetime.utcnow)
