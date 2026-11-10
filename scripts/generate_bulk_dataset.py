"""Generate the full evaluation dataset: ~50 employees x 2 pay periods, ~150 planted exceptions.

Output goes to data/bulk/ so the small hand-made boundary dataset in data/ is left alone.

    python scripts/generate_bulk_dataset.py
    python scripts/generate_bulk_dataset.py --seed 7

Design rules (so labels stay trustworthy):
  * Every clean day has a 30-minute meal break, so it is clean under MEAL-01 / MEAL-02.
  * Each planted exception changes ONE thing, so it should trigger exactly one exception type.
  * At most one planted exception per employee per week, so weekly totals never reach OT-02 by accident.
  * Night-shift employees (shifts crossing midnight) are clean, to test overnight handling.

Files written: employees.csv, schedules.csv, punches.csv, ground_truth.csv (planted exceptions
only; any employee-day not listed is clean) and scenario_manifest.csv (every employee-day).
"""
from __future__ import annotations

import argparse
import csv
import random
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "bulk"

N_EMPLOYEES = 50
N_NIGHT = 5
PERIOD_STARTS = [date(2026, 11, 2), date(2026, 11, 16)]  # two pay periods, Mon-Fri x 2 weeks each
DEPARTMENTS = [("Operations", "OPS"), ("Support", "SUP"), ("Warehouse", "WH"), ("Retail", "RET")]

# How many of each planted exception (sum = 150)
PLAN = {
    "missed_punch": {"missing_out": 10, "missing_in": 10, "consecutive_in": 10, "no_attendance": 10},
    "overtime": {"overtime": 35},
    "schedule_conflict": {"late_in": 14, "early_out": 13, "unscheduled": 13},
    "meal_break": {"meal_missing": 18, "meal_short": 17},
}
POLICY = {
    "missing_out": "PUNCH-01", "missing_in": "PUNCH-02", "consecutive_in": "PUNCH-01",
    "no_attendance": "PUNCH-02", "overtime": "OT-01", "late_in": "SCHED-01",
    "early_out": "SCHED-01", "unscheduled": "SCHED-02", "meal_missing": "MEAL-01",
    "meal_short": "MEAL-02",
}
SEVERITY = {
    "missed_punch": "high", "overtime": "medium", "schedule_conflict": "medium", "meal_break": "medium",
}

FIELDS = {
    "employees": ["id", "name", "department", "shift", "shift_start", "shift_end"],
    "schedules": ["id", "employee_id", "date", "start_time", "end_time", "department_id", "scheduled_break_minutes"],
    "punches": ["id", "employee_id", "timestamp", "punch_type", "source", "notes"],
    "truth": ["scenario_id", "employee_id", "date", "exception_type", "severity", "policy_reference",
              "expected", "description"],
    "manifest": ["scenario_id", "kind", "employee_id", "date"],
}


def weekdays() -> list[date]:
    days = []
    for start in PERIOD_STARTS:
        for w in range(2):
            for d in range(5):
                days.append(start + timedelta(days=7 * w + d))
    return days


def week_of(d: date) -> date:
    return d - timedelta(days=d.weekday())


def at(day: date, h: int, m: int = 0) -> datetime:
    return datetime(day.year, day.month, day.day) + timedelta(hours=h, minutes=m)


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=20261109)
    args = ap.parse_args()
    rnd = random.Random(args.seed)

    days = weekdays()
    employees, schedules, punches, truth, manifest = [], [], [], [], []

    # ---- employees ---------------------------------------------------------------------
    night_ids = set()
    for i in range(N_EMPLOYEES):
        emp = f"EMP{2001 + i:04d}"
        dept, _ = DEPARTMENTS[i % len(DEPARTMENTS)]
        night = i >= N_EMPLOYEES - N_NIGHT
        if night:
            night_ids.add(emp)
        employees.append({
            "id": emp, "name": f"Synthetic Employee {2001 + i:04d}", "department": dept,
            "shift": "Night" if night else "Day",
            "shift_start": "22:00" if night else "09:00", "shift_end": "06:00" if night else "17:00",
        })
    emp_dept = {e["id"]: DEPARTMENTS[i % len(DEPARTMENTS)][1] for i, e in enumerate(employees)}
    day_emps = [e["id"] for e in employees if e["id"] not in night_ids]

    # ---- choose where each planted exception goes (one per employee per week) ---------
    slots = [(emp, wk) for emp in day_emps for wk in sorted({week_of(d) for d in days})]
    rnd.shuffle(slots)
    planted: dict[tuple[str, date], tuple[str, str]] = {}  # (emp, day) -> (type, subtype)
    queue = [(etype, sub) for etype, subs in PLAN.items() for sub, n in subs.items() for _ in range(n)]
    rnd.shuffle(queue)
    for (etype, sub), (emp, wk) in zip(queue, slots):
        day = rnd.choice([d for d in days if week_of(d) == wk])
        planted[(emp, day)] = (etype, sub)

    # ---- build every employee-day --------------------------------------------------------
    counter = 0
    punch_n = 0

    def add_punch(emp: str, ts: datetime, ptype: str, note: str = "") -> None:
        nonlocal punch_n
        punch_n += 1
        punches.append({"id": f"BP{punch_n:05d}", "employee_id": emp, "timestamp": ts.isoformat(sep=" "),
                        "punch_type": ptype, "source": "synthetic", "notes": note})

    def add_schedule(emp: str, day: date, start: datetime, end: datetime) -> None:
        schedules.append({"id": f"BS{len(schedules) + 1:05d}", "employee_id": emp, "date": day.isoformat(),
                          "start_time": start.isoformat(), "end_time": end.isoformat(),
                          "department_id": emp_dept[emp], "scheduled_break_minutes": 30})

    for emp in [e["id"] for e in employees]:
        for day in days:
            counter += 1
            sid = f"BSCN{counter:05d}"
            ds = day.isoformat()
            night = emp in night_ids

            if night:
                start, end = at(day, 22), at(day, 22) + timedelta(hours=8)
                add_schedule(emp, day, start, end)
                add_punch(emp, start, "IN")
                add_punch(emp, at(day, 25, 0), "BREAK_START")
                add_punch(emp, at(day, 25, 30), "BREAK_END")
                add_punch(emp, end, "OUT")
                manifest.append({"scenario_id": sid, "kind": "night_clean", "employee_id": emp, "date": ds})
                continue

            etype, sub = planted.get((emp, day), (None, None))
            sched_start, sched_end = at(day, 9), at(day, 17)
            has_schedule = True
            seq: list[tuple[datetime, str, str]] = []  # (timestamp, punch_type, note)
            desc = "Clean day: 8-hour shift with a 30-minute meal break"
            kind = "clean"

            b_start = rnd.choice([11, 12, 12, 12, 13])  # meal break starts at 11:00-13:00
            normal = [
                (at(day, 9, rnd.choice([0, 0, 1, 2, 3])), "IN", ""),
                (at(day, b_start), "BREAK_START", ""),
                (at(day, b_start, 30), "BREAK_END", ""),
                (at(day, 17, rnd.choice([0, 0, 1, 2])), "OUT", ""),
            ]

            if sub is None:
                seq = normal
                # a few tricky-but-clean boundary days
                if rnd.random() < 0.04:
                    seq[0] = (at(day, 9, 5), "IN", "Exactly at the 5-minute grace boundary")
                    desc, kind = "Clean boundary: clock-in exactly 5 minutes late", "boundary_clean"
            elif sub == "missing_out":
                seq = normal[:3]
                seq[0] = (seq[0][0], "IN", "No clock-out")
                desc, kind = "Missing clock-out", sub
            elif sub == "missing_in":
                seq = [normal[1], normal[2], normal[3]]
                seq[2] = (seq[2][0], "OUT", "No clock-in")
                desc, kind = "Missing clock-in", sub
            elif sub == "consecutive_in":
                seq = [(at(day, 9), "IN", ""), (at(day, 12), "IN", "Second IN")]
                desc, kind = "Consecutive IN punches", sub
            elif sub == "no_attendance":
                seq = []
                desc, kind = "Scheduled shift without punches", sub
            elif sub == "overtime":
                # leave 17:45 .. 19:15 so the weekly total never exceeds 40 hours (OT-02)
                out = at(day, 17, 0) + timedelta(minutes=rnd.choice([45, 60, 75, 90, 105, 120, 135]))
                sched_end = out
                seq = [normal[0], normal[1], normal[2], (out, "OUT", "")]
                net = (out - at(day, 9)).total_seconds() / 3600 - 0.5
                desc, kind = f"Daily overtime: {net:.2f} net hours", sub
            elif sub == "late_in":
                late = rnd.choice([6, 7, 10, 15, 20, 30, 45])
                seq = [(at(day, 9, late), "IN", ""), normal[1], normal[2], (at(day, 17), "OUT", "")]
                desc, kind = f"Clock-in {late} minutes late", sub
            elif sub == "early_out":
                early = rnd.choice([6, 7, 10, 15, 20, 30, 45])
                seq = [(at(day, 9), "IN", ""), normal[1], normal[2], (at(day, 17) - timedelta(minutes=early), "OUT", "")]
                desc, kind = f"Clock-out {early} minutes early", sub
            elif sub == "unscheduled":
                has_schedule = False
                seq = normal
                desc, kind = "Punches without an assigned schedule", sub
            elif sub == "meal_missing":
                seq = [(at(day, 9), "IN", ""), (at(day, 17), "OUT", "")]
                desc, kind = "8-hour shift without a meal break", sub
            elif sub == "meal_short":
                short = rnd.choice([10, 15, 20, 25])
                seq = [normal[0], (at(day, 12), "BREAK_START", ""), (at(day, 12, short), "BREAK_END", ""),
                       (at(day, 17), "OUT", "")]
                desc, kind = f"Meal break only {short} minutes", sub

            if has_schedule:
                add_schedule(emp, day, sched_start, sched_end)
            for ts, ptype, note in seq:
                add_punch(emp, ts, ptype, note)

            if etype:
                truth.append({"scenario_id": sid, "employee_id": emp, "date": ds, "exception_type": etype,
                              "severity": SEVERITY[etype], "policy_reference": POLICY[sub],
                              "expected": "exception", "description": desc})
            manifest.append({"scenario_id": sid, "kind": kind, "employee_id": emp, "date": ds})

    write_csv(OUT / "employees.csv", employees, FIELDS["employees"])
    write_csv(OUT / "schedules.csv", schedules, FIELDS["schedules"])
    write_csv(OUT / "punches.csv", punches, FIELDS["punches"])
    write_csv(OUT / "ground_truth.csv", truth, FIELDS["truth"])
    write_csv(OUT / "scenario_manifest.csv", manifest, FIELDS["manifest"])

    by_type: dict[str, int] = {}
    for r in truth:
        by_type[r["exception_type"]] = by_type.get(r["exception_type"], 0) + 1
    print(f"{len(employees)} employees, {len(days)} days each, {len(manifest)} employee-days")
    print(f"{len(truth)} planted exceptions: {by_type}")
    print(f"Written to {OUT}")


if __name__ == "__main__":
    main()
