"""Proposal generation and resolution service.

Orchestrates the resolution pipeline:
1. Load exception record and employee schedule context.
2. Retrieve relevant policy clause using BM25 ranking.
3. Attempt LLM generation via Ollama (Qwen2.5) with strict JSON schema.
4. Execute deterministic safety validator (5 checks).
5. Retry once if initial LLM validation fails.
6. Trigger deterministic fallback engine if LLM fails or Ollama is offline.
7. Persist proposal, update exception lifecycle status, and record audit trail.
8. NEVER modify timecards or punch records at this stage.

Principle: "The LLM suggests. Code decides. A human approves."
"""

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models.employee import EmployeeModel
from app.models.exception import ExceptionModel
from app.models.proposal import ProposalModel
from app.models.punch import PunchModel
from app.models.schedule import ScheduleModel
from app.rules.detectors.cross_day import split_duplicate_punches
from app.services.audit_service import generate_trace_id, log_audit_event
from app.services.detector_service import to_detector_punch, to_detector_schedule
from app.services.llm_service import (
    LLMResult,
    build_prompt,
    build_retry_prompt,
    check_proposal_shape,
    check_timecard_changes,
    proposal_schema,
    query_llm,
    truncate_for_audit,
)
from app.services.policy_service import policy_service
from app.services.rules_adapter import (
    compute_net_hours,
    generate_fallback_proposal,
    validate_timecard_proposal,
)
from app.services.timecard import shift_context, timecard_view

logger = logging.getLogger(__name__)


def _finalize_timecard(
    proposed: dict[str, Any], original: dict[str, Any]
) -> tuple[dict[str, Any], list[str]]:
    """Normalise an AI timecard: code (not the model) sets total hours and the changed fields."""
    keys = ("checkIn", "checkOut", "mealStart", "mealEnd")
    card = {k: proposed.get(k) for k in keys}
    card["totalHours"] = compute_net_hours(
        card["checkIn"], card["checkOut"], card["mealStart"], card["mealEnd"]
    )
    changed = [k for k in keys if card[k] != original.get(k)]
    return card, changed


def _unresolvable_as_is(errors: list[str], description: str) -> bool:
    """True when every error says the original exception itself remains unresolved.

    That happens when the model correctly leaves the times alone (for example a missing meal
    break, which must never be fixed by inventing punches). A retry cannot help: only a manager
    can resolve it.
    """
    head = description.split(":")[0].strip().lower()
    return bool(errors) and all(
        "unresolved violation" in e.lower() and head in e.lower() for e in errors
    )


def _validate_llm_candidate(
    parsed: dict[str, Any],
    allowed_ids: set[str],
    primary_clause_id: str,
    exc: ExceptionModel,
    sched_start: str,
    sched_end: str,
    detector_punches: list[Any],
    detector_schedule: Any,
) -> tuple[list[str], Any, str]:
    """Run grounding and validator checks. Returns (errors, validation summary, cited id)."""
    errors = check_proposal_shape(parsed, allowed_ids)
    if errors:
        return errors, None, primary_clause_id

    citations = [str(c).strip() for c in parsed["policy_citations"]]
    cited_id = citations[0]
    errors = check_timecard_changes(
        parsed["proposed_timecard"], timecard_view(exc.original_attendance), exc.type
    )
    if errors:
        return errors, None, cited_id
    summary = validate_timecard_proposal(
        proposed_tc=parsed["proposed_timecard"],
        cited_clause_id=cited_id,
        reasoning=str(parsed.get("reason", "")),
        original_type=exc.type,
        schedule_start=sched_start,
        schedule_end=sched_end,
        original_punches=detector_punches,
        original_schedule=detector_schedule,
        original_exception=exc,
        # What changed is decided by comparing the times, not by the model's own claim
        changed_fields=_finalize_timecard(
            parsed["proposed_timecard"], timecard_view(exc.original_attendance)
        )[1],
    )
    return (
        ([] if summary.valid else list(summary.errors or ["Validation failed."])),
        summary,
        cited_id,
    )


def generate_proposal_for_exception(
    session: Session,
    exception_id: str,
    trace_id: str | None = None,
) -> ProposalModel:
    """Generate and validate a proposal for the specified exception."""
    t_id = trace_id or generate_trace_id()

    # 1. Fetch exception
    exc = session.get(ExceptionModel, exception_id)
    if exc is None:
        raise ValueError(f"Exception '{exception_id}' not found.")

    if exc.status in ("approved", "rejected"):
        raise ValueError(f"Exception '{exception_id}' is already {exc.status.lower()}.")

    # 2. Retrieve employee schedule ground truth
    emp = exc.employee or session.get(EmployeeModel, exc.employee_id)
    sched = (
        session.query(ScheduleModel)
        .filter(
            ScheduleModel.employee_id == exc.employee_id,
            ScheduleModel.date == exc.date,
        )
        .first()
    )

    sched_start_str = (
        sched.start_time.strftime("%H:%M") if sched else (emp.shift_start if emp else "09:00")
    )
    sched_end_str = (
        sched.end_time.strftime("%H:%M") if sched else (emp.shift_end if emp else "17:00")
    )

    # Convert punches and schedule to detector models for validation
    raw_punches = session.query(PunchModel).filter(PunchModel.employee_id == exc.employee_id).all()
    shift_punches = [p for p in raw_punches if p.timestamp.strftime("%Y-%m-%d") == exc.date]
    # Double taps are removed first, as the detectors do, so the validator does not mistake
    # the duplicate itself for an overlapping punch or an unresolved violation.
    detector_punches, _ = split_duplicate_punches([to_detector_punch(p) for p in shift_punches])
    detector_schedule = to_detector_schedule(sched) if sched else None

    # 3. Retrieve relevant policy clauses (best first; conflicting clauses are included)
    retrieved = policy_service.retrieve_policies(
        exc.type, exc.description, preferred_id=exc.policy_reference
    )
    clauses = [c for c, _ in retrieved]
    clause = clauses[0]
    allowed_ids = {c.id for c in clauses}

    log_audit_event(
        session=session,
        action="Policy retrieved",
        user="SmartAttend Agent",
        status="info",
        trace_id=t_id,
        exception_id=exc.id,
        detail=("Retrieved via BM25: " + ", ".join(f"{c.id} ({c.name})" for c in clauses) + "."),
        flags=[],
    )

    # 4. Attempt proposal generation via LLM (one retry), then fallback
    orig_tc = timecard_view(exc.original_attendance)
    proposal_data: dict[str, Any] | None = None
    used_fallback = False
    retried = False
    cited_clause_id = clause.id
    last_errors: list[str] = []
    rejected_llm: dict[str, Any] | None = None  # last AI suggestion that failed checks
    needs_manager = False  # model left the times alone; only a manager can resolve it

    punch_notes = [str(p.notes) for p in shift_punches if p.notes]
    # Multi-day exceptions (rest period, consecutive days): the facts live on other days
    context_shifts, context_summary = shift_context(raw_punches, exc.type, exc.date)
    context_facts = ""
    if context_summary:
        listed = "; ".join(
            f"{c['date']} {c['start']}-{c['end'] or 'no clock-out'}" for c in context_shifts
        )
        context_facts = f"{context_summary} Shifts: {listed}."

    base_prompt = build_prompt(
        clauses=clauses,
        exception_type=exc.type,
        date=exc.date,
        description=exc.description,
        schedule_start=sched_start_str,
        schedule_end=sched_end_str,
        original_timecard=orig_tc,
        notes=punch_notes,
        context=context_facts,
    )

    def _log_llm(result: LLMResult, attempt: int) -> None:
        log_audit_event(
            session=session,
            action="LLM response received" if result.parsed else "LLM call failed",
            user="SmartAttend Agent",
            status="info" if result.parsed else "warning",
            trace_id=t_id,
            exception_id=exc.id,
            detail=(
                f"Attempt {attempt}; model={result.model}; prompt={result.prompt_version}; "
                f"{result.duration_seconds}s; "
                + (
                    f"raw output: {truncate_for_audit(result.raw)}"
                    if result.parsed
                    else str(result.error)
                )
            ),
            flags=[],
        )

    prompt = base_prompt
    for attempt in (1, 2):
        result = query_llm(prompt, schema=proposal_schema(allowed_ids))
        _log_llm(result, attempt)
        if result.parsed is None:
            break  # model offline or unusable output: retrying the same call is pointless

        last_errors, val_summary, cited = _validate_llm_candidate(
            result.parsed,
            allowed_ids,
            clause.id,
            exc,
            sched_start_str,
            sched_end_str,
            detector_punches,
            detector_schedule,
        )
        if not last_errors:
            raw_llm = result.parsed
            cited_clause_id = cited
            card, changed = _finalize_timecard(raw_llm["proposed_timecard"], orig_tc)
            proposal_data = {
                "proposed_timecard": card,
                "changed_fields": changed,
                "reason": str(raw_llm.get("reason", "")),
                "recommendation": str(raw_llm.get("recommendation", "Review proposed timecard.")),
                "confidence": float(raw_llm.get("confidence") or 0.0),
                "missing_information": raw_llm.get("missing_information", []),
                "blocked": False,
                "validators": [v.model_dump() for v in val_summary.validators],
            }
            break

        if isinstance(result.parsed.get("proposed_timecard"), dict):
            rejected_llm = {
                "parsed": result.parsed,
                "errors": list(last_errors),
                "validators": (
                    [v.model_dump() for v in val_summary.validators]
                    if val_summary is not None
                    else [
                        {
                            "name": "Proposal Check",
                            "passed": False,
                            "reason": "; ".join(last_errors),
                        }
                    ]
                ),
            }

        if (
            rejected_llm is not None
            and not _finalize_timecard(result.parsed["proposed_timecard"], orig_tc)[1]
            and _unresolvable_as_is(last_errors, exc.description)
        ):
            needs_manager = True
            break  # same answer would come back: do not spend a second model call

        if attempt == 1:
            retried = True
            log_audit_event(
                session=session,
                action="Retry attempted",
                user="SmartAttend Agent",
                status="warning",
                trace_id=t_id,
                exception_id=exc.id,
                detail=(
                    f"LLM proposal failed validation: {'; '.join(last_errors)}. "
                    "Sending errors back to the model for one retry."
                ),
                flags=["Retried"],
            )
            prompt = build_retry_prompt(base_prompt, result.parsed, last_errors)

    # If LLM didn't produce a valid proposal, use deterministic fallback
    if proposal_data is None:
        used_fallback = True
        fallback_res = generate_fallback_proposal(
            exception_type=exc.type,
            original_attendance=orig_tc,
            schedule_start=sched_start_str,
            schedule_end=sched_end_str,
            policy_clause_id=clause.id,
            original_exception=exc,
            original_punches=detector_punches,
            original_schedule=detector_schedule,
        )

        val_summary = validate_timecard_proposal(
            proposed_tc=fallback_res["proposed_timecard"],
            cited_clause_id=clause.id,
            reasoning=fallback_res["reason"],
            original_type=exc.type,
            schedule_start=sched_start_str,
            schedule_end=sched_end_str,
            original_punches=detector_punches,
            original_schedule=detector_schedule,
            original_exception=exc,
            changed_fields=fallback_res.get("changed_fields"),
        )

        flags = ["Fallback"]
        if retried:
            flags.append("Retried")
        # A rejected AI suggestion is shown hard-blocked, so the manager must act on it.
        escalated = bool(fallback_res["blocked"] or val_summary.blocked or rejected_llm)
        if escalated:
            flags.append("Escalated")

        log_audit_event(
            session=session,
            action="Fallback triggered",
            user="SmartAttend Agent",
            status="warning",
            trace_id=t_id,
            exception_id=exc.id,
            detail=(
                (f"LLM output rejected ({'; '.join(last_errors)}). " if last_errors else "")
                + fallback_res["reason"]
            ),
            flags=flags,
        )

        proposal_data = {
            "proposed_timecard": fallback_res["proposed_timecard"],
            "changed_fields": fallback_res["changed_fields"],
            "reason": fallback_res["reason"],
            "recommendation": fallback_res["recommendation"],
            "confidence": fallback_res["confidence"],
            "missing_information": fallback_res["missing_information"],
            "blocked": fallback_res["blocked"] or val_summary.blocked,
            "validators": [v.model_dump() for v in val_summary.validators],
        }

    # If the AI's suggestion was rejected, still show it to the manager, but hard-blocked.
    # The rule-based fallback result stays in the audit log and the recommendation text.
    if used_fallback and rejected_llm is not None:
        ai = rejected_llm["parsed"]
        shown, shown_changed = _finalize_timecard(ai["proposed_timecard"], orig_tc)
        proposal_data = {
            "proposed_timecard": shown,
            "changed_fields": shown_changed,
            "reason": (
                (
                    "No time change can resolve this exception, so it cannot be approved as-is: "
                    if needs_manager
                    else "AI suggestion BLOCKED by validation: "
                )
                + "; ".join(rejected_llm["errors"])
                + f" AI reasoning: {str(ai.get('reason', '')).strip()}"
            ),
            "recommendation": (
                (
                    "A manager must verify what happened, then edit the timecard or reject. "
                    if needs_manager
                    else "This AI suggestion cannot be approved. Edit the times or reject it. "
                )
                + f"Rule-based alternative: {proposal_data['recommendation']}"
            ),
            "confidence": min(float(ai.get("confidence") or 0.0), 0.5),
            "missing_information": list(ai.get("missing_information") or [])
            or ["Manager review required"],
            "blocked": True,
            "validators": rejected_llm["validators"],
        }
        # The punch can be filled in, but the shift then has no recorded meal break and meal
        # times are never invented: say exactly what the manager has to do.
        only_meal = all("missing meal break" in e.lower() for e in rejected_llm["errors"])
        if only_meal and shown_changed:
            filled = ", ".join(f"{k} {shown[k]}" for k in shown_changed if shown[k])
            hours = shown.get("totalHours")
            proposal_data["reason"] = (
                f"The missing punch can be filled in from the schedule ({filled}), but that "
                + (f"makes a {hours:g}-hour shift " if hours else "makes a long shift ")
                + "with no recorded meal break, and meal times are never invented."
            )
            proposal_data["recommendation"] = (
                "Ask the employee when they took their break, then use Edit times to enter the "
                "clock-out and the meal times."
            )
            proposal_data["missing_information"] = ["Meal break start and end (not recorded)"]

    # The facts are stated by code, so the explanation always shows the other days' times
    # whether the reason came from the model or from the fallback.
    if context_facts and context_facts not in proposal_data["reason"]:
        proposal_data["reason"] = f"{context_facts} {proposal_data['reason']}"

    # 5. Persist ProposalModel
    proposal_id = f"PROP-{uuid.uuid4().hex[:12].upper()}"
    new_proposal = ProposalModel(
        id=proposal_id,
        exception_id=exc.id,
        proposed_timecard=proposal_data["proposed_timecard"],
        changed_fields=proposal_data["changed_fields"],
        detected_issue=exc.description,
        reason=proposal_data["reason"],
        policy_title=(policy_service.clauses.get(cited_clause_id) or clause).name,
        policy_clause_id=cited_clause_id,
        policy_excerpt=(policy_service.clauses.get(cited_clause_id) or clause).description,
        recommendation=proposal_data["recommendation"],
        confidence=proposal_data["confidence"],
        missing_information=proposal_data["missing_information"],
        validators=proposal_data["validators"],
        blocked=proposal_data["blocked"],
        generated_at=datetime.now(UTC).replace(tzinfo=None),
    )
    session.add(new_proposal)

    # 6. Update exception active proposal and status
    exc.proposal_id = proposal_id
    exc.status = "awaiting_approval"

    # 7. Record AI proposal and validation audit logs
    proposal_action = "Fallback proposal generated" if used_fallback else "AI proposal generated"
    log_audit_event(
        session=session,
        action=proposal_action,
        user="SmartAttend Agent",
        status="success",
        trace_id=t_id,
        exception_id=exc.id,
        detail=f"Resolution proposal generated: {proposal_data['reason']}",
        flags=["Fallback"] if used_fallback else [],
    )

    log_audit_event(
        session=session,
        action="Validation completed",
        user="Validator Suite",
        status="success" if not proposal_data["blocked"] else "warning",
        trace_id=t_id,
        exception_id=exc.id,
        detail="Proposal validated: ready for review."
        if not proposal_data["blocked"]
        else "Proposal blocked by validation: requires manager investigation.",
        flags=[],
    )

    session.commit()
    session.refresh(new_proposal)
    return new_proposal
