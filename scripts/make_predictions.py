"""Run Person 3's detectors on the CSV dataset and write predictions.json.

Usage (from the project root, venv active):
    python scripts\\make_predictions.py
    python scripts\\make_predictions.py --data data --out predictions.json
    python eval\\evaluate.py --truth data\\ground_truth.csv --predictions predictions.json
"""
import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.rules.detectors import detect_all_exceptions
from app.rules.models.exception import Punch, Schedule


def read_csv(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(ROOT / "data"), help="folder with punches.csv and schedules.csv")
    ap.add_argument("--out", default="predictions.json")
    args = ap.parse_args()
    data = Path(args.data)

    punches = [
        Punch(
            id=r["id"] or None,
            employee_id=r["employee_id"],
            timestamp=r["timestamp"],
            punch_type=r["punch_type"],
            source=r.get("source") or "synthetic",
            notes=r.get("notes") or None,
        )
        for r in read_csv(data / "punches.csv")
    ]
    schedules = [
        Schedule(
            id=r["id"] or None,
            employee_id=r["employee_id"],
            date=r["date"],
            start_time=r["start_time"],
            end_time=r["end_time"],
            department_id=r.get("department_id") or None,
            scheduled_break_minutes=int(r.get("scheduled_break_minutes") or 30),
        )
        for r in read_csv(data / "schedules.csv")
    ]

    found = detect_all_exceptions(punches, schedules)
    preds = [
        {
            "employee_id": e.employee_id,
            "date": str(e.date),
            "exception_type": getattr(e.exception_type, "value", e.exception_type),
        }
        for e in found
    ]
    Path(args.out).write_text(json.dumps(preds, indent=2), encoding="utf-8")
    print(f"{len(punches)} punches, {len(schedules)} schedules -> {len(preds)} exceptions -> {args.out}")


if __name__ == "__main__":
    main()
