"""Attendance records endpoint: who was scheduled and who actually worked on a given day."""

from datetime import date as date_type
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import AttendanceDay, AttendanceSummary
from app.services.attendance_service import attendance_for_day, attendance_summary

router = APIRouter(prefix="/attendance", tags=["Attendance"])


@router.get(
    "/summary",
    response_model=AttendanceSummary,
    summary="Attendance Summary For The Dashboard",
    description=(
        "Read-only. Present, late and absent counts for a day, that day's Monday-to-Sunday week, "
        "and the attendance rate for each of the last six weeks. Defaults to the busiest date."
    ),
)
def get_attendance_summary(
    db: Annotated[Session, Depends(get_db)],
    date: Annotated[
        date_type | None, Query(description="Reference day (YYYY-MM-DD); default: busiest day")
    ] = None,
) -> AttendanceSummary:
    """Return the dashboard attendance numbers."""
    return attendance_summary(db, date.isoformat() if date else None)


@router.get(
    "",
    response_model=AttendanceDay,
    summary="Attendance Records For A Day",
    description=(
        "Read-only. One row per employee scheduled or working that day, with the first clock-in, "
        "last clock-out and a status worked out from the data. Defaults to the date with the most "
        "employees."
    ),
)
def get_attendance(
    db: Annotated[Session, Depends(get_db)],
    date: Annotated[
        date_type | None, Query(description="Day to show (YYYY-MM-DD); default: busiest day")
    ] = None,
) -> AttendanceDay:
    """Return the attendance records for one day."""
    return attendance_for_day(db, date.isoformat() if date else None)
