"""Tests for Rule-Based Fallback Engine verifying strict compliance and anti-fabrication rules."""

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


def test_missed_clock_out_short_shift_with_schedule(fallback_engine: FallbackEngine) -> None:
    """For shifts under meal break threshold (<5h), fallback proposes clock-out at scheduled end."""
    sched = Schedule(
        employee_id="E1",
        date="2026-11-07",
        start_time=datetime(2026, 11, 7, 9, 0),
        end_time=datetime(2026, 11, 7, 13, 0),  # 4 hour shift
    )
    punches = [
        Punch(employee_id="E1", timestamp=datetime(2026, 11, 7, 9, 0), punch_type=PunchType.IN),
    ]
    exc = TimecardException(
        exception_id="EXC-MP-1",
        employee_id="E1",
        exception_type=ExceptionType.MISSED_PUNCH,
        date="2026-11-07",
        description="Missing clock-out on 4h shift",
        policy_reference="PUNCH-01",
    )
    res = fallback_engine.generate_fallback(exc, punches, sched)
    assert res.success is True
    assert res.exception_id == "EXC-MP-1"
    assert res.proposed_correction is not None
    # Verify NO break punches were fabricated
    proposed_punches = res.proposed_correction["proposed_punches"]
    assert len(proposed_punches) == 1
    assert proposed_punches[0]["punch_type"] == "OUT"
    assert res.requires_manager_review is True
    assert res.validation_result is not None
    assert res.validation_result.valid is True


def test_missed_clock_out_never_fabricates_meal_breaks_on_long_shift(
    fallback_engine: FallbackEngine,
) -> None:
    """Safety Rule: On shifts > 5h with no break punches, fallback NEVER invents/fabricates meal break punches.

    Instead, it must escalate directly to the manager.
    """
    sched = Schedule(
        employee_id="E1",
        date="2026-11-07",
        start_time=datetime(2026, 11, 7, 9, 0),
        end_time=datetime(2026, 11, 7, 17, 30),  # 8.5 hour shift
    )
    punches = [
        Punch(employee_id="E1", timestamp=datetime(2026, 11, 7, 9, 0), punch_type=PunchType.IN),
    ]
    exc = TimecardException(
        exception_id="EXC-MP-LONG",
        employee_id="E1",
        exception_type=ExceptionType.MISSED_PUNCH,
        date="2026-11-07",
        description="Missing clock-out on 8.5h shift without break",
        policy_reference="PUNCH-01",
    )
    res = fallback_engine.generate_fallback(exc, punches, sched)
    # Must refuse to fabricate punches and escalate
    assert res.success is False
    assert res.proposed_correction is None
    assert res.requires_manager_review is True
    assert "fabricating unrecorded meal break punches" in res.reason


def test_meal_break_fallback_never_fabricates_punches_and_escalates(
    fallback_engine: FallbackEngine,
) -> None:
    """Safety Rule: Fallback must NEVER fabricate midpoint BREAK_START / BREAK_END punches for meal break exceptions.

    Actual attendance and break times must be investigated and confirmed by the manager.
    """
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
    assert res.success is False
    assert res.proposed_correction is None
    assert res.requires_manager_review is True
    assert "fabricating employee punch times" in res.reason


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
    assert res.validation_result is not None
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
