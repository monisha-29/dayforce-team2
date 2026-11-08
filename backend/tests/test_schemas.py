"""Test Pydantic v2 schemas for camelCase serialization and snake_case parsing."""

from datetime import datetime

from app.schemas import (
    AuditEvent,
    DecisionRequest,
    DecisionResponse,
    DecisionType,
    Employee,
    Proposal,
    Timecard,
    ValidatorResult,
)


def test_employee_serialization() -> None:
    """Verify Employee serializes to camelCase and parses from snake_case."""
    emp = Employee(
        id="EMP-101",
        name="Alice Smith",
        department="Engineering",
        shift="Morning Shift",
        shift_start="09:00",
        shift_end="17:00",
    )
    dumped = emp.model_dump(by_alias=True)
    assert dumped["shiftStart"] == "09:00"
    assert dumped["shiftEnd"] == "17:00"

    # Verify parsing from frontend camelCase JSON
    parsed = Employee.model_validate(
        {
            "id": "EMP-102",
            "name": "Bob Jones",
            "department": "Support",
            "shift": "Evening Shift",
            "shiftStart": "13:00",
            "shiftEnd": "21:00",
        }
    )
    assert parsed.shift_start == "13:00"
    assert parsed.shift_end == "21:00"


def test_proposal_and_timecard_serialization() -> None:
    """Verify Proposal and Timecard serialize with camelCase aliases."""
    timecard = Timecard(
        check_in="09:00",
        check_out="17:30",
        meal_start="12:00",
        meal_end="12:30",
        total_hours=8.0,
    )
    tc_dump = timecard.model_dump(by_alias=True)
    assert tc_dump["checkIn"] == "09:00"
    assert tc_dump["checkOut"] == "17:30"
    assert tc_dump["mealStart"] == "12:00"
    assert tc_dump["totalHours"] == 8.0

    proposal = Proposal(
        id="PROP-001",
        exception_id="EXC-100",
        proposed=timecard,
        changed_fields=["check_out"],
        detected_issue="Missed check-out punch",
        reason="Employee forgot to clock out at shift end",
        policy_title="Missed Punch Resolution Policy",
        policy_clause_id="PUNCH-01",
        policy_excerpt="Propose shift end boundary punch",
        recommendation="Insert OUT punch at 17:30",
        confidence=0.95,
        missing_information=[],
        validators=[
            ValidatorResult(name="Schema Validation", passed=True),
            ValidatorResult(name="Working Hours Validation", passed=True),
        ],
        blocked=False,
        generated_at=datetime(2026, 11, 8, 12, 0, 0),
    )
    prop_dump = proposal.model_dump(by_alias=True)
    assert prop_dump["exceptionId"] == "EXC-100"
    assert prop_dump["changedFields"] == ["check_out"]
    assert prop_dump["policyClauseId"] == "PUNCH-01"
    assert len(prop_dump["validators"]) == 2
    assert prop_dump["validators"][0]["name"] == "Schema Validation"


def test_decision_and_audit_schemas() -> None:
    """Verify Decision and AuditEvent models handle aliasing correctly."""
    req = DecisionRequest.model_validate(
        {
            "decision": "approve",
            "reason": "Approved by supervisor",
        }
    )
    assert req.decision == DecisionType.APPROVE

    res = DecisionResponse(
        exception_id="EXC-100",
        new_status="Approved",
        message="Correction accepted",
        trace_id="tr-123456",
    )
    res_dump = res.model_dump(by_alias=True)
    assert res_dump["exceptionId"] == "EXC-100"
    assert res_dump["newStatus"] == "Approved"
    assert res_dump["traceId"] == "tr-123456"

    audit = AuditEvent(
        id="AUD-001",
        exception_id="EXC-100",
        timestamp=datetime(2026, 11, 8, 12, 1, 0),
        action="Manager approved",
        user="Rebecca Thorne",
        status="success",
        trace_id="tr-123456",
        flags=["Retried"],
    )
    audit_dump = audit.model_dump(by_alias=True)
    assert audit_dump["exceptionId"] == "EXC-100"
    assert audit_dump["traceId"] == "tr-123456"
    assert audit_dump["flags"] == ["Retried"]
