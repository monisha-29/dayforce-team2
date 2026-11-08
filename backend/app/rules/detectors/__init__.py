"""Detectors package and unified detection engine for Timecard Exception Agent."""

import logging
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from ..hours_calculator import CalculatorConfig
from ..models.exception import (
    Punch,
    Schedule,
    TimecardException,
)
from .base import BaseDetector
from .meal_break import MealBreakConfig, MealBreakDetector
from .missed_punch import MissedPunchDetector
from .overtime import OvertimeDetector
from .schedule_conflict import ScheduleConflictConfig, ScheduleConflictDetector

logger = logging.getLogger(__name__)

__all__ = [
    "BaseDetector",
    "MealBreakDetector",
    "MissedPunchDetector",
    "OvertimeDetector",
    "RulesConfig",
    "ScheduleConflictDetector",
    "detect_all_exceptions",
    "detect_shift_exceptions",
]


@dataclass
class RulesConfig:
    """Unified configuration for all detection rules and calculators."""

    calculator: CalculatorConfig = field(default_factory=CalculatorConfig)
    schedule_conflict: ScheduleConflictConfig = field(default_factory=ScheduleConflictConfig)
    meal_break: MealBreakConfig = field(default_factory=MealBreakConfig)

    @classmethod
    def from_policies(cls, registry: Any) -> "RulesConfig":
        """Construct RulesConfig dynamically from parameters in loaded policy clauses."""
        daily_ot_clause = registry.get_clause("OT-01") if hasattr(registry, "get_clause") else None
        daily_limit = (
            float(daily_ot_clause.parameters.get("daily_threshold_hours", 8.0))
            if daily_ot_clause and hasattr(daily_ot_clause, "parameters")
            else 8.0
        )

        weekly_ot_clause = registry.get_clause("OT-02") if hasattr(registry, "get_clause") else None
        weekly_limit = (
            float(weekly_ot_clause.parameters.get("weekly_threshold_hours", 40.0))
            if weekly_ot_clause and hasattr(weekly_ot_clause, "parameters")
            else 40.0
        )

        sched_clause = registry.get_clause("SCHED-01") if hasattr(registry, "get_clause") else None
        grace_period = (
            int(sched_clause.parameters.get("grace_period_minutes", 5))
            if sched_clause and hasattr(sched_clause, "parameters")
            else 5
        )

        meal_clause = registry.get_clause("MEAL-01") if hasattr(registry, "get_clause") else None
        meal_threshold = (
            float(meal_clause.parameters.get("shift_threshold_hours", 5.0))
            if meal_clause and hasattr(meal_clause, "parameters")
            else 5.0
        )
        min_break = (
            int(meal_clause.parameters.get("min_break_minutes", 30))
            if meal_clause and hasattr(meal_clause, "parameters")
            else 30
        )

        return cls(
            calculator=CalculatorConfig(
                daily_regular_hours_limit=daily_limit,
                weekly_regular_hours_limit=weekly_limit,
                meal_break_threshold_hours=meal_threshold,
                min_meal_break_minutes=min_break,
            ),
            schedule_conflict=ScheduleConflictConfig(
                late_grace_period_minutes=grace_period,
                early_exit_grace_period_minutes=grace_period,
            ),
            meal_break=MealBreakConfig(
                shift_threshold_hours=meal_threshold,
                min_break_minutes=min_break,
            ),
        )


def detect_shift_exceptions(
    employee_id: str,
    date_str: str,
    punches: Sequence[Punch],
    schedule: Schedule | None = None,
    config: RulesConfig | None = None,
) -> list[TimecardException]:
    """Run all 4 detectors on attendance data for a single employee and shift date."""
    cfg = config or RulesConfig()

    detectors: list[BaseDetector] = [
        MissedPunchDetector(),
        OvertimeDetector(cfg.calculator),
        ScheduleConflictDetector(cfg.schedule_conflict),
        MealBreakDetector(cfg.meal_break),
    ]

    found_exceptions: list[TimecardException] = []
    seen_ids: set[str] = set()

    for detector in detectors:
        try:
            excs = detector.detect(
                employee_id=employee_id,
                date_str=date_str,
                punches=punches,
                schedule=schedule,
            )
            for exc in excs:
                if exc.exception_id not in seen_ids:
                    seen_ids.add(exc.exception_id)
                    found_exceptions.append(exc)
        except Exception as err:  # noqa: BLE001
            logger.warning("Detector %s raised unexpected error: %s", type(detector).__name__, err)
            continue

    return found_exceptions


def detect_all_exceptions(
    punches: Sequence[Punch],
    schedules: Sequence[Schedule],
    config: RulesConfig | None = None,
) -> list[TimecardException]:
    """Run all 4 detectors across an entire dataset of punches and schedules.

    Groups attendance by employee and date, processes overnight shifts,
    and deduplicates results.
    """
    cfg = config or RulesConfig()
    all_exceptions: list[TimecardException] = []
    seen_ids: set[str] = set()

    # 1. Map schedules by (employee_id, date)
    schedules_by_emp_date: dict[tuple[str, str], Schedule] = {}
    schedules_by_emp: dict[str, list[Schedule]] = defaultdict(list)
    for s in schedules:
        schedules_by_emp_date[(s.employee_id, s.date)] = s
        schedules_by_emp[s.employee_id].append(s)

    # 2. Check for overlapping schedules per employee
    sched_detector = ScheduleConflictDetector(cfg.schedule_conflict)
    for emp_id, emp_scheds in schedules_by_emp.items():
        if len(emp_scheds) > 1:
            overlap_excs = sched_detector.detect_overlapping_schedules(emp_id, emp_scheds)
            for oe in overlap_excs:
                if oe.exception_id not in seen_ids:
                    seen_ids.add(oe.exception_id)
                    all_exceptions.append(oe)

    # 3. Group punches by employee and shift date
    sorted_punches = sorted(punches, key=lambda p: p.timestamp)
    punches_by_emp_date: dict[tuple[str, str], list[Punch]] = defaultdict(list)
    active_shift_date: dict[str, str] = {}

    for p in sorted_punches:
        emp_id = p.employee_id
        if p.punch_type.value == "IN":
            shift_date = p.timestamp.date().isoformat()
            active_shift_date[emp_id] = shift_date
            punches_by_emp_date[(emp_id, shift_date)].append(p)
        elif p.punch_type.value == "OUT":
            if emp_id in active_shift_date:
                shift_date = active_shift_date.pop(emp_id)
                punches_by_emp_date[(emp_id, shift_date)].append(p)
            else:
                shift_date = p.timestamp.date().isoformat()
                punches_by_emp_date[(emp_id, shift_date)].append(p)
        else:
            shift_date = active_shift_date.get(emp_id, p.timestamp.date().isoformat())
            punches_by_emp_date[(emp_id, shift_date)].append(p)

    # 4. Gather all unique (employee_id, date) pairs from both schedules and punches
    all_keys = set(punches_by_emp_date.keys()) | set(schedules_by_emp_date.keys())

    for emp_id, shift_date in all_keys:
        shift_punches = punches_by_emp_date.get((emp_id, shift_date), [])
        shift_schedule = schedules_by_emp_date.get((emp_id, shift_date))

        shift_excs = detect_shift_exceptions(
            employee_id=emp_id,
            date_str=shift_date,
            punches=shift_punches,
            schedule=shift_schedule,
            config=cfg,
        )
        for exc in shift_excs:
            if exc.exception_id not in seen_ids:
                seen_ids.add(exc.exception_id)
                all_exceptions.append(exc)

    return all_exceptions
