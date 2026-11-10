"""LLM access layer: versioned prompts, Ollama calls and proposal checks.

Everything model-facing lives here so ``proposal_service`` only orchestrates:
- Prompt templates are loaded from ``prompts/`` (``<version>.md`` and ``<version>_retry.md``).
- The model is called with a JSON schema enforced and temperature 0.
- The reply is checked for shape and for grounding (only retrieved clauses may be cited).

The LLM only suggests. It never calculates hours; the validator does.
"""

import copy
import json
import logging
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from string import Template
from typing import Any

import httpx

from app.config import settings
from app.services.policy_service import PolicyClauseRecord

logger = logging.getLogger(__name__)

PROMPTS_DIR = Path(settings.PROMPTS_DIR)

MAX_RAW_AUDIT_CHARS = 1500
MAX_NOTE_CHARS = 300

# JSON schema handed to Ollama so decoding is constrained to the proposal shape.
_TIME_OR_NULL = {"type": ["string", "null"]}
PROPOSAL_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "proposed_timecard": {
            "type": "object",
            "properties": {
                "checkIn": _TIME_OR_NULL,
                "checkOut": _TIME_OR_NULL,
                "mealStart": _TIME_OR_NULL,
                "mealEnd": _TIME_OR_NULL,
            },
            "required": ["checkIn", "checkOut", "mealStart", "mealEnd"],
        },
        "changed_fields": {"type": "array", "items": {"type": "string"}},
        "reason": {"type": "string"},
        "recommendation": {"type": "string"},
        "confidence": {"type": "number"},
        "missing_information": {"type": "array", "items": {"type": "string"}},
        "policy_citations": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "proposed_timecard",
        "changed_fields",
        "reason",
        "recommendation",
        "confidence",
        "missing_information",
        "policy_citations",
    ],
}


def proposal_schema(allowed_clause_ids: Iterable[str]) -> dict[str, Any]:
    """The proposal schema with `policy_citations` limited to the retrieved clause IDs.

    Ollama constrains decoding to the schema, so the model physically cannot cite a clause
    that does not exist (it used to copy the placeholder `CLAUSE-ID` from the prompt).
    """
    schema = copy.deepcopy(PROPOSAL_JSON_SCHEMA)
    ids = sorted({str(i) for i in allowed_clause_ids})
    if ids:
        schema["properties"]["policy_citations"] = {
            "type": "array",
            "items": {"type": "string", "enum": ids},
            "minItems": 1,
        }
    return schema


@dataclass
class LLMResult:
    """Outcome of a single model call."""

    parsed: dict[str, Any] | None
    raw: str
    model: str
    prompt_version: str
    duration_seconds: float
    error: str | None = None
    errors: list[str] = field(default_factory=list)


def load_prompt(name: str) -> Template:
    """Load a prompt template from the prompts directory."""
    return Template((PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8"))


# What a safe correction looks like, per exception type. Most exceptions are about what the
# punches mean, not about wrong times, so the honest suggestion is "no time change, manager decides".
TYPE_GUIDANCE: dict[str, str] = {
    "missed_punch": (
        "Fill in only the missing punch: the scheduled start for a missing clock-in, or the "
        "scheduled end for a missing clock-out, as the cited clause says. If no schedule exists, "
        "keep the original timecard, list what is missing and ask the manager to verify the real "
        "times."  # DEMO: the "5 hours with no meal punches" refusal was removed so the AI fills the punch
    ),
    "overtime": (
        "The hours were really worked, so do not change any time. Return the original timecard "
        "unchanged, leave changed_fields empty, and recommend that the manager reviews and "
        "authorizes the overtime."
    ),
    "schedule_conflict": (
        "Punches record what happened, so do not move them. Return the original timecard "
        "unchanged, leave changed_fields empty, describe the deviation from the schedule, and "
        "ask the manager to decide how it is treated."
    ),
    "meal_break": (
        "Never invent meal punches. Return the original timecard unchanged, leave changed_fields "
        "empty, and ask the manager to verify whether a break was taken or to apply the policy."
    ),
    "duplicate_punch": (
        "Keep the first punch and ignore the repeat. Return the original timecard unchanged, "
        "leave changed_fields empty, and ask the manager to confirm removing the duplicate."
    ),
    "rest_period": (
        "State plainly that the rest between shifts was below the minimum. Return the original "
        "timecard unchanged, leave changed_fields empty, and ask the manager to document the "
        "reason (schedule change or voluntary swap)."
    ),
    "consecutive_days": (
        "State plainly that the policy limit on consecutive working days is exceeded. Return the "
        "original timecard unchanged, leave changed_fields empty, and ask the manager for "
        "authorization or a schedule correction."
    ),
}
DEFAULT_GUIDANCE = (
    "Change as little as possible, and keep recorded punches unless a clause says otherwise."
)


# Appended to the guidance of every exception that has no time fix.
DECISION_HINT = (
    " In `recommendation`, name the decision you suggest (authorize, do not authorize, or "
    "escalate) and the one fact that should decide it, using only the facts given."
)


def guidance_for(exception_type: str) -> str:
    """Guidance text for an exception type (matches the canonical type names)."""
    key = exception_type.strip().lower()
    text = TYPE_GUIDANCE.get(key, DEFAULT_GUIDANCE)
    return text + DECISION_HINT if key in NO_TIME_CHANGE_TYPES else text


def format_clauses(clauses: list[PolicyClauseRecord]) -> str:
    """Render retrieved clauses for the prompt, flagging declared conflicts."""
    blocks = []
    for c in clauses:
        block = f"[{c.id}] {c.name}\n{c.description}"
        if c.conflicts_with:
            block += f"\n(Note: this clause conflicts with {', '.join(c.conflicts_with)}.)"
        blocks.append(block)
    return "\n\n".join(blocks)


def clean_note(note: str) -> str:
    """Flatten and truncate a free-text note so it stays inside its data block."""
    flat = " ".join(note.split())[:MAX_NOTE_CHARS]
    # Employee text must not be able to close the untrusted-data block early.
    return flat.replace("</employee_data>", "")


def build_prompt(
    *,
    clauses: list[PolicyClauseRecord],
    exception_type: str,
    date: str,
    description: str,
    schedule_start: str,
    schedule_end: str,
    original_timecard: dict[str, Any],
    notes: list[str],
    context: str = "",
    version: str | None = None,
) -> str:
    """Fill the versioned proposal prompt."""
    template = load_prompt(version or settings.PROMPT_VERSION)
    safe_notes = [clean_note(n) for n in notes if n and n.strip()]
    return template.safe_substitute(
        clauses=format_clauses(clauses),
        exception_type=exception_type,
        date=date,
        description=description,
        guidance=guidance_for(exception_type),
        context=context or "none",
        allowed_ids=", ".join(c.id for c in clauses),
        example_clause=clauses[0].id if clauses else "",
        schedule=f"{schedule_start} to {schedule_end}",
        original_timecard=json.dumps(original_timecard),
        notes=json.dumps(safe_notes) if safe_notes else "none",
    )


def build_retry_prompt(base_prompt: str, previous: dict[str, Any], errors: list[str]) -> str:
    """Append the retry instructions (previous answer plus validator errors)."""
    retry = load_prompt(f"{settings.PROMPT_VERSION}_retry").safe_substitute(
        previous=json.dumps(previous),
        errors="\n".join(f"- {e}" for e in errors) or "- Unspecified validation failure.",
    )
    return f"{base_prompt}\n\n---\n\n{retry}"


def _post(client: httpx.Client, url: str, payload: dict[str, Any]) -> httpx.Response:
    resp = client.post(url, json=payload)
    if resp.status_code == 400 and isinstance(payload.get("format"), dict):
        # Older Ollama builds only accept format="json"; keep JSON mode as a floor.
        resp = client.post(url, json={**payload, "format": "json"})
    return resp


def query_llm(
    prompt: str,
    model: str | None = None,
    temperature: float | None = None,
    timeout_seconds: float | None = None,
    schema: dict[str, Any] | None = None,
) -> LLMResult:
    """Call Ollama with the proposal JSON schema enforced.

    Never raises: failures come back as ``LLMResult(parsed=None, error=...)`` so the
    caller can fall through to the rule-based fallback.
    """
    model_name = model or settings.LLM_MODEL
    url = f"{settings.OLLAMA_URL.rstrip('/')}/api/generate"
    payload = {
        "model": model_name,
        "prompt": prompt,
        "stream": False,
        "format": schema or PROPOSAL_JSON_SCHEMA,
        "keep_alive": settings.LLM_KEEP_ALIVE,
        "options": {
            "temperature": settings.LLM_TEMPERATURE if temperature is None else temperature,
            "num_predict": settings.LLM_NUM_PREDICT,
        },
    }
    started = time.monotonic()
    raw = ""
    error: str | None = None
    parsed: dict[str, Any] | None = None
    try:
        with httpx.Client(timeout=timeout_seconds or settings.LLM_TIMEOUT_SECONDS) as client:
            resp = _post(client, url, payload)
        if resp.status_code != 200:
            error = f"Ollama returned HTTP {resp.status_code}"
        else:
            raw = str(resp.json().get("response", ""))
            loaded = json.loads(raw)
            if isinstance(loaded, dict):
                parsed = loaded
            else:
                error = "Model reply was JSON but not an object"
    except (httpx.HTTPError, OSError) as exc:
        error = f"Ollama unavailable: {exc}"
    except json.JSONDecodeError as exc:
        error = f"Model reply was not valid JSON: {exc}"

    if error:
        logger.info("LLM query failed: %s", error)
    return LLMResult(
        parsed=parsed,
        raw=raw,
        model=model_name,
        prompt_version=settings.PROMPT_VERSION,
        duration_seconds=round(time.monotonic() - started, 2),
        error=error,
    )


def check_proposal_shape(parsed: dict[str, Any], allowed_clause_ids: set[str]) -> list[str]:
    """Return LLM-readable errors for shape and grounding problems.

    This runs before the validator: it catches missing keys and citations of clauses
    that were not provided, which the validator's catalog check alone would let through.
    """
    errors: list[str] = []
    timecard = parsed.get("proposed_timecard")
    if not isinstance(timecard, dict):
        errors.append(
            "`proposed_timecard` must be an object with checkIn, checkOut, mealStart, mealEnd."
        )
    for key in ("changed_fields", "missing_information", "policy_citations"):
        if not isinstance(parsed.get(key, []), list):
            errors.append(f"`{key}` must be a list.")

    citations = parsed.get("policy_citations")
    if not isinstance(citations, list) or not citations:
        errors.append(
            "`policy_citations` is empty. Cite at least one of: "
            f"{', '.join(sorted(allowed_clause_ids))}."
        )
    else:
        unknown = [str(c) for c in citations if str(c).strip() not in allowed_clause_ids]
        if unknown:
            errors.append(
                f"Cited clause(s) {', '.join(unknown)} do not exist for this exception. "
                f"Cite only: {', '.join(sorted(allowed_clause_ids))}."
            )
    return errors


# Exceptions that punch times cannot fix: the proposal must keep the original timecard. Worked
# hours are never removed, meal punches are never invented, and recorded punches are not moved.
# Only a missed punch can be filled in.
NO_TIME_CHANGE_TYPES = frozenset(
    {
        "overtime",
        "schedule_conflict",
        "meal_break",
        "duplicate_punch",
        "rest_period",
        "consecutive_days",
    }
)
TIMECARD_FIELDS = ("checkIn", "checkOut", "mealStart", "mealEnd")


def check_timecard_changes(
    proposed: dict[str, Any],
    original: dict[str, Any],
    exception_type: str,
) -> list[str]:
    """Reject proposals that delete recorded punches or edit times that cannot fix the problem.

    These checks do not depend on the exception having a time-based fix, so they also
    protect the exception types the validator has no dedicated rules for.
    """
    errors: list[str] = []
    for key in TIMECARD_FIELDS:
        if original.get(key) and not proposed.get(key):
            errors.append(
                f"Proposed timecard removes the recorded {key} ({original[key]}). "
                "Recorded punches must never be deleted; keep the original value."
            )
    if exception_type in NO_TIME_CHANGE_TYPES:
        changed = [k for k in TIMECARD_FIELDS if proposed.get(k) != original.get(k)]
        if changed:
            errors.append(
                f"A {exception_type.replace('_', ' ')} exception cannot be fixed by changing "
                f"punch times, but {', '.join(changed)} was changed. Return the original "
                "timecard unchanged and explain the policy issue in `reason`."
            )
    return errors


def truncate_for_audit(raw: str) -> str:
    """Bound raw model output stored in the audit log."""
    if len(raw) <= MAX_RAW_AUDIT_CHARS:
        return raw
    return raw[:MAX_RAW_AUDIT_CHARS] + "...[truncated]"
