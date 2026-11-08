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

import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy.orm import Session

from app.config import settings
from app.models.employee import EmployeeModel
from app.models.exception import ExceptionModel
from app.models.proposal import ProposalModel
from app.models.punch import PunchModel
from app.models.schedule import ScheduleModel
from app.services.audit_service import generate_trace_id, log_audit_event
from app.services.detector_service import to_detector_punch, to_detector_schedule
from app.services.policy_service import policy_service
from app.services.rules_adapter import (
    generate_fallback_proposal,
    validate_timecard_proposal,
)

logger = logging.getLogger(__name__)


def _query_ollama(
    prompt: str,
    model: str = settings.LLM_MODEL,
    temperature: float = settings.LLM_TEMPERATURE,
    timeout_seconds: float = 3.0,
) -> dict[str, Any] | None:
    """Send generation prompt to local Ollama instance with timeout.

    Returns parsed JSON dictionary if successful, None if unreachable or invalid.
    """
    url = f"{settings.OLLAMA_URL.rstrip('/')}/api/generate"
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "options": {
            "temperature": temperature,
        },
    }

    try:
        with httpx.Client(timeout=timeout_seconds) as client:
            resp = client.post(url, json=payload)
            if resp.status_code == 200:
                body = resp.json()
                raw_response = body.get("response", "")
                parsed = json.loads(raw_response)
                if isinstance(parsed, dict):
                    return parsed
    except (httpx.HTTPError, json.JSONDecodeError, OSError) as exc:
        logger.info("Ollama LLM query omitted/unavailable: %s", exc)

    return None


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
    raw_punches = (
        session.query(PunchModel)
        .filter(PunchModel.employee_id == exc.employee_id)
        .all()
    )
    shift_punches = [
        p for p in raw_punches if p.timestamp.strftime("%Y-%m-%d") == exc.date
    ]
    detector_punches = [to_detector_punch(p) for p in shift_punches]
    detector_schedule = to_detector_schedule(sched) if sched else None

    # 3. Retrieve relevant policy clause
    clause, _confidence = policy_service.retrieve_policy(exc.type, exc.description)

    log_audit_event(
        session=session,
        action="Policy retrieved",
        user="SmartAttend Agent",
        status="info",
        trace_id=t_id,
        exception_id=exc.id,
        detail=f"Retrieved policy {clause.id} ({clause.name}) via BM25 retrieval.",
        flags=[],
    )

    # 4. Attempt proposal generation via LLM or fallback
    orig_tc = exc.original_attendance or {}
    proposal_data: dict[str, Any] | None = None
    used_fallback = False
    retried = False

    # Build prompt for LLM
    prompt_text = (
        f"Company Policy:\n"
        f"Clause ID: {clause.id}\n"
        f"Title: {clause.name}\n"
        f"Rule: {clause.description}\n\n"
        f"Exception:\n"
        f"Type: {exc.type}\n"
        f"Date: {exc.date}\n"
        f"Description: {exc.description}\n"
        f"Original Attendance: {json.dumps(orig_tc)}\n"
        f"Assigned Schedule: Start={sched_start_str}, End={sched_end_str}\n\n"
        f"Return JSON with keys: proposed_timecard, changed_fields, reason, recommendation, confidence, missing_information."
    )

    # Try Ollama
    raw_llm = _query_ollama(prompt_text)
    if raw_llm and isinstance(raw_llm.get("proposed_timecard"), dict):
        proposed_candidate = raw_llm["proposed_timecard"]
        candidate_reason = str(raw_llm.get("reason", ""))

        # Validate with deterministic validator
        val_summary = validate_timecard_proposal(
            proposed_tc=proposed_candidate,
            cited_clause_id=clause.id,
            reasoning=candidate_reason,
            original_type=exc.type,
            schedule_start=sched_start_str,
            schedule_end=sched_end_str,
            original_punches=detector_punches,
            original_schedule=detector_schedule,
            original_exception=exc,
            changed_fields=raw_llm.get("changed_fields"),
        )

        if val_summary.valid:
            proposal_data = {
                "proposed_timecard": proposed_candidate,
                "changed_fields": raw_llm.get("changed_fields", list(proposed_candidate.keys())),
                "reason": candidate_reason,
                "recommendation": str(raw_llm.get("recommendation", "Review proposed timecard.")),
                "confidence": float(raw_llm.get("confidence", 0.95)),
                "missing_information": raw_llm.get("missing_information", []),
                "blocked": False,
                "validators": [v.model_dump() for v in val_summary.validators],
            }
        else:
            # Retry once
            retried = True
            log_audit_event(
                session=session,
                action="Retry attempted",
                user="SmartAttend Agent",
                status="warning",
                trace_id=t_id,
                exception_id=exc.id,
                detail=f"Initial LLM proposal failed validation: {val_summary.errors[0] if val_summary.errors else 'Unknown'}. Retrying...",
                flags=["Retried"],
            )

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

        log_audit_event(
            session=session,
            action="Fallback triggered",
            user="SmartAttend Agent",
            status="warning",
            trace_id=t_id,
            exception_id=exc.id,
            detail=fallback_res["reason"],
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

    # 5. Persist ProposalModel
    proposal_id = f"PROP-{uuid.uuid4().hex[:12].upper()}"
    new_proposal = ProposalModel(
        id=proposal_id,
        exception_id=exc.id,
        proposed_timecard=proposal_data["proposed_timecard"],
        changed_fields=proposal_data["changed_fields"],
        detected_issue=exc.description,
        reason=proposal_data["reason"],
        policy_title=clause.name,
        policy_clause_id=clause.id,
        policy_excerpt=clause.description,
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
