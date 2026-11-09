"""Policy retrieval service using BM25 ranking over YAML policy clauses.

Retrieves policy clauses matching exception types and descriptions to ground
proposals in real, traceable company regulations.
"""

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from rank_bm25 import BM25Okapi

from app.config import settings

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
    conflicts_with: list[str] = field(default_factory=list)
    keywords: str = ""


_STOPWORDS = frozenset(
    [
        "the",
        "and",
        "for",
        "are",
        "was",
        "with",
        "that",
        "this",
        "from",
        "have",
        "has",
        "had",
        "been",
        "not",
        "but",
        "any",
        "all",
        "who",
        "when",
        "than",
        "then",
        "into",
        "only",
        "may",
        "must",
        "shall",
        "also",
        "such",
        "their",
        "there",
        "which",
        "while",
    ]
)


_CLOCK_TIME = re.compile(r"[0-9]{1,2}:[0-9]{2}")


def _stem(word: str) -> str:
    """Very light stemmer so "shifts"/"shift" and "punches"/"punch" match."""
    for suffix in ("ing", "es", "ed", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            return word[: -len(suffix)]
    return word


def _tokenize(text: str) -> list[str]:
    """Tokenize, drop stopwords and stem text for BM25 ranking."""
    clean = "".join(ch.lower() if ch.isalnum() else " " for ch in text)
    return [
        _stem(word)
        for word in clean.split()
        if word not in _STOPWORDS and (len(word) > 2 or word.isdigit())
    ]


class PolicyService:
    """Manages policy loading from YAML files and BM25 retrieval."""

    def __init__(self, policies_dir: Path | str | None = None) -> None:
        self.clauses: dict[str, PolicyClauseRecord] = {}
        # Try to locate repository policies directory
        if policies_dir:
            self.policies_path = Path(policies_dir)
        else:
            # backend/app/services -> dayforce-team2/policies
            self.policies_path = Path(settings.POLICIES_DIR)

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
                                conflicts_with=[str(c) for c in item.get("conflicts_with", [])],
                                keywords=str(item.get("keywords", "")),
                            )
                except (yaml.YAMLError, OSError, ValueError) as err:
                    logger.warning("Failed to parse policy YAML %s: %s", yaml_file, err)

        return len(self.clauses)

    @staticmethod
    def _normalize_type(exception_type: str) -> str:
        """Map exception type variants (e.g. "missing_punch") onto canonical types."""
        clean_type = exception_type.strip().lower()
        if clean_type in ("duplicate_punch", "rest_period", "consecutive_days"):
            return clean_type
        if "miss" in clean_type or "punch" in clean_type:
            return "missed_punch"
        if "overtime" in clean_type:
            return "overtime"
        if "conflict" in clean_type or "sched" in clean_type:
            return "schedule_conflict"
        if "meal" in clean_type or "break" in clean_type:
            return "meal_break"
        return clean_type

    def retrieve_policies(
        self,
        exception_type: str,
        query_context: str = "",
        top_k: int = 3,
        preferred_id: str | None = None,
    ) -> list[tuple[PolicyClauseRecord, float]]:
        """Return the top_k clauses for an exception, best first, with confidence scores.

        Filters by exception type where possible, then ranks using BM25. When the
        best clause is in conflict with another clause of the same type, the
        conflicting clause is pulled into the result so the LLM can see (and flag)
        the conflict instead of silently picking a side.

        ``preferred_id`` is the clause the detector already tied to the exception. It is
        trusted over BM25 and moved to the front when it exists in the catalog, because
        keyword ranking on a handful of short clauses can pick a near-miss (for example a
        clock-in clause for a missing clock-out).
        """
        ranked = self._rank(exception_type, query_context, top_k)
        preferred = self.clauses.get((preferred_id or "").strip())
        if preferred is None or preferred.exception_type != self._normalize_type(exception_type):
            return ranked
        rest = [(c, conf) for c, conf in ranked if c.id != preferred.id]
        return [(preferred, 0.95), *rest][: max(1, top_k) + 1]

    def _rank(
        self,
        exception_type: str,
        query_context: str,
        top_k: int,
    ) -> list[tuple[PolicyClauseRecord, float]]:
        """BM25 ranking plus conflict surfacing (see retrieve_policies)."""
        target_type = self._normalize_type(exception_type)
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
            return [(fallback, 0.5)]

        if len(candidates) == 1:
            return [(candidates[0], 0.95)]

        # Name and keywords are repeated so they outweigh incidental words in long descriptions.
        corpus = [
            f"{c.name} {c.keywords} {c.name} {c.keywords} {c.description}" for c in candidates
        ]
        tokenized_corpus = [_tokenize(doc) for doc in corpus]
        # Clock times (09:00, 14:30) say nothing about which clause applies and only add noise.
        query_tokens = _tokenize(_CLOCK_TIME.sub(" ", query_context) or exception_type)
        if not any(tokenized_corpus) or not query_tokens:
            return [(candidates[0], 0.90)]

        scores = BM25Okapi(tokenized_corpus).get_scores(query_tokens)
        ranked = sorted(range(len(candidates)), key=lambda i: (-float(scores[i]), i))

        results: list[tuple[PolicyClauseRecord, float]] = []
        for idx in ranked[: max(1, top_k)]:
            # Normalize confidence to [0.75, 0.99] range for BM25 match
            raw = max(0.0, float(scores[idx]))
            confidence = min(0.99, max(0.75, 0.75 + (raw / (raw + 5.0)) * 0.24))
            results.append((candidates[idx], round(confidence, 2)))

        # Surface conflicts with the best clause (in either direction)
        best = results[0][0]
        present = {c.id for c, _ in results}
        for other in candidates:
            if other.id in present:
                continue
            if other.id in best.conflicts_with or best.id in other.conflicts_with:
                results.append((other, 0.75))
                present.add(other.id)
        return results

    def retrieve_policy(
        self,
        exception_type: str,
        query_context: str = "",
    ) -> tuple[PolicyClauseRecord, float]:
        """Retrieve the single most relevant policy clause using BM25 ranking."""
        return self.retrieve_policies(exception_type, query_context, top_k=1)[0]


# Global policy service instance
policy_service = PolicyService()
