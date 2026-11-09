"""Common shared schemas: Employee, Timecard, Punch, Schedule."""

from datetime import datetime
from enum import Enum

from .base import CamelModel


class PunchType(str, Enum):
    """Supported punch types."""

    IN = "IN"
    OUT = "OUT"
    BREAK_START = "BREAK_START"
    BREAK_END = "BREAK_END"


class Employee(CamelModel):
    """Employee representation matching frontend and backend requirements."""

    id: str
    name: str
    department: str
    shift: str
    shift_start: str
    shift_end: str


class Timecard(CamelModel):
    """Timecard summary with punch times and total computed hours."""

    check_in: str | None = None
    check_out: str | None = None
    meal_start: str | None = None
    meal_end: str | None = None
    total_hours: float | None = None


class Punch(CamelModel):
    """Individual recorded punch."""

    id: str | None = None
    employee_id: str
    timestamp: datetime
    punch_type: str
    source: str = "terminal"
    notes: str | None = None


class Schedule(CamelModel):
    """Assigned employee work schedule."""

    id: str | None = None
    employee_id: str
    date: str
    start_time: datetime
    end_time: datetime
    department_id: str | None = None
    scheduled_break_minutes: int = 30
