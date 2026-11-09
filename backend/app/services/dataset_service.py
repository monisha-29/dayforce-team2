"""Dataset loading service for ingesting synthetic or benchmark attendance records.

Loads employees, schedules, punches, and optional pre-seeded exceptions into the database
in strict dependency order with Pydantic validation, idempotent duplicate prevention,
and transactional safety.
"""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.models.employee import EmployeeModel
from app.models.exception import ExceptionModel
from app.models.punch import PunchModel
from app.models.schedule import ScheduleModel


class DatasetLoadResult(BaseModel):
    """Execution summary of dataset ingestion."""

    employees_loaded: int = Field(default=0, description="New employees inserted")
    schedules_loaded: int = Field(default=0, description="New schedules inserted")
    punches_loaded: int = Field(default=0, description="New punches inserted")
    exceptions_loaded: int = Field(default=0, description="New exceptions inserted")
    skipped_count: int = Field(
        default=0, description="Records skipped because identical or existing"
    )
    errors: list[str] = Field(default_factory=list, description="Validation or relational errors")

    @property
    def total_loaded(self) -> int:
        return (
            self.employees_loaded
            + self.schedules_loaded
            + self.punches_loaded
            + self.exceptions_loaded
        )


def _parse_datetime(val: Any) -> datetime:
    """Safely parse datetime from ISO string or datetime object."""
    if isinstance(val, datetime):
        return val.replace(tzinfo=None)
    if isinstance(val, str):
        # Handle ISO strings with Z or timezone offset
        clean_str = val.replace("Z", "+00:00")
        dt = datetime.fromisoformat(clean_str)
        return dt.replace(tzinfo=None)
    raise ValueError(f"Cannot parse datetime from: {val!r}")


def load_dataset_from_dict(session: Session, data: dict[str, Any]) -> DatasetLoadResult:
    """Validate and ingest raw dataset dictionary in dependency order into database.

    Strict ingestion sequence:
    1. Employees (referenced by schedules, punches, and exceptions)
    2. Schedules
    3. Punches
    4. Exceptions
    """
    result = DatasetLoadResult()

    if not isinstance(data, dict):
        result.errors.append(f"Root dataset must be a dictionary/object, got {type(data).__name__}")
        return result

    raw_employees = data.get("employees", [])
    raw_schedules = data.get("schedules", [])
    raw_punches = data.get("punches", [])
    raw_exceptions = data.get("exceptions", [])

    # Keep track of active employee IDs (both existing in DB and added in current batch)
    known_employee_ids: set[str] = {row[0] for row in session.query(EmployeeModel.id).all()}

    # -------------------------------------------------------------
    # 1. EMPLOYEES
    # -------------------------------------------------------------
    for idx, raw_emp in enumerate(raw_employees):
        if not isinstance(raw_emp, dict):
            result.errors.append(f"employees[{idx}] is not an object")
            continue

        emp_id = str(raw_emp.get("id", "")).strip()
        if not emp_id:
            result.errors.append(f"employees[{idx}] missing required 'id'")
            continue

        existing_emp = session.get(EmployeeModel, emp_id)
        if existing_emp is not None:
            # Update attributes if needed
            existing_emp.name = str(raw_emp.get("name", existing_emp.name))
            existing_emp.department = str(raw_emp.get("department", existing_emp.department))
            existing_emp.shift = str(raw_emp.get("shift", existing_emp.shift))
            existing_emp.shift_start = str(raw_emp.get("shift_start", existing_emp.shift_start))
            existing_emp.shift_end = str(raw_emp.get("shift_end", existing_emp.shift_end))
            result.skipped_count += 1
        else:
            new_emp = EmployeeModel(
                id=emp_id,
                name=str(raw_emp.get("name", "")),
                department=str(raw_emp.get("department", "")),
                shift=str(raw_emp.get("shift", "")),
                shift_start=str(raw_emp.get("shift_start", "09:00")),
                shift_end=str(raw_emp.get("shift_end", "17:00")),
            )
            session.add(new_emp)
            result.employees_loaded += 1
            known_employee_ids.add(emp_id)

    # Flush employees so foreign keys can be resolved
    session.flush()

    # -------------------------------------------------------------
    # 2. SCHEDULES
    # -------------------------------------------------------------
    for idx, raw_sched in enumerate(raw_schedules):
        if not isinstance(raw_sched, dict):
            result.errors.append(f"schedules[{idx}] is not an object")
            continue

        sched_id = str(raw_sched.get("id", "")).strip()
        emp_id = str(raw_sched.get("employee_id", "")).strip()

        if not sched_id or not emp_id:
            result.errors.append(f"schedules[{idx}] requires 'id' and 'employee_id'")
            continue

        if emp_id not in known_employee_ids:
            result.errors.append(
                f"schedules[{idx}] employee_id '{emp_id}' not found in database or dataset"
            )
            continue

        try:
            start_dt = _parse_datetime(raw_sched.get("start_time"))
            end_dt = _parse_datetime(raw_sched.get("end_time"))
        except (ValueError, TypeError) as err:
            result.errors.append(f"schedules[{idx}] invalid start/end datetime: {err}")
            continue

        existing_sched = session.get(ScheduleModel, sched_id)
        if existing_sched is not None:
            existing_sched.employee_id = emp_id
            existing_sched.date = str(raw_sched.get("date", existing_sched.date))
            existing_sched.start_time = start_dt
            existing_sched.end_time = end_dt
            existing_sched.department_id = raw_sched.get(
                "department_id", existing_sched.department_id
            )
            existing_sched.scheduled_break_minutes = int(
                raw_sched.get("scheduled_break_minutes", existing_sched.scheduled_break_minutes)
            )
            result.skipped_count += 1
        else:
            new_sched = ScheduleModel(
                id=sched_id,
                employee_id=emp_id,
                date=str(raw_sched.get("date", start_dt.strftime("%Y-%m-%d"))),
                start_time=start_dt,
                end_time=end_dt,
                department_id=raw_sched.get("department_id"),
                scheduled_break_minutes=int(raw_sched.get("scheduled_break_minutes", 30)),
            )
            session.add(new_sched)
            result.schedules_loaded += 1

    # -------------------------------------------------------------
    # 3. PUNCHES
    # -------------------------------------------------------------
    for idx, raw_punch in enumerate(raw_punches):
        if not isinstance(raw_punch, dict):
            result.errors.append(f"punches[{idx}] is not an object")
            continue

        punch_id = str(raw_punch.get("id", "")).strip()
        emp_id = str(raw_punch.get("employee_id", "")).strip()

        if not punch_id or not emp_id:
            result.errors.append(f"punches[{idx}] requires 'id' and 'employee_id'")
            continue

        if emp_id not in known_employee_ids:
            result.errors.append(
                f"punches[{idx}] employee_id '{emp_id}' not found in database or dataset"
            )
            continue

        try:
            punch_dt = _parse_datetime(raw_punch.get("timestamp"))
        except (ValueError, TypeError) as err:
            result.errors.append(f"punches[{idx}] invalid timestamp: {err}")
            continue

        existing_punch = session.get(PunchModel, punch_id)
        if existing_punch is not None:
            existing_punch.employee_id = emp_id
            existing_punch.timestamp = punch_dt
            existing_punch.punch_type = str(raw_punch.get("punch_type", existing_punch.punch_type))
            existing_punch.source = str(raw_punch.get("source", existing_punch.source))
            existing_punch.notes = raw_punch.get("notes", existing_punch.notes)
            result.skipped_count += 1
        else:
            new_punch = PunchModel(
                id=punch_id,
                employee_id=emp_id,
                timestamp=punch_dt,
                punch_type=str(raw_punch.get("punch_type", "IN")),
                source=str(raw_punch.get("source", "terminal")),
                notes=raw_punch.get("notes"),
            )
            session.add(new_punch)
            result.punches_loaded += 1

    # -------------------------------------------------------------
    # 4. EXCEPTIONS (if pre-computed or provided by dataset)
    # -------------------------------------------------------------
    for idx, raw_exc in enumerate(raw_exceptions):
        if not isinstance(raw_exc, dict):
            result.errors.append(f"exceptions[{idx}] is not an object")
            continue

        exc_id = str(raw_exc.get("id", "")).strip()
        emp_id = str(raw_exc.get("employee_id", "")).strip()

        if not exc_id or not emp_id:
            result.errors.append(f"exceptions[{idx}] requires 'id' and 'employee_id'")
            continue

        if emp_id not in known_employee_ids:
            result.errors.append(
                f"exceptions[{idx}] employee_id '{emp_id}' not found in database or dataset"
            )
            continue

        try:
            detected_at = (
                _parse_datetime(raw_exc.get("detected_at"))
                if raw_exc.get("detected_at")
                else datetime.now(UTC).replace(tzinfo=None)
            )
        except (ValueError, TypeError) as err:
            result.errors.append(f"exceptions[{idx}] invalid detected_at: {err}")
            continue

        existing_exc = session.get(ExceptionModel, exc_id)
        if existing_exc is not None:
            existing_exc.employee_id = emp_id
            existing_exc.type = str(raw_exc.get("type", existing_exc.type))
            existing_exc.date = str(raw_exc.get("date", existing_exc.date))
            existing_exc.severity = str(raw_exc.get("severity", existing_exc.severity))
            existing_exc.status = str(raw_exc.get("status", existing_exc.status))
            existing_exc.description = str(raw_exc.get("description", existing_exc.description))
            existing_exc.original_attendance = raw_exc.get(
                "original_attendance", existing_exc.original_attendance
            )
            existing_exc.policy_reference = str(
                raw_exc.get("policy_reference", existing_exc.policy_reference)
            )
            existing_exc.detected_at = detected_at
            result.skipped_count += 1
        else:
            new_exc = ExceptionModel(
                id=exc_id,
                employee_id=emp_id,
                type=str(raw_exc.get("type", "missed_punch")),
                date=str(raw_exc.get("date", detected_at.strftime("%Y-%m-%d"))),
                severity=str(raw_exc.get("severity", "medium")),
                status=str(raw_exc.get("status", "pending_review")),
                description=str(raw_exc.get("description", "")),
                original_attendance=raw_exc.get("original_attendance", {}),
                policy_reference=str(raw_exc.get("policy_reference", "")),
                detected_at=detected_at,
                proposal_id=raw_exc.get("proposal_id"),
            )
            session.add(new_exc)
            result.exceptions_loaded += 1

    # Final transactional commit
    session.commit()
    return result


def load_dataset_from_file(session: Session, file_path: str | Path) -> DatasetLoadResult:
    """Load JSON attendance dataset from specified file path."""
    path = Path(file_path)
    if not path.is_file():
        res = DatasetLoadResult()
        res.errors.append(f"Dataset file '{path}' does not exist.")
        return res

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as err:
        res = DatasetLoadResult()
        res.errors.append(f"Failed to read JSON from '{path}': {err}")
        return res

    return load_dataset_from_dict(session, data)
