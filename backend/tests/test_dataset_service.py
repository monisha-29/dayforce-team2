"""Unit tests for dataset loading service."""

from collections.abc import Generator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.employee import EmployeeModel
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
