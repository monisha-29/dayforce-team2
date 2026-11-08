"""Tests for policy configuration and policy ID verification."""

import tempfile
from pathlib import Path

import yaml

from app.rules.detectors import RulesConfig
from app.rules.hours_calculator import CalculatorConfig
from app.rules.policy_loader import PolicyClause, PolicyRegistry


def test_reject_fabricated_policy_ids() -> None:
    """PolicyRegistry strictly rejects non-existent or fabricated policy IDs."""
    registry = PolicyRegistry()
    assert not registry.is_valid_clause_id("FABRICATED-999")
    assert not registry.is_valid_clause_id("BYPASS-01")
    assert not registry.is_valid_clause_id("ATTACK-RULE")
    assert not registry.is_valid_clause_id("")
    assert not registry.is_valid_clause_id("   ")


def test_load_policies_from_yaml_directory() -> None:
    """PolicyRegistry dynamically loads and parses actual YAML policy files from disk."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        yaml_content = [
            {
                "id": "CUSTOM-OT-01",
                "name": "Custom Overtime",
                "exception_type": "overtime",
                "description": "Custom daily OT threshold at 10 hours",
                "parameters": {"daily_threshold_hours": 10.0},
            },
            {
                "id": "CUSTOM-MEAL-01",
                "name": "Custom Meal Break",
                "exception_type": "meal_break",
                "description": "Custom meal break threshold at 6 hours",
                "parameters": {"shift_threshold_hours": 6.0, "min_break_minutes": 45},
            },
        ]
        test_file = tmp_path / "custom_policy.yaml"
        with open(test_file, "w", encoding="utf-8") as f:
            yaml.dump(yaml_content, f)

        registry = PolicyRegistry()
        # Load from disk with clear_existing=True to prove only file-based policies are active
        loaded_count = registry.load_from_directory(tmp_path, clear_existing=True)
        assert loaded_count == 2
        assert registry.is_valid_clause_id("CUSTOM-OT-01")
        assert registry.is_valid_clause_id("CUSTOM-MEAL-01")
        # Previously existing default IDs should now be absent
        assert not registry.is_valid_clause_id("OT-01")


def test_configurable_thresholds_via_rules_config() -> None:
    """All calculation and detection thresholds can be configured dynamically without hardcoded limits."""
    custom_cfg = RulesConfig(
        calculator=CalculatorConfig(
            daily_regular_hours_limit=10.0,
            weekly_regular_hours_limit=50.0,
            max_shift_hours=18.0,
            meal_break_threshold_hours=6.0,
            min_meal_break_minutes=45,
        )
    )
    assert custom_cfg.calculator.daily_regular_hours_limit == 10.0
    assert custom_cfg.calculator.weekly_regular_hours_limit == 50.0
    assert custom_cfg.calculator.max_shift_hours == 18.0
    assert custom_cfg.calculator.meal_break_threshold_hours == 6.0
    assert custom_cfg.calculator.min_meal_break_minutes == 45


def test_rules_config_from_policy_registry() -> None:
    """RulesConfig can be automatically built from parameters in loaded policy clauses."""
    registry = PolicyRegistry()
    registry.clear()
    registry.register_clause(
        PolicyClause(
            id="OT-01",
            name="Daily OT",
            exception_type="overtime",
            description="10h OT",
            parameters={"daily_threshold_hours": 10.0},
        )
    )
    registry.register_clause(
        PolicyClause(
            id="OT-02",
            name="Weekly OT",
            exception_type="overtime",
            description="45h weekly OT",
            parameters={"weekly_threshold_hours": 45.0},
        )
    )
    registry.register_clause(
        PolicyClause(
            id="SCHED-01",
            name="Tardiness",
            exception_type="schedule_conflict",
            description="10m grace period",
            parameters={"grace_period_minutes": 10},
        )
    )

    cfg = RulesConfig.from_policies(registry)
    assert cfg.calculator.daily_regular_hours_limit == 10.0
    assert cfg.calculator.weekly_regular_hours_limit == 45.0
    assert cfg.schedule_conflict.late_grace_period_minutes == 10
