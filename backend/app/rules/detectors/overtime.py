"""Overtime Detector for Timecard Exception Agent.

Detects:
- Daily overtime (> 8.0 hours)
- Weekly overtime (> 40.0 regular hours)
- Working hours exceeding configured maximum limits
- Strict boundary conditions (8.00h is regular; 8.01h is overtime; 40.00h is regular)
"""

from collections.abc import Sequence

from ..hours_calculator import CalculatorConfig, DailyHoursResult, HoursCalculator
from ..models.exception import (
    ExceptionType,
    Punch,
    Schedule,
    Severity,
    TimecardException,
)
from .base import BaseDetector


class OvertimeDetector(BaseDetector):
    """Detector for daily and weekly overtime threshold violations."""

    def __init__(self, config: CalculatorConfig | None = None) -> None:
        self.config = config or CalculatorConfig()
        self.calculator = HoursCalculator(self.config)

    @property
    def exception_type(self) -> ExceptionType:
        return ExceptionType.OVERTIME

    def detect(
        self,
        employee_id: str,
        date_str: str,
        punches: Sequence[Punch],
        schedule: Schedule | None = None,
    ) -> list[TimecardException]:
        """Detect daily overtime and excessive work duration for a single shift date."""
        exceptions: list[TimecardException] = []
        if not punches:
            return exceptions

        daily_calc = self.calculator.calculate_daily_hours(punches, target_date=date_str)

        # Skip overtime calculation if there are unclosed/missing punches that prevent accurate hours
        if daily_calc.has_missing_punches or daily_calc.net_hours <= 0:
            return exceptions

        # 1. Check excessive single shift duration limit (e.g. > 12h or > 16h)
        if daily_calc.net_hours > 12.0:
            exc_id = self.generate_exception_id(employee_id, date_str, "excessive_hours")
            is_cap = daily_calc.net_hours >= self.config.max_shift_hours
            exceptions.append(
                TimecardException(
                    exception_id=exc_id,
                    employee_id=employee_id,
                    exception_type=self.exception_type,
                    date=date_str,
                    severity=Severity.CRITICAL if is_cap else Severity.HIGH,
                    description=(
                        f"Excessive working hours: Employee worked {daily_calc.net_hours:.2f} hours "
                        f"(exceeds {self.config.max_shift_hours:.0f}h safety cap), "
                        f"substantially exceeding daily health and safety limits."
                        if is_cap
                        else (
                            f"Excessive working hours: Employee worked {daily_calc.net_hours:.2f} hours, "
                            f"substantially exceeding daily health and safety limits."
                        )
                    ),
                    original_attendance=daily_calc.to_dict(),
                    policy_reference="OT-01",
                )
            )

        # 2. Daily overtime threshold check (> 8.0 hours)
        # Note: Boundary check - exactly 8.00 is NOT overtime; 8.01 is overtime
        if daily_calc.net_hours > self.config.daily_regular_hours_limit:
            ot_hours = daily_calc.daily_overtime_hours
            exc_id = self.generate_exception_id(employee_id, date_str, "daily_overtime")
            exceptions.append(
                TimecardException(
                    exception_id=exc_id,
                    employee_id=employee_id,
                    exception_type=self.exception_type,
                    date=date_str,
                    severity=Severity.MEDIUM if ot_hours <= 2.0 else Severity.HIGH,
                    description=(
                        f"Daily overtime: Employee worked {daily_calc.net_hours:.2f} net hours "
                        f"({ot_hours:.2f} hours overtime beyond {self.config.daily_regular_hours_limit:.1f}h standard limit)."
                    ),
                    original_attendance=daily_calc.to_dict(),
                    policy_reference="OT-01",
                )
            )

        return exceptions

    def detect_weekly_overtime(
        self,
        employee_id: str,
        week_label: str,
        daily_punches: Sequence[Sequence[Punch]],
    ) -> list[TimecardException]:
        """Detect weekly overtime across a sequence of workdays in a workweek."""
        exceptions: list[TimecardException] = []
        daily_calcs: list[DailyHoursResult] = [
            self.calculator.calculate_daily_hours(p_seq) for p_seq in daily_punches if p_seq
        ]

        if not daily_calcs:
            return exceptions

        weekly_res = self.calculator.calculate_weekly_hours(daily_calcs)

        # Boundary: exactly 40.00 regular hours is NOT weekly overtime; 40.01 is
        if weekly_res.weekly_overtime_hours > 0.0:
            exc_id = self.generate_exception_id(employee_id, week_label, "weekly_overtime")
            exceptions.append(
                TimecardException(
                    exception_id=exc_id,
                    employee_id=employee_id,
                    exception_type=self.exception_type,
                    date=week_label,
                    severity=Severity.HIGH,
                    description=(
                        f"Weekly overtime: Employee accumulated {weekly_res.total_net_hours:.2f} net hours, "
                        f"triggering {weekly_res.weekly_overtime_hours:.2f} hours of weekly overtime "
                        f"beyond the {self.config.weekly_regular_hours_limit:.1f}h threshold."
                    ),
                    original_attendance=weekly_res.to_dict(),
                    policy_reference="OT-02",
                )
            )

        return exceptions
