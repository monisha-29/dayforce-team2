"""Unit tests for dataset loading service."""

from collections.abc import Generator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.employee import EmployeeModel
from app.models.exception import ExceptionModel
from app.models.punch import PunchModel
from app.models.schedule import ScheduleModel
from app.services.dataset_service import load_dataset_from_dict


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    """Provide an isolated in-memory SQLite session for testing."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestingSession()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)


def test_load_dataset_from_dict_success(db_session: Session) -> None:
    data = {
        "employees": [
            {
                "id": "EMP-TEST-1",
                "name": "Test User",
                "department": "Engineering",
                "shift": "Standard",
                "shift_start": "09:00",
                "shift_end": "17:00",
            }
        ],
        "schedules": [
            {
                "id": "SCHED-TEST-1",
                "employee_id": "EMP-TEST-1",
                "date": "2026-11-08",
                "start_time": "2026-11-08T09:00:00",
                "end_time": "2026-11-08T17:00:00",
                "department_id": "ENG",
                "scheduled_break_minutes": 30,
            }
        ],
        "punches": [
            {
                "id": "PUNCH-TEST-1",
                "employee_id": "EMP-TEST-1",
                "timestamp": "2026-11-08T09:01:00",
                "punch_type": "IN",
                "source": "terminal",
            }
        ],
        "exceptions": [
            {
                "id": "EXC-TEST-1",
                "employee_id": "EMP-TEST-1",
                "type": "missed_punch",
                "date": "2026-11-08",
                "severity": "medium",
                "status": "pending_review",
                "description": "Missing punch test",
                "original_attendance": {"checkIn": "09:01"},
                "policy_reference": "PUNCH-01",
            }
        ],
    }

    result = load_dataset_from_dict(db_session, data)
    assert result.employees_loaded == 1
    assert result.schedules_loaded == 1
    assert result.punches_loaded == 1
    assert result.exceptions_loaded == 1
    assert result.errors == []
    assert result.total_loaded == 4

    # Verify query
    emp = db_session.get(EmployeeModel, "EMP-TEST-1")
    assert emp is not None
    assert emp.name == "Test User"
    assert len(emp.schedules) == 1
    assert len(emp.punches) == 1
    assert len(emp.exceptions) == 1


def test_load_dataset_idempotent(db_session: Session) -> None:
    data = {
        "employees": [
            {
                "id": "EMP-IDEM",
                "name": "Idempotent User",
                "department": "Security",
                "shift": "Night",
                "shift_start": "22:00",
                "shift_end": "06:00",
            }
        ]
    }

    res1 = load_dataset_from_dict(db_session, data)
    assert res1.employees_loaded == 1
    assert res1.skipped_count == 0

    # Second load must skip duplicate
    res2 = load_dataset_from_dict(db_session, data)
    assert res2.employees_loaded == 0
    assert res2.skipped_count == 1
    assert res2.errors == []


def test_load_dataset_relational_validation_error(db_session: Session) -> None:
    # Schedule references nonexistent employee
    data = {
        "schedules": [
            {
                "id": "SCHED-ORPHAN",
                "employee_id": "NONEXISTENT-EMP",
                "date": "2026-11-08",
                "start_time": "2026-11-08T09:00:00",
                "end_time": "2026-11-08T17:00:00",
            }
        ]
    }

    res = load_dataset_from_dict(db_session, data)
    assert res.schedules_loaded == 0
    assert len(res.errors) == 1
    assert "NONEXISTENT-EMP" in res.errors[0]
    assert res.total_errors == 1


def test_load_dataset_updates_existing_records(db_session: Session) -> None:
    """Verify distinguishing newly inserted, existing updated, and genuinely skipped."""
    initial_data = {
        "employees": [
            {
                "id": "EMP-UPDATE-1",
                "name": "Initial Name",
                "department": "Engineering",
                "shift": "Standard",
                "shift_start": "09:00",
                "shift_end": "17:00",
            }
        ],
        "schedules": [
            {
                "id": "SCHED-UPDATE-1",
                "employee_id": "EMP-UPDATE-1",
                "date": "2026-11-08",
                "start_time": "2026-11-08T09:00:00",
                "end_time": "2026-11-08T17:00:00",
                "department_id": "ENG",
                "scheduled_break_minutes": 30,
            }
        ],
        "punches": [
            {
                "id": "PUNCH-UPDATE-1",
                "employee_id": "EMP-UPDATE-1",
                "timestamp": "2026-11-08T09:01:00",
                "punch_type": "IN",
                "source": "terminal",
                "notes": "Original note",
            }
        ],
        "exceptions": [
            {
                "id": "EXC-UPDATE-1",
                "employee_id": "EMP-UPDATE-1",
                "type": "missed_punch",
                "date": "2026-11-08",
                "severity": "medium",
                "status": "pending_review",
                "description": "Original description",
                "original_attendance": {"checkIn": "09:01"},
                "policy_reference": "PUNCH-01",
                "detected_at": "2026-11-08T17:05:00",
            }
        ],
    }

    # 1. First load: all 4 records are newly inserted
    res1 = load_dataset_from_dict(db_session, initial_data)
    assert res1.employees_loaded == 1
    assert res1.schedules_loaded == 1
    assert res1.punches_loaded == 1
    assert res1.exceptions_loaded == 1
    assert res1.employees_updated == 0
    assert res1.schedules_updated == 0
    assert res1.punches_updated == 0
    assert res1.exceptions_updated == 0
    assert res1.skipped_count == 0
    assert res1.total_inserted == 4
    assert res1.total_updated == 0
    assert res1.total_skipped == 0
    assert res1.total_loaded == 4
    assert res1.errors == []

    # 2. Second load with modified fields: all 4 records should be counted as updated
    modified_data = {
        "employees": [
            {
                "id": "EMP-UPDATE-1",
                "name": "Updated Name",
                "department": "Platform Eng",
                "shift": "Flexible",
                "shift_start": "08:30",
                "shift_end": "16:30",
            }
        ],
        "schedules": [
            {
                "id": "SCHED-UPDATE-1",
                "employee_id": "EMP-UPDATE-1",
                "date": "2026-11-08",
                "start_time": "2026-11-08T08:30:00",
                "end_time": "2026-11-08T16:30:00",
                "department_id": "PLT",
                "scheduled_break_minutes": 45,
            }
        ],
        "punches": [
            {
                "id": "PUNCH-UPDATE-1",
                "employee_id": "EMP-UPDATE-1",
                "timestamp": "2026-11-08T08:31:00",
                "punch_type": "IN",
                "source": "mobile_app",
                "notes": "Updated note",
            }
        ],
        "exceptions": [
            {
                "id": "EXC-UPDATE-1",
                "employee_id": "EMP-UPDATE-1",
                "type": "tardiness",
                "date": "2026-11-08",
                "severity": "high",
                "status": "pending_review",
                "description": "Updated description",
                "original_attendance": {"checkIn": "08:31"},
                "policy_reference": "TARDY-01",
                "detected_at": "2026-11-08T17:05:00",
            }
        ],
    }

    res2 = load_dataset_from_dict(db_session, modified_data)
    assert res2.employees_loaded == 0
    assert res2.schedules_loaded == 0
    assert res2.punches_loaded == 0
    assert res2.exceptions_loaded == 0
    assert res2.employees_updated == 1
    assert res2.schedules_updated == 1
    assert res2.punches_updated == 1
    assert res2.exceptions_updated == 1
    assert res2.skipped_count == 0
    assert res2.total_inserted == 0
    assert res2.total_updated == 4
    assert res2.total_skipped == 0
    assert res2.total_loaded == 4
    assert res2.errors == []

    # Verify changes persisted to the database
    emp = db_session.get(EmployeeModel, "EMP-UPDATE-1")
    assert emp is not None
    assert emp.name == "Updated Name"
    assert emp.department == "Platform Eng"

    sched = db_session.get(ScheduleModel, "SCHED-UPDATE-1")
    assert sched is not None
    assert sched.scheduled_break_minutes == 45
    assert sched.department_id == "PLT"

    punch = db_session.get(PunchModel, "PUNCH-UPDATE-1")
    assert punch is not None
    assert punch.source == "mobile_app"
    assert punch.notes == "Updated note"

    exc = db_session.get(ExceptionModel, "EXC-UPDATE-1")
    assert exc is not None
    assert exc.type == "tardiness"
    assert exc.severity == "high"
    assert exc.description == "Updated description"

    # 3. Third load with identical modified_data: all 4 records must be genuinely skipped
    res3 = load_dataset_from_dict(db_session, modified_data)
    assert res3.employees_loaded == 0
    assert res3.schedules_loaded == 0
    assert res3.punches_loaded == 0
    assert res3.exceptions_loaded == 0
    assert res3.employees_updated == 0
    assert res3.schedules_updated == 0
    assert res3.punches_updated == 0
    assert res3.exceptions_updated == 0
    assert res3.skipped_count == 4
    assert res3.total_inserted == 0
    assert res3.total_updated == 0
    assert res3.total_skipped == 4
    assert res3.errors == []

    # 4. Partial update: only employee changed, others identical
    partial_data = {
        "employees": [
            {
                "id": "EMP-UPDATE-1",
                "name": "Final Employee Name",
                "department": "Platform Eng",
                "shift": "Flexible",
                "shift_start": "08:30",
                "shift_end": "16:30",
            }
        ],
        "schedules": modified_data["schedules"],
        "punches": modified_data["punches"],
        "exceptions": modified_data["exceptions"],
    }
    res4 = load_dataset_from_dict(db_session, partial_data)
    assert res4.employees_loaded == 0
    assert res4.employees_updated == 1
    assert res4.schedules_updated == 0
    assert res4.punches_updated == 0
    assert res4.exceptions_updated == 0
    assert res4.skipped_count == 3
    assert res4.total_inserted == 0
    assert res4.total_updated == 1
    assert res4.total_skipped == 3
    assert res4.errors == []


def test_load_dataset_validation_errors(db_session: Session) -> None:
    """Verify validation errors are captured and reported."""
    # 1. Invalid root type
    res_invalid_root = load_dataset_from_dict(db_session, "not-a-dict")  # type: ignore[arg-type]
    assert len(res_invalid_root.errors) == 1
    assert "must be a dictionary" in res_invalid_root.errors[0]

    # 2. Missing ID in employee
    data_bad_emp = {"employees": [{"name": "No ID User"}]}
    res_bad_emp = load_dataset_from_dict(db_session, data_bad_emp)
    assert len(res_bad_emp.errors) == 1
    assert "missing required 'id'" in res_bad_emp.errors[0]

    # 3. Invalid datetime in schedule
    emp_data = {
        "employees": [
            {
                "id": "EMP-ERR-1",
                "name": "Err User",
                "department": "QA",
                "shift": "Day",
                "shift_start": "09:00",
                "shift_end": "17:00",
            }
        ]
    }
    load_dataset_from_dict(db_session, emp_data)

    data_bad_sched = {
        "schedules": [
            {
                "id": "SCHED-BAD-DATE",
                "employee_id": "EMP-ERR-1",
                "start_time": "invalid-datetime-string",
                "end_time": "2026-11-08T17:00:00",
            }
        ]
    }
    res_bad_sched = load_dataset_from_dict(db_session, data_bad_sched)
    assert len(res_bad_sched.errors) == 1
    assert "invalid start/end datetime" in res_bad_sched.errors[0]
