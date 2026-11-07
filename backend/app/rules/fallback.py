"""Rule-Based Fallback Engine for Timecard Exception Agent.

Provides deterministic Python fallback logic when Person 4's LLM module fails
validation twice.

Principles:
- Applies deterministic Python rules.
- Generates a proposed correction ONLY if sufficient source information exists.
- Never invents missing attendance times or fabricates punches without schedule ground truth.
- Validates the fallback using the same ProposalValidator.
- Never directly updates timecards; always returns structured output for manager approval or escalation.
"""

from collections.abc import Sequence
from datetime import timedelta

from .detectors import RulesConfig
from .models.exception import (
    ExceptionType,
    Punch,
    PunchType,
    Schedule,
    TimecardException,
)
from .models.proposal import LLMProposal, ProposedPunch
from .models.validation import FallbackResult
from .validator import ProposalValidator


class FallbackEngine:
    """Deterministic fallback generator for timecard exceptions."""

    def __init__(self, config: RulesConfig | None = None) -> None:
        self.config = config or RulesConfig()
        self.validator = ProposalValidator(self.config)

    def generate_fallback(
        self,
        exception: TimecardException,
        punches: Sequence[Punch],
        schedule: Schedule | None = None,
    ) -> FallbackResult:
        """Generate a deterministic fallback correction and validate it."""
        exc_type = exception.exception_type

        # Dispatch by exception type
        if exc_type == ExceptionType.MISSED_PUNCH:
            return self._fallback_missed_punch(exception, punches, schedule)
        elif exc_type == ExceptionType.OVERTIME:
            return self._fallback_overtime(exception, punches, schedule)
        elif exc_type == ExceptionType.SCHEDULE_CONFLICT:
            return self._fallback_schedule_conflict(exception, punches, schedule)
        elif exc_type == ExceptionType.MEAL_BREAK:
            return self._fallback_meal_break(exception, punches, schedule)
        else:
            return self._escalate(
                exception=exception,
                reason=f"Unknown or unsupported exception type: {exc_type}",
            )

    def _fallback_missed_punch(
        self,
        exception: TimecardException,
        punches: Sequence[Punch],
        schedule: Schedule | None,
    ) -> FallbackResult:
        """Fallback for missed punches."""
        # Check if schedule exists to provide deterministic boundary
        if schedule is None:
            return self._escalate(
                exception=exception,
                reason="Insufficient attendance and schedule information to safely infer missing punch. Escalating to manager.",
            )

        sorted_punches = sorted(punches, key=lambda p: p.timestamp)
        in_punches = [p for p in sorted_punches if p.punch_type == PunchType.IN]
        out_punches = [p for p in sorted_punches if p.punch_type == PunchType.OUT]

        # Case A: Clocked in, missing clock-out
        if in_punches and not out_punches:
            first_in = in_punches[0]
            # Use scheduled end time
            proposed_out = schedule.end_time

            # If proposed shift > 5 hours, include a compliant 30m meal break if not already taken
            proposed_punches: list[ProposedPunch] = []
            gross_hours = (proposed_out - first_in.timestamp).total_seconds() / 3600.0

            has_break = any(
                p.punch_type in (PunchType.BREAK_START, PunchType.BREAK_END) for p in sorted_punches
            )
            if gross_hours >= 5.0 and not has_break:
                # Add 30-min break at shift midpoint
                midpoint = first_in.timestamp + timedelta(hours=gross_hours / 2.0)
                break_start = midpoint.replace(second=0, microsecond=0)
                break_end = break_start + timedelta(minutes=30)
                proposed_punches.append(
                    ProposedPunch(
                        punch_type=PunchType.BREAK_START,
                        timestamp=break_start,
                        action="insert",
                        notes="Fallback: Standard 30m meal break at shift midpoint",
                    )
                )
                proposed_punches.append(
                    ProposedPunch(
                        punch_type=PunchType.BREAK_END,
                        timestamp=break_end,
                        action="insert",
                        notes="Fallback: Standard 30m meal break at shift midpoint",
                    )
                )

            proposed_punches.append(
                ProposedPunch(
                    punch_type=PunchType.OUT,
                    timestamp=proposed_out,
                    action="insert",
                    notes="Fallback: Aligned missing clock-out with scheduled shift end",
                )
            )

            proposal = LLMProposal(
                exception_id=exception.exception_id,
                suggested_action="insert_punch",
                proposed_punches=proposed_punches,
                policy_citations=["PUNCH-01", "MEAL-01"]
                if (gross_hours >= 5.0 and not has_break)
                else ["PUNCH-01"],
                reasoning=(
                    f"Deterministic fallback: Missing clock-out inferred from assigned schedule "
                    f"(end time: {schedule.end_time.strftime('%H:%M')})."
                ),
            )
            return self._validate_and_wrap(exception, punches, schedule, proposal)

        # Case B: Clocked out, missing clock-in
        if out_punches and not in_punches:
            proposed_in = schedule.start_time

            proposed_punches = [
                ProposedPunch(
                    punch_type=PunchType.IN,
                    timestamp=proposed_in,
                    action="insert",
                    notes="Fallback: Aligned missing clock-in with scheduled shift start",
                )
            ]

            proposal = LLMProposal(
                exception_id=exception.exception_id,
                suggested_action="insert_punch",
                proposed_punches=proposed_punches,
                policy_citations=["PUNCH-02"],
                reasoning=(
                    f"Deterministic fallback: Missing clock-in inferred from assigned schedule "
                    f"(start time: {schedule.start_time.strftime('%H:%M')})."
                ),
            )
            return self._validate_and_wrap(exception, punches, schedule, proposal)

        # Incomplete or ambiguous punches without single missing punch
        return self._escalate(
            exception=exception,
            reason="Ambiguous punch sequence cannot be resolved deterministically without human verification.",
        )

    def _fallback_overtime(
        self,
        exception: TimecardException,
        punches: Sequence[Punch],
        schedule: Schedule | None,
    ) -> FallbackResult:
        """Fallback for overtime exception."""
        # Overtime cannot be fabricated or removed arbitrarily; prepare for manager authorization
        proposal = LLMProposal(
            exception_id=exception.exception_id,
            suggested_action="approve_overtime",
            proposed_punches=[],  # Retain existing punches, approve recorded hours
            policy_citations=["OT-01"],
            reasoning="Deterministic fallback: Overtime verified and packaged for manager authorization.",
        )
        return self._validate_and_wrap(exception, punches, schedule, proposal)

    def _fallback_schedule_conflict(
        self,
        exception: TimecardException,
        punches: Sequence[Punch],
        schedule: Schedule | None,
    ) -> FallbackResult:
        """Fallback for schedule conflict (tardiness or early departure)."""
        if schedule is None:
            return self._escalate(
                exception=exception,
                reason="Unscheduled shift conflict cannot be resolved automatically. Escalating to manager.",
            )

        # Propose acknowledging actual attendance with policy reference
        proposal = LLMProposal(
            exception_id=exception.exception_id,
            suggested_action="acknowledge_schedule_deviation",
            proposed_punches=[],
            policy_citations=["SCHED-01"],
            reasoning="Deterministic fallback: Schedule deviation recorded with actual punch times.",
        )
        return self._validate_and_wrap(exception, punches, schedule, proposal)

    def _fallback_meal_break(
        self,
        exception: TimecardException,
        punches: Sequence[Punch],
        schedule: Schedule | None,
    ) -> FallbackResult:
        """Fallback for missing or short meal break."""
        sorted_punches = sorted(punches, key=lambda p: p.timestamp)
        if len(sorted_punches) < 2:
            return self._escalate(
                exception=exception,
                reason="Insufficient punches to place a deterministic meal break. Escalating to manager.",
            )

        first_in = sorted_punches[0]
        last_out = sorted_punches[-1]
        shift_duration_hours = (last_out.timestamp - first_in.timestamp).total_seconds() / 3600.0

        if shift_duration_hours < 5.0:
            return self._escalate(
                exception=exception,
                reason="Shift is under 5 hours; meal break not required. Escalating to manager.",
            )

        # Insert 30-min break at shift midpoint
        midpoint = first_in.timestamp + timedelta(hours=shift_duration_hours / 2.0)
        break_start = midpoint.replace(second=0, microsecond=0)
        break_end = break_start + timedelta(minutes=30)

        proposal = LLMProposal(
            exception_id=exception.exception_id,
            suggested_action="insert_meal_break",
            proposed_punches=[
                ProposedPunch(
                    punch_type=PunchType.BREAK_START,
                    timestamp=break_start,
                    action="insert",
                    notes="Fallback: 30m meal break inserted at midpoint",
                ),
                ProposedPunch(
                    punch_type=PunchType.BREAK_END,
                    timestamp=break_end,
                    action="insert",
                    notes="Fallback: 30m meal break inserted at midpoint",
                ),
            ],
            policy_citations=["MEAL-01"],
            reasoning="Deterministic fallback: Inserted standard 30-minute meal break at shift midpoint.",
        )
        return self._validate_and_wrap(exception, punches, schedule, proposal)

    def _validate_and_wrap(
        self,
        exception: TimecardException,
        punches: Sequence[Punch],
        schedule: Schedule | None,
        proposal: LLMProposal,
    ) -> FallbackResult:
        """Validate fallback proposal using ProposalValidator."""
        val_result = self.validator.validate(
            original_punches=punches,
            proposal_input=proposal,
            original_schedule=schedule,
            original_exception=exception,
        )

        if val_result.valid:
            return FallbackResult(
                success=True,
                exception_id=exception.exception_id,
                proposed_correction=proposal.model_dump(mode="json"),
                reason="Deterministic rule-based fallback successfully generated and validated.",
                validation_result=val_result,
                requires_manager_review=True,
            )
        else:
            return FallbackResult(
                success=False,
                exception_id=exception.exception_id,
                proposed_correction=None,
                reason=f"Deterministic fallback proposal failed validation: {val_result.explanation}. Escalating to manager.",
                validation_result=val_result,
                requires_manager_review=True,
            )

    def _escalate(self, exception: TimecardException, reason: str) -> FallbackResult:
        """Escalate directly to manager with no automated modification."""
        return FallbackResult(
            success=False,
            exception_id=exception.exception_id,
            proposed_correction=None,
            reason=reason,
            validation_result=None,
            requires_manager_review=True,
        )
