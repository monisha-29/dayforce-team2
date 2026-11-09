"""Policy retrieval service using BM25 ranking over YAML policy clauses.

Retrieves policy clauses matching exception types and descriptions to ground
proposals in real, traceable company regulations.
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from rank_bm25 import BM25Okapi  # type: ignore[import-untyped]

logger = logging.getLogger(__name__)

# Standard fallback catalog if no YAML policies are present
DEFAULT_POLICY_CLAUSES: dict[str, dict[str, Any]] = {
    "PUNCH-01": {
        "id": "PUNCH-01",
        "name": "Missed Clock-Out Resolution",
        "exception_type": "missed_punch",
        "description": "When an employee clocks in but misses clock-out, determine shift end from schedule or manager verification. Default resolution aligns with scheduled shift end.",
        "parameters": {"default_resolution": "scheduled_end"},
    },
    "PUNCH-02": {
        "id": "PUNCH-02",
        "name": "Missing Clock-In Resolution",
        "exception_type": "missed_punch",
        "description": "When an employee clocks out without a prior clock-in, verify attendance and record approved shift start based on assigned schedule.",
        "parameters": {"default_resolution": "scheduled_start"},
    },
    "OT-01": {
        "id": "OT-01",
        "name": "Daily Overtime Rule",
        "exception_type": "overtime",
        "description": "Hours worked in excess of 8.0 regular hours in a single workday qualify as daily overtime and require manager authorization.",
        "parameters": {"daily_threshold_hours": 8.0},
    },
    "OT-02": {
        "id": "OT-02",
        "name": "Weekly Overtime Rule",
        "exception_type": "overtime",
        "description": "Hours worked in excess of 40.0 regular hours in a workweek qualify as weekly overtime and require manager sign-off.",
        "parameters": {"weekly_threshold_hours": 40.0},
    },
    "SCHED-01": {
        "id": "SCHED-01",
        "name": "Tardiness and Schedule Adherence",
        "exception_type": "schedule_conflict",
        "description": "Arrivals exceeding 5 minutes after scheduled start are flagged as tardy; departures more than 5 minutes early are flagged as early exit.",
        "parameters": {"grace_period_minutes": 5},
    },
    "SCHED-02": {
        "id": "SCHED-02",
        "name": "Unscheduled Shift Work",
        "exception_type": "schedule_conflict",
        "description": "Shifts worked without a prior schedule assignment or outside scheduled shift boundaries require manager sign-off.",
        "parameters": {"requires_manager_approval": True},
    },
    "MEAL-01": {
        "id": "MEAL-01",
        "name": "Mandatory Meal Break (>5 Hours)",
        "exception_type": "meal_break",
        "description": "Shifts longer than 5.0 hours require at least one uninterrupted unpaid meal break of at least 30 minutes. Historical meal break punches must never be fabricated automatically.",
        "parameters": {"shift_threshold_hours": 5.0, "min_break_minutes": 30},
    },
    "MEAL-02": {
        "id": "MEAL-02",
        "name": "Short or Interrupted Meal Break",
        "exception_type": "meal_break",
        "description": "Meal breaks shorter than 30 minutes or delayed beyond the 6th hour of work trigger a meal break exception requiring manager verification.",
        "parameters": {"min_break_minutes": 30, "latest_start_hour": 6.0},
    },
}


@dataclass
class PolicyClauseRecord:
    id: str
    name: str
    exception_type: str
    description: str
    parameters: dict[str, Any] = field(default_factory=dict)


def _tokenize(text: str) -> list[str]:
    """Tokenize and normalize text for BM25 ranking."""
    clean = "".join(ch.lower() if ch.isalnum() else " " for ch in text)
    return [word for word in clean.split() if len(word) > 2]


class PolicyService:
    """Manages policy loading from YAML files and BM25 retrieval."""

    def __init__(self, policies_dir: Path | str | None = None) -> None:
        self.clauses: dict[str, PolicyClauseRecord] = {}
        # Try to locate repository policies directory
        if policies_dir:
            self.policies_path = Path(policies_dir)
        else:
            # backend/app/services -> dayforce-team2/policies
            self.policies_path = Path(__file__).resolve().parents[3] / "policies"

        self.reload_policies()

    def reload_policies(self) -> int:
        """Load YAML policies from disk or fall back to default catalog."""
        self.clauses.clear()

        # 1. Load from default catalog first
        for cid, data in DEFAULT_POLICY_CLAUSES.items():
            self.clauses[cid] = PolicyClauseRecord(
                id=cid,
                name=data["name"],
                exception_type=data["exception_type"],
                description=data["description"],
                parameters=data.get("parameters", {}),
            )

        # 2. Check for YAML files in directory and override/supplement
        if self.policies_path.is_dir():
            for yaml_file in sorted(self.policies_path.glob("*.yaml")) + sorted(
                self.policies_path.glob("*.yml")
            ):
                try:
                    with open(yaml_file, "r", encoding="utf-8") as f:
                        content = yaml.safe_load(f)
                    if isinstance(content, dict) and "clauses" in content:
                        raw_list = content["clauses"]
                    elif isinstance(content, list):
                        raw_list = content
                    else:
                        raw_list = []

                    for item in raw_list:
                        if isinstance(item, dict) and "id" in item:
                            cid = str(item["id"]).strip()
                            self.clauses[cid] = PolicyClauseRecord(
                                id=cid,
                                name=str(item.get("name", cid)),
                                exception_type=str(item.get("exception_type", "general")),
                                description=str(item.get("description", "")),
                                parameters=item.get("parameters", {}),
                            )
                except (yaml.YAMLError, OSError, ValueError) as err:
                    logger.warning("Failed to parse policy YAML %s: %s", yaml_file, err)

        return len(self.clauses)

    def retrieve_policy(
        self,
        exception_type: str,
        query_context: str = "",
    ) -> tuple[PolicyClauseRecord, float]:
        """Retrieve the most relevant policy clause using BM25 ranking.

        Filters by exception type where possible, then ranks using BM25.
        Returns the top matching PolicyClauseRecord and a confidence score (0.0 to 1.0).
        """
        clean_type = exception_type.strip().lower()

        # Normalize exception type variants (e.g. "missing_punch" -> "missed_punch")
        if "miss" in clean_type or "punch" in clean_type:
            target_type = "missed_punch"
        elif "overtime" in clean_type:
            target_type = "overtime"
        elif "conflict" in clean_type or "sched" in clean_type:
            target_type = "schedule_conflict"
        elif "meal" in clean_type or "break" in clean_type:
            target_type = "meal_break"
        else:
            target_type = clean_type

        # Filter candidate clauses
        candidates = [c for c in self.clauses.values() if c.exception_type == target_type]
        if not candidates:
            candidates = list(self.clauses.values())

        if not candidates:
            # Fallback clause if registry is unexpectedly empty
            fallback = PolicyClauseRecord(
                id="GEN-01",
                name="General Timecard Policy",
                exception_type="general",
                description="General time and attendance policy adherence.",
            )
            return fallback, 0.5

        if len(candidates) == 1:
            return candidates[0], 0.95

        # Perform BM25 ranking
        corpus = [f"{c.name} {c.description}" for c in candidates]
        tokenized_corpus = [_tokenize(doc) for doc in corpus]

        # Handle empty tokens
        if not any(tokenized_corpus):
            return candidates[0], 0.90

        bm25 = BM25Okapi(tokenized_corpus)
        query_tokens = _tokenize(f"{exception_type} {query_context}")
        if not query_tokens:
            return candidates[0], 0.90

        scores = bm25.get_scores(query_tokens)
        best_idx = int(scores.argmax())
        best_clause = candidates[best_idx]
        max_score = float(scores[best_idx])

        # Normalize confidence to [0.70, 0.99] range for BM25 match
        confidence = min(0.99, max(0.75, 0.75 + (max_score / (max_score + 5.0)) * 0.24))
        return best_clause, round(confidence, 2)


# Global policy service instance
policy_service = PolicyService()
