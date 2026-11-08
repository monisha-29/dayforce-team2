"""Tests for MealBreakDetector."""

from datetime import datetime

import pytest

from app.rules.detectors.meal_break import MealBreakConfig, MealBreakDetector
from app.rules.models.exception import (
    ExceptionType,
    Punch,
    PunchType,
    Severity,
)


@pytest.fixture
def detector() -> MealBreakDetector:
    return MealBreakDetector(MealBreakConfig(shift_threshold_hours=5.0, min_break_minutes=30))


def test_shift_under_5_hours_no_break_needed(detector: MealBreakDetector) -> None:
    """A 4-hour shift does not require a meal break."""
    punches = [
        Punch(employee_id="E1", timestamp=datetime(2026, 11, 7, 9, 0), punch_type=PunchType.IN),
        Punch(employee_id="E1", timestamp=datetime(2026, 11, 7, 13, 0), punch_type=PunchType.OUT),
    ]
    excs = detector.detect("E1", "2026-11-07", punches)
    assert len(excs) == 0


def test_shift_over_5_hours_missing_meal_break(detector: MealBreakDetector) -> None:
    """An 8-hour shift without any meal break triggers missing meal break exception."""
    punches = [
        Punch(employee_id="E1", timestamp=datetime(2026, 11, 7, 9, 0), punch_type=PunchType.IN),
        Punch(employee_id="E1", timestamp=datetime(2026, 11, 7, 17, 0), punch_type=PunchType.OUT),
    ]
    excs = detector.detect("E1", "2026-11-07", punches)
    assert len(excs) == 1
    e = excs[0]
    assert e.exception_type == ExceptionType.MEAL_BREAK
    assert e.policy_reference == "MEAL-01"
    assert e.severity == Severity.HIGH
    assert "Missing meal break" in e.description


def test_short_meal_break(detector: MealBreakDetector) -> None:
    """A meal break of only 15 minutes triggers short meal break exception (policy MEAL-02)."""
    punches = [
        Punch(employee_id="E1", timestamp=datetime(2026, 11, 7, 9, 0), punch_type=PunchType.IN),
        Punch(
            employee_id="E1",
            timestamp=datetime(2026, 11, 7, 12, 0),
            punch_type=PunchType.BREAK_START,
        ),
        Punch(
            employee_id="E1",
            timestamp=datetime(2026, 11, 7, 12, 15),
            punch_type=PunchType.BREAK_END,
        ),  # 15 mins
        Punch(employee_id="E1", timestamp=datetime(2026, 11, 7, 17, 0), punch_type=PunchType.OUT),
    ]
    excs = detector.detect("E1", "2026-11-07", punches)
    assert len(excs) == 1
    e = excs[0]
    assert e.exception_type == ExceptionType.MEAL_BREAK
    assert e.policy_reference == "MEAL-02"
    assert "Short meal break" in e.description
    assert "15.0 minutes" in e.description


def test_compliant_meal_break(detector: MealBreakDetector) -> None:
    """An 8.5-hour shift with a 30-minute break at hour 3 produces no violations."""
    punches = [
        Punch(employee_id="E1", timestamp=datetime(2026, 11, 7, 9, 0), punch_type=PunchType.IN),
        Punch(
            employee_id="E1",
            timestamp=datetime(2026, 11, 7, 12, 0),
            punch_type=PunchType.BREAK_START,
        ),
        Punch(
            employee_id="E1",
            timestamp=datetime(2026, 11, 7, 12, 30),
            punch_type=PunchType.BREAK_END,
        ),  # 30 mins
        Punch(employee_id="E1", timestamp=datetime(2026, 11, 7, 17, 30), punch_type=PunchType.OUT),
    ]
    excs = detector.detect("E1", "2026-11-07", punches)
    assert len(excs) == 0


def test_delayed_meal_break(detector: MealBreakDetector) -> None:
    """Working 6.5 hours continuously before taking a break triggers delayed break exception."""
    punches = [
        Punch(employee_id="E1", timestamp=datetime(2026, 11, 7, 9, 0), punch_type=PunchType.IN),
        Punch(
            employee_id="E1",
            timestamp=datetime(2026, 11, 7, 15, 30),
            punch_type=PunchType.BREAK_START,
        ),  # 6.5 hours in
        Punch(
            employee_id="E1", timestamp=datetime(2026, 11, 7, 16, 0), punch_type=PunchType.BREAK_END
        ),
        Punch(employee_id="E1", timestamp=datetime(2026, 11, 7, 18, 0), punch_type=PunchType.OUT),
    ]
    excs = detector.detect("E1", "2026-11-07", punches)
    assert len(excs) == 1
    assert excs[0].policy_reference == "MEAL-02"
    assert "Delayed meal break" in excs[0].description
