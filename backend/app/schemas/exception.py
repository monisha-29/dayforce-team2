"""Exception schemas matching PROJECT_SPEC.md and frontend UI contracts."""

from datetime import datetime
from enum import Enum

from pydantic import Field

from .base import CamelModel
from .common import Employee, Timecard
from .proposal import Proposal


class ExceptionType(str, Enum):
    """The four core exception types from the project spec, plus three extended types."""

    MISSED_PUNCH = "missed_punch"
    OVERTIME = "overtime"
    SCHEDULE_CONFLICT = "schedule_conflict"
    MEAL_BREAK = "meal_break"
    DUPLICATE_PUNCH = "duplicate_punch"
    REST_PERIOD = "rest_period"
    CONSECUTIVE_DAYS = "consecutive_days"


class Severity(str, Enum):
    """Exception severity levels."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ExceptionStatus(str, Enum):
    """Lifecycle statuses for timecard exceptions."""

    PENDING_REVIEW = "pending_review"
    AI_PROCESSING = "ai_processing"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    ESCALATED = "escalated"


class AttendanceException(CamelModel):
    """Attendance exception representation for list and queue views."""

    id: str
    employee: Employee
    type: str
    date: str
    severity: str
    status: str
    original: Timecard
    proposal_id: str | None = None
    detected_at: str | datetime


class PunchRecord(CamelModel):
    """One recorded punch from the shift behind an exception."""

    id: str
    type: str  # IN, OUT, BREAK_START, BREAK_END
    date: str
    time: str  # HH:MM
    source: str
    notes: str | None = None
    is_duplicate: bool = False  # repeat of the previous punch of the same type within minutes


class ContextShift(CamelModel):
    """Another shift of the same employee that explains a multi-day exception."""

    date: str
    start: str  # HH:MM
    end: str | None = None
    end_date: str | None = None  # set when the shift ends on a later day


class ScheduleWindow(CamelModel):
    """Assigned shift for the day."""

    start: str  # HH:MM
    end: str


class ExceptionDetail(AttendanceException):
    """Detailed exception view including current proposal if generated."""

    detected_issue: str = ""  # the detector's own description of the problem
    proposal: Proposal | None = None
    punches: list[PunchRecord] = Field(default_factory=list)
    schedule: ScheduleWindow | None = None
    context_shifts: list[ContextShift] = Field(default_factory=list)
    context_summary: str | None = None


class ExceptionFilters(CamelModel):
    """Filter parameters for listing attendance exceptions."""

    search: str | None = None
    type: str | None = None
    status: str | None = None
    severity: str | None = None
