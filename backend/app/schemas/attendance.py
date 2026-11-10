"""Attendance-record schemas: one row per employee for one day."""

from typing import Literal

from pydantic import Field

from .base import CamelModel

AttendanceStatus = Literal["Present", "Late", "Absent"]


class AttendanceRecord(CamelModel):
    """An employee's day, worked out from their punches and schedule."""

    employee_id: str
    name: str
    department: str
    shift: str
    scheduled_start: str | None = None
    scheduled_end: str | None = None
    check_in: str | None = None
    check_out: str | None = None
    status: AttendanceStatus
    exception_ids: list[str] = Field(default_factory=list)


class AttendanceDay(CamelModel):
    """All attendance records for one date, plus the dates that have data."""

    date: str
    min_date: str | None = None
    max_date: str | None = None
    records: list[AttendanceRecord]


class DayCount(CamelModel):
    """Present, late and absent employees on one date."""

    date: str
    label: str
    present: int
    late: int
    absent: int


class WeekRate(CamelModel):
    """Share of scheduled-or-working employees who worked in one week (None: no data)."""

    week: str
    start: str
    rate: float | None = None
    exceptions: int = 0


class AttendanceSummary(CamelModel):
    """Dashboard attendance numbers: one day's counts, its week, and a weekly trend."""

    date: str
    total_employees: int
    departments: int
    scheduled: int
    present: int
    late: int
    absent: int
    days: list[DayCount]
    weeks: list[WeekRate]
