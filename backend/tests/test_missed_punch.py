"""Tests for MissedPunchDetector."""

from datetime import datetime

import pytest

from app.rules.detectors.missed_punch import MissedPunchDetector
from app.rules.models.exception import (
    ExceptionType,
    Punch,
    PunchType,
    Schedule,
    Severity,
)


@pytest.fixture
def detector() -> MissedPunchDetector:
    return MissedPunchDetector()


def test_normal_attendance_no_exceptions(detector: MissedPunchDetector) -> None:
    """Standard shift with IN and OUT produces no missed punch exceptions."""
    punches = [
        Punch(employee_id="EMP-1", timestamp=datetime(2026, 11, 7, 9, 0), punch_type=PunchType.IN),
        Punch(
            employee_id="EMP-1", timestamp=datetime(2026, 11, 7, 17, 0), punch_type=PunchType.OUT
        ),
    ]
    excs = detector.detect("EMP-1", "2026-11-07", punches)
    assert len(excs) == 0


def test_missing_clock_out(detector: MissedPunchDetector) -> None:
    """Single IN with no OUT triggers trailing missing clock-out."""
    punches = [
        Punch(employee_id="EMP-1", timestamp=datetime(2026, 11, 7, 9, 0), punch_type=PunchType.IN),
    ]
    excs = detector.detect("EMP-1", "2026-11-07", punches)
    assert len(excs) == 1
    e = excs[0]
    assert e.exception_type == ExceptionType.MISSED_PUNCH
    assert e.employee_id == "EMP-1"
    assert e.date == "2026-11-07"
    assert e.severity == Severity.HIGH
    assert e.policy_reference == "PUNCH-01"
    assert "Missing clock-out" in e.description
    assert "unclosed_punch" in e.original_attendance


def test_missing_clock_in(detector: MissedPunchDetector) -> None:
    """OUT punch without preceding IN triggers missing clock-in."""
    punches = [
        Punch(
            employee_id="EMP-1", timestamp=datetime(2026, 11, 7, 17, 0), punch_type=PunchType.OUT
        ),
    ]
    excs = detector.detect("EMP-1", "2026-11-07", punches)
    assert len(excs) == 1
    e = excs[0]
    assert e.exception_type == ExceptionType.MISSED_PUNCH
    assert e.policy_reference == "PUNCH-02"
    assert "Missing clock-in" in e.description
    assert "orphan_punch" in e.original_attendance


def test_consecutive_in_punches(detector: MissedPunchDetector) -> None:
    """Two consecutive IN punches triggers missed clock-out for first punch."""
    punches = [
        Punch(employee_id="EMP-1", timestamp=datetime(2026, 11, 7, 8, 0), punch_type=PunchType.IN),
        Punch(employee_id="EMP-1", timestamp=datetime(2026, 11, 7, 12, 0), punch_type=PunchType.IN),
        Punch(
            employee_id="EMP-1", timestamp=datetime(2026, 11, 7, 17, 0), punch_type=PunchType.OUT
        ),
    ]
    excs = detector.detect("EMP-1", "2026-11-07", punches)
    assert len(excs) == 1
    assert "Missing clock-out" in excs[0].description


def test_missing_punch_split_shift(detector: MissedPunchDetector) -> None:
    """Split shift where second shift has IN but missing OUT."""
    punches = [
        Punch(employee_id="EMP-1", timestamp=datetime(2026, 11, 7, 8, 0), punch_type=PunchType.IN),
        Punch(
            employee_id="EMP-1", timestamp=datetime(2026, 11, 7, 12, 0), punch_type=PunchType.OUT
        ),
        Punch(employee_id="EMP-1", timestamp=datetime(2026, 11, 7, 16, 0), punch_type=PunchType.IN),
    ]
    excs = detector.detect("EMP-1", "2026-11-07", punches)
    assert len(excs) == 1
    assert excs[0].policy_reference == "PUNCH-01"


def test_scheduled_shift_zero_punches(detector: MissedPunchDetector) -> None:
    """Scheduled shift with 0 punches triggers unrecorded shift exception."""
    sched = Schedule(
        employee_id="EMP-1",
        date="2026-11-07",
        start_time=datetime(2026, 11, 7, 9, 0),
        end_time=datetime(2026, 11, 7, 17, 0),
    )
    excs = detector.detect("EMP-1", "2026-11-07", punches=[], schedule=sched)
    assert len(excs) == 1
    assert excs[0].policy_reference == "PUNCH-02"
    assert "no recorded punches" in excs[0].description


def test_invalid_break_sequence(detector: MissedPunchDetector) -> None:
    """Break start without break end, or break end without break start."""
    punches = [
        Punch(employee_id="EMP-1", timestamp=datetime(2026, 11, 7, 9, 0), punch_type=PunchType.IN),
        Punch(
            employee_id="EMP-1",
            timestamp=datetime(2026, 11, 7, 12, 30),
            punch_type=PunchType.BREAK_END,
        ),  # Orphan BREAK_END
        Punch(
            employee_id="EMP-1", timestamp=datetime(2026, 11, 7, 17, 0), punch_type=PunchType.OUT
        ),
    ]
    excs = detector.detect("EMP-1", "2026-11-07", punches)
    assert any("Break end recorded" in e.description for e in excs)
