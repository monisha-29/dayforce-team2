"""Tests for GET /api/v1/exceptions/{id}/audit and GET /api/v1/audit endpoints."""

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
from app.services.audit_service import log_audit_event


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
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


def test_get_exception_audit_empty(client: TestClient, db_session: Session) -> None:
    response = client.get("/api/v1/exceptions/EXC-NONEXISTENT/audit")
    assert response.status_code == 200
    assert response.json() == []


def test_get_exception_audit_with_events(client: TestClient, db_session: Session) -> None:
    emp = EmployeeModel(
        id="EMP-AUDIT-1",
        name="Alex River",
        department="Logistics",
        shift="Morning",
        shift_start="08:00",
        shift_end="16:30",
    )
    db_session.add(emp)

    exc = ExceptionModel(
        id="EXC-AUDIT-1",
        employee_id=emp.id,
        type="missed_punch",
        date="2026-11-08",
        severity="medium",
        status="pending_review",
        description="Missing punch test",
        original_attendance={"checkIn": "08:00"},
        policy_reference="PUNCH-01",
        detected_at=datetime(2026, 11, 8, 8, 15, 0),
    )
    db_session.add(exc)
    db_session.commit()

    log_audit_event(
        session=db_session,
        action="Exception detected",
        user="RuleDetector",
        status="warning",
        trace_id="tr-test01",
        exception_id=exc.id,
        detail="Anomaly identified.",
        flags=[],
    )
    log_audit_event(
        session=db_session,
        action="Manager approved",
        user="Rebecca Thorne",
        status="success",
        trace_id="tr-test02",
        exception_id=exc.id,
        detail="Approved timecard fix.",
        flags=[],
    )
    db_session.commit()

    # Query exception audit trail
    response = client.get(f"/api/v1/exceptions/{exc.id}/audit")
    assert response.status_code == 200
    events = response.json()
    assert len(events) == 2
    assert events[0]["action"] == "Exception detected"
    assert events[1]["action"] == "Manager approved"
    assert events[0]["traceId"] == "tr-test01"
    assert events[1]["user"] == "Rebecca Thorne"

    # Query global audit trail
    global_resp = client.get("/api/v1/audit")
    assert global_resp.status_code == 200
    all_events = global_resp.json()
    assert len(all_events) == 2
