"""Attendance records come from real punches and schedules, not from sample data."""

from collections.abc import Generator
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import EmployeeModel
from app.models.punch import PunchModel
from app.models.schedule import ScheduleModel

DAY = "2026-11-02"


def _emp(db: Session, emp_id: str, name: str) -> None:
    db.add(
        EmployeeModel(
            id=emp_id,
            name=name,
            department="Ops",
            shift="Day",
            shift_start="09:00",
            shift_end="17:00",
        )
    )


def _sched(db: Session, emp_id: str) -> None:
    db.add(
        ScheduleModel(
            id=f"S-{emp_id}",
            employee_id=emp_id,
            date=DAY,
            start_time=datetime(2026, 11, 2, 9),
            end_time=datetime(2026, 11, 2, 17),
        )
    )


def _punch(db: Session, emp_id: str, kind: str, hour: int, minute: int = 0) -> None:
    db.add(
        PunchModel(
            id=f"P-{emp_id}-{kind}-{hour}{minute}",
            employee_id=emp_id,
            timestamp=datetime(2026, 11, 2, hour, minute),
            punch_type=kind,
            source="terminal",
        )
    )


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)

    def override() -> Generator[Session, None, None]:
        with factory() as s:
            yield s

    app.dependency_overrides[get_db] = override
    with factory() as db:
        for emp_id, name in [
            ("E1", "On Time"),
            ("E2", "Late Larry"),
            ("E3", "No Show"),
            ("E4", "Day Off"),
            ("E5", "Walk In"),
        ]:
            _emp(db, emp_id, name)
        for emp_id in ("E1", "E2", "E3"):
            _sched(db, emp_id)
        _punch(db, "E1", "IN", 9, 3)  # inside the 5 minute grace period
        _punch(db, "E1", "OUT", 17)
        _punch(db, "E2", "IN", 9, 20)
        _punch(db, "E2", "OUT", 17)
        _punch(db, "E5", "IN", 10)  # worked without being scheduled
        _punch(db, "E5", "OUT", 14)
        db.commit()
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)


def test_status_is_worked_out_from_punches_and_schedule(client: TestClient) -> None:
    body = client.get("/api/v1/attendance", params={"date": DAY}).json()
    by_name = {r["name"]: r for r in body["records"]}

    assert by_name["On Time"]["status"] == "Present"
    assert by_name["Late Larry"]["status"] == "Late"
    assert by_name["No Show"]["status"] == "Absent"
    assert by_name["No Show"]["checkIn"] is None
    assert by_name["Walk In"]["status"] == "Present"
    assert by_name["Walk In"]["scheduledStart"] is None
    assert "Day Off" not in by_name  # nothing scheduled, nothing worked

    assert by_name["Late Larry"]["checkIn"] == "09:20"
    assert by_name["Late Larry"]["scheduledStart"] == "09:00"
    assert by_name["Late Larry"]["checkOut"] == "17:00"


def test_defaults_to_the_busiest_date(client: TestClient) -> None:
    body = client.get("/api/v1/attendance").json()
    assert body["date"] == DAY
    assert body["minDate"] == body["maxDate"] == DAY
    assert len(body["records"]) == 4


def test_a_day_with_no_data_is_empty_not_sample_data(client: TestClient) -> None:
    body = client.get("/api/v1/attendance", params={"date": "2026-01-01"}).json()
    assert body["records"] == []


def test_a_bad_date_is_rejected(client: TestClient) -> None:
    assert client.get("/api/v1/attendance", params={"date": "tomorrow"}).status_code == 422


def test_summary_counts_the_day_and_its_week(client: TestClient) -> None:
    body = client.get("/api/v1/attendance/summary").json()

    assert body["date"] == DAY
    assert body["totalEmployees"] == 5
    assert body["departments"] == 1
    # E1 present, E5 present (unscheduled), E2 late, E3 absent
    assert (body["present"], body["late"], body["absent"], body["scheduled"]) == (2, 1, 1, 4)

    week = {d["label"]: d for d in body["days"]}
    assert list(week) == ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    assert (week["Mon"]["present"], week["Mon"]["late"], week["Mon"]["absent"]) == (2, 1, 1)
    assert all(week[d]["present"] == 0 for d in ("Tue", "Sat", "Sun"))  # no invented weekend staff

    this_week = body["weeks"][-1]
    assert this_week["rate"] == 75.0  # 3 of the 4 scheduled-or-working people showed up
    assert body["weeks"][0]["rate"] is None  # a week with no data has no rate
    assert len(body["weeks"]) == 6
