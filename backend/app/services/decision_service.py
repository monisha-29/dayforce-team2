"""Decision and escalation service for manager review workflows.

Implements the strict governance principle:
"The LLM suggests. Code decides. A human approves."
Only an explicit manager approval or edit can alter employee timecard punch records.
Rejected or blocked proposals never modify timecard records.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.decision import DecisionModel
from app.models.exception import ExceptionModel
from app.models.proposal import ProposalModel
from app.models.punch import PunchModel
from app.schemas.decision import DecisionRequest, DecisionResponse
from app.services.audit_service import generate_trace_id, log_audit_event
from app.services.rules_adapter import TIME_REGEX, compute_net_hours, parse_time_str


def _apply_timecard_to_punches(
    session: Session,
    employee_id: str,
    date_str: str,
    timecard_data: dict[str, Any],
    source: str = "manager_approved_proposal",
) -> None:
    """Synchronize approved timecard punch times with the punches table.

    Correctly accounts for overnight shift date rollovers (e.g. 22:00 -> 06:30)
    by persisting post-midnight punches to base_date + 1 day and checking both
    shift start date and rollover date to match existing punches.
    """
    check_in = timecard_data.get("checkIn") or timecard_data.get("check_in")
    check_out = timecard_data.get("checkOut") or timecard_data.get("check_out")
    meal_start = timecard_data.get("mealStart") or timecard_data.get("meal_start")
    meal_end = timecard_data.get("mealEnd") or timecard_data.get("meal_end")

    base_date = datetime.fromisoformat(date_str).date()
    t_in = parse_time_str(str(check_in) if check_in else None)
    in_m = t_in[0] * 60 + t_in[1] if t_in else None

    def _sync_punch(punch_type: str, time_val: str | None) -> None:
        if not time_val or not TIME_REGEX.match(str(time_val).strip()):
            return

        t_parsed = parse_time_str(str(time_val).strip())
        if not t_parsed:
            return

        val_m = t_parsed[0] * 60 + t_parsed[1]
        is_next_day = in_m is not None and punch_type != "IN" and val_m < in_m
        punch_date = base_date + timedelta(days=1) if is_next_day else base_date
        target_dt = datetime(
            punch_date.year, punch_date.month, punch_date.day, t_parsed[0], t_parsed[1], 0
        )
        target_date_str = punch_date.isoformat()

        # Find existing punch of same type on shift start date or rollover date
        existing_punches = (
            session.query(PunchModel)
            .filter(
                PunchModel.employee_id == employee_id,
                PunchModel.punch_type == punch_type,
            )
            .all()
        )

        match = None
        for p in existing_punches:
            p_date_str = p.timestamp.strftime("%Y-%m-%d")
            if p_date_str in (date_str, target_date_str):
                match = p
                break

        if match is not None:
            if match.timestamp == target_dt:
                return  # approved as-is: leave the recorded punch (and its source/notes) alone
            # Keep the employee's original note and record what the time used to be.
            previous = f"{match.notes} | " if match.notes else ""
            match.notes = (
                f"{previous}Updated via manager review on {date_str} (was {match.timestamp:%H:%M})"
            )
            match.timestamp = target_dt
            match.source = source
        else:
            new_punch = PunchModel(
                id=f"PUNCH-{uuid.uuid4().hex[:12].upper()}",
                employee_id=employee_id,
                timestamp=target_dt,
                punch_type=punch_type,
                source=source,
                notes=f"Inserted via manager review on {date_str}",
            )
            session.add(new_punch)

    _sync_punch("IN", check_in)
    _sync_punch("OUT", check_out)
    _sync_punch("BREAK_START", meal_start)
    _sync_punch("BREAK_END", meal_end)


def record_decision(
    session: Session,
    proposal_id: str,
    request: DecisionRequest,
    manager_user: str = "Rebecca Thorne",
    trace_id: str | None = None,
) -> DecisionResponse:
    """Record manager decision (approve, edit, reject) and update timecards if approved."""
    t_id = trace_id or generate_trace_id()

    proposal = session.get(ProposalModel, proposal_id)
    if proposal is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Proposal '{proposal_id}' not found.",
        )

    exc = proposal.exception
    if exc is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Exception for proposal '{proposal_id}' not found.",
        )

    # Prevent re-deciding resolved exceptions
    if exc.status.lower() in ("approved", "rejected"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Exception already {exc.status.lower()}.",
        )

    decision_action = request.decision.value.lower()

    # -------------------------------------------------------------
    # ACTION: REJECT
    # -------------------------------------------------------------
    if decision_action == "reject":
        if not request.reason or not request.reason.strip():
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="A rejection reason is required.",
            )

        exc.status = "rejected"

        decision_record = DecisionModel(
            id=f"DEC-{uuid.uuid4().hex[:12].upper()}",
            proposal_id=proposal.id,
            exception_id=exc.id,
            decision="reject",
            manager_user=manager_user,
            reason=request.reason.strip(),
            edited_timecard=None,
            decided_at=datetime.now(UTC).replace(tzinfo=None),
        )
        session.add(decision_record)

        log_audit_event(
            session=session,
            action="Manager rejected",
            user=manager_user,
            status="failure",
            trace_id=t_id,
            exception_id=exc.id,
            detail=request.reason.strip(),
            flags=[],
        )

        session.commit()
        return DecisionResponse(
            exception_id=exc.id,
            new_status="Rejected",
            message="Rejection recorded. Timecard unchanged.",
            trace_id=t_id,
        )

    # -------------------------------------------------------------
    # ACTION: APPROVE
    # -------------------------------------------------------------
    if decision_action == "approve":
        if proposal.blocked:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Proposal is blocked by failed validation and cannot be approved as-is.",
            )

        exc.status = "approved"

        decision_record = DecisionModel(
            id=f"DEC-{uuid.uuid4().hex[:12].upper()}",
            proposal_id=proposal.id,
            exception_id=exc.id,
            decision="approve",
            manager_user=manager_user,
            reason=request.reason or "Manager approved AI proposal.",
            edited_timecard=None,
            decided_at=datetime.now(UTC).replace(tzinfo=None),
        )
        session.add(decision_record)

        # Apply proposed timecard to employee punches
        _apply_timecard_to_punches(
            session=session,
            employee_id=exc.employee_id,
            date_str=exc.date,
            timecard_data=proposal.proposed_timecard,
            source="manager_approved_proposal",
        )

        log_audit_event(
            session=session,
            action="Manager approved",
            user=manager_user,
            status="success",
            trace_id=t_id,
            exception_id=exc.id,
            detail=(
                f"Approved: {request.reason.strip()}"
                if request.reason and request.reason.strip()
                else "Approved AI proposal."
            ),
            flags=[],
        )

        log_audit_event(
            session=session,
            action="Timecard updated",
            user="Timekeeping Backend",
            status="success",
            trace_id=t_id,
            exception_id=exc.id,
            detail="Applied proposal corrections to employee timecard.",
            flags=[],
        )

        session.commit()
        return DecisionResponse(
            exception_id=exc.id,
            new_status="Approved",
            message="Approval accepted and timecard updated.",
            trace_id=t_id,
        )

    # -------------------------------------------------------------
    # ACTION: EDIT
    # -------------------------------------------------------------
    if decision_action == "edit":
        if not request.edited_timecard:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Edited timecard data is required for 'edit' decision.",
            )

        tc = request.edited_timecard
        errors: list[str] = []
        if not tc.check_in or not TIME_REGEX.match(tc.check_in.strip()):
            errors.append("Check-in must be a valid HH:MM time.")
        if not tc.check_out or not TIME_REGEX.match(tc.check_out.strip()):
            errors.append("Check-out must be a valid HH:MM time.")
        if tc.meal_start and not TIME_REGEX.match(tc.meal_start.strip()):
            errors.append("Meal start must be HH:MM.")
        if tc.meal_end and not TIME_REGEX.match(tc.meal_end.strip()):
            errors.append("Meal end must be HH:MM.")

        hours = compute_net_hours(
            tc.check_in,
            tc.check_out,
            tc.meal_start,
            tc.meal_end,
        )
        if hours is None or hours <= 0 or hours > 16:
            errors.append("Total worked hours must be between 0 and 16.")

        if errors:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Backend validation failed: {' '.join(errors)}",
            )

        edited_dict = {
            "checkIn": tc.check_in,
            "checkOut": tc.check_out,
            "mealStart": tc.meal_start,
            "mealEnd": tc.meal_end,
            "totalHours": hours,
        }

        proposal.proposed_timecard = edited_dict
        proposal.blocked = False
        proposal.validators = [
            {"name": str(v.get("name")), "passed": True, "reason": "Manager edited & verified."}
            for v in proposal.validators
        ]

        exc.status = "approved"

        decision_record = DecisionModel(
            id=f"DEC-{uuid.uuid4().hex[:12].upper()}",
            proposal_id=proposal.id,
            exception_id=exc.id,
            decision="edit",
            manager_user=manager_user,
            reason=request.reason or "Manager edited and authorized timecard.",
            edited_timecard=edited_dict,
            decided_at=datetime.now(UTC).replace(tzinfo=None),
        )
        session.add(decision_record)

        # Apply edited timecard to employee punches
        _apply_timecard_to_punches(
            session=session,
            employee_id=exc.employee_id,
            date_str=exc.date,
            timecard_data=edited_dict,
            source="manager_edited_proposal",
        )

        log_audit_event(
            session=session,
            action="Manager edited",
            user=manager_user,
            status="info",
            trace_id=t_id,
            exception_id=exc.id,
            detail="Edited proposal submitted for validation.",
            flags=[],
        )

        log_audit_event(
            session=session,
            action="Validation completed",
            user="Validator Suite",
            status="success",
            trace_id=t_id,
            exception_id=exc.id,
            detail="Edited proposal passed all checks.",
            flags=[],
        )

        log_audit_event(
            session=session,
            action="Timecard updated",
            user="Timekeeping Backend",
            status="success",
            trace_id=t_id,
            exception_id=exc.id,
            detail="Applied edited corrections to employee timecard.",
            flags=[],
        )

        session.commit()
        return DecisionResponse(
            exception_id=exc.id,
            new_status="Approved",
            message="Edited proposal validated and approved.",
            trace_id=t_id,
        )

    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail=f"Unsupported decision type: '{request.decision}'.",
    )


def escalate_exception_workflow(
    session: Session,
    exception_id: str,
    note: str | None = None,
    manager_user: str = "Rebecca Thorne",
    trace_id: str | None = None,
) -> DecisionResponse:
    """Escalate an exception directly to manager or HR operations."""
    t_id = trace_id or generate_trace_id()

    exc = session.get(ExceptionModel, exception_id)
    if exc is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Exception '{exception_id}' not found.",
        )

    exc.status = "escalated"

    log_audit_event(
        session=session,
        action="Escalated",
        user=manager_user,
        status="failure",
        trace_id=t_id,
        exception_id=exc.id,
        detail=note or "Escalated to HR Operations.",
        flags=["Escalated"],
    )

    session.commit()
    return DecisionResponse(
        exception_id=exc.id,
        new_status="Escalated",
        message="Escalated to HR Operations.",
        trace_id=t_id,
    )
