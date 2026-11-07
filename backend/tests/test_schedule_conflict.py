"""Tests for ScheduleConflictDetector."""

from datetime import datetime

import pytest

from app.rules.detectors.schedule_conflict import (
    ScheduleConflictConfig,
    ScheduleConflictDetector,
)
from app.rules.models.exception import (
    ExceptionType,
    Punch,
    PunchType,
    Schedule,
)


@pytest.fixture
def detector() -> ScheduleConflictDetector:
    return ScheduleConflictDetector(
        ScheduleConflictConfig(late_grace_period_minutes=5, early_exit_grace_period_minutes=5)
    )


def test_punctual_shift_no_conflict(detector: ScheduleConflictDetector) -> None:
    """Clocking in at 09:03 with 5-minute grace period produces no tardy exception."""
    sched = Schedule(
        employee_id="E1",
        date="2026-11-07",
        start_time=datetime(2026, 11, 7, 9, 0),
        end_time=datetime(2026, 11, 7, 17, 0),
    )
    punches = [
        Punch(employee_id="E1", timestamp=datetime(2026, 11, 7, 9, 3), punch_type=PunchType.IN),
        Punch(employee_id="E1", timestamp=datetime(2026, 11, 7, 17, 0), punch_type=PunchType.OUT),
    ]
    excs = detector.detect("E1", "2026-11-07", punches, sched)
    assert len(excs) == 0


def test_late_clock_in_detected(detector: ScheduleConflictDetector) -> None:
    """Clocking in at 09:12 (12 minutes late, beyond 5 min grace) triggers tardiness exception."""
    sched = Schedule(
        employee_id="E1",
        date="2026-11-07",
        start_time=datetime(2026, 11, 7, 9, 0),
        end_time=datetime(2026, 11, 7, 17, 0),
    )
    punches = [
        Punch(employee_id="E1", timestamp=datetime(2026, 11, 7, 9, 12), punch_type=PunchType.IN),
        Punch(employee_id="E1", timestamp=datetime(2026, 11, 7, 17, 0), punch_type=PunchType.OUT),
    ]
    excs = detector.detect("E1", "2026-11-07", punches, sched)
    assert len(excs) == 1
    e = excs[0]
    assert e.exception_type == ExceptionType.SCHEDULE_CONFLICT
    assert e.policy_reference == "SCHED-01"
    assert "Late clock-in" in e.description
    assert "12 minutes after scheduled start" in e.description


def test_early_clock_out_detected(detector: ScheduleConflictDetector) -> None:
    """Leaving at 16:30 for a 17:00 shift triggers early departure exception."""
    sched = Schedule(
        employee_id="E1",
        date="2026-11-07",
        start_time=datetime(2026, 11, 7, 9, 0),
        end_time=datetime(2026, 11, 7, 17, 0),
    )
    punches = [
        Punch(employee_id="E1", timestamp=datetime(2026, 11, 7, 9, 0), punch_type=PunchType.IN),
        Punch(employee_id="E1", timestamp=datetime(2026, 11, 7, 16, 30), punch_type=PunchType.OUT),
    ]
    excs = detector.detect("E1", "2026-11-07", punches, sched)
    assert len(excs) == 1
    e = excs[0]
    assert e.exception_type == ExceptionType.SCHEDULE_CONFLICT
    assert e.policy_reference == "SCHED-01"
    assert "Early clock-out" in e.description
    assert "30 minutes before scheduled end" in e.description


def test_unscheduled_shift_detected(detector: ScheduleConflictDetector) -> None:
    """Working without a schedule triggers unscheduled shift conflict."""
    punches = [
        Punch(employee_id="E1", timestamp=datetime(2026, 11, 7, 9, 0), punch_type=PunchType.IN),
        Punch(employee_id="E1", timestamp=datetime(2026, 11, 7, 17, 0), punch_type=PunchType.OUT),
    ]
    excs = detector.detect("E1", "2026-11-07", punches, schedule=None)
    assert len(excs) == 1
    assert excs[0].policy_reference == "SCHED-02"
    assert "Unscheduled shift" in excs[0].description


def test_overlapping_schedules(detector: ScheduleConflictDetector) -> None:
    """Two overlapping schedules for the same employee triggers conflict."""
    sched1 = Schedule(
        id="S1",
        employee_id="E1",
        date="2026-11-07",
        start_time=datetime(2026, 11, 7, 8, 0),
        end_time=datetime(2026, 11, 7, 14, 0),
    )
    sched2 = Schedule(
        id="S2",
        employee_id="E1",
        date="2026-11-07",
        start_time=datetime(2026, 11, 7, 12, 0),
        end_time=datetime(2026, 11, 7, 18, 0),
    )
    excs = detector.detect_overlapping_schedules("E1", [sched1, sched2])
    assert len(excs) == 1
    assert excs[0].exception_type == ExceptionType.SCHEDULE_CONFLICT
    assert excs[0].policy_reference == "SCHED-02"
    assert "Overlapping schedules" in excs[0].description
