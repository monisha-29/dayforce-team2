"""Unit tests for policy retrieval service using BM25 ranking."""

from app.services.policy_service import PolicyService


def test_policy_service_loads_default_catalog() -> None:
    service = PolicyService()
    assert len(service.clauses) >= 8
    assert "PUNCH-01" in service.clauses
    assert "OT-01" in service.clauses
    assert "MEAL-01" in service.clauses
    assert "SCHED-01" in service.clauses


def test_retrieve_policy_by_type_missed_punch() -> None:
    service = PolicyService()
    clause, confidence = service.retrieve_policy("missed_punch", "clocked in at 08:00 but missed clock-out")
    assert clause.id in ("PUNCH-01", "PUNCH-02")
    assert confidence >= 0.70


def test_retrieve_policy_by_type_overtime() -> None:
    service = PolicyService()
    clause, confidence = service.retrieve_policy("overtime", "daily hours exceeded 8.0 hours")
    assert clause.id in ("OT-01", "OT-02")
    assert confidence >= 0.70


def test_retrieve_policy_by_type_meal_break() -> None:
    service = PolicyService()
    clause, confidence = service.retrieve_policy("meal_break", "shift longer than 5 hours with no 30-minute break")
    assert clause.id in ("MEAL-01", "MEAL-02")
    assert confidence >= 0.70


def test_retrieve_policy_by_type_schedule_conflict() -> None:
    service = PolicyService()
    clause, confidence = service.retrieve_policy("schedule_conflict", "arrived 120 minutes prior to scheduled start")
    assert clause.id in ("SCHED-01", "SCHED-02")
    assert confidence >= 0.70
