"""Tests for Rule-Based Fallback Engine."""

from datetime import datetime

import pytest

from app.rules.fallback import FallbackEngine
from app.rules.models.exception import (
    ExceptionType,
    Punch,
    PunchType,
    Schedule,
    TimecardException,
)


@pytest.fixture
def fallback_engine() -> FallbackEngine:
    return FallbackEngine()


def test_missed_clock_out_fallback_with_schedule(fallback_engine: FallbackEngine) -> None:
    """Fallback generates compliant clock-out at scheduled end with midpoint break."""
    sched = Schedule(
        employee_id="E1",
        date="2026-11-07",
        start_time=datetime(2026, 11, 7, 9, 0),
        end_time=datetime(2026, 11, 7, 17, 30),
    )
    punches = [
        Punch(employee_id="E1", timestamp=datetime(2026, 11, 7, 9, 0), punch_type=PunchType.IN),
    ]
    exc = TimecardException(
        exception_id="EXC-MP-1",
        employee_id="E1",
        exception_type=ExceptionType.MISSED_PUNCH,
        date="2026-11-07",
        description="Missing clock-out",
        policy_reference="PUNCH-01",
    )
    res = fallback_engine.generate_fallback(exc, punches, sched)
    assert res.success is True
    assert res.exception_id == "EXC-MP-1"
    assert res.proposed_correction is not None
    assert res.requires_manager_review is True
    assert res.validation_result is not None
    assert res.validation_result.valid is True


def test_missed_clock_in_fallback_with_schedule(fallback_engine: FallbackEngine) -> None:
    """Fallback generates clock-in at scheduled start time."""
    sched = Schedule(
        employee_id="E1",
        date="2026-11-07",
        start_time=datetime(2026, 11, 7, 9, 0),
        end_time=datetime(2026, 11, 7, 13, 0),
    )
    punches = [
        Punch(employee_id="E1", timestamp=datetime(2026, 11, 7, 13, 0), punch_type=PunchType.OUT),
    ]
    exc = TimecardException(
        exception_id="EXC-MP-2",
        employee_id="E1",
        exception_type=ExceptionType.MISSED_PUNCH,
        date="2026-11-07",
        description="Missing clock-in",
        policy_reference="PUNCH-02",
    )
    res = fallback_engine.generate_fallback(exc, punches, sched)
    assert res.success is True
    assert res.requires_manager_review is True
    assert res.validation_result.valid is True


def test_fallback_escalates_when_schedule_missing(fallback_engine: FallbackEngine) -> None:
    """When schedule is missing, fallback refuses to hallucinate and escalates to manager."""
    punches = [
        Punch(employee_id="E1", timestamp=datetime(2026, 11, 7, 9, 0), punch_type=PunchType.IN),
    ]
    exc = TimecardException(
        exception_id="EXC-MP-3",
        employee_id="E1",
        exception_type=ExceptionType.MISSED_PUNCH,
        date="2026-11-07",
        description="Missing clock-out without schedule",
        policy_reference="PUNCH-01",
    )
    res = fallback_engine.generate_fallback(exc, punches, schedule=None)
    assert res.success is False
    assert res.proposed_correction is None
    assert res.requires_manager_review is True
    assert "Insufficient attendance and schedule information" in res.reason


def test_meal_break_fallback_insertion(fallback_engine: FallbackEngine) -> None:
    """Fallback inserts 30-minute meal break at shift midpoint for shifts over 5 hours."""
    sched = Schedule(
        employee_id="E1",
        date="2026-11-07",
        start_time=datetime(2026, 11, 7, 9, 0),
        end_time=datetime(2026, 11, 7, 17, 30),
    )
    punches = [
        Punch(employee_id="E1", timestamp=datetime(2026, 11, 7, 9, 0), punch_type=PunchType.IN),
        Punch(employee_id="E1", timestamp=datetime(2026, 11, 7, 17, 30), punch_type=PunchType.OUT),
    ]
    exc = TimecardException(
        exception_id="EXC-MB-1",
        employee_id="E1",
        exception_type=ExceptionType.MEAL_BREAK,
        date="2026-11-07",
        description="Missing meal break on 8.5h shift",
        policy_reference="MEAL-01",
    )
    res = fallback_engine.generate_fallback(exc, punches, sched)
    assert res.success is True
    assert res.validation_result.valid is True
    assert "MEAL-01" in res.validation_result.cited_policy_ids


def test_overtime_fallback_packages_for_manager_authorization(
    fallback_engine: FallbackEngine,
) -> None:
    """Overtime fallback packages shift for manager sign-off without deleting worked hours."""
    sched = Schedule(
        employee_id="E1",
        date="2026-11-07",
        start_time=datetime(2026, 11, 7, 8, 0),
        end_time=datetime(2026, 11, 7, 18, 0),
    )
    punches = [
        Punch(employee_id="E1", timestamp=datetime(2026, 11, 7, 8, 0), punch_type=PunchType.IN),
        Punch(
            employee_id="E1",
            timestamp=datetime(2026, 11, 7, 12, 0),
            punch_type=PunchType.BREAK_START,
        ),
        Punch(
            employee_id="E1",
            timestamp=datetime(2026, 11, 7, 12, 30),
            punch_type=PunchType.BREAK_END,
        ),
        Punch(employee_id="E1", timestamp=datetime(2026, 11, 7, 18, 0), punch_type=PunchType.OUT),
    ]
    exc = TimecardException(
        exception_id="EXC-OT-1",
        employee_id="E1",
        exception_type=ExceptionType.OVERTIME,
        date="2026-11-07",
        description="Daily overtime 9.5 hours",
        policy_reference="OT-01",
    )
    res = fallback_engine.generate_fallback(exc, punches, sched)
    assert res.success is True
    assert res.requires_manager_review is True
    assert "OT-01" in res.validation_result.cited_policy_ids
