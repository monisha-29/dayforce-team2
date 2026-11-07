"""Comprehensive tests for ProposalValidator (The 5 Safety Checks)."""

import json
from datetime import datetime, timedelta

import pytest

from app.rules.models.exception import (
    ExceptionType,
    Punch,
    PunchType,
    Schedule,
    TimecardException,
)
from app.rules.validator import ProposalValidator


@pytest.fixture
def validator() -> ProposalValidator:
    return ProposalValidator()


@pytest.fixture
def base_context():
    """Provides base punch, schedule, and exception for tests."""
    schedule = Schedule(
        employee_id="E-100",
        date="2026-11-07",
        start_time=datetime(2026, 11, 7, 9, 0),
        end_time=datetime(2026, 11, 7, 13, 0),
    )
    punches = [
        Punch(employee_id="E-100", timestamp=datetime(2026, 11, 7, 9, 0), punch_type=PunchType.IN),
    ]
    exception = TimecardException(
        exception_id="EXC-100",
        employee_id="E-100",
        exception_type=ExceptionType.MISSED_PUNCH,
        date="2026-11-07",
        description="Missing clock-out punch",
        policy_reference="PUNCH-01",
    )
    return schedule, punches, exception


# -----------------------------------------------------------------
# CHECK 1: JSON FORMAT & SCHEMA
# -----------------------------------------------------------------
def test_check1_valid_json_string(validator: ProposalValidator, base_context) -> None:
    """Valid JSON string is parsed and passes check 1."""
    sched, punches, exc = base_context
    payload = json.dumps(
        {
            "exception_id": "EXC-100",
            "suggested_action": "insert_punch",
            "proposed_punches": [
                {"punch_type": "OUT", "timestamp": "2026-11-07T13:00:00", "action": "insert"}
            ],
            "policy_citations": ["PUNCH-01"],
            "reasoning": "Inserted scheduled end time punch.",
        }
    )
    res = validator.validate(punches, payload, sched, exc)
    assert res.validation_checks["format_valid"] is True
    assert res.valid is True


def test_check1_invalid_json_string(validator: ProposalValidator, base_context) -> None:
    """Malformed JSON string fails check 1 with clear INVALID_JSON_FORMAT code."""
    sched, punches, exc = base_context
    malformed_payload = '{ "exception_id": "EXC-100", "suggested_action": ... broken JSON'
    res = validator.validate(punches, malformed_payload, sched, exc)
    assert res.valid is False
    assert res.validation_checks["format_valid"] is False
    assert any(e.code == "INVALID_JSON_FORMAT" for e in res.errors)


def test_check1_missing_required_fields(validator: ProposalValidator, base_context) -> None:
    """Payload missing required fields fails check 1."""
    sched, punches, exc = base_context
    incomplete_dict = {
        "exception_id": "EXC-100",
        # missing suggested_action, proposed_punches, policy_citations, reasoning
    }
    res = validator.validate(punches, incomplete_dict, sched, exc)
    assert res.valid is False
    assert any(e.code == "MISSING_REQUIRED_FIELDS" for e in res.errors)


# -----------------------------------------------------------------
# CHECK 2: POLICY CITATIONS
# -----------------------------------------------------------------
def test_check2_fake_policy_ids_rejected(validator: ProposalValidator, base_context) -> None:
    """Proposals citing non-existent/fabricated policy IDs are rejected."""
    sched, punches, exc = base_context
    payload = {
        "exception_id": "EXC-100",
        "suggested_action": "insert_punch",
        "proposed_punches": [
            {"punch_type": "OUT", "timestamp": "2026-11-07T13:00:00", "action": "insert"}
        ],
        "policy_citations": ["FAKE-POLICY-99", "ATTACK-CLAUSE-01"],
        "reasoning": "Fabricated policies",
    }
    res = validator.validate(punches, payload, sched, exc)
    assert res.valid is False
    assert res.validation_checks["policy_clauses_valid"] is False
    assert any(e.code == "FABRICATED_POLICY_ID" for e in res.errors)
    assert "FAKE-POLICY-99" in res.errors[0].message


def test_check2_no_policy_cited_rejected(validator: ProposalValidator, base_context) -> None:
    """Empty policy citations list is rejected."""
    sched, punches, exc = base_context
    payload = {
        "exception_id": "EXC-100",
        "suggested_action": "insert_punch",
        "proposed_punches": [
            {"punch_type": "OUT", "timestamp": "2026-11-07T13:00:00", "action": "insert"}
        ],
        "policy_citations": [],
        "reasoning": "No policies cited",
    }
    res = validator.validate(punches, payload, sched, exc)
    assert res.valid is False
    assert any(e.code == "NO_POLICY_CITED" for e in res.errors)


# -----------------------------------------------------------------
# CHECK 3: WORKING HOURS RECALCULATION
# -----------------------------------------------------------------
def test_check3_disregards_llm_hallucinated_hours(validator: ProposalValidator) -> None:
    """Validator recalculates hours from timestamps and ignores LLM-stated hours."""
    sched = Schedule(
        employee_id="E-1",
        date="2026-11-07",
        start_time=datetime(2026, 11, 7, 9, 0),
        end_time=datetime(2026, 11, 7, 18, 0),
    )
    punches = [
        Punch(employee_id="E-1", timestamp=datetime(2026, 11, 7, 9, 0), punch_type=PunchType.IN),
    ]
    # LLM claims shift is 4.0 hours, but proposed punch creates 9.0 hours (overtime)
    payload = {
        "exception_id": "EXC-1",
        "suggested_action": "insert_punch",
        "proposed_punches": [
            {"punch_type": "OUT", "timestamp": "2026-11-07T18:00:00", "action": "insert"}
        ],
        "policy_citations": ["PUNCH-01"],
        "reasoning": "Clock-out inserted",
        "raw_llm_hours": 4.0,  # Hallucinated!
    }
    res = validator.validate(punches, payload, sched)
    # Python code calculates 9.0 hours, not 4.0!
    assert res.validated_working_hours == 9.0
    # Overtime limit exceeded (9.0h > 8.0h daily limit without overtime approval)
    assert res.valid is False
    assert any(e.code == "OVERTIME_LIMIT_EXCEEDED" for e in res.errors)


# -----------------------------------------------------------------
# CHECK 4: NEW VIOLATIONS CHECK
# -----------------------------------------------------------------
def test_check4_rejects_proposal_introducing_meal_break_violation(
    validator: ProposalValidator,
) -> None:
    """Fixing missed punch by inserting 8-hour shift without meal break triggers check 4 failure."""
    sched = Schedule(
        employee_id="E-1",
        date="2026-11-07",
        start_time=datetime(2026, 11, 7, 9, 0),
        end_time=datetime(2026, 11, 7, 17, 0),
    )
    punches = [
        Punch(employee_id="E-1", timestamp=datetime(2026, 11, 7, 9, 0), punch_type=PunchType.IN),
    ]
    exc = TimecardException(
        exception_id="EXC-1",
        employee_id="E-1",
        exception_type=ExceptionType.MISSED_PUNCH,
        date="2026-11-07",
        description="Missing clock-out",
        policy_reference="PUNCH-01",
    )
    # 8 hour shift with NO break triggers mandatory meal break violation
    payload = {
        "exception_id": "EXC-1",
        "suggested_action": "insert_punch",
        "proposed_punches": [
            {"punch_type": "OUT", "timestamp": "2026-11-07T17:00:00", "action": "insert"}
        ],
        "policy_citations": ["PUNCH-01"],
        "reasoning": "Inserted clock out at 17:00",
    }
    res = validator.validate(punches, payload, sched, exc)
    assert res.valid is False
    assert res.validation_checks["no_new_violations"] is False
    assert any("NEW_VIOLATION" in e.code for e in res.errors)


# -----------------------------------------------------------------
# CHECK 5: ALLOWED LIMITS & SAFETY
# -----------------------------------------------------------------
def test_check5_excessive_shift_duration_rejected(validator: ProposalValidator) -> None:
    """Gross shift exceeding 16 hours is rejected by limits check."""
    punches = [
        Punch(employee_id="E-1", timestamp=datetime(2026, 11, 7, 6, 0), punch_type=PunchType.IN),
    ]
    payload = {
        "exception_id": "EXC-1",
        "suggested_action": "insert_punch",
        "proposed_punches": [
            {
                "punch_type": "OUT",
                "timestamp": "2026-11-07T23:30:00",
                "action": "insert",
            }  # 17.5 hours
        ],
        "policy_citations": ["PUNCH-01", "OT-01"],
        "reasoning": "Long shift",
    }
    res = validator.validate(punches, payload)
    assert res.valid is False
    assert any(e.code == "EXCESSIVE_SHIFT_DURATION" for e in res.errors)


def test_check5_future_timestamp_rejected(validator: ProposalValidator) -> None:
    """Timestamps in the far future are rejected."""
    future_time = datetime.now() + timedelta(days=10)
    punches = [
        Punch(employee_id="E-1", timestamp=datetime(2026, 11, 7, 9, 0), punch_type=PunchType.IN),
    ]
    payload = {
        "exception_id": "EXC-1",
        "suggested_action": "insert_punch",
        "proposed_punches": [
            {"punch_type": "OUT", "timestamp": future_time.isoformat(), "action": "insert"}
        ],
        "policy_citations": ["PUNCH-01"],
        "reasoning": "Future punch",
    }
    res = validator.validate(punches, payload)
    assert res.valid is False
    assert any(e.code == "FUTURE_TIMESTAMP_PROHIBITED" for e in res.errors)
