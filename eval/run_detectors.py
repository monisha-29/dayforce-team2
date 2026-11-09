"""Run the rule-based detectors on a dataset folder and write predictions for evaluate.py.

    python eval/run_detectors.py --data data --out predictions.json
    python eval/evaluate.py --truth data/ground_truth.csv --predictions predictions.json
"""

import argparse
import csv
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.rules import Punch, Schedule, detect_all_exceptions


def load(data_dir: Path) -> tuple[list[Punch], list[Schedule]]:
    with (data_dir / "punches.csv").open(newline="", encoding="utf-8") as f:
        punches = [
            Punch(
                id=r["id"],
                employee_id=r["employee_id"],
                timestamp=datetime.fromisoformat(r["timestamp"]),
                punch_type=r["punch_type"],
                source=r["source"],
                notes=r["notes"] or None,
            )
            for r in csv.DictReader(f)
        ]
    with (data_dir / "schedules.csv").open(newline="", encoding="utf-8") as f:
        schedules = [
            Schedule(
                id=r["id"],
                employee_id=r["employee_id"],
                date=r["date"],
                start_time=datetime.fromisoformat(r["start_time"]),
                end_time=datetime.fromisoformat(r["end_time"]),
            )
            for r in csv.DictReader(f)
        ]
    return punches, schedules


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(ROOT / "data"))
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    punches, schedules = load(Path(args.data))
    found = detect_all_exceptions(punches, schedules)
    rows = [
        {
            "employee_id": e.employee_id,
            "date": e.date,
            "exception_type": getattr(e.exception_type, "value", str(e.exception_type)),
            "policy_reference": e.policy_reference,
            "description": e.description,
        }
        for e in found
    ]
    Path(args.out).write_text(json.dumps(rows, indent=2), encoding="utf-8")
    print(f"{len(rows)} predicted exceptions written to {args.out}")


if __name__ == "__main__":
    main()
