"""Schedule Conflict Detector for Timecard Exception Agent.

Detects:
- Late clock-in (exceeding configurable grace period)
- Early clock-out (prior to scheduled shift end minus grace period)
- Clock-in outside assigned schedule (unscheduled work or extreme discrepancy)
- Actual shift conflicting with assigned schedule
- Overlapping schedule assignments
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import timedelta

from ..models.exception import (
    ExceptionType,
    Punch,
    PunchType,
    Schedule,
    Severity,
    TimecardException,
)
from .base import BaseDetector


@dataclass(frozen=True)
class ScheduleConflictConfig:
    """Configurable thresholds for schedule adherence and conflict detection."""

    late_grace_period_minutes: int = 5
    early_exit_grace_period_minutes: int = 5
    unscheduled_early_in_minutes: int = 30
    unscheduled_late_out_minutes: int = 30


class ScheduleConflictDetector(BaseDetector):
    """Detector for deviations between scheduled shifts and actual punches."""

    def __init__(self, config: ScheduleConflictConfig | None = None) -> None:
        self.config = config or ScheduleConflictConfig()

    @property
    def exception_type(self) -> ExceptionType:
        return ExceptionType.SCHEDULE_CONFLICT

    def detect(
        self,
        employee_id: str,
        date_str: str,
        punches: Sequence[Punch],
        schedule: Schedule | None = None,
    ) -> list[TimecardException]:
        exceptions: list[TimecardException] = []
        sorted_punches = sorted(punches, key=lambda p: p.timestamp)

        in_punches = [p for p in sorted_punches if p.punch_type == PunchType.IN]
        out_punches = [p for p in sorted_punches if p.punch_type == PunchType.OUT]

        # Case 1: Unscheduled shift (punches recorded when no schedule exists for this employee/date)
        if sorted_punches and schedule is None:
            exc_id = self.generate_exception_id(employee_id, date_str, "unscheduled_shift")
            exceptions.append(
                TimecardException(
                    exception_id=exc_id,
                    employee_id=employee_id,
                    exception_type=self.exception_type,
                    date=date_str,
                    severity=Severity.MEDIUM,
                    description=(
                        f"Unscheduled shift: Employee recorded {len(sorted_punches)} punch(es) "
                        f"on {date_str} with no assigned schedule in the system."
                    ),
                    original_attendance={
                        "punches": [
                            {"type": p.punch_type.value, "timestamp": p.timestamp.isoformat()}
                            for p in sorted_punches
                        ],
                        "schedule": None,
                    },
                    policy_reference="SCHED-02",
                )
            )
            return exceptions

        if not schedule or not sorted_punches:
            return exceptions

        # Case 2: Late clock-in check
        if in_punches:
            first_in = in_punches[0]
            grace_threshold = schedule.start_time + timedelta(
                minutes=self.config.late_grace_period_minutes
            )
            if first_in.timestamp > grace_threshold:
                tardy_minutes = int((first_in.timestamp - schedule.start_time).total_seconds() / 60)
                exc_id = self.generate_exception_id(employee_id, date_str, "late_arrival")
                exceptions.append(
                    TimecardException(
                        exception_id=exc_id,
                        employee_id=employee_id,
                        exception_type=self.exception_type,
                        date=date_str,
                        severity=Severity.HIGH if tardy_minutes > 30 else Severity.LOW,
                        description=(
                            f"Late clock-in: Employee clocked in at {first_in.timestamp.strftime('%H:%M')}, "
                            f"which is {tardy_minutes} minutes after scheduled start ({schedule.start_time.strftime('%H:%M')}). "
                            f"Grace period is {self.config.late_grace_period_minutes} minutes."
                        ),
                        original_attendance={
                            "first_in": first_in.timestamp.isoformat(),
                            "scheduled_start": schedule.start_time.isoformat(),
                            "tardy_minutes": tardy_minutes,
                        },
                        policy_reference="SCHED-01",
                    )
                )

            # Case 2b: Extreme early arrival outside assigned schedule
            extreme_early_threshold = schedule.start_time - timedelta(
                minutes=self.config.unscheduled_early_in_minutes
            )
            if first_in.timestamp < extreme_early_threshold:
                early_in_minutes = int(
                    (schedule.start_time - first_in.timestamp).total_seconds() / 60
                )
                exc_id = self.generate_exception_id(employee_id, date_str, "extreme_early_in")
                exceptions.append(
                    TimecardException(
                        exception_id=exc_id,
                        employee_id=employee_id,
                        exception_type=self.exception_type,
                        date=date_str,
                        severity=Severity.LOW,
                        description=(
                            f"Clock-in outside assigned schedule: Clock-in at {first_in.timestamp.strftime('%H:%M')} "
                            f"is {early_in_minutes} minutes prior to scheduled start ({schedule.start_time.strftime('%H:%M')})."
                        ),
                        original_attendance={
                            "first_in": first_in.timestamp.isoformat(),
                            "scheduled_start": schedule.start_time.isoformat(),
                            "early_in_minutes": early_in_minutes,
                        },
                        policy_reference="SCHED-02",
                    )
                )

        # Case 3: Early clock-out check
        if out_punches:
            last_out = out_punches[-1]
            early_exit_threshold = schedule.end_time - timedelta(
                minutes=self.config.early_exit_grace_period_minutes
            )
            if last_out.timestamp < early_exit_threshold:
                early_exit_minutes = int(
                    (schedule.end_time - last_out.timestamp).total_seconds() / 60
                )
                exc_id = self.generate_exception_id(employee_id, date_str, "early_departure")
                exceptions.append(
                    TimecardException(
                        exception_id=exc_id,
                        employee_id=employee_id,
                        exception_type=self.exception_type,
                        date=date_str,
                        severity=Severity.MEDIUM if early_exit_minutes > 15 else Severity.LOW,
                        description=(
                            f"Early clock-out: Employee clocked out at {last_out.timestamp.strftime('%H:%M')}, "
                            f"which is {early_exit_minutes} minutes before scheduled end ({schedule.end_time.strftime('%H:%M')})."
                        ),
                        original_attendance={
                            "last_out": last_out.timestamp.isoformat(),
                            "scheduled_end": schedule.end_time.isoformat(),
                            "early_exit_minutes": early_exit_minutes,
                        },
                        policy_reference="SCHED-01",
                    )
                )

        return exceptions

    def detect_overlapping_schedules(
        self,
        employee_id: str,
        schedules: Sequence[Schedule],
    ) -> list[TimecardException]:
        """Detect if an employee has conflicting overlapping schedule assignments."""
        exceptions: list[TimecardException] = []
        sorted_scheds = sorted(schedules, key=lambda s: s.start_time)

        for i in range(len(sorted_scheds)):
            for j in range(i + 1, len(sorted_scheds)):
                s1 = sorted_scheds[i]
                s2 = sorted_scheds[j]
                if max(s1.start_time, s2.start_time) < min(s1.end_time, s2.end_time):
                    exc_id = self.generate_exception_id(
                        employee_id, s1.date, f"overlap_{s1.id or i}_{s2.id or j}"
                    )
                    exceptions.append(
                        TimecardException(
                            exception_id=exc_id,
                            employee_id=employee_id,
                            exception_type=self.exception_type,
                            date=s1.date,
                            severity=Severity.HIGH,
                            description=(
                                f"Overlapping schedules: Shift [{s1.start_time.strftime('%H:%M')} - "
                                f"{s1.end_time.strftime('%H:%M')}] conflicts with shift [{s2.start_time.strftime('%H:%M')} - "
                                f"{s2.end_time.strftime('%H:%M')}]."
                            ),
                            original_attendance={
                                "schedule_1": s1.model_dump(mode="json"),
                                "schedule_2": s2.model_dump(mode="json"),
                            },
                            policy_reference="SCHED-02",
                        )
                    )
        return exceptions
