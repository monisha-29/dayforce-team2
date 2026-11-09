"""Tests for the extended exception types: duplicate punch, rest period, consecutive days."""

from collections.abc import Generator
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import EmployeeModel, ExceptionModel
from app.rules import Punch, Schedule, detect_all_exceptions, detect_shift_exceptions
from app.rules.detectors.cross_day import (
    ConsecutiveDaysDetector,
    RestPeriodDetector,
    ShiftSpan,
    split_duplicate_punches,
)
from app.services import proposal_service
from app.services.policy_service import PolicyService


def punch(emp: str, ts: str, kind: str) -> Punch:
    return Punch(employee_id=emp, timestamp=datetime.fromisoformat(ts), punch_type=kind)


def types(excs: list) -> set[str]:
    return {e.exception_type.value for e in excs}


# --- duplicate punch ---------------------------------------------------------


def test_split_duplicates_keeps_first_and_honours_window() -> None:
    punches = [
        punch("E", "2027-03-01 09:00", "IN"),
        punch("E", "2027-03-01 09:02", "IN"),  # exactly 2 minutes: duplicate
        punch("E", "2027-03-01 17:00", "OUT"),
    ]
    kept, dupes = split_duplicate_punches(punches, 2)
    assert [p.timestamp.strftime("%H:%M") for p in kept] == ["09:00", "17:00"]
    assert len(dupes) == 1

    kept, dupes = split_duplicate_punches(
        [punch("E", "2027-03-01 09:00", "IN"), punch("E", "2027-03-01 09:03", "IN")], 2
    )
    assert len(kept) == 2 and not dupes  # 3 minutes apart is not a double tap


def test_double_tap_is_a_duplicate_not_a_missed_punch() -> None:
    punches = [
        punch("E", "2027-03-01 09:00", "IN"),
        punch("E", "2027-03-01 09:01", "IN"),
        punch("E", "2027-03-01 12:00", "BREAK_START"),
        punch("E", "2027-03-01 12:30", "BREAK_END"),
        punch("E", "2027-03-01 17:30", "OUT"),
    ]
    sched = Schedule(
        employee_id="E",
        date="2027-03-01",
        start_time=datetime(2027, 3, 1, 9),
        end_time=datetime(2027, 3, 1, 17, 30),
    )
    found = detect_shift_exceptions("E", "2027-03-01", punches, sched)
    assert types(found) == {"duplicate_punch"}
    assert found[0].policy_reference == "DUP-01"


def test_slow_second_in_is_still_a_missed_punch() -> None:
    punches = [punch("E", "2027-03-01 09:00", "IN"), punch("E", "2027-03-01 09:03", "IN")]
    assert "missed_punch" in types(detect_shift_exceptions("E", "2027-03-01", punches, None))


# --- rest period -----------------------------------------------------------------


def span(date: str, start: str, end: str | None) -> ShiftSpan:
    return ShiftSpan(
        date, datetime.fromisoformat(start), datetime.fromisoformat(end) if end else None
    )


@pytest.mark.parametrize(
    ("next_start", "flagged"),
    [("2027-03-02 06:59", True), ("2027-03-02 07:00", False), ("2027-03-02 12:00", False)],
)
def test_rest_period_boundary_is_eight_hours(next_start: str, flagged: bool) -> None:
    spans = [
        span("2027-03-01", "2027-03-01 15:00", "2027-03-01 23:00"),
        span("2027-03-02", next_start, "2027-03-02 15:00"),
    ]
    found = RestPeriodDetector().detect_across_days("E", spans)
    assert bool(found) is flagged
    if flagged:
        assert found[0].date == "2027-03-02" and found[0].policy_reference == "REST-01"


def test_rest_period_ignores_unclosed_shift() -> None:
    spans = [
        span("2027-03-01", "2027-03-01 15:00", None),
        span("2027-03-02", "2027-03-02 06:00", None),
    ]
    assert RestPeriodDetector().detect_across_days("E", spans) == []


# --- consecutive days ---------------------------------------------------------------


def days(n: int, skip: set[int] | None = None) -> list[ShiftSpan]:
    start = datetime(2027, 3, 1, 9)
    out = []
    for k in range(n):
        if skip and k in skip:
            continue
        d = start + timedelta(days=k)
        out.append(ShiftSpan(d.date().isoformat(), d, d + timedelta(hours=4)))
    return out


@pytest.mark.parametrize(("n", "expected"), [(6, 0), (7, 1), (10, 1)])
def test_consecutive_days_flags_once_after_six(n: int, expected: int) -> None:
    found = ConsecutiveDaysDetector().detect_across_days("E", days(n))
    assert len(found) == expected
    if expected:
        assert found[0].date == "2027-03-07" and found[0].policy_reference == "CONSEC-01"


def test_day_off_resets_the_streak() -> None:
    assert ConsecutiveDaysDetector().detect_across_days("E", days(10, skip={6})) == []


def test_detect_all_runs_cross_day_checks() -> None:
    punches = []
    for k in range(7):
        d = datetime(2027, 3, 1) + timedelta(days=k)
        punches += [
            Punch(employee_id="E", timestamp=d.replace(hour=9), punch_type="IN"),
            Punch(employee_id="E", timestamp=d.replace(hour=13, minute=30), punch_type="OUT"),
        ]
    schedules = [
        Schedule(
            employee_id="E",
            date=(datetime(2027, 3, 1) + timedelta(days=k)).date().isoformat(),
            start_time=datetime(2027, 3, 1, 9) + timedelta(days=k),
            end_time=datetime(2027, 3, 1, 13, 30) + timedelta(days=k),
        )
        for k in range(7)
    ]
    assert types(detect_all_exceptions(punches, schedules)) == {"consecutive_days"}


# --- retrieval, API names and the proposal flow ------------------------------------


@pytest.mark.parametrize(
    ("exc_type", "expected"),
    [("duplicate_punch", "DUP-01"), ("rest_period", "REST-01"), ("consecutive_days", "CONSEC-01")],
)
def test_retrieval_returns_clauses_of_the_new_type(exc_type: str, expected: str) -> None:
    results = PolicyService().retrieve_policies(exc_type, "", preferred_id=expected)
    assert results[0][0].id == expected
    assert all(c.exception_type == exc_type for c, _ in results)


@pytest.fixture
def session() -> Generator[Session, None, None]:
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    db.add(
        EmployeeModel(
            id="EMP-X",
            name="Ari Fox",
            department="Ops",
            shift="Day",
            shift_start="09:00",
            shift_end="17:00",
        )
    )
    db.commit()
    yield db
    db.close()
    Base.metadata.drop_all(engine)


@pytest.mark.parametrize(
    ("exc_type", "clause"),
    [("duplicate_punch", "DUP-01"), ("rest_period", "REST-01"), ("consecutive_days", "CONSEC-01")],
)
def test_new_types_go_to_the_manager_without_a_time_change(
    session: Session, exc_type: str, clause: str
) -> None:
    """With the model unavailable, the fallback must not invent a timecard change."""
    session.add(
        ExceptionModel(
            id="EXC-NEW",
            employee_id="EMP-X",
            type=exc_type,
            date="2027-03-02",
            severity="medium",
            status="open",
            description=f"{exc_type} detected",
            original_attendance={"checkIn": "09:00", "checkOut": "17:00"},
            policy_reference=clause,
            detected_at=datetime(2027, 3, 2, 18, 0),
        )
    )
    session.commit()
    proposal = proposal_service.generate_proposal_for_exception(session, "EXC-NEW")
    assert proposal.policy_clause_id == clause
    assert proposal.blocked is False  # "keep the record as is" is a valid proposal
    assert proposal.changed_fields == []
    assert "No time change is proposed" in proposal.reason
    assert proposal.proposed_timecard.get("checkIn") == "09:00"
    assert proposal.proposed_timecard.get("checkOut") == "17:00"


# --- change guard: the model must not delete punches or "fix" untouchable types ----------

ORIGINAL = {"checkIn": "09:00", "checkOut": "13:30", "mealStart": None, "mealEnd": None}


def test_guard_rejects_deleting_a_recorded_punch_for_any_type() -> None:
    from app.services.llm_service import check_timecard_changes

    erased = {**ORIGINAL, "checkOut": None}
    errors = check_timecard_changes(erased, ORIGINAL, "missed_punch")
    assert errors and "checkOut" in errors[0]


def test_guard_allows_filling_in_a_missing_punch() -> None:
    from app.services.llm_service import check_timecard_changes

    original = {**ORIGINAL, "checkOut": None}
    assert check_timecard_changes({**ORIGINAL, "checkOut": "17:00"}, original, "missed_punch") == []


@pytest.mark.parametrize("exc_type", ["duplicate_punch", "rest_period", "consecutive_days"])
def test_guard_requires_unchanged_timecard_for_untouchable_types(exc_type: str) -> None:
    from app.services.llm_service import check_timecard_changes

    assert check_timecard_changes(dict(ORIGINAL), ORIGINAL, exc_type) == []
    errors = check_timecard_changes({**ORIGINAL, "checkOut": "17:00"}, ORIGINAL, exc_type)
    assert errors and "cannot be fixed by changing punch times" in errors[0]


def _llm_result(timecard: dict, citation: str) -> object:
    from app.services.llm_service import LLMResult

    parsed = {
        "proposed_timecard": timecard,
        "changed_fields": [],
        "reason": "Policy issue for the manager.",
        "recommendation": "Manager decision needed.",
        "confidence": 0.8,
        "missing_information": [],
        "policy_citations": [citation],
    }
    return LLMResult(
        parsed=parsed, raw=str(parsed), model="m", prompt_version="v1", duration_seconds=0.1
    )


def _consecutive_days_exception(session: Session) -> None:
    session.add(
        ExceptionModel(
            id="EXC-CD",
            employee_id="EMP-X",
            type="consecutive_days",
            date="2027-03-07",
            severity="medium",
            status="open",
            description="Day 7 worked in a row",
            original_attendance=dict(ORIGINAL),
            policy_reference="CONSEC-01",
            detected_at=datetime(2027, 3, 7, 18, 0),
        )
    )
    session.commit()


def test_model_deleting_checkout_is_blocked_not_approved(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression: the 3B model proposed checkOut=null for a consecutive-days exception."""
    _consecutive_days_exception(session)
    erased = _llm_result({**ORIGINAL, "checkOut": None}, "CONSEC-01")
    monkeypatch.setattr(proposal_service, "query_llm", lambda *a, **k: erased)
    proposal = proposal_service.generate_proposal_for_exception(session, "EXC-CD")
    assert proposal.blocked is True
    assert "removes the recorded checkOut" in proposal.reason


def test_unchanged_timecard_is_accepted_for_untouchable_types(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _consecutive_days_exception(session)
    same = _llm_result(dict(ORIGINAL), "CONSEC-01")
    monkeypatch.setattr(proposal_service, "query_llm", lambda *a, **k: same)
    proposal = proposal_service.generate_proposal_for_exception(session, "EXC-CD")
    assert proposal.blocked is False
    assert proposal.proposed_timecard["checkOut"] == "13:30"


def test_accepted_proposal_has_code_computed_hours_and_real_changed_fields(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _consecutive_days_exception(session)
    same = _llm_result(dict(ORIGINAL), "CONSEC-01")  # model reports no changed fields
    monkeypatch.setattr(proposal_service, "query_llm", lambda *a, **k: same)
    proposal = proposal_service.generate_proposal_for_exception(session, "EXC-CD")
    assert proposal.changed_fields == []  # nothing differs from the original
    assert proposal.proposed_timecard["totalHours"] == 4.5  # 09:00-13:30, set by code


def test_duplicate_tap_does_not_block_an_unchanged_timecard(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression: the validator saw the duplicate IN itself as an overlapping punch."""
    from app.models.punch import PunchModel
    from app.models.schedule import ScheduleModel

    session.add(
        ExceptionModel(
            id="EXC-DUP",
            employee_id="EMP-X",
            type="duplicate_punch",
            date="2027-03-02",
            severity="low",
            status="open",
            description="Duplicate IN punch",
            original_attendance={
                "checkIn": "09:00",
                "checkOut": "17:30",
                "mealStart": "12:00",
                "mealEnd": "12:30",
            },
            policy_reference="DUP-01",
            detected_at=datetime(2027, 3, 2, 18, 0),
        )
    )
    session.add(
        ScheduleModel(
            id="S-DUP",
            employee_id="EMP-X",
            date="2027-03-02",
            start_time=datetime(2027, 3, 2, 9),
            end_time=datetime(2027, 3, 2, 17, 30),
        )
    )
    for pid, hh, mm, kind in (
        ("P1", 9, 0, "IN"),
        ("P2", 9, 1, "IN"),
        ("P3", 12, 0, "BREAK_START"),
        ("P4", 12, 30, "BREAK_END"),
        ("P5", 17, 30, "OUT"),
    ):
        session.add(
            PunchModel(
                id=pid,
                employee_id="EMP-X",
                timestamp=datetime(2027, 3, 2, hh, mm),
                punch_type=kind,
                source="synthetic",
            )
        )
    session.commit()
    same = _llm_result(
        {"checkIn": "09:00", "checkOut": "17:30", "mealStart": "12:00", "mealEnd": "12:30"},
        "DUP-01",
    )
    monkeypatch.setattr(proposal_service, "query_llm", lambda *a, **k: same)
    proposal = proposal_service.generate_proposal_for_exception(session, "EXC-DUP")
    assert proposal.blocked is False


def test_slow_proposal_does_not_freeze_other_requests(monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression: proposal generation ran on the event loop and froze the whole API."""
    import asyncio
    import time

    import httpx

    from app.database import get_db
    from app.main import app
    from app.services.llm_service import LLMResult

    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as db:
        db.add(
            EmployeeModel(
                id="EMP-S",
                name="Slow Test",
                department="Ops",
                shift="Day",
                shift_start="09:00",
                shift_end="17:00",
            )
        )
        db.add(
            ExceptionModel(
                id="EXC-SLOW",
                employee_id="EMP-S",
                type="rest_period",
                date="2027-03-02",
                severity="medium",
                status="open",
                description="Short rest",
                original_attendance={"checkIn": "09:00", "checkOut": "17:00"},
                policy_reference="REST-01",
                detected_at=datetime(2027, 3, 2, 18, 0),
            )
        )
        db.commit()

    def slow_llm(prompt: str, *args: object, **kwargs: object) -> LLMResult:
        time.sleep(1.5)  # stands in for a minutes-long model call
        return LLMResult(
            parsed=None, raw="", model="m", prompt_version="v1", duration_seconds=1.5, error="x"
        )

    def override() -> Generator[Session, None, None]:
        with factory() as s:
            yield s

    monkeypatch.setattr(proposal_service, "query_llm", slow_llm)
    app.dependency_overrides[get_db] = override

    async def scenario() -> float:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
            started = time.monotonic()
            slow = asyncio.create_task(client.post("/api/v1/exceptions/EXC-SLOW/proposal"))
            await asyncio.sleep(0.3)  # a blocked event loop cannot even wake up on time
            health = await client.get("/health")
            elapsed = time.monotonic() - started
            assert health.status_code == 200
            assert (await slow).status_code == 200
            return elapsed

    try:
        health_latency = asyncio.run(scenario())
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
    assert health_latency < 1.0, f"health check waited {health_latency:.1f}s behind a proposal"


@pytest.mark.parametrize("exc_type", ["overtime", "schedule_conflict", "meal_break"])
def test_guard_also_covers_the_core_types_that_punch_times_cannot_fix(exc_type: str) -> None:
    from app.services.llm_service import check_timecard_changes

    assert check_timecard_changes(dict(ORIGINAL), ORIGINAL, exc_type) == []
    shortened = {**ORIGINAL, "checkOut": "10:00"}  # the 3B model "fixed" overtime like this
    assert check_timecard_changes(shortened, ORIGINAL, exc_type)


def test_guard_still_lets_a_missed_punch_be_filled_in() -> None:
    from app.services.llm_service import check_timecard_changes

    original = {**ORIGINAL, "checkOut": None}
    assert check_timecard_changes({**ORIGINAL, "checkOut": "17:00"}, original, "missed_punch") == []
