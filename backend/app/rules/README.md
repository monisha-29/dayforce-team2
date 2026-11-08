# Rules and Validation Module (Person 3)
## Timecard Exception Agent

The **Rules and Validation** module serves as the deterministic core and safety harness for the Timecard Exception Agent.

> **Principle:** *The LLM suggests. Code decides. A human approves.*

---

## Architecture Overview

```
Timecard Data
      │
      ▼
[Four Exception Detectors] ────► [TimecardException Objects]
      │                                   │
      │                                   ▼
      │                       Person 4 LLM Proposal
      │                                   │
      ▼                                   ▼
[HoursCalculator] ─────────────► [ProposalValidator] (5 Checks)
                                          │
                                 ┌────────┴────────┐
                              PASS               FAIL (Retry once)
                                 │                 │
                                 ▼               FAIL (Second time)
                           Manager Review          │
                                                   ▼
                                           [FallbackEngine]
                                                   │
                                          ┌────────┴────────┐
                                       VALID             INVALID / UNSAFE
                                          │                 │
                                          ▼                 ▼
                                   Manager Review       Escalate to Manager
                                   (Badge: Fallback)    (No punch changes)
```

---

## Module Components

### 1. Working Hours Calculator (`hours_calculator.py`)
* **Deterministic Math:** Pure Python using `datetime` and `timedelta`. The LLM **never** performs math.
* **Capabilities:**
  * Daily gross hours, break deductions, net working hours.
  * Overnight shifts (e.g. 22:00 to 06:00).
  * Split shifts with multiple `IN` / `OUT` punch pairs.
  * Explicit break intervals (`BREAK_START` / `BREAK_END`).
  * Daily overtime (> 8.0h threshold) with boundary precision (8.00h is regular; 8.01h is overtime).
  * Weekly overtime (> 40.0h regular threshold) with non-pyramiding logic.
  * Detects missing punches and overlapping punch intervals.

### 2. Four Exception Detectors (`detectors/`)
* **Missed Punch Detector (`detectors/missed_punch.py`):**
  * Detects missing clock-in, missing clock-out, orphan punches, and unrecorded scheduled shifts.
  * Policies: `PUNCH-01`, `PUNCH-02`.
* **Overtime Detector (`detectors/overtime.py`):**
  * Detects daily overtime (> 8.0h), weekly overtime (> 40.0h), and excessive shift hours (> 12h / 16h with Critical severity).
  * Policies: `OT-01`, `OT-02`.
* **Schedule Conflict Detector (`detectors/schedule_conflict.py`):**
  * Detects late arrivals (configurable grace period, default 5m), early exits, unscheduled shifts, and overlapping schedules.
  * Policies: `SCHED-01`, `SCHED-02`.
* **Meal Break Detector (`detectors/meal_break.py`):**
  * Detects shifts > 5.0h without an uninterrupted 30-min break, short breaks (< 30m), and delayed breaks (> 5.0h continuous work).
  * Policies: `MEAL-01`, `MEAL-02`.
* **Orchestrator (`detect_all_exceptions`):**
  * Groups punches and schedules by employee and date, manages overnight shifts, and deduplicates exception records.

### 3. Safety Validator (`validator.py`)
Executes **5 Independent Deterministic Checks**:
1. **JSON Format & Schema:** Validates payload structure, required fields, and ISO-8601 timestamps.
2. **Policy Clauses:** Verifies that all cited policy IDs exist in the repository catalog (`policies/` or default registry). Rejects fabricated IDs.
3. **Working Hours Recalculation:** Code re-computes daily/weekly hours using `HoursCalculator`. Hallucinated LLM hours are discarded. Overtime thresholds are enforced.
4. **No New Violations:** Runs all 4 detectors against the proposed revised timecard to guarantee the fix does not introduce new exceptions.
5. **Allowed Limits & Security:** Verifies shift duration sanity (< 16h), blocks future timestamps, and defends against prompt injection patterns in reasoning/notes.

### 4. Rule-Based Fallback Engine (`fallback.py`)
* Activated when Person 4's LLM proposal fails validation twice.
* Generates deterministic corrections strictly using assigned schedule boundaries for short shifts (<5h) or shifts with confirmed breaks.
* **Anti-Fabrication & Escalation Guarantee:** Code **never** invents historical employee punches or fabricates unrecorded meal breaks. If attendance cannot be established safely without guessing (e.g., shifts exceeding 5h with no break punches, meal break violations, or missing schedules), it immediately escalates to the manager with `requires_manager_review=True` and `proposed_correction=None`.
* All fallback proposals are independently validated through `ProposalValidator` before return.

---

## Integration Guide

### For Person 2 (Backend API & Database)
```python
from app.rules import (
    HoursCalculator,
    detect_all_exceptions,
    ProposalValidator,
    FallbackEngine,
    Punch,
    Schedule,
)

# 1. Detection endpoint / batch ingest
exceptions = detect_all_exceptions(punches=db_punches, schedules=db_schedules)
# Save exceptions into `exceptions` table for GET /exceptions

# 2. Proposal validation in POST /exceptions/{id}/proposal
validator = ProposalValidator()
val_result = validator.validate(
    original_punches=db_punches,
    proposal_input=llm_proposal_json,
    original_schedule=db_schedule,
    original_exception=db_exception,
)

if val_result.valid:
    # Save proposal with status PASSED
    pass
else:
    # Trigger LLM retry once, or invoke fallback
    pass

# 3. Fallback execution
fallback_engine = FallbackEngine()
fallback_result = fallback_engine.generate_fallback(
    exception=db_exception,
    punches=db_punches,
    schedule=db_schedule,
)
```

### For Person 4 (LLM & Prompts)
* **Agreed Proposal JSON Format:**
```json
{
  "exception_id": "EXC-123456",
  "suggested_action": "insert_punch",
  "proposed_punches": [
    {
      "punch_type": "OUT",
      "timestamp": "2026-11-07T17:00:00",
      "action": "insert"
    }
  ],
  "policy_citations": ["PUNCH-01"],
  "reasoning": "Employee clocked in at 09:00 with no clock-out recorded. Aligned with scheduled 17:00 end."
}
```
* **Retry Error Feedback Format:**
When a proposal fails validation, `val_result.errors` provides structured, LLM-readable errors:
```json
{
  "valid": false,
  "errors": [
    {
      "code": "OVERTIME_LIMIT_EXCEEDED",
      "message": "Proposed shift creates 9.50 working hours. Configured daily limit is 8.0 hours.",
      "field": "proposed_punches"
    }
  ]
}
```
Person 4's retry prompt passes `error["message"]` back to Ollama for the single retry attempt.

---

## Testing & Quality

* **Test Suite:** 59 tests across 9 test modules covering all modules, boundary conditions, edge cases, security, and Hypothesis property-based testing.
* **Execution:**
```bash
pytest backend/tests
```
* **Linting & Strict Type Checking:**
```bash
ruff check backend/app/rules backend/tests
mypy backend/app/rules
```

