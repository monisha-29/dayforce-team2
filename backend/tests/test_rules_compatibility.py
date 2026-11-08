"""Tests for rules adapter compatibility bridges, fallback 5.0h boundary, and Person 3 integration."""

import io
import os
import subprocess
import tempfile
import zipfile
from datetime import UTC, datetime
from typing import Any

import pytest

from app.schemas.proposal import ValidatorName
from app.services.detector_service import (
    convert_detector_exception_to_model,
    generate_deterministic_exception_id,
)
from app.services.rules_adapter import (
    generate_fallback_proposal,
    llm_proposal_to_timecard,
    timecard_to_llm_proposal,
    validate_timecard_proposal,
    validation_result_to_validator_results,
)

# =============================================================================
# 1. TEST FALLBACK 5.0-HOUR BOUNDARY RULE
# =============================================================================

def test_fallback_missed_punch_under_5_hours() -> None:
    """Gross shift < 5.0h allows inferring clock-out from schedule without break fabrication."""
    original_attendance = {
        "checkIn": "09:00",
        "checkOut": None,
        "mealStart": None,
        "mealEnd": None,
    }
    # 09:00 to 13:00 = 4.0 hours (< 5.0h)
    fb = generate_fallback_proposal(
        exception_type="missed_punch",
        original_attendance=original_attendance,
        schedule_start="09:00",
        schedule_end="13:00",
        policy_clause_id="PUNCH-02",
    )
    assert fb["blocked"] is False
    assert fb["proposed_timecard"]["checkOut"] == "13:00"
    assert fb["proposed_timecard"]["totalHours"] == 4.0
    assert "checkOut" in fb["changed_fields"]
    assert fb["confidence"] >= 0.8


def test_fallback_missed_punch_exact_5_hours_without_break_escalates() -> None:
    """Gross shift == 5.0h with no recorded break MUST escalate to manager."""
    original_attendance = {
        "checkIn": "09:00",
        "checkOut": None,
        "mealStart": None,
        "mealEnd": None,
    }
    # 09:00 to 14:00 = 5.0 hours (>= 5.0h boundary)
    fb = generate_fallback_proposal(
        exception_type="missed_punch",
        original_attendance=original_attendance,
        schedule_start="09:00",
        schedule_end="14:00",
        policy_clause_id="PUNCH-02",
    )
    assert fb["blocked"] is True
    assert fb["proposed_timecard"]["checkOut"] is None
    assert "5.0h" in fb["reason"]
    assert "fabricat" in fb["reason"].lower()
    assert fb["changed_fields"] == []
    assert len(fb["missing_information"]) > 0


def test_fallback_missed_punch_over_5_hours_without_break_escalates() -> None:
    """Gross shift > 5.0h (e.g. 8h) with no break MUST escalate to manager."""
    original_attendance = {
        "checkIn": "09:00",
        "checkOut": None,
        "mealStart": None,
        "mealEnd": None,
    }
    # 09:00 to 17:00 = 8.0 hours
    fb = generate_fallback_proposal(
        exception_type="missed_punch",
        original_attendance=original_attendance,
        schedule_start="09:00",
        schedule_end="17:00",
        policy_clause_id="PUNCH-02",
    )
    assert fb["blocked"] is True
    assert "fabricat" in fb["reason"].lower()
    assert fb["blocked"] is True


def test_fallback_missed_punch_over_5_hours_with_break_allows_proposal() -> None:
    """Gross shift >= 5.0h with already recorded meal break does not need break fabrication."""
    original_attendance = {
        "checkIn": "09:00",
        "checkOut": None,
        "mealStart": "12:00",
        "mealEnd": "12:30",
    }
    # 09:00 to 17:00 = 8.0h gross, 7.5h net with break
    fb = generate_fallback_proposal(
        exception_type="missed_punch",
        original_attendance=original_attendance,
        schedule_start="09:00",
        schedule_end="17:00",
        policy_clause_id="PUNCH-02",
    )
    assert fb["blocked"] is False
    assert fb["proposed_timecard"]["checkOut"] == "17:00"
    assert fb["proposed_timecard"]["totalHours"] == 7.5
    assert "checkOut" in fb["changed_fields"]


def test_fallback_meal_break_never_fabricates_punches() -> None:
    """Meal break violations must always escalate; code never invents break punches."""
    original_attendance = {
        "checkIn": "09:00",
        "checkOut": "17:00",
        "mealStart": None,
        "mealEnd": None,
    }
    fb = generate_fallback_proposal(
        exception_type="meal_break",
        original_attendance=original_attendance,
        schedule_start="09:00",
        schedule_end="17:00",
        policy_clause_id="MEAL-01",
    )
    assert fb["blocked"] is True
    assert "fabricating" in fb["reason"].lower()
    assert fb["proposed_timecard"]["mealStart"] is None
    assert fb["proposed_timecard"]["mealEnd"] is None


# =============================================================================
# 2. TEST PROPOSAL REPRESENTATION TRANSLATION (TIMECARD <-> LLM_PROPOSAL)
# =============================================================================

def test_timecard_to_llm_proposal_translation() -> None:
    """timecard_to_llm_proposal should produce discrete ProposedPunch operations."""
    proposed_tc = {
        "checkIn": "09:00",
        "checkOut": "17:00",
        "mealStart": "12:00",
        "mealEnd": "12:30",
        "totalHours": 7.5,
    }
    changed_fields = ["checkOut", "mealEnd"]

    proposal = timecard_to_llm_proposal(
        exception_id="EXC-123",
        proposed_tc=proposed_tc,
        changed_fields=changed_fields,
        policy_id="PUNCH-02",
        reasoning="Correct missing punch and short break.",
        shift_date="2026-11-02",
        employee_id="EMP001",
    )

    assert proposal.exception_id == "EXC-123"
    assert len(proposal.proposed_punches) == 2

    p_types = [str(getattr(p.punch_type, "value", p.punch_type)) for p in proposal.proposed_punches]
    assert "OUT" in p_types
    assert "BREAK_END" in p_types


def test_llm_proposal_to_timecard_translation() -> None:
    """llm_proposal_to_timecard converts discrete punches back to consolidated timecard."""
    class DummyPunch:
        def __init__(self, pt: str, dt: datetime) -> None:
            self.punch_type = pt
            self.timestamp = dt

    class DummyProposal:
        def __init__(self) -> None:
            self.proposed_punches = [
                DummyPunch("OUT", datetime(2026, 11, 2, 17, 0)),
                DummyPunch("BREAK_END", datetime(2026, 11, 2, 12, 30)),
            ]

    orig_tc = {
        "checkIn": "09:00",
        "checkOut": None,
        "mealStart": "12:00",
        "mealEnd": None,
    }

    updated_tc, changed_fields = llm_proposal_to_timecard(DummyProposal(), orig_tc)
    assert updated_tc["checkOut"] == "17:00"
    assert updated_tc["mealEnd"] == "12:30"
    assert "checkOut" in changed_fields
    assert "mealEnd" in changed_fields
    assert updated_tc["totalHours"] == 7.5


# =============================================================================
# 3. TEST VALIDATION RESULT REPRESENTATION TRANSLATION
# =============================================================================

def test_validation_result_to_validator_results_mapping() -> None:
    """Translates Person 3's 5 validation checks to frontend display names."""
    class DummyCheckDetail:
        def __init__(self, name: str, passed: bool, msg: str) -> None:
            self.check_name = name
            self.passed = passed
            self.message = msg

    class DummyValidationResult:
        def __init__(self) -> None:
            self.validation_checks = {
                "format_valid": True,
                "policy_clauses_valid": True,
                "working_hours_valid": False,
                "no_new_violations": False,
                "limits_valid": True,
            }
            self.check_details = [
                DummyCheckDetail("format_valid", True, "JSON schema passed"),
                DummyCheckDetail("policy_clauses_valid", True, "Policy exists"),
                DummyCheckDetail("working_hours_valid", False, "Math error"),
                DummyCheckDetail("no_new_violations", False, "Introduces overtime"),
                DummyCheckDetail("limits_valid", True, "Within limits"),
            ]
            self.errors = []

    res = validation_result_to_validator_results(DummyValidationResult())
    assert len(res) == 5

    name_map = {r.name: r for r in res}
    assert name_map[ValidatorName.SCHEMA_VALIDATION.value].passed is True
    assert name_map[ValidatorName.POLICY_CITATION_VALIDATION.value].passed is True
    assert name_map[ValidatorName.WORKING_HOURS_VALIDATION.value].passed is False
    assert name_map[ValidatorName.NEW_VIOLATION_CHECK.value].passed is False
    assert name_map[ValidatorName.VALUE_BOUNDS_CHECK.value].passed is True


# =============================================================================
# 4. TEST MULTI-DETECTOR NEW VIOLATION DETECTION IN STANDALONE VALIDATOR
# =============================================================================

def test_standalone_validator_detects_unauthorized_overtime() -> None:
    """Proposal exceeding 8.0h daily limit without overtime exception fails Check 4."""
    summary = validate_timecard_proposal(
        proposed_tc={"checkIn": "09:00", "checkOut": "18:00"},  # 9.0 hours
        cited_clause_id="POL-ATT-001",
        reasoning="Extended work shift.",
        original_type="missed_punch",
    )
    assert summary.valid is False
    new_violation_check = next(
        v for v in summary.validators if v.name == ValidatorName.NEW_VIOLATION_CHECK.value
    )
    assert new_violation_check.passed is False
    assert "overtime" in new_violation_check.reason.lower()


def test_standalone_validator_detects_missing_meal_break_on_long_shift() -> None:
    """Proposal >= 5.0h with no meal break fails Check 4."""
    summary = validate_timecard_proposal(
        proposed_tc={"checkIn": "09:00", "checkOut": "14:30"},  # 5.5 hours without break
        cited_clause_id="POL-ATT-001",
        reasoning="Five and a half hour shift.",
        original_type="missed_punch",
    )
    assert summary.valid is False
    new_violation_check = next(
        v for v in summary.validators if v.name == ValidatorName.NEW_VIOLATION_CHECK.value
    )
    assert new_violation_check.passed is False
    assert "meal break" in new_violation_check.reason.lower()


def test_standalone_validator_detects_excessive_shift_duration_cap() -> None:
    """Proposal exceeding 16.0h safety cap fails Check 4."""
    summary = validate_timecard_proposal(
        proposed_tc={"checkIn": "06:00", "checkOut": "23:00"},  # 17.0 hours
        cited_clause_id="POL-ATT-001",
        reasoning="Very long shift.",
        original_type="overtime",
    )
    assert summary.valid is False
    new_violation_check = next(
        v for v in summary.validators if v.name == ValidatorName.NEW_VIOLATION_CHECK.value
    )
    assert new_violation_check.passed is False
    assert "16h" in new_violation_check.reason


# =============================================================================
# 5. TEST DETECTOR INTEGRATION AND STATUS MAPPING
# =============================================================================

def test_detector_exception_status_mapping() -> None:
    """Detector status 'open' maps to backend status 'pending_review'."""
    class DummyTimecardException:
        def __init__(self) -> None:
            self.exception_id = "EXC-1234567890AB"
            self.employee_id = "EMP001"
            self.exception_type = "missed_punch"
            self.date = "2026-11-02"
            self.severity = "high"
            self.status = "open"  # Person 3 detector output
            self.description = "Employee missed punch"
            self.original_attendance = {"checkIn": "09:00"}
            self.policy_reference = "PUNCH-01"
            self.created_at = datetime.now(UTC)

    model = convert_detector_exception_to_model(DummyTimecardException())
    assert model.status == "pending_review"
    assert model.id == "EXC-1234567890AB"
    assert model.severity == "high"


def test_deterministic_exception_id_consistency() -> None:
    """Deterministic ID matches Person 3 UUIDv5 specification."""
    id1 = generate_deterministic_exception_id("EMP001", "2026-11-02", "missed_punch")
    id2 = generate_deterministic_exception_id("EMP001", "2026-11-02", "missed_punch")
    assert id1 == id2
    assert id1.startswith("EXC-")
    assert len(id1) == 16  # EXC- + 12 hex chars


# =============================================================================
# 6. INTEGRATION WITH PERSON 3'S ACTUAL MODULE (EXTRACTED VIA GIT ARCHIVE)
# =============================================================================

@pytest.fixture(scope="module")
def person3_rules_module() -> Any:
    """Safely extracts Person 3's backend/app/rules from origin/feature/rules-validation.

    Does NOT merge branches or modify working directory files.
    """
    try:
        data = subprocess.check_output(
            ["git", "archive", "--format=zip", "origin/feature/rules-validation", "backend/app/rules"],
            stderr=subprocess.PIPE,
        )
    except subprocess.CalledProcessError:
        pytest.skip("origin/feature/rules-validation remote branch not available for integration test.")

    temp_dir = tempfile.mkdtemp()
    z = zipfile.ZipFile(io.BytesIO(data))
    z.extractall(temp_dir)

    rules_parent = os.path.join(temp_dir, "backend", "app")
    import app
    app.__path__.append(rules_parent)

    import importlib

    import app.rules

    from app.services import detector_service, rules_adapter
    importlib.reload(detector_service)
    importlib.reload(rules_adapter)

    yield app.rules

    # Cleanup
    if rules_parent in app.__path__:
        app.__path__.remove(rules_parent)


def test_person3_validator_direct_integration(person3_rules_module: Any) -> None:
    """Test proposal validation against Person 3's real ProposalValidator."""
    from app.rules.models.exception import (
        ExceptionType,
        Punch,
        PunchType,
        Schedule,
        Severity,
        TimecardException,
    )

    from app.services.rules_adapter import validate_timecard_proposal

    orig_in = Punch(
        id="P-1",
        employee_id="EMP001",
        timestamp=datetime(2026, 11, 2, 9, 0),
        punch_type=PunchType.IN,
    )
    sched = Schedule(
        id="S-1",
        employee_id="EMP001",
        date="2026-11-02",
        start_time=datetime(2026, 11, 2, 9, 0),
        end_time=datetime(2026, 11, 2, 13, 0),
    )
    exc = TimecardException(
        exception_id="EXC-001",
        employee_id="EMP001",
        exception_type=ExceptionType.MISSED_PUNCH,
        date="2026-11-02",
        severity=Severity.HIGH,
        description="Missing clock-out punch",
        policy_reference="PUNCH-02",
    )

    # 4-hour shift resolution: 09:00 to 13:00 with cited policy PUNCH-02
    summary = validate_timecard_proposal(
        proposed_tc={"checkIn": "09:00", "checkOut": "13:00"},
        cited_clause_id="PUNCH-02",
        reasoning="Deterministic resolution aligned with scheduled end time.",
        original_type="missed_punch",
        schedule_start="09:00",
        schedule_end="13:00",
        original_punches=[orig_in],
        original_schedule=sched,
        original_exception=exc,
        changed_fields=["checkOut"],
    )

    assert summary.valid is True
    assert summary.status == "PASSED"
    assert summary.blocked is False
    assert len(summary.validators) == 5
    assert all(v.passed for v in summary.validators)


def test_person3_fallback_engine_direct_integration(person3_rules_module: Any) -> None:
    """Test fallback generation against Person 3's real FallbackEngine at the 5.0h boundary."""
    from app.rules.fallback import FallbackEngine
    from app.rules.models.exception import (
        ExceptionType,
        Punch,
        PunchType,
        Schedule,
        Severity,
        TimecardException,
    )

    engine = FallbackEngine()

    orig_in = Punch(
        id="P-1",
        employee_id="EMP001",
        timestamp=datetime(2026, 11, 2, 9, 0),
        punch_type=PunchType.IN,
    )
    # 5.0-hour shift without break
    sched_5h = Schedule(
        id="S-1",
        employee_id="EMP001",
        date="2026-11-02",
        start_time=datetime(2026, 11, 2, 9, 0),
        end_time=datetime(2026, 11, 2, 14, 0),
    )
    exc = TimecardException(
        exception_id="EXC-001",
        employee_id="EMP001",
        exception_type=ExceptionType.MISSED_PUNCH,
        date="2026-11-02",
        severity=Severity.HIGH,
        description="Missing clock-out punch",
        policy_reference="PUNCH-02",
    )

    result_5h = engine.generate_fallback(exc, [orig_in], sched_5h)
    assert result_5h.success is False
    assert "5.0h" in result_5h.reason
    assert "fabricat" in result_5h.reason.lower()

    # 4.0-hour shift allows inferring clock-out
    sched_4h = Schedule(
        id="S-2",
        employee_id="EMP001",
        date="2026-11-02",
        start_time=datetime(2026, 11, 2, 9, 0),
        end_time=datetime(2026, 11, 2, 13, 0),
    )
    result_4h = engine.generate_fallback(exc, [orig_in], sched_4h)
    assert result_4h.success is True
    assert result_4h.proposed_correction is not None


def test_person3_detect_all_exceptions_pipeline_integration(person3_rules_module: Any) -> None:
    """Test full database detection pipeline with Person 3's real detect_all_exceptions."""
    from app.rules.detectors import detect_all_exceptions
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.database import Base
    from app.models.employee import EmployeeModel
    from app.models.exception import ExceptionModel
    from app.models.punch import PunchModel
    from app.models.schedule import ScheduleModel
    from app.services.detector_service import run_detection_pipeline

    test_engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=test_engine)

    with Session(test_engine) as session:
        # Create employee, schedule, and in-only punch (missed punch)
        emp = EmployeeModel(
            id="EMP-COMPAT-1",
            name="Alice Smith",
            department="Engineering",
            shift="Day",
            shift_start="09:00",
            shift_end="17:00",
        )
        sched = ScheduleModel(
            id="SCHED-COMPAT-1",
            employee_id="EMP-COMPAT-1",
            date="2026-11-02",
            start_time=datetime(2026, 11, 2, 9, 0),
            end_time=datetime(2026, 11, 2, 17, 0),
            scheduled_break_minutes=30,
        )
        punch_in = PunchModel(
            id="PUNCH-COMPAT-1",
            employee_id="EMP-COMPAT-1",
            punch_type="IN",
            timestamp=datetime(2026, 11, 2, 9, 0),
            source="terminal",
        )
        session.add_all([emp, sched, punch_in])
        session.commit()

        # Run detection pipeline using Person 3's detect_all_exceptions
        summary1 = run_detection_pipeline(
            session=session,
            detector_fn=detect_all_exceptions,
        )

        assert summary1.detected_count >= 1
        assert summary1.newly_saved_count >= 1
        assert summary1.duplicate_skipped_count == 0

        # Verify saved ExceptionModel properties
        saved_exceptions = session.query(ExceptionModel).filter(ExceptionModel.employee_id == "EMP-COMPAT-1").all()
        assert len(saved_exceptions) >= 1
        saved = saved_exceptions[0]
        assert saved.status == "pending_review"  # 'open' mapped to 'pending_review'
        assert saved.id.startswith("EXC-")
        assert saved.type == "missed_punch"

        # Idempotency: re-running pipeline skips duplicates
        summary2 = run_detection_pipeline(
            session=session,
            detector_fn=detect_all_exceptions,
        )
        assert summary2.newly_saved_count == 0
        assert summary2.duplicate_skipped_count == summary1.detected_count

