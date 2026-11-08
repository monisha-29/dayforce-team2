"""Tests for OvertimeDetector."""

from datetime import datetime

import pytest

from app.rules.detectors.overtime import OvertimeDetector
from app.rules.models.exception import (
    ExceptionType,
    Punch,
    PunchType,
    Severity,
)


@pytest.fixture
def detector() -> OvertimeDetector:
    return OvertimeDetector()


def test_standard_8_hours_no_overtime(detector: OvertimeDetector) -> None:
    """Exact 8.00-hour shift boundary triggers NO overtime."""
    punches = [
        Punch(employee_id="E1", timestamp=datetime(2026, 11, 7, 9, 0), punch_type=PunchType.IN),
        Punch(employee_id="E1", timestamp=datetime(2026, 11, 7, 17, 0), punch_type=PunchType.OUT),
    ]
    excs = detector.detect("E1", "2026-11-07", punches)
    assert len(excs) == 0


def test_daily_overtime_detected(detector: OvertimeDetector) -> None:
    """Shift of 9.5 hours triggers daily overtime exception (policy OT-01)."""
    punches = [
        Punch(employee_id="E1", timestamp=datetime(2026, 11, 7, 8, 0), punch_type=PunchType.IN),
        Punch(employee_id="E1", timestamp=datetime(2026, 11, 7, 17, 30), punch_type=PunchType.OUT),
    ]
    excs = detector.detect("E1", "2026-11-07", punches)
    assert len(excs) == 1
    e = excs[0]
    assert e.exception_type == ExceptionType.OVERTIME
    assert e.policy_reference == "OT-01"
    assert e.severity == Severity.MEDIUM
    assert "Daily overtime" in e.description
    assert "9.50" in e.description


def test_boundary_condition_8_01_hours(detector: OvertimeDetector) -> None:
    """8.01 hours (8 hours 1 minute) triggers overtime; 8.00 does not."""
    punches_801 = [
        Punch(employee_id="E1", timestamp=datetime(2026, 11, 7, 9, 0), punch_type=PunchType.IN),
        Punch(employee_id="E1", timestamp=datetime(2026, 11, 7, 17, 1), punch_type=PunchType.OUT),
    ]
    excs = detector.detect("E1", "2026-11-07", punches_801)
    assert len(excs) == 1
    assert excs[0].policy_reference == "OT-01"


def test_excessive_shift_hours_critical_severity(detector: OvertimeDetector) -> None:
    """16.5-hour shift triggers both daily overtime and excessive hours with CRITICAL severity."""
    punches = [
        Punch(employee_id="E1", timestamp=datetime(2026, 11, 7, 6, 0), punch_type=PunchType.IN),
        Punch(employee_id="E1", timestamp=datetime(2026, 11, 7, 22, 30), punch_type=PunchType.OUT),
    ]
    excs = detector.detect("E1", "2026-11-07", punches)
    assert len(excs) == 2
    crit_excs = [e for e in excs if e.severity == Severity.CRITICAL]
    assert len(crit_excs) == 1
    assert "Excessive working hours" in crit_excs[0].description


def test_weekly_overtime_detection(detector: OvertimeDetector) -> None:
    """6 days of 8 hours triggers weekly overtime on the 6th day."""
    daily_punches = []
    for day in range(1, 7):
        daily_punches.append(
            [
                Punch(
                    employee_id="E1",
                    timestamp=datetime(2026, 11, day, 9, 0),
                    punch_type=PunchType.IN,
                ),
                Punch(
                    employee_id="E1",
                    timestamp=datetime(2026, 11, day, 17, 0),
                    punch_type=PunchType.OUT,
                ),
            ]
        )

    excs = detector.detect_weekly_overtime("E1", "2026-W45", daily_punches)
    assert len(excs) == 1
    e = excs[0]
    assert e.exception_type == ExceptionType.OVERTIME
    assert e.policy_reference == "OT-02"
    assert "Weekly overtime" in e.description
    assert "8.00" in e.description  # 48 - 40 = 8 OT hours
