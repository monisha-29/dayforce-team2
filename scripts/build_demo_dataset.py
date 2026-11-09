"""Turn a generated CSV dataset into the JSON format that scripts/load_dataset.py ingests.

The detectors run on the CSV punches and schedules, and every exception they find is written
with its original timecard (checkIn, checkOut, mealStart, mealEnd, totalHours), which is what
the API and the UI display.

    python scripts/build_demo_dataset.py                      # data/ -> data/demo_attendance.json
    python scripts/load_dataset.py --file data/demo_attendance.json
"""

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "eval"))

from app.rules import detect_all_exceptions
from app.services.timecard import build_timecard
from run_detectors import load


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(ROOT / "data"))
    ap.add_argument("--out", default=str(ROOT / "data" / "demo_attendance.json"))
    args = ap.parse_args()
    data = Path(args.data)

    punches, schedules = load(data)
    by_emp = {}
    for p in punches:
        by_emp.setdefault(p.employee_id, []).append(p)

    with (data / "employees.csv").open(newline="", encoding="utf-8") as f:
        employees = list(csv.DictReader(f))
    with (data / "schedules.csv").open(newline="", encoding="utf-8") as f:
        schedule_rows = list(csv.DictReader(f))
    with (data / "punches.csv").open(newline="", encoding="utf-8") as f:
        punch_rows = list(csv.DictReader(f))
    for r in punch_rows:
        r["notes"] = r["notes"] or None

    exceptions = []
    for e in detect_all_exceptions(punches, schedules):
        exceptions.append(
            {
                "id": e.exception_id,
                "employee_id": e.employee_id,
                "type": e.exception_type.value,
                "date": e.date,
                "severity": e.severity.value,
                "status": "pending_review",
                "description": e.description,
                "original_attendance": build_timecard(by_emp.get(e.employee_id, []), e.date),
                "policy_reference": e.policy_reference,
                "detected_at": f"{e.date}T17:00:00",
            }
        )

    out = {
        "employees": employees,
        "schedules": schedule_rows,
        "punches": punch_rows,
        "exceptions": sorted(exceptions, key=lambda x: (x["date"], x["employee_id"], x["type"])),
    }
    Path(args.out).write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"{len(employees)} employees, {len(punch_rows)} punches, {len(exceptions)} exceptions -> {args.out}")


if __name__ == "__main__":
    main()
