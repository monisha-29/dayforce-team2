"""Tests for POST /api/v1/proposals/{id}/decision endpoint."""

from collections.abc import Generator
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models.employee import EmployeeModel
from app.models.exception import ExceptionModel
from app.models.proposal import ProposalModel
from app.models.punch import PunchModel


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    """Provide an in-memory SQLite database for testing API endpoints."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestingSessionLocal()

    def override_get_db() -> Generator[Session, None, None]:
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)
        app.dependency_overrides.clear()


@pytest.fixture
def client(db_session: Session) -> TestClient:
    return TestClient(app)


def seed_test_records(session: Session) -> tuple[EmployeeModel, ExceptionModel, ProposalModel]:
    emp = EmployeeModel(
        id="EMP-TEST-PROP",
        name="Jordan Lee",
        department="Operations",
        shift="Day",
        shift_start="09:00",
        shift_end="17:00",
    )
    session.add(emp)

    exc = ExceptionModel(
        id="EXC-TEST-PROP",
        employee_id=emp.id,
        type="missed_punch",
        date="2026-11-08",
        severity="medium",
        status="awaiting_approval",
        description="Missing clock-out punch",
        original_attendance={"checkIn": "09:00", "checkOut": None},
        policy_reference="PUNCH-01",
        detected_at=datetime(2026, 11, 8, 17, 30, 0),
    )
    session.add(exc)

    prop = ProposalModel(
        id="PROP-TEST-001",
        exception_id=exc.id,
        proposed_timecard={
            "checkIn": "09:00",
            "checkOut": "17:00",
            "mealStart": "13:00",
            "mealEnd": "13:30",
            "totalHours": 7.5,
        },
        changed_fields=["checkOut"],
        detected_issue=exc.description,
        reason="Inferred clock-out from scheduled shift end.",
        policy_title="Missed Clock-Out Resolution",
        policy_clause_id="PUNCH-01",
        policy_excerpt="Shift end inferred from schedule.",
        recommendation="Approve scheduled end time.",
        confidence=0.95,
        missing_information=[],
        validators=[{"name": "Schema Validation", "passed": True}],
        blocked=False,
        generated_at=datetime(2026, 11, 8, 17, 31, 0),
    )
    session.add(prop)
    exc.proposal_id = prop.id
    session.commit()
    return emp, exc, prop


def test_submit_decision_approve_success(client: TestClient, db_session: Session) -> None:
    _, exc, prop = seed_test_records(db_session)

    response = client.post(
        f"/api/v1/proposals/{prop.id}/decision",
        json={"decision": "approve"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["exceptionId"] == exc.id
    assert data["newStatus"] == "Approved"
    assert "traceId" in data

    # Verify database state
    db_session.refresh(exc)
    assert exc.status == "approved"
    assert len(exc.decisions) == 1
    assert exc.decisions[0].decision == "approve"

    # Verify punches updated
    punches = db_session.query(PunchModel).filter(PunchModel.employee_id == exc.employee_id).all()
    out_punches = [p for p in punches if p.punch_type == "OUT"]
    assert len(out_punches) == 1
    assert out_punches[0].timestamp.strftime("%H:%M") == "17:00"


def test_submit_decision_reject_requires_reason(client: TestClient, db_session: Session) -> None:
    _, _exc, prop = seed_test_records(db_session)

    # Empty reason should fail
    response = client.post(
        f"/api/v1/proposals/{prop.id}/decision",
        json={"decision": "reject", "reason": ""},
    )
    assert response.status_code == 422
    assert "rejection reason is required" in response.json()["detail"].lower()


def test_submit_decision_reject_success(client: TestClient, db_session: Session) -> None:
    _, exc, prop = seed_test_records(db_session)

    response = client.post(
        f"/api/v1/proposals/{prop.id}/decision",
        json={"decision": "reject", "reason": "Employee actually left early at 15:30."},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["exceptionId"] == exc.id
    assert data["newStatus"] == "Rejected"

    # Verify database state: status changed to rejected, but timecard untouched
    db_session.refresh(exc)
    assert exc.status == "rejected"
    assert len(exc.decisions) == 1
    assert exc.decisions[0].decision == "reject"
    # No OUT punch should have been created
    punches = db_session.query(PunchModel).filter(PunchModel.employee_id == exc.employee_id).all()
    assert len(punches) == 0


def test_submit_decision_edit_success(client: TestClient, db_session: Session) -> None:
    _, exc, prop = seed_test_records(db_session)

    response = client.post(
        f"/api/v1/proposals/{prop.id}/decision",
        json={
            "decision": "edit",
            "editedTimecard": {
                "checkIn": "09:00",
                "checkOut": "16:45",
                "mealStart": "12:30",
                "mealEnd": "13:00",
            },
            "reason": "Corrected punch to actual verified departure time 16:45.",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["newStatus"] == "Approved"

    # Verify proposal and exception state
    db_session.refresh(exc)
    db_session.refresh(prop)
    assert exc.status == "approved"
    assert prop.proposed_timecard["checkOut"] == "16:45"
    assert prop.proposed_timecard["totalHours"] == 7.25

    # Verify punches updated with edited time
    punches = db_session.query(PunchModel).filter(PunchModel.employee_id == exc.employee_id).all()
    out_punches = [p for p in punches if p.punch_type == "OUT"]
    assert len(out_punches) == 1
    assert out_punches[0].timestamp.strftime("%H:%M") == "16:45"


def test_submit_decision_blocked_proposal_fails_approval(
    client: TestClient, db_session: Session
) -> None:
    _, _exc, prop = seed_test_records(db_session)
    prop.blocked = True
    db_session.commit()

    response = client.post(
        f"/api/v1/proposals/{prop.id}/decision",
        json={"decision": "approve"},
    )
    assert response.status_code == 422
    assert "blocked" in response.json()["detail"].lower()


def test_submit_decision_already_decided_conflict(client: TestClient, db_session: Session) -> None:
    _, exc, prop = seed_test_records(db_session)
    exc.status = "approved"
    db_session.commit()

    response = client.post(
        f"/api/v1/proposals/{prop.id}/decision",
        json={"decision": "approve"},
    )
    assert response.status_code == 409
    assert "already approved" in response.json()["detail"].lower()
