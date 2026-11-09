# Timecard Exception Agent — Rules & Validation Specification (Person 3)

**Author:** Person 3 (Rules and Validation Developer)  
**Status:** Implemented & Verified  
**Package:** `backend/app/rules/`  
**Core Principle:** *The LLM suggests. Code decides. A human approves.*

---

## 1. Executive Summary

This document establishes the exact mathematical, temporal, and legal boundary rules used by the Timecard Exception Agent.

Under our system architecture:
1. **The LLM never calculates hours:** All gross, net, break, daily overtime, and weekly overtime math is executed exclusively by deterministic Python code.
2. **The LLM never modifies timecards directly:** All proposals must pass 5 strict code-level safety checks.
3. **The system never fabricates attendance:** The fallback mechanism will never invent missing punches or synthesize meal breaks without source evidence; unresolvable discrepancies escalate directly to the manager.

---

## 2. Shift Definition & Midnight Crossing

### Overnight Shift Counting Rule
* **Shift Association:** A shift that crosses midnight (e.g., clock-in at 22:00 on Friday, clock-out at 06:00 on Saturday) is counted as belonging to the **workday of the initial clock-in** (Friday).
* **Continuous Duration:** Working duration is calculated using continuous timestamp subtraction:
  $$\text{Gross Hours} = \frac{\text{Clock-Out Timestamp} - \text{Clock-In Timestamp}}{3600}$$
  A shift from `2026-11-07 22:00` to `2026-11-08 06:00` is computed as exactly $8.0$ hours belonging to the `2026-11-07` workday.
* **Split Shifts:** If an employee clocks out and clocks in again within the same workday, each interval is calculated independently and summed into the workday's net hours:
  $$\text{Net Work Hours} = \sum_{i} (\text{ShiftEnd}_i - \text{ShiftStart}_i) - \text{Explicit Breaks}$$

---

## 3. The Four Core Exception Types

### A. Missed Punch (`missed_punch`)
* **Missing Clock-Out (Policy `PUNCH-01`):**
  * Trigger: An `IN` punch is followed by another `IN` punch, or remains unclosed at shift end.
  * Severity: `HIGH`.
* **Missing Clock-In (Policy `PUNCH-02`):**
  * Trigger: An `OUT` punch occurs with no preceding `IN` punch.
  * Severity: `HIGH`.
* **Scheduled Shift Without Attendance (Policy `PUNCH-02`):**
  * Trigger: An employee has an active assigned schedule for the date but zero punches recorded.
  * Severity: `HIGH`.

### B. Overtime (`overtime`)
* **Daily Overtime (Policy `OT-01`):**
  * Trigger: Net working hours within a single workday exceed the daily threshold ($8.0$ hours).
  * Boundary:
    * $8.000$ hours = Regular hours ($0.0$ overtime).
    * $8.010$ hours = Daily overtime ($0.01$ overtime).
  * Severity: `MEDIUM` for $\le 2.0$h overtime; `HIGH` for $>2.0$h overtime.
* **Weekly Overtime (Policy `OT-02`):**
  * Trigger: Cumulative regular hours in a single workweek exceed $40.0$ hours.
  * Non-Pyramiding Rule: Hours already compensated as daily overtime do not count toward the $40.0$-hour weekly regular threshold.
  * Boundary:
    * Exactly $40.00$ cumulative regular hours = $0.0$ weekly overtime.
    * $40.25$ cumulative regular hours = $0.25$ weekly overtime.
  * Severity: `HIGH`.
* **Excessive Shift Limit (Policy `OT-01`):**
  * Trigger: Net hours in a single shift exceed $12.0$ hours (`HIGH`) or $\ge 16.0$ hours (`CRITICAL`).

### C. Schedule Conflict (`schedule_conflict`)
* **Late Clock-In / Tardiness (Policy `SCHED-01`):**
  * Trigger: First clock-in occurs after $\text{Scheduled Start} + \text{Grace Period}$ (default $5$ minutes).
  * Example: Scheduled at 09:00 with 5m grace. Clock-in at 09:04 is compliant. Clock-in at 09:06 triggers exception.
* **Early Departure (Policy `SCHED-01`):**
  * Trigger: Final clock-out occurs before $\text{Scheduled End} - \text{Grace Period}$ (default $5$ minutes).
* **Unscheduled Shift (Policy `SCHED-02`):**
  * Trigger: Punches recorded on a date where no schedule was assigned in the database.
* **Overlapping Schedules (Policy `SCHED-02`):**
  * Trigger: Two conflicting shifts assigned to the same employee that overlap chronologically.

### D. Meal Break (`meal_break`)
* **Missing Meal Break (Policy `MEAL-01`):**
  * Trigger: Gross working duration $\ge 5.0$ hours without an uninterrupted meal break of at least $30$ minutes.
  * Severity: `HIGH`.
* **Short Meal Break (Policy `MEAL-02`):**
  * Trigger: A break was recorded, but its uninterrupted duration was $< 30$ minutes (e.g. 15 or 20 minutes).
  * Severity: `MEDIUM`.
* **Delayed Meal Break (Policy `MEAL-02`):**
  * Trigger: Employee worked continuously for $> 5.0$ hours before commencing their first meal break.
  * Severity: `MEDIUM`.

### E. Extended Exception Types (beyond the four in the project spec)

These three were added after the original plan. Code: `backend/app/rules/detectors/cross_day.py`.
Thresholds live in `CrossDayConfig`.

* **Duplicate Punch (`duplicate_punch`, Policy `DUP-01`):**
  * Trigger: The same punch type is recorded again within $2$ minutes of the previous kept punch (a terminal double tap). Exactly $2$ minutes is a duplicate; $3$ minutes is not.
  * Handling: The first punch is kept. Duplicates are removed before the other detectors run, so a double tap is never reported as a missed punch. A second `IN` more than $2$ minutes later is still a missed punch.
  * Severity: `LOW`.
* **Rest Period Violation (`rest_period`, Policy `REST-01`):**
  * Trigger: Fewer than $8.0$ hours between the last clock-out of one workday and the first clock-in of the next worked day. Exactly $8.0$ hours is compliant.
  * Reported on the date of the later shift. Shifts without a clock-out are skipped.
  * Severity: `MEDIUM`.
* **Consecutive Days (`consecutive_days`, Policy `CONSEC-01`):**
  * Trigger: The $7$th consecutive calendar day with a clock-in (maximum is $6$). Flagged once per streak, on the $7$th day. A day with no punches resets the streak.
  * Severity: `MEDIUM`.

For all three the fallback proposes **no timecard change** and escalates to the manager, because punch times cannot fix these problems.

---

## 4. Proposal Safety Validator (5 Deterministic Checks)

Every proposal generated by Person 4's LLM must pass all 5 checks:

| Check | Name | Description | Rejection Code |
|---|---|---|---|
| **1** | Format & Schema | Valid JSON object, all required fields present, timestamps ISO-8601 compliant. | `INVALID_JSON_FORMAT`, `MISSING_REQUIRED_FIELDS`, `SCHEMA_VALIDATION_ERROR` |
| **2** | Policy Verification | Every cited policy ID exists in repository YAML files. | `NO_POLICY_CITED`, `FABRICATED_POLICY_ID` |
| **3** | Hours Recalculation | Code re-computes hours from punch timestamps; discards LLM math; enforces daily regular limits. | `CALCULATION_ERROR`, `OVERTIME_LIMIT_EXCEEDED` |
| **4** | No New Violations | Re-runs the detectors on the proposed timecard; guarantees the fix does not introduce a secondary violation. Violations the recorded timecard already had are not counted against the proposal (each is its own exception), and a proposal that changes no punches cannot "create" hours. The original exception stays unresolved unless the proposal acknowledges it. | `NEW_VIOLATION_<TYPE>` |
| **5** | Allowed Limits & Security | Shift duration $\le 16$h, no future timestamps, shift date alignment, employee ID ownership, and prompt injection defense. | `EXCESSIVE_SHIFT_DURATION`, `FUTURE_TIMESTAMP_PROHIBITED`, `TIMESTAMP_DATE_MISMATCH`, `EMPLOYEE_OWNERSHIP_MISMATCH`, `UNAUTHORIZED_PROPOSAL_TAMPERING` |

---

## 5. Fallback & Anti-Fabrication Guarantees

When an LLM proposal fails validation twice:
1. **Short Shifts ($<5.0$h):** If schedule ground truth exists and the shift does not require a meal break, the fallback proposes clock-out at the scheduled shift boundary for manager review.
2. **Long Shifts ($\ge 5.0$h):** Code **never** fabricates midpoint break punches. If an unclosed shift $>5.0$h has no recorded break punches, the fallback escalates to the manager.
3. **Missing Schedules:** Code **never** invents punch times when no schedule exists; escalates directly to manager.
4. **Validation:** All fallback proposals are independently checked by `ProposalValidator`.

---

## 6. Integration Contract (Pydantic / JSON)

### LLM Proposal Format (Person 4 Input)
```json
{
  "exception_id": "EXC-1042",
  "suggested_action": "insert_punch",
  "proposed_punches": [
    {
      "punch_type": "OUT",
      "timestamp": "2026-11-08T17:00:00",
      "action": "insert"
    }
  ],
  "policy_citations": ["PUNCH-01"],
  "reasoning": "Inserting clock-out at scheduled shift end time."
}
```

### Validator Error Response Format (For Person 4 Retry Prompt)
```json
{
  "valid": false,
  "status": "FAILED",
  "errors": [
    {
      "code": "OVERTIME_LIMIT_EXCEEDED",
      "message": "Proposed shift creates 9.50 working hours. Configured daily limit is 8.0 hours.",
      "field": "proposed_punches"
    }
  ]
}
```
Person 4's retry loop takes `errors[0].message` and feeds it back into the prompt for the single allowable retry attempt.
