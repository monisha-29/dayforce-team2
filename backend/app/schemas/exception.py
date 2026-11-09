"""Exception schemas matching PROJECT_SPEC.md and frontend UI contracts."""

from datetime import datetime
from enum import Enum

from .base import CamelModel
from .common import Employee, Timecard
from .proposal import Proposal


class ExceptionType(str, Enum):
    """The four core exception types required by project specification."""

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


class ExceptionDetail(AttendanceException):
    """Detailed exception view including current proposal if generated."""

    proposal: Proposal | None = None


class ExceptionFilters(CamelModel):
    """Filter parameters for listing attendance exceptions."""

    search: str | None = None
    type: str | None = None
    status: str | None = None
    severity: str | None = None
