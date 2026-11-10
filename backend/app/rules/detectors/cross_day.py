"""Detectors for the extended exception types.

Detects:
- Duplicate punches: the same punch type recorded again within a couple of minutes
  (double tap on the terminal). Duplicates are removed before the other detectors run,
  so a double tap is never mistaken for a missed punch.
- Rest period violations: too little time between the end of one shift and the start
  of the next.
- Consecutive working days: more than the allowed number of days worked in a row.

The last two look across days, so they take a per-employee list of shifts rather than a
single day of punches.
"""

import itertools
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from ..models.exception import (
    ExceptionType,
    Punch,
    Schedule,
    Severity,
    TimecardException,
)
from .base import BaseDetector


@dataclass(frozen=True)
class CrossDayConfig:
    """Configurable thresholds for the extended exception types."""

    duplicate_window_minutes: int = 2
    min_rest_hours: float = 8.0
    max_consecutive_days: int = 6


@dataclass(frozen=True)
class ShiftSpan:
    """First clock-in and last clock-out of one workday (clock-out is None if missing)."""

    date: str
    start: datetime
    end: datetime | None


def split_duplicate_punches(
    punches: Sequence[Punch],
    window_minutes: int = 2,
) -> tuple[list[Punch], list[tuple[Punch, Punch]]]:
    """Separate punches into (kept, [(duplicate, original)]).

    A punch is a duplicate when the previous kept punch has the same type and is at most
    ``window_minutes`` earlier. The first punch of the burst is the one kept.
    """
    kept: list[Punch] = []
    duplicates: list[tuple[Punch, Punch]] = []
    window = timedelta(minutes=window_minutes)
    for p in sorted(punches, key=lambda x: x.timestamp):
        if (
            kept
            and kept[-1].punch_type == p.punch_type
            and p.timestamp - kept[-1].timestamp <= window
        ):
            duplicates.append((p, kept[-1]))
        else:
            kept.append(p)
    return kept, duplicates


def shift_spans(punches_by_date: Mapping[str, Sequence[Punch]]) -> list[ShiftSpan]:
    """Summarise each workday's punches as a (first IN, last OUT) span, oldest first."""
    spans: list[ShiftSpan] = []
    for date_str, punches in punches_by_date.items():
        ins = [p.timestamp for p in punches if p.punch_type.value == "IN"]
        outs = [p.timestamp for p in punches if p.punch_type.value == "OUT"]
        if not ins:
            continue
        start = min(ins)
        # Only a clock-out after the clock-in closes the shift.
        later_outs = [o for o in outs if o > start]
        spans.append(ShiftSpan(date_str, start, max(later_outs) if later_outs else None))
    return sorted(spans, key=lambda s: s.start)


class DuplicatePunchDetector(BaseDetector):
    """Detector for punches recorded twice within a short window."""

    def __init__(self, config: CrossDayConfig | None = None) -> None:
        self.config = config or CrossDayConfig()

    @property
    def exception_type(self) -> ExceptionType:
        return ExceptionType.DUPLICATE_PUNCH

    def detect(
        self,
        employee_id: str,
        date_str: str,
        punches: Sequence[Punch],
        schedule: Schedule | None = None,
    ) -> list[TimecardException]:
        _, duplicates = split_duplicate_punches(punches, self.config.duplicate_window_minutes)
        exceptions: list[TimecardException] = []
        for dup, original in duplicates:
            gap = int((dup.timestamp - original.timestamp).total_seconds() // 60)
            kind = dup.punch_type.value
            exceptions.append(
                TimecardException(
                    exception_id=self.generate_exception_id(
                        employee_id,
                        date_str,
                        f"duplicate_{kind}_{dup.timestamp.strftime('%H%M%S')}",
                    ),
                    employee_id=employee_id,
                    exception_type=self.exception_type,
                    date=date_str,
                    severity=Severity.LOW,
                    description=(
                        f"Duplicate {kind} punch: recorded at {dup.timestamp.strftime('%H:%M')}, "
                        f"{gap} minute(s) after the same punch at {original.timestamp.strftime('%H:%M')}."
                    ),
                    original_attendance={
                        "duplicate_punch": dup.model_dump(mode="json"),
                        "kept_punch": original.model_dump(mode="json"),
                    },
                    policy_reference="DUP-01",
                )
            )
        return exceptions


class RestPeriodDetector(BaseDetector):
    """Detector for too little rest between consecutive shifts."""

    def __init__(self, config: CrossDayConfig | None = None) -> None:
        self.config = config or CrossDayConfig()

    @property
    def exception_type(self) -> ExceptionType:
        return ExceptionType.REST_PERIOD

    def detect(
        self,
        employee_id: str,
        date_str: str,
        punches: Sequence[Punch],
        schedule: Schedule | None = None,
    ) -> list[TimecardException]:
        return []  # needs more than one day: see detect_across_days

    def detect_across_days(
        self,
        employee_id: str,
        spans: Sequence[ShiftSpan],
    ) -> list[TimecardException]:
        exceptions: list[TimecardException] = []
        ordered = sorted(spans, key=lambda s: s.start)
        for prev, cur in itertools.pairwise(ordered):
            if prev.end is None or cur.start <= prev.end:
                continue
            rest_hours = (cur.start - prev.end).total_seconds() / 3600
            if rest_hours >= self.config.min_rest_hours:
                continue
            exceptions.append(
                TimecardException(
                    exception_id=self.generate_exception_id(employee_id, cur.date, "short_rest"),
                    employee_id=employee_id,
                    exception_type=self.exception_type,
                    date=cur.date,
                    severity=Severity.MEDIUM,
                    description=(
                        f"Rest period violation: only {rest_hours:.1f} hours between the end of the "
                        f"{prev.date} shift ({prev.end.strftime('%H:%M')}) and the start of this shift "
                        f"({cur.start.strftime('%H:%M')}); minimum is {self.config.min_rest_hours:.1f} hours."
                    ),
                    original_attendance={
                        "previous_shift_end": prev.end.isoformat(),
                        "shift_start": cur.start.isoformat(),
                        "rest_hours": round(rest_hours, 2),
                    },
                    policy_reference="REST-01",
                )
            )
        return exceptions


class ConsecutiveDaysDetector(BaseDetector):
    """Detector for working more consecutive days than allowed."""

    def __init__(self, config: CrossDayConfig | None = None) -> None:
        self.config = config or CrossDayConfig()

    @property
    def exception_type(self) -> ExceptionType:
        return ExceptionType.CONSECUTIVE_DAYS

    def detect(
        self,
        employee_id: str,
        date_str: str,
        punches: Sequence[Punch],
        schedule: Schedule | None = None,
    ) -> list[TimecardException]:
        return []  # needs more than one day: see detect_across_days

    def detect_across_days(
        self,
        employee_id: str,
        spans: Sequence[ShiftSpan],
    ) -> list[TimecardException]:
        """Flag the first day that pushes a streak past the limit (once per streak)."""
        exceptions: list[TimecardException] = []
        days = sorted({s.start.date() for s in spans})
        streak = 0
        previous = None
        for day in days:
            streak = (
                streak + 1 if previous is not None and day - previous == timedelta(days=1) else 1
            )
            previous = day
            if streak == self.config.max_consecutive_days + 1:
                exceptions.append(
                    TimecardException(
                        exception_id=self.generate_exception_id(
                            employee_id, day.isoformat(), "consecutive_days"
                        ),
                        employee_id=employee_id,
                        exception_type=self.exception_type,
                        date=day.isoformat(),
                        severity=Severity.MEDIUM,
                        description=(
                            f"Consecutive days: this is day {streak} worked in a row "
                            f"(maximum is {self.config.max_consecutive_days} without a day off)."
                        ),
                        original_attendance={"consecutive_days": streak},
                        policy_reference="CONSEC-01",
                    )
                )
        return exceptions
