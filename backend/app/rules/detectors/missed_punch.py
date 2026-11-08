"""Missed Punch Detector for Timecard Exception Agent.

Detects:
- Missing clock-in
- Missing clock-out
- Incomplete punch pairs
- Missing punches in split shifts
- Invalid punch sequences
"""

from collections.abc import Sequence

from ..models.exception import (
    ExceptionType,
    Punch,
    PunchType,
    Schedule,
    Severity,
    TimecardException,
)
from .base import BaseDetector


class MissedPunchDetector(BaseDetector):
    """Detector for missed or unpaired timecard punches."""

    @property
    def exception_type(self) -> ExceptionType:
        return ExceptionType.MISSED_PUNCH

    def detect(
        self,
        employee_id: str,
        date_str: str,
        punches: Sequence[Punch],
        schedule: Schedule | None = None,
    ) -> list[TimecardException]:
        exceptions: list[TimecardException] = []
        sorted_punches = sorted(punches, key=lambda p: p.timestamp)

        # Case 1: Scheduled shift with zero punches recorded
        if not sorted_punches:
            if schedule is not None:
                exc_id = self.generate_exception_id(employee_id, date_str, "scheduled_no_punches")
                exceptions.append(
                    TimecardException(
                        exception_id=exc_id,
                        employee_id=employee_id,
                        exception_type=self.exception_type,
                        date=date_str,
                        severity=Severity.HIGH,
                        description=(
                            f"Employee was scheduled for shift {schedule.start_time.strftime('%H:%M')} - "
                            f"{schedule.end_time.strftime('%H:%M')} but has no recorded punches."
                        ),
                        original_attendance={
                            "punch_count": 0,
                            "punches": [],
                            "schedule": schedule.model_dump(mode="json"),
                        },
                        policy_reference="PUNCH-02",
                    )
                )
            return exceptions

        # Case 2: Inspect sequence of punches for pairing and anomalies
        current_in: Punch | None = None
        current_break_start: Punch | None = None

        raw_punches_info = [
            {"type": p.punch_type.value, "timestamp": p.timestamp.isoformat()}
            for p in sorted_punches
        ]

        pair_index = 0
        for i, punch in enumerate(sorted_punches):
            ptype = punch.punch_type

            if ptype == PunchType.IN:
                if current_in is not None:
                    # Previous IN had no matching OUT (Incomplete pair / Missing clock-out)
                    exc_id = self.generate_exception_id(
                        employee_id, date_str, f"missing_out_pair_{pair_index}"
                    )
                    exceptions.append(
                        TimecardException(
                            exception_id=exc_id,
                            employee_id=employee_id,
                            exception_type=self.exception_type,
                            date=date_str,
                            severity=Severity.HIGH,
                            description=(
                                f"Missing clock-out: Employee clocked in at {current_in.timestamp.strftime('%H:%M')} "
                                f"but a new clock-in occurred at {punch.timestamp.strftime('%H:%M')} without an intervening clock-out."
                            ),
                            original_attendance={
                                "unclosed_punch": {
                                    "type": current_in.punch_type.value,
                                    "timestamp": current_in.timestamp.isoformat(),
                                },
                                "next_punch": {
                                    "type": punch.punch_type.value,
                                    "timestamp": punch.timestamp.isoformat(),
                                },
                                "punches": raw_punches_info,
                            },
                            policy_reference="PUNCH-01",
                        )
                    )
                    pair_index += 1
                current_in = punch

            elif ptype == PunchType.OUT:
                if current_in is None:
                    # OUT without preceding IN (Missing clock-in)
                    exc_id = self.generate_exception_id(
                        employee_id, date_str, f"missing_in_index_{i}"
                    )
                    exceptions.append(
                        TimecardException(
                            exception_id=exc_id,
                            employee_id=employee_id,
                            exception_type=self.exception_type,
                            date=date_str,
                            severity=Severity.HIGH,
                            description=(
                                f"Missing clock-in: Clock-out recorded at {punch.timestamp.strftime('%H:%M')} "
                                f"with no preceding clock-in."
                            ),
                            original_attendance={
                                "orphan_punch": {
                                    "type": punch.punch_type.value,
                                    "timestamp": punch.timestamp.isoformat(),
                                },
                                "punches": raw_punches_info,
                            },
                            policy_reference="PUNCH-02",
                        )
                    )
                else:
                    # Successfully closed pair
                    current_in = None
                    pair_index += 1

            elif ptype == PunchType.BREAK_START:
                if current_break_start is not None:
                    exc_id = self.generate_exception_id(
                        employee_id, date_str, f"duplicate_break_start_{i}"
                    )
                    exceptions.append(
                        TimecardException(
                            exception_id=exc_id,
                            employee_id=employee_id,
                            exception_type=self.exception_type,
                            date=date_str,
                            severity=Severity.MEDIUM,
                            description=(
                                f"Invalid sequence: Consecutive break start at {punch.timestamp.strftime('%H:%M')} "
                                f"without ending previous break."
                            ),
                            original_attendance={"punches": raw_punches_info},
                            policy_reference="MEAL-02",
                        )
                    )
                current_break_start = punch

            elif ptype == PunchType.BREAK_END:
                if current_break_start is None:
                    exc_id = self.generate_exception_id(
                        employee_id, date_str, f"orphan_break_end_{i}"
                    )
                    exceptions.append(
                        TimecardException(
                            exception_id=exc_id,
                            employee_id=employee_id,
                            exception_type=self.exception_type,
                            date=date_str,
                            severity=Severity.MEDIUM,
                            description=(
                                f"Invalid sequence: Break end recorded at {punch.timestamp.strftime('%H:%M')} "
                                f"without a preceding break start."
                            ),
                            original_attendance={"punches": raw_punches_info},
                            policy_reference="MEAL-02",
                        )
                    )
                else:
                    current_break_start = None

        # Trailing unclosed clock-in at the end of the day/shift
        if current_in is not None:
            exc_id = self.generate_exception_id(
                employee_id, date_str, f"trailing_missing_out_{pair_index}"
            )
            exceptions.append(
                TimecardException(
                    exception_id=exc_id,
                    employee_id=employee_id,
                    exception_type=self.exception_type,
                    date=date_str,
                    severity=Severity.HIGH,
                    description=(
                        f"Missing clock-out: Employee clocked in at {current_in.timestamp.strftime('%H:%M')} "
                        f"with no subsequent clock-out recorded for the shift."
                    ),
                    original_attendance={
                        "unclosed_punch": {
                            "type": current_in.punch_type.value,
                            "timestamp": current_in.timestamp.isoformat(),
                        },
                        "schedule": schedule.model_dump(mode="json") if schedule else None,
                        "punches": raw_punches_info,
                    },
                    policy_reference="PUNCH-01",
                )
            )

        return exceptions
