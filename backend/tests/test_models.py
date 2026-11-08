"""Focused tests for the seven SQLAlchemy ORM models using an in-memory SQLite database."""

from datetime import datetime

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.database import Base
from app.models import (
    AuditEventModel,
    DecisionModel,
    EmployeeModel,
    ExceptionModel,
    ProposalModel,
    PunchModel,
    ScheduleModel,
)


@pytest.fixture
def test_session() -> Session:
    """Provide a clean in-memory database and session for model testing."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)


def test_all_seven_tables_registered() -> None:
    """Verify that all seven tables are registered on Base.metadata."""
    registered_tables = set(Base.metadata.tables.keys())
    expected_tables = {
        "employees",
        "schedules",
        "punches",
        "exceptions",
        "proposals",
        "decisions",
        "audit_log",
    }
    assert expected_tables.issubset(registered_tables), (
        f"Missing tables: {expected_tables - registered_tables}"
    )


def test_table_creation_and_foreign_keys() -> None:
    """Verify tables can be created and foreign key constraints exist."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    inspector = inspect(engine)

    # Verify primary keys
    assert inspector.get_pk_constraint("employees")["constrained_columns"] == ["id"]
    assert inspector.get_pk_constraint("schedules")["constrained_columns"] == ["id"]
    assert inspector.get_pk_constraint("punches")["constrained_columns"] == ["id"]
    assert inspector.get_pk_constraint("exceptions")["constrained_columns"] == ["id"]
    assert inspector.get_pk_constraint("proposals")["constrained_columns"] == ["id"]
    assert inspector.get_pk_constraint("decisions")["constrained_columns"] == ["id"]
    assert inspector.get_pk_constraint("audit_log")["constrained_columns"] == ["id"]

    # Verify key foreign keys
    schedule_fks = {
        fk["referred_table"]: fk["constrained_columns"]
        for fk in inspector.get_foreign_keys("schedules")
    }
    assert "employees" in schedule_fks
    assert schedule_fks["employees"] == ["employee_id"]

    punch_fks = {
        fk["referred_table"]: fk["constrained_columns"]
        for fk in inspector.get_foreign_keys("punches")
    }
    assert "employees" in punch_fks
    assert punch_fks["employees"] == ["employee_id"]

    exception_fks = {
        fk["referred_table"]: fk["constrained_columns"]
        for fk in inspector.get_foreign_keys("exceptions")
    }
    assert "employees" in exception_fks
    assert exception_fks["employees"] == ["employee_id"]

    proposal_fks = {
        fk["referred_table"]: fk["constrained_columns"]
        for fk in inspector.get_foreign_keys("proposals")
    }
    assert "exceptions" in proposal_fks
    assert proposal_fks["exceptions"] == ["exception_id"]

    decision_fks = {
        fk["referred_table"]: fk["constrained_columns"]
        for fk in inspector.get_foreign_keys("decisions")
    }
    assert "exceptions" in decision_fks
    assert decision_fks["exceptions"] == ["exception_id"]


def test_models_crud_and_relationships(test_session: Session) -> None:
    """Verify inserting records across all seven models and traversing ORM relationships."""
    now = datetime(2026, 11, 8, 8, 0, 0)

    # 1. Create Employee
    emp = EmployeeModel(
        id="EMP-1042",
        name="Aarav Mehta",
        department="Operations",
        shift="Day Shift",
        shift_start="09:00",
        shift_end="18:00",
        created_at=now,
    )
    test_session.add(emp)
    test_session.flush()

    # 2. Create Schedule
    sched = ScheduleModel(
        id="SCHED-1001",
        employee_id=emp.id,
        date="2026-11-08",
        start_time=datetime(2026, 11, 8, 9, 0, 0),
        end_time=datetime(2026, 11, 8, 18, 0, 0),
        scheduled_break_minutes=30,
    )
    test_session.add(sched)

    # 3. Create Punch
    punch = PunchModel(
        id="PUNCH-5001",
        employee_id=emp.id,
        timestamp=datetime(2026, 11, 8, 9, 0, 0),
        punch_type="IN",
        source="terminal",
    )
    test_session.add(punch)

    # 4. Create Exception
    exc = ExceptionModel(
        id="EXC-2401",
        employee_id=emp.id,
        type="missed_punch",
        date="2026-11-08",
        severity="high",
        status="awaiting_approval",
        description="Missing check-out punch",
        original_attendance={"check_in": "09:00", "check_out": None},
        policy_reference="PUNCH-01",
        detected_at=now,
    )
    test_session.add(exc)
    test_session.flush()

    # 5. Create Proposal
    prop = ProposalModel(
        id="PRP-7101",
        exception_id=exc.id,
        proposed_timecard={"check_in": "09:00", "check_out": "18:00", "total_hours": 8.5},
        changed_fields=["check_out", "total_hours"],
        detected_issue="Missing OUT punch",
        reason="Employee forgot to clock out at shift boundary",
        policy_title="Missed Punch Resolution Policy",
        policy_clause_id="PUNCH-01",
        policy_excerpt="Propose shift end boundary punch",
        recommendation="Insert OUT punch at 18:00",
        confidence=0.92,
        missing_information=[],
        validators=[{"name": "Schema Validation", "passed": True}],
        blocked=False,
        generated_at=now,
    )
    test_session.add(prop)
    test_session.flush()

    # Link active proposal on exception
    exc.proposal_id = prop.id
    test_session.flush()

    # 6. Create Decision
    dec = DecisionModel(
        id="DEC-8001",
        proposal_id=prop.id,
        exception_id=exc.id,
        decision="approve",
        manager_user="Rebecca Thorne",
        reason="Approved by supervisor",
        decided_at=now,
    )
    test_session.add(dec)

    # 7. Create Audit Event
    audit = AuditEventModel(
        id="AUD-9001",
        exception_id=exc.id,
        timestamp=now,
        action="Exception detected",
        user="Detection Engine",
        status="info",
        trace_id="tr-3a7f1",
        detail="Missing Punch detected on 2026-11-08",
        flags=["Retried"],
    )
    test_session.add(audit)
    test_session.commit()

    # Traverse relationships from Employee
    loaded_emp = test_session.get(EmployeeModel, "EMP-1042")
    assert loaded_emp is not None
    assert len(loaded_emp.schedules) == 1
    assert loaded_emp.schedules[0].id == "SCHED-1001"
    assert len(loaded_emp.punches) == 1
    assert loaded_emp.punches[0].id == "PUNCH-5001"
    assert len(loaded_emp.exceptions) == 1
    assert loaded_emp.exceptions[0].id == "EXC-2401"

    # Traverse relationships from Exception
    loaded_exc = test_session.get(ExceptionModel, "EXC-2401")
    assert loaded_exc is not None
    assert loaded_exc.employee.name == "Aarav Mehta"
    assert loaded_exc.active_proposal is not None
    assert loaded_exc.active_proposal.id == "PRP-7101"
    assert len(loaded_exc.proposals) == 1
    assert len(loaded_exc.decisions) == 1
    assert loaded_exc.decisions[0].decision == "approve"
    assert len(loaded_exc.audit_events) == 1
    assert loaded_exc.audit_events[0].action == "Exception detected"

    # Traverse relationships from Proposal
    loaded_prop = test_session.get(ProposalModel, "PRP-7101")
    assert loaded_prop is not None
    assert loaded_prop.exception.id == "EXC-2401"
    assert loaded_prop.decision is not None
    assert loaded_prop.decision.id == "DEC-8001"


def test_nullable_fields_and_defaults(test_session: Session) -> None:
    """Verify that optional fields permit None and JSON fields default to empty collections."""
    emp = EmployeeModel(
        id="EMP-9999",
        name="Test Employee",
        department="Quality",
        shift="Day",
        shift_start="09:00",
        shift_end="17:00",
    )
    test_session.add(emp)

    exc = ExceptionModel(
        id="EXC-9999",
        employee_id=emp.id,
        type="overtime",
        date="2026-11-08",
        description="Daily overtime",
        policy_reference="OT-01",
        proposal_id=None,  # Nullable when first detected
    )
    test_session.add(exc)
    test_session.commit()

    reloaded = test_session.get(ExceptionModel, "EXC-9999")
    assert reloaded is not None
    assert reloaded.proposal_id is None
    assert reloaded.severity == "medium"  # Default
    assert reloaded.status == "pending_review"  # Default
    assert isinstance(reloaded.original_attendance, dict)


def test_foreign_key_not_null_violation(test_session: Session) -> None:
    """Verify that missing required non-nullable fields raise IntegrityError."""
    # Attempt to insert an exception with None for required description
    exc = ExceptionModel(
        id="EXC-FAIL",
        employee_id="EMP-NONEXISTENT",
        type="missed_punch",
        date="2026-11-08",
        description=None,  # type: ignore[arg-type]
        policy_reference="PUNCH-01",
    )
    test_session.add(exc)
    with pytest.raises(IntegrityError):
        test_session.commit()
    test_session.rollback()
