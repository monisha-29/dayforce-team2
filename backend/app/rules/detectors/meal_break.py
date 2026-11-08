"""Meal Break Detector for Timecard Exception Agent.

Detects:
- Missing meal breaks (shift > 5.0 hours with no qualifying meal break)
- Break duration below configured minimum (< 30 minutes)
- Continuous work beyond configured limit (working > 5 hours before taking a break)
- Incorrectly recorded break intervals
"""

from collections.abc import Sequence
from dataclasses import dataclass

from ..hours_calculator import BreakInterval, CalculatorConfig, HoursCalculator
from ..models.exception import (
    ExceptionType,
    Punch,
    Schedule,
    Severity,
    TimecardException,
)
from .base import BaseDetector


@dataclass(frozen=True)
class MealBreakConfig:
    """Configurable thresholds for meal breaks."""

    shift_threshold_hours: float = 5.0
    min_break_minutes: int = 30
    max_continuous_work_hours: float = 5.0
    max_break_minutes: int = 120


class MealBreakDetector(BaseDetector):
    """Detector for mandatory meal break violations."""

    def __init__(self, config: MealBreakConfig | None = None) -> None:
        self.config = config or MealBreakConfig()
        self.calculator = HoursCalculator(
            CalculatorConfig(
                meal_break_threshold_hours=self.config.shift_threshold_hours,
                min_meal_break_minutes=self.config.min_break_minutes,
            )
        )

    @property
    def exception_type(self) -> ExceptionType:
        return ExceptionType.MEAL_BREAK

    def detect(
        self,
        employee_id: str,
        date_str: str,
        punches: Sequence[Punch],
        schedule: Schedule | None = None,
    ) -> list[TimecardException]:
        exceptions: list[TimecardException] = []
        if not punches:
            return exceptions

        daily_calc = self.calculator.calculate_daily_hours(punches, target_date=date_str)

        # If punches are missing/unclosed, missed punch detector handles the structural flaw
        if daily_calc.has_missing_punches or daily_calc.net_hours <= 0:
            return exceptions

        # 1. Total shift duration qualifies for mandatory break (> 5.0 hours)
        qualifies_for_break = daily_calc.gross_hours >= self.config.shift_threshold_hours

        # Detect breaks taken either via explicit break intervals or gap between split shifts
        qualifying_breaks: list[BreakInterval] = []
        short_breaks: list[BreakInterval] = []

        # Analyze explicit breaks
        for b in daily_calc.breaks:
            if b.duration_minutes >= self.config.min_break_minutes:
                qualifying_breaks.append(b)
            else:
                short_breaks.append(b)

        # Analyze split shift gaps ONLY if no explicit break punches were recorded
        if not daily_calc.breaks and len(daily_calc.shifts) > 1:
            for i in range(len(daily_calc.shifts) - 1):
                s_curr = daily_calc.shifts[i]
                s_next = daily_calc.shifts[i + 1]
                gap_min = (s_next.start - s_curr.end).total_seconds() / 60.0
                gap_interval = BreakInterval(
                    start=s_curr.end,
                    end=s_next.start,
                    duration_minutes=gap_min,
                )
                if gap_min >= self.config.min_break_minutes:
                    qualifying_breaks.append(gap_interval)
                elif 0 < gap_min < self.config.min_break_minutes:
                    short_breaks.append(gap_interval)

        # Case 1: Missing meal break on qualifying shift (> 5h) with ZERO breaks taken
        if qualifies_for_break and not qualifying_breaks and not short_breaks:
            exc_id = self.generate_exception_id(employee_id, date_str, "missing_meal_break")
            exceptions.append(
                TimecardException(
                    exception_id=exc_id,
                    employee_id=employee_id,
                    exception_type=self.exception_type,
                    date=date_str,
                    severity=Severity.HIGH,
                    description=(
                        f"Missing meal break: Employee worked {daily_calc.gross_hours:.2f} gross hours "
                        f"(threshold is {self.config.shift_threshold_hours:.1f}h) without an uninterrupted "
                        f"{self.config.min_break_minutes}-minute meal break."
                    ),
                    original_attendance=daily_calc.to_dict(),
                    policy_reference="MEAL-01",
                )
            )

        # Case 2: Short meal break (break recorded, but duration below required minimum e.g. <30m)
        for sb in short_breaks:
            dur = sb.duration_minutes
            exc_id = self.generate_exception_id(employee_id, date_str, f"short_break_{int(dur)}")
            exceptions.append(
                TimecardException(
                    exception_id=exc_id,
                    employee_id=employee_id,
                    exception_type=self.exception_type,
                    date=date_str,
                    severity=Severity.MEDIUM,
                    description=(
                        f"Short meal break: Break of {dur:.1f} minutes recorded, "
                        f"which is less than the required {self.config.min_break_minutes} minutes."
                    ),
                    original_attendance={
                        "break_duration_minutes": dur,
                        "required_minutes": self.config.min_break_minutes,
                        "shift_details": daily_calc.to_dict(),
                    },
                    policy_reference="MEAL-02",
                )
            )

        # Case 3: Continuous work beyond 5.0 hours before taking first break
        if qualifies_for_break and daily_calc.shifts:
            first_shift = daily_calc.shifts[0]
            if first_shift.duration_hours > self.config.max_continuous_work_hours and (
                len(daily_calc.shifts) > 1 or daily_calc.breaks
            ):
                exc_id = self.generate_exception_id(employee_id, date_str, "delayed_meal_break")
                exceptions.append(
                    TimecardException(
                        exception_id=exc_id,
                        employee_id=employee_id,
                        exception_type=self.exception_type,
                        date=date_str,
                        severity=Severity.MEDIUM,
                        description=(
                            f"Delayed meal break: Employee worked {first_shift.duration_hours:.2f} hours continuously "
                            f"before taking a meal break (maximum continuous work limit is {self.config.max_continuous_work_hours:.1f}h)."
                        ),
                        original_attendance=daily_calc.to_dict(),
                        policy_reference="MEAL-02",
                    )
                )

        # Case 4: Exceptionally long break (> 120 minutes)
        for b in daily_calc.breaks:
            if b.duration_minutes > self.config.max_break_minutes:
                exc_id = self.generate_exception_id(
                    employee_id, date_str, f"excessive_break_{int(b.duration_minutes)}"
                )
                exceptions.append(
                    TimecardException(
                        exception_id=exc_id,
                        employee_id=employee_id,
                        exception_type=self.exception_type,
                        date=date_str,
                        severity=Severity.LOW,
                        description=(
                            f"Excessive break duration: Break of {b.duration_minutes:.1f} minutes recorded "
                            f"(limit is {self.config.max_break_minutes} minutes). Verify if this was a split shift."
                        ),
                        original_attendance={"break_duration_minutes": b.duration_minutes},
                        policy_reference="MEAL-02",
                    )
                )

        return exceptions
