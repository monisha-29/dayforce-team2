"""Tests for detector integration service and database synchronization."""

from datetime import datetime
from typing import Any

import pytest
from pydantic import BaseModel
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.database import Base
from app.models.employee import EmployeeModel
from app.models.exception import ExceptionModel
from app.models.punch import PunchModel
from app.models.schedule import ScheduleModel
from app.services.detector_service import (
    DetectionSummary,
    RulesModuleNotAvailableError,
    convert_detector_exception_to_model,
    generate_deterministic_exception_id,
    run_detection_pipeline,
    to_detector_punch,
    to_detector_schedule,
)


class MockDetectorException(BaseModel):
    """Synthetic exception matching Person 3's TimecardException interface."""

    exception_id: str
    employee_id: str
    exception_type: str
    date: str
    severity: str = "high"
    description: str
    original_attendance: dict[str, Any] = {}
    policy_reference: str
    status: str = "open"
    created_at: datetime = datetime(2026, 11, 8, 8, 15, 0)


@pytest.fixture
def sqlite_session() -> Session:
    """Provide a clean in-memory SQLite database session."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = TestingSession()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)


def test_punch_and_schedule_conversion() -> None:
    """Verify SQLAlchemy models convert accurately to detector Pydantic models."""
    now = datetime(2026, 11, 8, 9, 0, 0)

    punch_model = PunchModel(
        id="PUNCH-101",
        employee_id="EMP-1042",
        timestamp=now,
        punch_type="IN",
        source="terminal",
        notes="Card swipe",
    )
    det_punch = to_detector_punch(punch_model)
    assert det_punch.id == "PUNCH-101"
    assert det_punch.employee_id == "EMP-1042"
    assert det_punch.timestamp == now
    assert str(det_punch.punch_type) in ("IN", "PunchType.IN")
    assert det_punch.source == "terminal"
    assert det_punch.notes == "Card swipe"

    sched_model = ScheduleModel(
        id="SCHED-202",
        employee_id="EMP-1042",
        date="2026-11-08",
        start_time=datetime(2026, 11, 8, 9, 0, 0),
        end_time=datetime(2026, 11, 8, 18, 0, 0),
        department_id="DEP-OPS",
        scheduled_break_minutes=30,
    )
    det_sched = to_detector_schedule(sched_model)
    assert det_sched.id == "SCHED-202"
    assert det_sched.employee_id == "EMP-1042"
    assert det_sched.date == "2026-11-08"
    assert det_sched.start_time == datetime(2026, 11, 8, 9, 0, 0)
    assert det_sched.scheduled_break_minutes == 30


def test_deterministic_exception_id_generation() -> None:
    """Verify deterministic exception ID generation is reproducible and formatted."""
    id1 = generate_deterministic_exception_id(
        "EMP-1042", "2026-11-08", "missed_punch", "missing_out"
    )
    id2 = generate_deterministic_exception_id(
        "EMP-1042", "2026-11-08", "missed_punch", "missing_out"
    )
    id3 = generate_deterministic_exception_id("EMP-1042", "2026-11-08", "overtime", "daily_ot")

    assert id1 == id2, "Same inputs must produce identical exception IDs"
    assert id1 != id3, "Different inputs must produce distinct exception IDs"
    assert id1.startswith("EXC-")
    assert len(id1) == 16  # "EXC-" + 12 hex characters


def test_convert_detector_exception_status_mapping() -> None:
    """Verify detector status 'open' maps to backend status 'pending_review'."""
    raw = MockDetectorException(
        exception_id="EXC-1234567890AB",
        employee_id="EMP-1042",
        exception_type="missed_punch",
        date="2026-11-08",
        severity="HIGH",
        description="Missing check-out punch",
        original_attendance={"check_in": "09:00", "check_out": None},
        policy_reference="PUNCH-01",
        status="open",
    )
    model = convert_detector_exception_to_model(raw)
    assert model.id == "EXC-1234567890AB"
    assert model.employee_id == "EMP-1042"
    assert model.type == "missed_punch"
    assert model.severity == "high"
    assert model.status == "pending_review", "Status 'open' must map to 'pending_review'"
    assert model.policy_reference == "PUNCH-01"
    assert model.original_attendance["check_in"] == "09:00"


def test_run_detection_pipeline_with_mock_detector(sqlite_session: Session) -> None:
    """Verify the pipeline executes detection, saves exceptions, and handles deduplication."""
    # 1. Setup employee and schedule in DB
    emp = EmployeeModel(
        id="EMP-1042",
        name="Aarav Mehta",
        department="Operations",
        shift="Day Shift",
        shift_start="09:00",
        shift_end="18:00",
    )
    sqlite_session.add(emp)

    sched = ScheduleModel(
        id="SCHED-1",
        employee_id=emp.id,
        date="2026-11-08",
        start_time=datetime(2026, 11, 8, 9, 0, 0),
        end_time=datetime(2026, 11, 8, 18, 0, 0),
    )
    sqlite_session.add(sched)

    punch = PunchModel(
        id="PUNCH-1",
        employee_id=emp.id,
        timestamp=datetime(2026, 11, 8, 9, 0, 0),
        punch_type="IN",
        source="terminal",
    )
    sqlite_session.add(punch)
    sqlite_session.commit()

    # 2. Mock detector function representing Person 3's detect_all_exceptions
    def mock_detector(punches: list[Any], schedules: list[Any]) -> list[Any]:
        assert len(punches) == 1
        assert len(schedules) == 1
        exc_id = generate_deterministic_exception_id("EMP-1042", "2026-11-08", "missed_punch")
        return [
            MockDetectorException(
                exception_id=exc_id,
                employee_id="EMP-1042",
                exception_type="missed_punch",
                date="2026-11-08",
                severity="HIGH",
                description="Missing clock-out punch",
                original_attendance={"check_in": "09:00"},
                policy_reference="PUNCH-01",
                status="open",
            )
        ]

    # 3. First execution: should save 1 new exception
    summary1 = run_detection_pipeline(sqlite_session, detector_fn=mock_detector)
    assert isinstance(summary1, DetectionSummary)
    assert summary1.detected_count == 1
    assert summary1.newly_saved_count == 1
    assert summary1.duplicate_skipped_count == 0

    # Verify exception is actually in database
    saved_exc = sqlite_session.query(ExceptionModel).filter_by(employee_id="EMP-1042").first()
    assert saved_exc is not None
    assert saved_exc.status == "pending_review"
    assert saved_exc.type == "missed_punch"
    assert saved_exc.policy_reference == "PUNCH-01"

    # 4. Second execution with same data: should detect 1 but skip saving duplicates
    summary2 = run_detection_pipeline(sqlite_session, detector_fn=mock_detector)
    assert summary2.detected_count == 1
    assert summary2.newly_saved_count == 0
    assert summary2.duplicate_skipped_count == 1

    # Total exceptions in DB remains 1
    total = sqlite_session.query(ExceptionModel).count()
    assert total == 1


def test_rules_module_not_available_error_raised_when_unmerged(sqlite_session: Session) -> None:
    """Verify that calling detection without an injected function raises clean error if rules unmerged."""
    from app.services.detector_service import RULES_MODULE_AVAILABLE

    if not RULES_MODULE_AVAILABLE:
        with pytest.raises(RulesModuleNotAvailableError) as exc_info:
            run_detection_pipeline(sqlite_session, detector_fn=None)
        assert "Person 3's rules engine" in str(exc_info.value)
