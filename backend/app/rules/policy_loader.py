"""Policy loader and catalog for Timecard Exception Agent.

Loads policy clauses from the `policies/` directory (YAML files) or falls back to
the standard policy registry agreed with Person 4.
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

logger = logging.getLogger(__name__)


@dataclass
class PolicyClause:
    """Represents an individual company policy clause."""

    id: str
    name: str
    exception_type: str
    description: str
    parameters: dict[str, Any] = field(default_factory=dict)


# Standard default policy catalog defined in accordance with project specification
DEFAULT_POLICY_CLAUSES: dict[str, PolicyClause] = {
    "PUNCH-01": PolicyClause(
        id="PUNCH-01",
        name="Missed Clock-Out Resolution",
        exception_type="missed_punch",
        description="When an employee clocks in but misses clock-out, determine shift end from schedule or manager verification.",
        parameters={"default_resolution": "scheduled_end"},
    ),
    "PUNCH-02": PolicyClause(
        id="PUNCH-02",
        name="Missing Clock-In Resolution",
        exception_type="missed_punch",
        description="When an employee clocks out without a prior clock-in, verify attendance and record approved shift start.",
        parameters={"default_resolution": "scheduled_start"},
    ),
    "OT-01": PolicyClause(
        id="OT-01",
        name="Daily Overtime Rule",
        exception_type="overtime",
        description="Hours worked in excess of 8.0 regular hours in a single workday qualify as daily overtime.",
        parameters={"daily_threshold_hours": 8.0},
    ),
    "OT-02": PolicyClause(
        id="OT-02",
        name="Weekly Overtime Rule",
        exception_type="overtime",
        description="Hours worked in excess of 40.0 regular hours in a workweek qualify as weekly overtime.",
        parameters={"weekly_threshold_hours": 40.0},
    ),
    "SCHED-01": PolicyClause(
        id="SCHED-01",
        name="Tardiness and Schedule Adherence",
        exception_type="schedule_conflict",
        description="Arrivals exceeding 5 minutes after scheduled start are flagged as tardy; departure >5 min early flagged as early exit.",
        parameters={"grace_period_minutes": 5},
    ),
    "SCHED-02": PolicyClause(
        id="SCHED-02",
        name="Unscheduled Shift Work",
        exception_type="schedule_conflict",
        description="Shifts worked without a prior schedule assignment or outside scheduled shift boundaries require manager sign-off.",
        parameters={"requires_manager_approval": True},
    ),
    "MEAL-01": PolicyClause(
        id="MEAL-01",
        name="Mandatory Meal Break (>5 Hours)",
        exception_type="meal_break",
        description="Shifts longer than 5.0 hours require at least one uninterrupted unpaid meal break of at least 30 minutes.",
        parameters={"shift_threshold_hours": 5.0, "min_break_minutes": 30},
    ),
    "MEAL-02": PolicyClause(
        id="MEAL-02",
        name="Short or Interrupted Meal Break",
        exception_type="meal_break",
        description="Meal breaks shorter than 30 minutes or delayed beyond the 6th hour of work trigger a meal break exception.",
        parameters={"min_break_minutes": 30, "latest_start_hour": 6.0},
    ),
}


class PolicyRegistry:
    """Manages loaded company policies from repository YAML files or defaults."""

    def __init__(self, policies_dir: Path | str | None = None) -> None:
        self.clauses: dict[str, PolicyClause] = dict(DEFAULT_POLICY_CLAUSES)
        if policies_dir:
            self.load_from_directory(Path(policies_dir))
        else:
            # Check default workspace path
            default_path = Path(__file__).resolve().parents[3] / "policies"
            if default_path.is_dir():
                self.load_from_directory(default_path)

    def load_from_directory(self, directory: Path, clear_existing: bool = False) -> int:
        """Scan directory for YAML policy files and load clauses.

        If clear_existing is True and YAML files exist, previous clauses are cleared
        so that ONLY actual policy files from disk are registered.
        Returns the count of registered clauses.
        """
        if not directory.exists() or not directory.is_dir():
            return 0

        yaml_files = list(directory.glob("*.yaml")) + list(directory.glob("*.yml"))
        if not yaml_files:
            return 0

        if clear_existing:
            self.clauses.clear()

        loaded_count = 0
        for yfile in yaml_files:
            try:
                with open(yfile, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                    if isinstance(data, list):
                        for item in data:
                            if self._register_clause_dict(item):
                                loaded_count += 1
                    elif isinstance(data, dict):
                        if "clauses" in data and isinstance(data["clauses"], list):
                            for item in data["clauses"]:
                                if self._register_clause_dict(item):
                                    loaded_count += 1
                        else:
                            if self._register_clause_dict(data):
                                loaded_count += 1
            except (yaml.YAMLError, OSError, ValueError) as err:
                # Fallback to existing clauses if YAML has syntax issues
                logger.warning("Failed to parse policy YAML file %s: %s", yfile, err)

        return loaded_count

    def clear(self) -> None:
        """Clear all registered policy clauses."""
        self.clauses.clear()

    def register_clause(self, clause: PolicyClause) -> None:
        """Manually register an active policy clause."""
        self.clauses[clause.id.strip()] = clause

    def _register_clause_dict(self, item: dict[str, Any]) -> bool:
        cid = item.get("id") or item.get("clause_id")
        if cid and isinstance(cid, str):
            self.clauses[cid.strip()] = PolicyClause(
                id=cid.strip(),
                name=item.get("name", cid),
                exception_type=item.get("exception_type", "general"),
                description=item.get("description", ""),
                parameters=item.get("parameters", {}),
            )
            return True
        return False

    def is_valid_clause_id(self, clause_id: str) -> bool:
        """Verify whether a cited clause ID actually exists in the registry."""
        return clause_id.strip() in self.clauses

    def get_clause(self, clause_id: str) -> PolicyClause | None:
        """Fetch a specific policy clause by ID."""
        return self.clauses.get(clause_id.strip())

    def get_all_clause_ids(self) -> set[str]:
        """Return the set of all active policy clause IDs."""
        return set(self.clauses.keys())

    def get_clauses_for_exception(self, exception_type: str) -> list[PolicyClause]:
        """Retrieve all policy clauses relevant to a given exception type."""
        return [
            c for c in self.clauses.values() if c.exception_type.lower() == exception_type.lower()
        ]


# Singleton instance for general use
policy_registry = PolicyRegistry()
