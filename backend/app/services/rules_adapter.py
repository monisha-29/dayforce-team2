"""Rules adapter and compatibility bridge for Person 3's rules and validation module.

Bridges the contract differences between Person 3's module and the backend/frontend:
1. Proposal representation: Translates between consolidated Timecard objects and
   Person 3's LLMProposal / ProposedPunch operations.
2. Validation result representation: Translates Person 3's ValidationResult
   (validation_checks dict & check_details) to Person 1's list[ValidatorResult].
3. New violation detection: Implements multi-detector violation verification
   (overtime, meal break, early departure, shift caps).
4. Fallback alignment: Escalates missed-punch fallbacks for shifts >= 5.0h
   without recorded meal breaks (never fabricates break punches).
5. Dynamic delegation: When app.rules is available, delegates directly to Person 3's
   ProposalValidator and FallbackEngine.

Core Principle: "The LLM suggests. Code decides. A human approves."
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.proposal import ValidatorName, ValidatorResult
from app.services.policy_service import policy_service

# Dynamic import boundary for Person 3's rules module
try:
    from app.rules import (  # noqa: I001
        FallbackEngine as Person3FallbackEngine,
        HoursCalculator as Person3HoursCalculator,
        ProposalValidator as Person3ProposalValidator,
        RulesConfig as Person3RulesConfig,
        detect_all_exceptions as person3_detect_all_exceptions,
        detect_shift_exceptions as person3_detect_shift_exceptions,
    )
    from app.rules.models.exception import (
        ExceptionType as Person3ExceptionType,
        Punch as Person3Punch,
        PunchType as Person3PunchType,
        Schedule as Person3Schedule,
        Severity as Person3Severity,
        TimecardException as Person3TimecardException,
    )
    from app.rules.models.proposal import (
        LLMProposal as Person3LLMProposal,
        ProposedPunch as Person3ProposedPunch,
    )
    from app.rules.models.validation import (
        FallbackResult as Person3FallbackResult,
        ValidationCheckDetail as Person3ValidationCheckDetail,
        ValidationErrorItem as Person3ValidationErrorItem,
        ValidationResult as Person3ValidationResult,
    )
    from app.rules.policy_loader import (
        policy_registry as person3_policy_registry,
    )

    RULES_MODULE_AVAILABLE = True
except ImportError:
    Person3FallbackEngine = None  # type: ignore[assignment, misc]
    Person3HoursCalculator = None  # type: ignore[assignment, misc]
    Person3ProposalValidator = None  # type: ignore[assignment, misc]
    Person3RulesConfig = None  # type: ignore[assignment, misc]
    person3_detect_all_exceptions = None  # type: ignore[assignment]
    person3_detect_shift_exceptions = None  # type: ignore[assignment]
    Person3ExceptionType = None  # type: ignore[assignment, misc]
    Person3Punch = None  # type: ignore[assignment, misc]
    Person3PunchType = None  # type: ignore[assignment, misc]
    Person3Schedule = None  # type: ignore[assignment, misc]
    Person3Severity = None  # type: ignore[assignment, misc]
    Person3TimecardException = None  # type: ignore[assignment, misc]
    Person3LLMProposal = None  # type: ignore[assignment, misc]
    Person3ProposedPunch = None  # type: ignore[assignment, misc]
    Person3FallbackResult = None  # type: ignore[assignment, misc]
    Person3ValidationCheckDetail = None  # type: ignore[assignment, misc]
    Person3ValidationErrorItem = None  # type: ignore[assignment, misc]
    Person3ValidationResult = None  # type: ignore[assignment, misc]
    person3_policy_registry = None  # type: ignore[assignment]
    RULES_MODULE_AVAILABLE = False


# Prompt injection detection patterns matching Person 3's validator
INJECTION_PATTERNS = [
    re.compile(r"ignore\s+(all\s+)?(previous\s+)?instructions", re.IGNORECASE),
    re.compile(r"override\s+(all\s+)?policy", re.IGNORECASE),
    re.compile(r"bypass\s+validation", re.IGNORECASE),
    re.compile(r"system\s+prompt", re.IGNORECASE),
    re.compile(r"grant\s+(24|99)\s+hours", re.IGNORECASE),
    re.compile(r"admin\s+mode", re.IGNORECASE),
]

TIME_REGEX = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")

# Mapping from Person 3's 5 validation check keys to frontend ValidatorName labels
CHECK_NAME_MAP: dict[str, str] = {
    "format_valid": ValidatorName.SCHEMA_VALIDATION.value,
    "policy_clauses_valid": ValidatorName.POLICY_CITATION_VALIDATION.value,
    "working_hours_valid": ValidatorName.WORKING_HOURS_VALIDATION.value,
    "no_new_violations": ValidatorName.NEW_VIOLATION_CHECK.value,
    "limits_valid": ValidatorName.VALUE_BOUNDS_CHECK.value,
}


# Standalone compatible models matching Person 3's contracts when unmerged
class CompatiblePunchType(str, Enum):
    IN = "IN"
    OUT = "OUT"
    BREAK_START = "BREAK_START"
    BREAK_END = "BREAK_END"


class CompatibleProposedPunch(BaseModel):
    punch_type: str
    timestamp: datetime
    action: str = "insert"
    employee_id: str | None = None
    notes: str | None = None


class CompatibleLLMProposal(BaseModel):
    proposal_id: str | None = None
    exception_id: str
    suggested_action: str
    proposed_punches: list[CompatibleProposedPunch] = Field(default_factory=list)
    policy_citations: list[str] = Field(default_factory=list)
    reasoning: str
    raw_llm_hours: float | None = None


@dataclass
class ValidationSummary:
    valid: bool
    status: str
    recalculated_hours: float | None
    validators: list[ValidatorResult]
    blocked: bool
    explanation: str
    errors: list[str]


def parse_time_str(time_str: str | None) -> tuple[int, int] | None:
    """Parse 'HH:MM' string to (hours, minutes)."""
    if not time_str or not TIME_REGEX.match(time_str.strip()):
        return None
    parts = time_str.strip().split(":")
    return int(parts[0]), int(parts[1])


def compute_net_hours(
    check_in: str | None,
    check_out: str | None,
    meal_start: str | None = None,
    meal_end: str | None = None,
) -> float | None:
    """Deterministically recalculate net working hours in Python."""
    t_in = parse_time_str(check_in)
    t_out = parse_time_str(check_out)

    if t_in is None or t_out is None:
        return None

    in_mins = t_in[0] * 60 + t_in[1]
    out_mins = t_out[0] * 60 + t_out[1]

    # Handle overnight shifts
    if out_mins < in_mins:
        out_mins += 24 * 60

    gross_mins = out_mins - in_mins

    # Deduct meal break if recorded
    meal_mins = 0
    t_mstart = parse_time_str(meal_start)
    t_mend = parse_time_str(meal_end)
    if t_mstart is not None and t_mend is not None:
        ms = t_mstart[0] * 60 + t_mstart[1]
        me = t_mend[0] * 60 + t_mend[1]
        if me < ms:
            me += 24 * 60
        meal_mins = max(0, me - ms)

    net_mins = max(0, gross_mins - meal_mins)
    return round(net_mins / 60.0, 2)


def to_detector_exception(exc: Any) -> Any:
    """Convert an SQLAlchemy ExceptionModel or dict into Person 3's TimecardException."""
    if exc is None:
        return None
    if hasattr(exc, "exception_type") and isinstance(getattr(exc, "exception_type", None), Enum):
        return exc
    if (
        RULES_MODULE_AVAILABLE
        and Person3TimecardException is not None
        and Person3ExceptionType is not None
    ):
        raw_type = getattr(exc, "type", getattr(exc, "exception_type", "missed_punch"))
        type_str = str(getattr(raw_type, "value", raw_type)).strip().lower()
        try:
            exc_type = Person3ExceptionType(type_str)
        except (ValueError, KeyError):
            exc_type = Person3ExceptionType.MISSED_PUNCH

        raw_sev = getattr(exc, "severity", "medium")
        sev_str = str(getattr(raw_sev, "value", raw_sev)).strip().lower()
        try:
            severity = Person3Severity(sev_str) if Person3Severity else "medium"  # type: ignore[truthy-function]
        except (ValueError, KeyError):
            severity = Person3Severity.MEDIUM if Person3Severity else "medium"  # type: ignore[truthy-function]

        raw_date = getattr(exc, "date", datetime.now().date().isoformat())
        if isinstance(raw_date, datetime):
            date_str = raw_date.date().isoformat()
        else:
            date_str = str(raw_date)

        raw_att = getattr(exc, "original_attendance", {})
        att_dict = raw_att if isinstance(raw_att, dict) else {}

        return Person3TimecardException(
            exception_id=str(getattr(exc, "id", getattr(exc, "exception_id", "EXC-000"))),
            employee_id=str(getattr(exc, "employee_id", "EMP001")),
            exception_type=exc_type,
            date=date_str,
            severity=severity,
            description=str(getattr(exc, "description", "")),
            original_attendance=att_dict,
            policy_reference=str(getattr(exc, "policy_reference", "")),
            status=str(getattr(exc, "status", "pending_review")),
        )
    return exc


# =====================================================================
# CONTRACT TRANSLATION BRIDGES
# =====================================================================


def timecard_to_llm_proposal(
    exception_id: str,
    proposed_tc: dict[str, Any],
    changed_fields: list[str],
    policy_id: str,
    reasoning: str,
    shift_date: str,
    employee_id: str | None = None,
    suggested_action: str = "correct_timecard",
    original_punches: Sequence[Any] | None = None,
) -> Any:
    """Translate frontend Timecard dictionary to Person 3's LLMProposal model.

    Constructs discrete ProposedPunch operations for each changed attendance boundary.
    """
    punch_cls = Person3ProposedPunch if RULES_MODULE_AVAILABLE else CompatibleProposedPunch
    proposal_cls = Person3LLMProposal if RULES_MODULE_AVAILABLE else CompatibleLLMProposal

    # Index existing punch types in original_punches to distinguish insert vs modify
    existing_punch_types: set[str] = set()
    if original_punches:
        for p in original_punches:
            pt = getattr(p, "punch_type", None)
            pt_str = str(getattr(pt, "value", pt)).upper()
            existing_punch_types.add(pt_str)

    base_date = datetime.fromisoformat(shift_date).date()
    check_in = proposed_tc.get("checkIn") or proposed_tc.get("check_in")
    check_out = proposed_tc.get("checkOut") or proposed_tc.get("check_out")
    meal_start = proposed_tc.get("mealStart") or proposed_tc.get("meal_start")
    meal_end = proposed_tc.get("mealEnd") or proposed_tc.get("meal_end")

    t_in = parse_time_str(str(check_in) if check_in else None)
    in_m = t_in[0] * 60 + t_in[1] if t_in else None

    def _get_punch_dt(time_val: str, punch_type: str) -> datetime:
        t_parsed = parse_time_str(time_val)
        if not t_parsed:
            return datetime.fromisoformat(f"{shift_date}T{time_val.strip()}:00")
        val_m = t_parsed[0] * 60 + t_parsed[1]
        is_next_day = in_m is not None and punch_type != "IN" and val_m < in_m
        p_date = base_date + timedelta(days=1) if is_next_day else base_date
        return datetime(p_date.year, p_date.month, p_date.day, t_parsed[0], t_parsed[1], 0)

    punches: list[Any] = []

    if check_in and ("checkIn" in changed_fields or "check_in" in changed_fields):
        dt = _get_punch_dt(str(check_in).strip(), "IN")
        action = "modify" if "IN" in existing_punch_types else "insert"
        punches.append(
            punch_cls(
                punch_type="IN",  # type: ignore[arg-type]  # normalised by the model validator
                timestamp=dt,
                action=action,
                employee_id=employee_id,
                notes="Proposed shift clock-in",
            )
        )

    if check_out and ("checkOut" in changed_fields or "check_out" in changed_fields):
        dt = _get_punch_dt(str(check_out).strip(), "OUT")
        action = "modify" if "OUT" in existing_punch_types else "insert"
        punches.append(
            punch_cls(
                punch_type="OUT",  # type: ignore[arg-type]  # normalised by the model validator
                timestamp=dt,
                action=action,
                employee_id=employee_id,
                notes="Proposed shift clock-out",
            )
        )

    if meal_start and ("mealStart" in changed_fields or "meal_start" in changed_fields):
        dt = _get_punch_dt(str(meal_start).strip(), "BREAK_START")
        action = "modify" if "BREAK_START" in existing_punch_types else "insert"
        punches.append(
            punch_cls(
                punch_type="BREAK_START",  # type: ignore[arg-type]  # normalised by the model validator
                timestamp=dt,
                action=action,
                employee_id=employee_id,
                notes="Proposed meal break start",
            )
        )

    if meal_end and ("mealEnd" in changed_fields or "meal_end" in changed_fields):
        dt = _get_punch_dt(str(meal_end).strip(), "BREAK_END")
        action = "modify" if "BREAK_END" in existing_punch_types else "insert"
        punches.append(
            punch_cls(
                punch_type="BREAK_END",  # type: ignore[arg-type]  # normalised by the model validator
                timestamp=dt,
                action=action,
                employee_id=employee_id,
                notes="Proposed meal break end",
            )
        )

    return proposal_cls(
        exception_id=exception_id,
        suggested_action=suggested_action,
        proposed_punches=punches,
        policy_citations=[policy_id] if policy_id else [],
        reasoning=reasoning,
    )


def llm_proposal_to_timecard(
    proposal: Any,
    original_timecard: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """Translate Person 3's LLMProposal model into frontend consolidated Timecard dictionary.

    Returns (timecard_dict, changed_fields).
    """
    tc: dict[str, Any] = dict(original_timecard or {})
    changed_fields: list[str] = []

    punches = getattr(proposal, "proposed_punches", [])
    if isinstance(proposal, dict):
        punches = proposal.get("proposed_punches", [])

    for p in punches:
        if isinstance(p, dict):
            pt = p.get("punch_type")
            ts = p.get("timestamp")
        else:
            pt = getattr(p, "punch_type", None)
            ts = getattr(p, "timestamp", None)

        pt_str = str(getattr(pt, "value", pt)).upper()
        if isinstance(ts, str):
            time_str = ts.split("T")[-1][:5]
        elif isinstance(ts, datetime):
            time_str = ts.strftime("%H:%M")
        else:
            continue

        if pt_str == "IN":
            tc["checkIn"] = time_str
            if "checkIn" not in changed_fields:
                changed_fields.append("checkIn")
        elif pt_str == "OUT":
            tc["checkOut"] = time_str
            if "checkOut" not in changed_fields:
                changed_fields.append("checkOut")
        elif pt_str in ("BREAK_START", "MEAL_START"):
            tc["mealStart"] = time_str
            if "mealStart" not in changed_fields:
                changed_fields.append("mealStart")
        elif pt_str in ("BREAK_END", "MEAL_END"):
            tc["mealEnd"] = time_str
            if "mealEnd" not in changed_fields:
                changed_fields.append("mealEnd")

    hours = compute_net_hours(
        tc.get("checkIn"),
        tc.get("checkOut"),
        tc.get("mealStart"),
        tc.get("mealEnd"),
    )
    tc["totalHours"] = round(hours, 2) if hours is not None else None
    return tc, changed_fields


def validation_result_to_validator_results(validation_res: Any) -> list[ValidatorResult]:
    """Convert Person 3's ValidationResult object into Person 1's list[ValidatorResult].

    Maps the 5 check keys to user-facing display names and pairs them with specific error messages.
    """
    check_map = getattr(validation_res, "validation_checks", {})
    check_details = getattr(validation_res, "check_details", [])
    errors = getattr(validation_res, "errors", [])

    # Extract messages by check_name
    detail_messages: dict[str, str] = {}
    for cd in check_details:
        cname = getattr(cd, "check_name", "")
        cmsg = getattr(cd, "message", "")
        if cname and cmsg:
            detail_messages[cname] = cmsg

    results: list[ValidatorResult] = []
    standard_order = [
        "format_valid",
        "policy_clauses_valid",
        "working_hours_valid",
        "no_new_violations",
        "limits_valid",
    ]

    for key in standard_order:
        passed = bool(check_map.get(key, False))
        display_name = CHECK_NAME_MAP.get(key, key)
        reason = detail_messages.get(key)

        if not passed and not reason and errors:
            # Pick first relevant error message if detail message is missing
            reason = str(getattr(errors[0], "message", errors[0]))

        if not reason:
            reason = f"{display_name} {'passed' if passed else 'failed'}."

        results.append(
            ValidatorResult(
                name=display_name,
                passed=passed,
                reason=reason,
            )
        )

    return results


# =====================================================================
# VALIDATION & FALLBACK IMPLEMENTATION
# =====================================================================

# Why a fallback proposal can legitimately leave the times as recorded
NO_CHANGE_EXPLANATION: dict[str, str] = {
    "overtime": (
        "The hours were actually worked, so none are removed or invented; overtime needs manager "
        "authorization (OT-01)."
    ),
    "schedule_conflict": (
        "Punches are recorded as they happened; the manager decides how the deviation from the "
        "schedule is treated (SCHED-01)."
    ),
    "duplicate_punch": (
        "The repeat tap adds no time; the first punch is kept and the manager confirms removing "
        "the duplicate (DUP-01)."
    ),
    "rest_period": (
        "Punch times cannot create the missing rest; the manager documents the reason, such as a "
        "schedule change or a voluntary swap (REST-01)."
    ),
    "consecutive_days": (
        "The days were worked and are not altered; the manager authorizes the long streak or "
        "corrects the schedule (CONSEC-01)."
    ),
}
NO_TIME_CHANGE_TYPES = frozenset({"duplicate_punch", "rest_period", "consecutive_days"})


def validate_timecard_proposal(
    proposed_tc: dict[str, Any],
    cited_clause_id: str,
    reasoning: str,
    original_type: str,
    schedule_start: str | None = None,
    schedule_end: str | None = None,
    original_punches: Sequence[Any] | None = None,
    original_schedule: Any | None = None,
    original_exception: Any | None = None,
    changed_fields: list[str] | None = None,
    suggested_action: str | None = None,
) -> ValidationSummary:
    """Execute the 5 deterministic safety checks.

    When Person 3's module is merged, delegates to Person 3's ProposalValidator.
    Otherwise, runs the exact 5 deterministic checks with multi-violation verification.
    """
    # Resolve or infer changed fields
    resolved_changed_fields: list[str]
    if changed_fields is not None:
        resolved_changed_fields = list(changed_fields)
    else:
        resolved_changed_fields = []
        orig_att = getattr(original_exception, "original_attendance", {}) or {}
        if not isinstance(orig_att, dict):
            orig_att = {}
        for field_name in ("checkIn", "checkOut", "mealStart", "mealEnd"):
            val = proposed_tc.get(field_name)
            orig_val = orig_att.get(field_name)
            if val is not None and val != orig_val:
                resolved_changed_fields.append(field_name)
        if not resolved_changed_fields:
            resolved_changed_fields = list(proposed_tc.keys())

    # -------------------------------------------------------------
    # IF PERSON 3 MODULE AVAILABLE: DELEGATE DIRECTLY
    # -------------------------------------------------------------
    if RULES_MODULE_AVAILABLE and Person3ProposalValidator is not None:
        validator = Person3ProposalValidator()
        exc_id = getattr(original_exception, "exception_id", "") or getattr(
            original_exception, "id", "EXC-000"
        )
        target_emp_id = (
            getattr(original_exception, "employee_id", None)
            or getattr(original_schedule, "employee_id", None)
            or (original_punches[0].employee_id if original_punches else "EMP001")
        )
        shift_date = (
            getattr(original_schedule, "date", "")
            or getattr(original_exception, "date", "")
            or (
                original_punches[0].timestamp.date().isoformat()
                if original_punches
                else datetime.now().date().isoformat()
            )
        )

        from app.services.detector_service import to_detector_punch, to_detector_schedule

        p3_exception = to_detector_exception(original_exception) if original_exception else None
        p3_punches = [to_detector_punch(p) for p in (original_punches or [])]
        p3_schedule = to_detector_schedule(original_schedule) if original_schedule else None

        # Derive suggested action matching Person 3's validator requirements:
        # - Overtime: "approve_overtime" (required if net hours > daily limit or citing OT-01)
        # - Schedule conflict: "acknowledge_schedule_deviation" (required to acknowledge deviation)
        # - Missed punch: "insert_punch"
        # - Default: "correct_timecard"
        derived_action: str
        if suggested_action:
            derived_action = suggested_action
        else:
            orig_t = original_type or getattr(original_exception, "type", "")
            if hasattr(orig_t, "value"):
                orig_t = orig_t.value
            orig_t_lower = str(orig_t).lower()

            if "overtime" in orig_t_lower or (cited_clause_id and "ot" in cited_clause_id.lower()):
                derived_action = "approve_overtime"
            elif "conflict" in orig_t_lower or "schedule" in orig_t_lower:
                derived_action = "acknowledge_schedule_deviation"
            elif "miss" in orig_t_lower:
                derived_action = "insert_punch"
            else:
                derived_action = "correct_timecard"

        # Construct LLMProposal payload
        llm_prop = timecard_to_llm_proposal(
            exception_id=exc_id,
            proposed_tc=proposed_tc,
            changed_fields=resolved_changed_fields,
            policy_id=cited_clause_id,
            reasoning=reasoning,
            shift_date=shift_date,
            employee_id=target_emp_id,
            suggested_action=derived_action,
            original_punches=p3_punches,
        )

        p3_result = validator.validate(
            original_punches=p3_punches,
            proposal_input=llm_prop,
            original_schedule=p3_schedule,
            original_exception=p3_exception,
        )

        val_results = validation_result_to_validator_results(p3_result)
        err_msgs = [getattr(e, "message", str(e)) for e in p3_result.errors]

        return ValidationSummary(
            valid=p3_result.valid,
            status=p3_result.status,
            recalculated_hours=p3_result.validated_working_hours,
            validators=val_results,
            blocked=not p3_result.valid,
            explanation=p3_result.explanation,
            errors=err_msgs,
        )

    # -------------------------------------------------------------
    # UNMERGED STANDALONE EXECUTION: 5 DETERMINISTIC CHECKS
    # -------------------------------------------------------------
    errors: list[str] = []
    validators: list[ValidatorResult] = []

    # 1. Format and Schema Validation
    check_in = proposed_tc.get("checkIn") or proposed_tc.get("check_in")
    check_out = proposed_tc.get("checkOut") or proposed_tc.get("check_out")
    meal_start = proposed_tc.get("mealStart") or proposed_tc.get("meal_start")
    meal_end = proposed_tc.get("mealEnd") or proposed_tc.get("meal_end")

    format_passed = True
    format_reason = "All timecard fields conform to HH:MM schema."
    if check_in and not TIME_REGEX.match(str(check_in).strip()):
        format_passed = False
        format_reason = f"Invalid check_in format: '{check_in}'."
        errors.append(format_reason)
    if check_out and not TIME_REGEX.match(str(check_out).strip()):
        format_passed = False
        format_reason = f"Invalid check_out format: '{check_out}'."
        errors.append(format_reason)
    if meal_start and not TIME_REGEX.match(str(meal_start).strip()):
        format_passed = False
        format_reason = f"Invalid meal_start format: '{meal_start}'."
        errors.append(format_reason)
    if meal_end and not TIME_REGEX.match(str(meal_end).strip()):
        format_passed = False
        format_reason = f"Invalid meal_end format: '{meal_end}'."
        errors.append(format_reason)

    validators.append(
        ValidatorResult(
            name=ValidatorName.SCHEMA_VALIDATION.value,
            passed=format_passed,
            reason=format_reason,
        )
    )

    # 2. Policy Citation Validation
    cited_clean = cited_clause_id.strip()
    policy_exists = cited_clean in policy_service.clauses
    validators.append(
        ValidatorResult(
            name=ValidatorName.POLICY_CITATION_VALIDATION.value,
            passed=policy_exists,
            reason="Policy clause exists in active registry."
            if policy_exists
            else f"Cited policy clause '{cited_clean}' not found in registry.",
        )
    )
    if not policy_exists:
        errors.append(f"Invalid policy citation: {cited_clean}")

    # 3. Working Hours Recalculation (Python math, LLM math never trusted)
    recalculated_hours = compute_net_hours(
        str(check_in) if check_in else None,
        str(check_out) if check_out else None,
        str(meal_start) if meal_start else None,
        str(meal_end) if meal_end else None,
    )
    hours_valid = recalculated_hours is not None and recalculated_hours >= 0.0
    validators.append(
        ValidatorResult(
            name=ValidatorName.WORKING_HOURS_VALIDATION.value,
            passed=hours_valid,
            reason=f"Recalculated working hours: {recalculated_hours:.2f}h."
            if hours_valid
            else "Cannot calculate net hours from proposed times.",
        )
    )
    if not hours_valid:
        errors.append("Invalid or missing working hours calculation.")

    # 4. New Violation Check (Multi-detector violation verification)
    new_violation_errors: list[str] = []

    # 4a. Excessive single shift duration (> 16h cap)
    if recalculated_hours is not None and recalculated_hours > 16.0:
        new_violation_errors.append(
            f"Excessive shift duration: {recalculated_hours:.2f}h exceeds 16h safety cap."
        )

    # 4b. Overtime violation check (> 8.0h daily limit unless resolving overtime)
    is_overtime_case = "overtime" in original_type.lower() or "OT-01" in cited_clean
    if recalculated_hours is not None and recalculated_hours > 8.0 and not is_overtime_case:
        new_violation_errors.append(
            f"Proposed shift introduces unauthorized daily overtime ({recalculated_hours:.2f}h exceeds 8.0h limit)."
        )

    # 4c. Mandatory meal break violation (shift gross hours >= 5.0h with no meal break recorded)
    gross_hours = None
    t_in = parse_time_str(str(check_in) if check_in else None)
    t_out = parse_time_str(str(check_out) if check_out else None)
    if t_in and t_out:
        in_m = t_in[0] * 60 + t_in[1]
        out_m = t_out[0] * 60 + t_out[1]
        if out_m < in_m:
            out_m += 24 * 60
        gross_hours = (out_m - in_m) / 60.0

    is_meal_case = "meal" in original_type.lower() or "MEAL" in cited_clean
    if gross_hours is not None and gross_hours >= 5.0 and not meal_start and not is_meal_case:
        new_violation_errors.append(
            f"Proposed correction creates a {gross_hours:.2f}h shift without a 30-minute meal break, introducing a meal break violation."
        )

    # 4d. Schedule conflict (early exit deviation)
    if schedule_end and check_out:
        t_sched_end = parse_time_str(schedule_end)
        t_actual_out = parse_time_str(str(check_out))
        if t_sched_end and t_actual_out:
            sched_end_m = t_sched_end[0] * 60 + t_sched_end[1]
            actual_out_m = t_actual_out[0] * 60 + t_actual_out[1]
            early_mins = sched_end_m - actual_out_m
            if (
                early_mins > 5
                and "sched" not in original_type.lower()
                and "conflict" not in original_type.lower()
            ):
                new_violation_errors.append(
                    f"Proposed check-out at {check_out} introduces an early departure violation ({early_mins}m before scheduled {schedule_end})."
                )

    no_new_violation = len(new_violation_errors) == 0
    new_violation_reason = (
        "No new timecard exceptions detected."
        if no_new_violation
        else f"Proposed correction introduces new violation: {new_violation_errors[0]}"
    )
    if not no_new_violation:
        errors.extend(new_violation_errors)

    validators.append(
        ValidatorResult(
            name=ValidatorName.NEW_VIOLATION_CHECK.value,
            passed=no_new_violation,
            reason=new_violation_reason,
        )
    )

    # 5. Value Bounds and Prompt Injection Defense
    injection_detected = any(pattern.search(reasoning) for pattern in INJECTION_PATTERNS)
    limits_passed = not injection_detected
    limits_reason = (
        "Security check passed."
        if not injection_detected
        else "Suspicious instructions or prompt injection pattern detected in proposal reasoning."
    )
    if injection_detected:
        errors.append(limits_reason)

    validators.append(
        ValidatorResult(
            name=ValidatorName.VALUE_BOUNDS_CHECK.value,
            passed=limits_passed,
            reason=limits_reason,
        )
    )

    all_passed = len(errors) == 0 and all(v.passed for v in validators)
    blocked = not all_passed

    if all_passed:
        explanation = (
            f"Proposal PASSED all 5 validation checks. "
            f"Net hours: {recalculated_hours:.2f}h. Ready for manager review."
        )
    else:
        explanation = (
            f"Proposal FAILED validation checks: {errors[0] if errors else 'Unspecified error'}. "
            f"Blocked from approval."
        )

    return ValidationSummary(
        valid=all_passed,
        status="PASSED" if all_passed else "FAILED",
        recalculated_hours=recalculated_hours,
        validators=validators,
        blocked=blocked,
        explanation=explanation,
        errors=errors,
    )


def generate_fallback_proposal(
    exception_type: str,
    original_attendance: dict[str, Any],
    schedule_start: str | None,
    schedule_end: str | None,
    policy_clause_id: str,
    original_exception: Any | None = None,
    original_punches: Sequence[Any] | None = None,
    original_schedule: Any | None = None,
) -> dict[str, Any]:
    """Execute deterministic fallback logic aligned with Person 3's 5.0h boundary rule.

    Safety principles:
    - Missed punch: If shift gross duration >= 5.0h without recorded breaks, code cannot
      safely infer clock-out without fabricating break punches; ESCALATES to manager.
    - Meal break: Never fabricates employee break punches; ESCALATES to manager.
    - Overtime: Packages recorded hours for manager authorization.
    - Schedule conflict: Acknowledges actual punches with schedule reference.
    """
    # -------------------------------------------------------------
    # IF PERSON 3 MODULE AVAILABLE: DELEGATE DIRECTLY
    # -------------------------------------------------------------
    if (
        RULES_MODULE_AVAILABLE
        and Person3FallbackEngine is not None
        and original_exception is not None
    ):
        from app.services.detector_service import to_detector_punch, to_detector_schedule

        p3_exc = to_detector_exception(original_exception)
        p3_punches = [to_detector_punch(p) for p in (original_punches or [])]
        p3_sched = to_detector_schedule(original_schedule) if original_schedule else None

        engine = Person3FallbackEngine()
        fallback_res = engine.generate_fallback(p3_exc, p3_punches, p3_sched)

        if fallback_res.success and fallback_res.proposed_correction:
            proposed_tc, changed = llm_proposal_to_timecard(
                proposal=fallback_res.proposed_correction,
                original_timecard=original_attendance,
            )
            if not changed:
                return {
                    "proposed_timecard": proposed_tc,
                    "changed_fields": [],
                    "reason": (
                        "No time change is proposed. "
                        + NO_CHANGE_EXPLANATION.get(
                            exception_type.strip().lower(),
                            "The recorded punches stand and this exception needs a manager decision.",
                        )
                    ),
                    "recommendation": (
                        "Review the exception. Approve to acknowledge it with the recorded times "
                        "unchanged, or reject with a reason."
                    ),
                    "confidence": 0.85,
                    "missing_information": [],
                    "blocked": False,
                }
            return {
                "proposed_timecard": proposed_tc,
                "changed_fields": changed,
                "reason": fallback_res.reason,
                "recommendation": "Review deterministic fallback proposal aligned with policy rules.",
                "confidence": 0.85,
                "missing_information": [],
                "blocked": False,
            }
        elif exception_type.strip().lower() in NO_TIME_CHANGE_TYPES:
            # Punch times cannot fix these, so "keep the record as is" is the proposal.
            return {
                "proposed_timecard": dict(original_attendance),
                "changed_fields": [],
                "reason": "No time change is proposed. "
                + NO_CHANGE_EXPLANATION[exception_type.strip().lower()],
                "recommendation": (
                    "Review the exception. Approve to acknowledge it with the recorded times "
                    "unchanged, or reject with a reason."
                ),
                "confidence": 0.85,
                "missing_information": [],
                "blocked": False,
            }
        else:
            return {
                "proposed_timecard": dict(original_attendance),
                "changed_fields": [],
                "reason": fallback_res.reason,
                "recommendation": "Escalate to manager for manual review and punch adjustment.",
                "confidence": 0.50,
                "missing_information": ["Manual verification required"],
                "blocked": True,
            }

    clean_type = exception_type.strip().lower()
    check_in = original_attendance.get("checkIn") or original_attendance.get("check_in")
    check_out = original_attendance.get("checkOut") or original_attendance.get("check_out")
    meal_start = original_attendance.get("mealStart") or original_attendance.get("meal_start")
    meal_end = original_attendance.get("mealEnd") or original_attendance.get("meal_end")

    if "miss" in clean_type:
        # Case A: Clocked in, missing clock-out
        if check_in and not check_out and schedule_end:
            gross_hours = compute_net_hours(str(check_in), schedule_end)

            # Person 3 Safety Rule: Shift >= 5.0h threshold without recorded break MUST escalate
            if gross_hours is not None and gross_hours >= 5.0 and not meal_start:
                return {
                    "proposed_timecard": {
                        "checkIn": str(check_in),
                        "checkOut": None,
                        "mealStart": None,
                        "mealEnd": None,
                        "totalHours": None,
                    },
                    "changed_fields": [],
                    "reason": (
                        "Cannot safely infer missing clock-out for shifts exceeding 5.0h "
                        "without fabricating unrecorded meal break punches. "
                        "Actual attendance and break status must be verified by manager."
                    ),
                    "recommendation": "Escalate to manager to verify actual punch times and meal break status.",
                    "confidence": 0.50,
                    "missing_information": ["Actual departure time", "Meal break verification"],
                    "blocked": True,
                }
            else:
                hours = compute_net_hours(str(check_in), schedule_end, meal_start, meal_end)
                return {
                    "proposed_timecard": {
                        "checkIn": str(check_in),
                        "checkOut": schedule_end,
                        "mealStart": meal_start,
                        "mealEnd": meal_end,
                        "totalHours": hours,
                    },
                    "changed_fields": ["checkOut", "totalHours"],
                    "reason": f"Deterministic fallback: Missing clock-out inferred from assigned shift end ({schedule_end}).",
                    "recommendation": f"Approve clock-out time of {schedule_end} aligned with scheduled shift.",
                    "confidence": 0.85,
                    "missing_information": [],
                    "blocked": False,
                }

        # Case B: Clocked out, missing clock-in
        if check_out and not check_in and schedule_start:
            hours = compute_net_hours(schedule_start, str(check_out), meal_start, meal_end)
            return {
                "proposed_timecard": {
                    "checkIn": schedule_start,
                    "checkOut": str(check_out),
                    "mealStart": meal_start,
                    "mealEnd": meal_end,
                    "totalHours": hours,
                },
                "changed_fields": ["checkIn", "totalHours"],
                "reason": f"Deterministic fallback: Missing clock-in inferred from assigned shift start ({schedule_start}).",
                "recommendation": f"Approve clock-in time of {schedule_start} aligned with scheduled shift.",
                "confidence": 0.85,
                "missing_information": [],
                "blocked": False,
            }

        return {
            "proposed_timecard": {
                "checkIn": check_in,
                "checkOut": check_out,
                "mealStart": meal_start,
                "mealEnd": meal_end,
                "totalHours": None,
            },
            "changed_fields": [],
            "reason": "Insufficient attendance data to deterministically resolve missing punch without human input.",
            "recommendation": "Escalate to manager for manual punch entry.",
            "confidence": 0.40,
            "missing_information": ["Missing punch timestamp"],
            "blocked": True,
        }

    elif "overtime" in clean_type:
        hours = compute_net_hours(check_in, check_out, meal_start, meal_end)
        return {
            "proposed_timecard": {
                "checkIn": check_in,
                "checkOut": check_out,
                "mealStart": meal_start,
                "mealEnd": meal_end,
                "totalHours": hours,
            },
            "changed_fields": [],
            "reason": f"Deterministic fallback: Overtime hours ({hours}h) verified against punch records for manager authorization.",
            "recommendation": "Authorize recorded overtime hours or adjust based on approved overtime policy.",
            "confidence": 0.90,
            "missing_information": [],
            "blocked": False,
        }

    elif "meal" in clean_type:
        # Mandatory safety rule: Never fabricate meal break punches
        hours = compute_net_hours(check_in, check_out)
        return {
            "proposed_timecard": {
                "checkIn": check_in,
                "checkOut": check_out,
                "mealStart": meal_start,
                "mealEnd": meal_end,
                "totalHours": hours,
            },
            "changed_fields": [],
            "reason": (
                "Meal break violation cannot be resolved by fabricating employee punch times. "
                "Manager must verify whether an unrecorded break was taken or authorize a meal penalty."
            ),
            "recommendation": "Escalate to manager to investigate break compliance.",
            "confidence": 0.60,
            "missing_information": ["Meal break compliance statement"],
            "blocked": True,
        }

    else:
        # Schedule conflict or general
        hours = compute_net_hours(check_in, check_out, meal_start, meal_end)
        return {
            "proposed_timecard": {
                "checkIn": check_in,
                "checkOut": check_out,
                "mealStart": meal_start,
                "mealEnd": meal_end,
                "totalHours": hours,
            },
            "changed_fields": [],
            "reason": "Deterministic fallback: Schedule deviation recorded with actual punch times.",
            "recommendation": "Review schedule deviation and acknowledge actual hours worked.",
            "confidence": 0.85,
            "missing_information": [],
            "blocked": False,
        }
