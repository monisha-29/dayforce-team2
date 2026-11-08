"""Working Hours Calculator for Timecard Exception Agent.

Performs all deterministic working hours, break duration, daily overtime,
weekly overtime, and shift interval calculations.

Principles:
- Pure Python using datetime and timedelta.
- The LLM must NEVER calculate working hours; all math is done here.
- Fully configurable thresholds and boundaries.
- Resilient to overnight shifts, split shifts, missing punches, and overlaps.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from .models.exception import Punch, PunchType


@dataclass(frozen=True)
class CalculatorConfig:
    """Configurable thresholds for working hours and overtime calculations."""

    daily_regular_hours_limit: float = 8.0
    weekly_regular_hours_limit: float = 40.0
    max_shift_hours: float = 16.0
    min_meal_break_minutes: int = 30
    meal_break_threshold_hours: float = 5.0
    round_decimals: int = 2


@dataclass
class ShiftInterval:
    """A contiguous period of active work between an IN and OUT punch."""

    start: datetime
    end: datetime
    duration_hours: float

    @property
    def is_overnight(self) -> bool:
        return self.start.date() != self.end.date()


@dataclass
class BreakInterval:
    """A recorded or inferred break interval."""

    start: datetime
    end: datetime
    duration_minutes: float
    is_meal_break: bool = True


@dataclass
class DailyHoursResult:
    """Result of working hours calculations for a single shift/day."""

    shift_date: str  # YYYY-MM-DD
    gross_hours: float = 0.0
    break_hours: float = 0.0
    net_hours: float = 0.0
    regular_hours: float = 0.0
    daily_overtime_hours: float = 0.0
    shifts: list[ShiftInterval] = field(default_factory=list)
    breaks: list[BreakInterval] = field(default_factory=list)
    is_overnight: bool = False
    has_missing_punches: bool = False
    has_overlapping_punches: bool = False
    missing_punch_notes: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "shift_date": self.shift_date,
            "gross_hours": self.gross_hours,
            "break_hours": self.break_hours,
            "net_hours": self.net_hours,
            "regular_hours": self.regular_hours,
            "daily_overtime_hours": self.daily_overtime_hours,
            "is_overnight": self.is_overnight,
            "has_missing_punches": self.has_missing_punches,
            "has_overlapping_punches": self.has_overlapping_punches,
            "missing_punch_notes": self.missing_punch_notes,
            "errors": self.errors,
            "warnings": self.warnings,
        }


@dataclass
class WeeklyHoursResult:
    """Aggregated working hours across a workweek (e.g. 7 days)."""

    total_gross_hours: float = 0.0
    total_break_hours: float = 0.0
    total_net_hours: float = 0.0
    total_regular_hours: float = 0.0
    total_daily_overtime_hours: float = 0.0
    weekly_overtime_hours: float = 0.0
    total_overtime_hours: float = 0.0
    daily_breakdowns: list[DailyHoursResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_gross_hours": self.total_gross_hours,
            "total_break_hours": self.total_break_hours,
            "total_net_hours": self.total_net_hours,
            "total_regular_hours": self.total_regular_hours,
            "total_daily_overtime_hours": self.total_daily_overtime_hours,
            "weekly_overtime_hours": self.weekly_overtime_hours,
            "total_overtime_hours": self.total_overtime_hours,
        }


class HoursCalculator:
    """Deterministic calculator for employee working hours and overtime."""

    def __init__(self, config: CalculatorConfig | None = None) -> None:
        self.config = config or CalculatorConfig()

    def _round(self, val: float) -> float:
        return round(val, self.config.round_decimals)

    def calculate_daily_hours(
        self,
        punches: Sequence[Punch],
        target_date: str | None = None,
    ) -> DailyHoursResult:
        """Calculate working hours for a given sequence of punches.

        Handles:
        - Overnight shifts (IN on day 1, OUT on day 2)
        - Split shifts (multiple IN/OUT pairs)
        - Dedicated BREAK_START / BREAK_END punches
        - Missing IN or OUT detection
        - Overlapping punch detection
        - Exactly 8.0 hours vs > 8.0 hours
        """
        sorted_punches = sorted(punches, key=lambda p: p.timestamp)

        # Determine reference date if not provided
        if not target_date:
            if sorted_punches:
                target_date = sorted_punches[0].timestamp.date().isoformat()
            else:
                target_date = date.today().isoformat()

        result = DailyHoursResult(shift_date=target_date)

        if not sorted_punches:
            result.warnings.append("No punches provided for calculation.")
            return result

        # First pass: check for duplicate or inverted chronological anomalies
        for i in range(len(sorted_punches) - 1):
            curr_p = sorted_punches[i]
            next_p = sorted_punches[i + 1]
            if curr_p.timestamp == next_p.timestamp and curr_p.punch_type == next_p.punch_type:
                result.warnings.append(
                    f"Duplicate punch detected at {curr_p.timestamp.isoformat()}"
                )

        # Pair up punches into work intervals and break intervals
        work_intervals: list[ShiftInterval] = []
        break_intervals: list[BreakInterval] = []

        current_in: datetime | None = None
        current_break_start: datetime | None = None

        for punch in sorted_punches:
            ptype = punch.punch_type

            if ptype == PunchType.IN:
                if current_in is not None:
                    # Incomplete pair and overlapping clock-in
                    result.has_missing_punches = True
                    result.has_overlapping_punches = True
                    result.missing_punch_notes.append(
                        f"Missing OUT punch before new IN at {punch.timestamp.isoformat()}"
                    )
                    result.errors.append(
                        f"Overlapping punches: Clock-in at {punch.timestamp.isoformat()} occurs while already clocked in since {current_in.isoformat()}"
                    )
                current_in = punch.timestamp

            elif ptype == PunchType.OUT:
                if current_in is None:
                    # Incomplete pair: OUT without a preceding IN
                    result.has_missing_punches = True
                    result.missing_punch_notes.append(
                        f"Missing IN punch before OUT at {punch.timestamp.isoformat()}"
                    )
                else:
                    # Valid pair completed
                    start = current_in
                    end = punch.timestamp
                    current_in = None

                    if end < start:
                        result.errors.append(
                            f"Invalid timestamps: OUT {end.isoformat()} is earlier than IN {start.isoformat()}"
                        )
                        continue

                    duration_seconds = (end - start).total_seconds()
                    duration_hours = self._round(duration_seconds / 3600.0)

                    if duration_hours > self.config.max_shift_hours:
                        result.errors.append(
                            f"Shift duration {duration_hours}h exceeds maximum allowed limit {self.config.max_shift_hours}h"
                        )

                    interval = ShiftInterval(
                        start=start,
                        end=end,
                        duration_hours=duration_hours,
                    )
                    work_intervals.append(interval)

            elif ptype == PunchType.BREAK_START:
                if current_break_start is not None:
                    result.warnings.append("Consecutive BREAK_START without BREAK_END.")
                else:
                    # If currently clocked in, close the active work interval up to the break start
                    if current_in is not None:
                        start = current_in
                        end = punch.timestamp
                        current_in = None
                        if end >= start:
                            dur_h = self._round((end - start).total_seconds() / 3600.0)
                            work_intervals.append(
                                ShiftInterval(start=start, end=end, duration_hours=dur_h)
                            )
                current_break_start = punch.timestamp

            elif ptype == PunchType.BREAK_END:
                if current_break_start is None:
                    result.warnings.append("BREAK_END without preceding BREAK_START.")
                else:
                    b_start = current_break_start
                    b_end = punch.timestamp
                    current_break_start = None

                    if b_end < b_start:
                        result.errors.append(
                            f"Invalid break timestamps: BREAK_END {b_end.isoformat()} < BREAK_START {b_start.isoformat()}"
                        )
                        continue

                    b_duration_minutes = (b_end - b_start).total_seconds() / 60.0
                    break_intervals.append(
                        BreakInterval(
                            start=b_start,
                            end=b_end,
                            duration_minutes=self._round(b_duration_minutes),
                        )
                    )
                    # Automatically resume work interval after break ends
                    current_in = b_end

        # Check trailing unclosed punches
        if current_in is not None:
            result.has_missing_punches = True
            result.missing_punch_notes.append(
                f"Shift ending punch missing after IN at {current_in.isoformat()}"
            )

        if current_break_start is not None:
            result.has_missing_punches = True
            result.missing_punch_notes.append(
                f"Unclosed break: missing BREAK_END after {current_break_start.isoformat()}"
            )

        # Detect overlapping shift intervals
        for i in range(len(work_intervals)):
            for j in range(i + 1, len(work_intervals)):
                s1 = work_intervals[i]
                s2 = work_intervals[j]
                if max(s1.start, s2.start) < min(s1.end, s2.end):
                    result.has_overlapping_punches = True
                    result.errors.append(
                        f"Overlapping shifts detected: [{s1.start.isoformat()} - {s1.end.isoformat()}] "
                        f"overlaps with [{s2.start.isoformat()} - {s2.end.isoformat()}]"
                    )

        result.shifts = work_intervals
        result.breaks = break_intervals

        # Check if any shift is overnight
        result.is_overnight = any(s.is_overnight for s in work_intervals)

        # Compute net active work hours from valid completed shifts
        total_work_seconds = sum((s.end - s.start).total_seconds() for s in work_intervals)
        net_hours = self._round(total_work_seconds / 3600.0)

        # Compute break hours from explicit break punches
        total_break_seconds = sum((b.end - b.start).total_seconds() for b in break_intervals)
        explicit_break_hours = self._round(total_break_seconds / 3600.0)

        # Gross span is total elapsed time from shift start to shift end
        if work_intervals:
            first_start = min(s.start for s in work_intervals)
            last_end = max(s.end for s in work_intervals)
            gross_hours = self._round((last_end - first_start).total_seconds() / 3600.0)
        else:
            gross_hours = 0.0

        result.gross_hours = gross_hours
        result.break_hours = explicit_break_hours
        result.net_hours = net_hours

        # Calculate daily regular hours and daily overtime
        # Boundary: Exactly 8.0 hours -> regular=8.0, overtime=0.0
        daily_limit = self.config.daily_regular_hours_limit
        if net_hours <= daily_limit:
            result.regular_hours = net_hours
            result.daily_overtime_hours = 0.0
        else:
            result.regular_hours = daily_limit
            result.daily_overtime_hours = self._round(net_hours - daily_limit)

        return result

    def calculate_weekly_hours(
        self,
        daily_results: Sequence[DailyHoursResult],
    ) -> WeeklyHoursResult:
        """Calculate aggregated weekly hours and weekly overtime.

        Prevents double-counting: hours already counted as daily overtime
        do not count toward the 40-hour weekly threshold.
        Boundary: exactly 40.0 regular hours -> 0 weekly overtime.
        """
        weekly = WeeklyHoursResult()
        weekly.daily_breakdowns = list(daily_results)

        total_gross = 0.0
        total_break = 0.0
        total_net = 0.0
        total_daily_ot = 0.0
        accumulated_regular = 0.0
        weekly_ot = 0.0

        weekly_limit = self.config.weekly_regular_hours_limit

        for day in daily_results:
            total_gross += day.gross_hours
            total_break += day.break_hours
            total_net += day.net_hours
            total_daily_ot += day.daily_overtime_hours

            # Daily regular hours contribute to weekly regular calculation
            day_reg = day.regular_hours
            if accumulated_regular + day_reg <= weekly_limit:
                accumulated_regular += day_reg
            else:
                # Part of today's regular hours pushes over the 40h weekly limit
                allowed_reg = max(0.0, weekly_limit - accumulated_regular)
                excess_weekly = day_reg - allowed_reg
                accumulated_regular = weekly_limit
                weekly_ot += excess_weekly

        weekly.total_gross_hours = self._round(total_gross)
        weekly.total_break_hours = self._round(total_break)
        weekly.total_net_hours = self._round(total_net)
        weekly.total_daily_overtime_hours = self._round(total_daily_ot)
        weekly.total_regular_hours = self._round(accumulated_regular)
        weekly.weekly_overtime_hours = self._round(weekly_ot)
        weekly.total_overtime_hours = self._round(total_daily_ot + weekly_ot)

        return weekly
