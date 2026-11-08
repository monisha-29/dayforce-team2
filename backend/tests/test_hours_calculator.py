"""Comprehensive tests for HoursCalculator including Hypothesis property tests."""

from datetime import datetime, timedelta

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.rules.hours_calculator import HoursCalculator
from app.rules.models.exception import Punch, PunchType


@pytest.fixture
def calculator() -> HoursCalculator:
    return HoursCalculator()


def test_normal_shift(calculator: HoursCalculator) -> None:
    """Test standard 8-hour shift without breaks."""
    punches = [
        Punch(employee_id="E1", timestamp=datetime(2026, 11, 7, 9, 0), punch_type=PunchType.IN),
        Punch(employee_id="E1", timestamp=datetime(2026, 11, 7, 17, 0), punch_type=PunchType.OUT),
    ]
    res = calculator.calculate_daily_hours(punches)
    assert res.net_hours == 8.0
    assert res.regular_hours == 8.0
    assert res.daily_overtime_hours == 0.0
    assert not res.is_overnight
    assert not res.has_missing_punches


def test_overnight_shift(calculator: HoursCalculator) -> None:
    """Test shift that crosses midnight (22:00 to 06:00 next day)."""
    punches = [
        Punch(employee_id="E1", timestamp=datetime(2026, 11, 7, 22, 0), punch_type=PunchType.IN),
        Punch(employee_id="E1", timestamp=datetime(2026, 11, 8, 6, 0), punch_type=PunchType.OUT),
    ]
    res = calculator.calculate_daily_hours(punches)
    assert res.net_hours == 8.0
    assert res.regular_hours == 8.0
    assert res.daily_overtime_hours == 0.0
    assert res.is_overnight is True


def test_missing_punches(calculator: HoursCalculator) -> None:
    """Test missing IN and missing OUT detection."""
    # Only IN
    punches_in = [
        Punch(employee_id="E1", timestamp=datetime(2026, 11, 7, 9, 0), punch_type=PunchType.IN),
    ]
    res_in = calculator.calculate_daily_hours(punches_in)
    assert res_in.has_missing_punches is True
    assert len(res_in.missing_punch_notes) > 0

    # Only OUT
    punches_out = [
        Punch(employee_id="E1", timestamp=datetime(2026, 11, 7, 17, 0), punch_type=PunchType.OUT),
    ]
    res_out = calculator.calculate_daily_hours(punches_out)
    assert res_out.has_missing_punches is True


def test_split_shift(calculator: HoursCalculator) -> None:
    """Test split shifts with multiple IN/OUT pairs."""
    punches = [
        Punch(employee_id="E1", timestamp=datetime(2026, 11, 7, 8, 0), punch_type=PunchType.IN),
        Punch(employee_id="E1", timestamp=datetime(2026, 11, 7, 12, 0), punch_type=PunchType.OUT),
        Punch(employee_id="E1", timestamp=datetime(2026, 11, 7, 16, 0), punch_type=PunchType.IN),
        Punch(employee_id="E1", timestamp=datetime(2026, 11, 7, 20, 0), punch_type=PunchType.OUT),
    ]
    res = calculator.calculate_daily_hours(punches)
    assert res.net_hours == 8.0
    assert len(res.shifts) == 2
    assert res.shifts[0].duration_hours == 4.0
    assert res.shifts[1].duration_hours == 4.0


def test_exactly_8_hours_boundary(calculator: HoursCalculator) -> None:
    """Test boundary condition: exactly 8.00 hours has 0 daily overtime."""
    punches = [
        Punch(employee_id="E1", timestamp=datetime(2026, 11, 7, 9, 0), punch_type=PunchType.IN),
        Punch(employee_id="E1", timestamp=datetime(2026, 11, 7, 17, 0), punch_type=PunchType.OUT),
    ]
    res = calculator.calculate_daily_hours(punches)
    assert res.net_hours == 8.0
    assert res.daily_overtime_hours == 0.0


def test_more_than_8_hours_overtime(calculator: HoursCalculator) -> None:
    """Test shift exceeding 8.0 hours produces daily overtime."""
    # 9.5 hours
    punches = [
        Punch(employee_id="E1", timestamp=datetime(2026, 11, 7, 8, 0), punch_type=PunchType.IN),
        Punch(employee_id="E1", timestamp=datetime(2026, 11, 7, 17, 30), punch_type=PunchType.OUT),
    ]
    res = calculator.calculate_daily_hours(punches)
    assert res.net_hours == 9.5
    assert res.regular_hours == 8.0
    assert res.daily_overtime_hours == 1.5


def test_exactly_40_hours_weekly(calculator: HoursCalculator) -> None:
    """Test boundary: 5 days of 8 hours = 40.0 regular hours -> 0 weekly overtime."""
    daily_results = []
    for day in range(1, 6):
        punches = [
            Punch(
                employee_id="E1", timestamp=datetime(2026, 11, day, 9, 0), punch_type=PunchType.IN
            ),
            Punch(
                employee_id="E1", timestamp=datetime(2026, 11, day, 17, 0), punch_type=PunchType.OUT
            ),
        ]
        daily_results.append(calculator.calculate_daily_hours(punches))

    weekly = calculator.calculate_weekly_hours(daily_results)
    assert weekly.total_regular_hours == 40.0
    assert weekly.weekly_overtime_hours == 0.0
    assert weekly.total_overtime_hours == 0.0


def test_more_than_40_hours_weekly(calculator: HoursCalculator) -> None:
    """Test weekly overtime when cumulative regular hours exceed 40.0."""
    daily_results = []
    # 6 days of 8 hours = 48 hours total
    for day in range(1, 7):
        punches = [
            Punch(
                employee_id="E1", timestamp=datetime(2026, 11, day, 9, 0), punch_type=PunchType.IN
            ),
            Punch(
                employee_id="E1", timestamp=datetime(2026, 11, day, 17, 0), punch_type=PunchType.OUT
            ),
        ]
        daily_results.append(calculator.calculate_daily_hours(punches))

    weekly = calculator.calculate_weekly_hours(daily_results)
    assert weekly.total_regular_hours == 40.0
    assert weekly.weekly_overtime_hours == 8.0
    assert weekly.total_overtime_hours == 8.0


def test_invalid_timestamps(calculator: HoursCalculator) -> None:
    """Test rejection when OUT timestamp is earlier than IN timestamp."""
    punches = [
        Punch(employee_id="E1", timestamp=datetime(2026, 11, 7, 17, 0), punch_type=PunchType.IN),
        Punch(employee_id="E1", timestamp=datetime(2026, 11, 7, 9, 0), punch_type=PunchType.OUT),
    ]
    res = calculator.calculate_daily_hours(punches)
    # Sorted order puts OUT at 9:00 first, then IN at 17:00
    assert res.has_missing_punches is True


def test_overlapping_punches(calculator: HoursCalculator) -> None:
    """Test detection of overlapping shift intervals."""
    punches = [
        Punch(employee_id="E1", timestamp=datetime(2026, 11, 7, 8, 0), punch_type=PunchType.IN),
        Punch(employee_id="E1", timestamp=datetime(2026, 11, 7, 14, 0), punch_type=PunchType.OUT),
        Punch(employee_id="E1", timestamp=datetime(2026, 11, 7, 13, 0), punch_type=PunchType.IN),
        Punch(employee_id="E1", timestamp=datetime(2026, 11, 7, 18, 0), punch_type=PunchType.OUT),
    ]
    res = calculator.calculate_daily_hours(punches)
    assert res.has_overlapping_punches is True
    assert any("Overlapping" in err for err in res.errors)


# =====================================================================
# Hypothesis Property-Based Testing
# =====================================================================
@settings(max_examples=100)
@given(
    start_hour=st.integers(min_value=0, max_value=22),
    start_minute=st.integers(min_value=0, max_value=59),
    duration_minutes=st.integers(min_value=1, max_value=14 * 60),  # Up to 14 hours
)
def test_hypothesis_shift_properties(
    start_hour: int,
    start_minute: int,
    duration_minutes: int,
) -> None:
    """Property test verifying mathematical invariants for any valid shift."""
    calc = HoursCalculator()
    start_time = datetime(2026, 11, 7, start_hour, start_minute)
    end_time = start_time + timedelta(minutes=duration_minutes)

    punches = [
        Punch(employee_id="HYP", timestamp=start_time, punch_type=PunchType.IN),
        Punch(employee_id="HYP", timestamp=end_time, punch_type=PunchType.OUT),
    ]

    res = calc.calculate_daily_hours(punches)

    # Invariant 1: Net hours non-negative
    assert res.net_hours >= 0.0

    # Invariant 2: Regular hours never exceeds 8.0
    assert res.regular_hours <= 8.0

    # Invariant 3: Regular hours + overtime equals net hours
    assert pytest.approx(res.regular_hours + res.daily_overtime_hours, abs=0.02) == res.net_hours

    # Invariant 4: If net hours <= 8.0, daily overtime must be 0
    if res.net_hours <= 8.0:
        assert res.daily_overtime_hours == 0.0
    else:
        assert res.regular_hours == 8.0
        assert res.daily_overtime_hours > 0.0
