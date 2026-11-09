"""Tests for GET /api/v1/exceptions and GET /api/v1/exceptions/{id} endpoints."""

from collections.abc import Generator
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import EmployeeModel, ExceptionModel, ProposalModel


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
    """FastAPI TestClient with overridden database dependency."""
    return TestClient(app)


def test_list_exceptions_empty(client: TestClient) -> None:
    """Verify GET /api/v1/exceptions returns an empty list when no exceptions exist."""
    response = client.get("/api/v1/exceptions")
    assert response.status_code == 200
    assert response.json() == []


def test_list_exceptions_with_records(client: TestClient, db_session: Session) -> None:
    """Verify GET /api/v1/exceptions returns camelCase records with employee details."""
    now = datetime(2026, 11, 8, 8, 15, 0)

    # 1. Seed employee
    emp = EmployeeModel(
        id="EMP-1042",
        name="Aarav Mehta",
        department="Operations",
        shift="Day Shift",
        shift_start="09:00",
        shift_end="18:00",
    )
    db_session.add(emp)

    # 2. Seed exception
    exc = ExceptionModel(
        id="EXC-2401",
        employee_id=emp.id,
        type="missed_punch",
        date="2026-11-08",
        severity="high",
        status="awaiting_approval",
        description="Missing clock-out punch",
        original_attendance={
            "checkIn": "09:00",
            "checkOut": None,
            "mealStart": "13:00",
            "mealEnd": "13:30",
            "totalHours": None,
        },
        policy_reference="PUNCH-01",
        detected_at=now,
    )
    db_session.add(exc)
    db_session.commit()

    response = client.get("/api/v1/exceptions")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1

    item = data[0]
    # Check camelCase keys matching frontend contract
    assert item["id"] == "EXC-2401"
    assert item["type"] == "Missing Punch"
    assert item["date"] == "2026-11-08"
    assert item["severity"] == "High"
    assert item["status"] == "Awaiting Approval"
    assert item["proposalId"] is None

    # Check embedded employee
    emp_data = item["employee"]
    assert emp_data["id"] == "EMP-1042"
    assert emp_data["name"] == "Aarav Mehta"
    assert emp_data["department"] == "Operations"
    assert emp_data["shift"] == "Day Shift"
    assert emp_data["shiftStart"] == "09:00"
    assert emp_data["shiftEnd"] == "18:00"

    # Check embedded original timecard
    orig_data = item["original"]
    assert orig_data["checkIn"] == "09:00"
    assert orig_data["checkOut"] is None
    assert orig_data["mealStart"] == "13:00"
    assert orig_data["mealEnd"] == "13:30"


def test_list_exceptions_filters(client: TestClient, db_session: Session) -> None:
    """Verify search, type, status, and severity query filters."""
    emp1 = EmployeeModel(
        id="EMP-101",
        name="Alice Walker",
        department="Engineering",
        shift="Morning",
        shift_start="09:00",
        shift_end="17:00",
    )
    emp2 = EmployeeModel(
        id="EMP-102",
        name="Bob Martinez",
        department="Warehouse",
        shift="Night",
        shift_start="22:00",
        shift_end="06:00",
    )
    db_session.add_all([emp1, emp2])

    exc1 = ExceptionModel(
        id="EXC-1001",
        employee_id=emp1.id,
        type="missed_punch",
        date="2026-11-08",
        severity="high",
        status="awaiting_approval",
        description="Missing punch",
        original_attendance={},
        policy_reference="PUNCH-01",
    )
    exc2 = ExceptionModel(
        id="EXC-1002",
        employee_id=emp2.id,
        type="overtime",
        date="2026-11-07",
        severity="medium",
        status="pending_review",
        description="Overtime risk",
        original_attendance={},
        policy_reference="OT-01",
    )
    db_session.add_all([exc1, exc2])
    db_session.commit()

    # Search by employee name
    res_search_name = client.get("/api/v1/exceptions?search=Alice")
    assert res_search_name.status_code == 200
    assert len(res_search_name.json()) == 1
    assert res_search_name.json()[0]["id"] == "EXC-1001"

    # Search by employee ID
    res_search_id = client.get("/api/v1/exceptions?search=EMP-102")
    assert res_search_id.status_code == 200
    assert len(res_search_id.json()) == 1
    assert res_search_id.json()[0]["id"] == "EXC-1002"

    # Filter by display type ("Missing Punch") and canonical code ("missed_punch")
    res_type_display = client.get("/api/v1/exceptions?type=Missing+Punch")
    assert len(res_type_display.json()) == 1
    assert res_type_display.json()[0]["id"] == "EXC-1001"

    res_type_code = client.get("/api/v1/exceptions?type=missed_punch")
    assert len(res_type_code.json()) == 1
    assert res_type_code.json()[0]["id"] == "EXC-1001"

    # Filter by status ("pending_review" vs "Pending Review")
    res_status = client.get("/api/v1/exceptions?status=Pending+Review")
    assert len(res_status.json()) == 1
    assert res_status.json()[0]["id"] == "EXC-1002"

    # Filter by severity ("high")
    res_sev = client.get("/api/v1/exceptions?severity=High")
    assert len(res_sev.json()) == 1
    assert res_sev.json()[0]["id"] == "EXC-1001"

    # 'all' should return everything
    res_all = client.get("/api/v1/exceptions?type=all&status=all&severity=all")
    assert len(res_all.json()) == 2


def test_get_exception_by_id_success(client: TestClient, db_session: Session) -> None:
    """Verify GET /api/v1/exceptions/{id} returns full details and embedded proposal."""
    emp = EmployeeModel(
        id="EMP-1042",
        name="Aarav Mehta",
        department="Operations",
        shift="Day Shift",
        shift_start="09:00",
        shift_end="18:00",
    )
    db_session.add(emp)

    exc = ExceptionModel(
        id="EXC-2401",
        employee_id=emp.id,
        type="missed_punch",
        date="2026-11-08",
        severity="high",
        status="awaiting_approval",
        description="Missing clock-out punch",
        original_attendance={"checkIn": "09:00"},
        policy_reference="PUNCH-01",
    )
    db_session.add(exc)
    db_session.flush()

    prop = ProposalModel(
        id="PRP-7101",
        exception_id=exc.id,
        proposed_timecard={"checkIn": "09:00", "checkOut": "18:00", "totalHours": 8.5},
        changed_fields=["checkOut", "totalHours"],
        detected_issue="Unclosed shift",
        reason="No OUT punch",
        policy_title="Missed Punch Resolution Policy",
        policy_clause_id="PUNCH-01",
        policy_excerpt="Propose shift end boundary punch",
        recommendation="Insert check-out at 18:00",
        confidence=0.92,
        missing_information=[],
        validators=[{"name": "Schema Validation", "passed": True}],
        blocked=False,
    )
    db_session.add(prop)
    exc.proposal_id = prop.id
    db_session.commit()

    response = client.get("/api/v1/exceptions/EXC-2401")
    assert response.status_code == 200
    data = response.json()

    assert data["id"] == "EXC-2401"
    assert data["type"] == "Missing Punch"
    assert data["employee"]["name"] == "Aarav Mehta"
    assert data["proposalId"] == "PRP-7101"

    # Verify embedded proposal
    proposal = data["proposal"]
    assert proposal is not None
    assert proposal["id"] == "PRP-7101"
    assert proposal["exceptionId"] == "EXC-2401"
    assert proposal["proposed"]["checkOut"] == "18:00"
    assert proposal["changedFields"] == ["checkOut", "totalHours"]
    assert proposal["policyClauseId"] == "PUNCH-01"
    assert len(proposal["validators"]) == 1
    assert proposal["validators"][0]["name"] == "Schema Validation"
    assert proposal["validators"][0]["passed"] is True


def test_get_exception_not_found(client: TestClient) -> None:
    """Verify GET /api/v1/exceptions/{id} returns HTTP 404 for nonexistent IDs."""
    response = client.get("/api/v1/exceptions/NONEXISTENT-ID")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


def test_generate_proposal_success(client: TestClient, db_session: Session) -> None:
    """Verify POST /api/v1/exceptions/{id}/proposal generates a proposal and updates status."""
    emp = EmployeeModel(
        id="EMP-GEN-1",
        name="Elena Rostova",
        department="Warehouse",
        shift="Morning",
        shift_start="08:00",
        shift_end="16:30",
    )
    db_session.add(emp)

    exc = ExceptionModel(
        id="EXC-GEN-1",
        employee_id=emp.id,
        type="missed_punch",
        date="2026-11-08",
        severity="high",
        status="pending_review",
        description="Missing clock-out punch",
        original_attendance={"checkIn": "08:00", "checkOut": None},
        policy_reference="PUNCH-01",
        detected_at=datetime(2026, 11, 8, 17, 0, 0),
    )
    db_session.add(exc)
    db_session.commit()

    response = client.post(f"/api/v1/exceptions/{exc.id}/proposal")
    assert response.status_code == 200
    data = response.json()
    assert data["exceptionId"] == exc.id
    assert "policyTitle" in data
    assert "validators" in data
    assert len(data["validators"]) > 0

    # Verify exception updated in DB
    db_session.refresh(exc)
    assert exc.status == "awaiting_approval"
    assert exc.proposal_id == data["id"]


def test_escalate_exception_success(client: TestClient, db_session: Session) -> None:
    """Verify POST /api/v1/exceptions/{id}/escalate sets status and logs audit event."""
    emp = EmployeeModel(
        id="EMP-ESC-1",
        name="David Kim",
        department="Retail",
        shift="Evening",
        shift_start="14:00",
        shift_end="22:30",
    )
    db_session.add(emp)

    exc = ExceptionModel(
        id="EXC-ESC-1",
        employee_id=emp.id,
        type="schedule_conflict",
        date="2026-11-08",
        severity="medium",
        status="pending_review",
        description="Unscheduled attendance",
        original_attendance={"checkIn": "12:00", "checkOut": "22:30"},
        policy_reference="SCHED-01",
        detected_at=datetime(2026, 11, 8, 22, 45, 0),
    )
    db_session.add(exc)
    db_session.commit()

    response = client.post(
        f"/api/v1/exceptions/{exc.id}/escalate",
        json={"note": "Employee claims verbal manager authorization."},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["exceptionId"] == exc.id
    assert data["newStatus"] == "Escalated"
    assert "traceId" in data

    # Verify database state
    db_session.refresh(exc)
    assert exc.status == "escalated"

