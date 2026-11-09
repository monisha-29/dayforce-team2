"""Create deterministic synthetic Dayforce evaluation data."""
from __future__ import annotations
import csv
import random
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data"
SEED = 20261108

employees = []
schedules = []
punches = []
truth = []
scenarios = []

def add_case(kind, day, punch_specs, schedule_spec=True, severity=None, policy=None,
             exception_type=None, description="", employee_num=None):
    idx = employee_num if employee_num is not None else len(scenarios) + 1
    emp = f"EMP{idx:04d}"
    sid = f"SCH{idx:04d}"
    base = datetime.fromisoformat(day)
    employees.append({"id": emp, "name": f"Synthetic Employee {idx:04d}",
                      "department": "Operations", "shift": "Day",
                      "shift_start": "09:00", "shift_end": "17:00"})
    if schedule_spec:
        start, end = schedule_spec if isinstance(schedule_spec, tuple) else (
            base.replace(hour=9), base.replace(hour=17))
        schedules.append({"id": sid, "employee_id": emp, "date": day,
                          "start_time": start.isoformat(), "end_time": end.isoformat(),
                          "department_id": "OPS", "scheduled_break_minutes": 30})
    for j, (offset, ptype, note) in enumerate(punch_specs, 1):
        punches.append({"id": f"P{idx:04d}_{j:02d}", "employee_id": emp,
                        "timestamp": (base + offset).isoformat(sep=" "),
                        "punch_type": ptype, "source": "synthetic", "notes": note})
    if exception_type:
        truth.append({"scenario_id": f"SCN{idx:04d}", "employee_id": emp, "date": day,
                      "exception_type": exception_type, "severity": severity or "medium",
                      "policy_reference": policy or "", "expected": "exception",
                      "description": description})
    else:
        truth.append({"scenario_id": f"SCN{idx:04d}", "employee_id": emp, "date": day,
                      "exception_type": "none", "severity": "none",
                      "policy_reference": "", "expected": "no_exception",
                      "description": description or "Clean attendance"})
    scenarios.append({"scenario_id": f"SCN{idx:04d}", "kind": kind, "employee_id": emp, "date": day})

def t(h, m=0):
    return timedelta(hours=h, minutes=m)

def build():
    # Clean baseline cases
    for i in range(10):
        day = (datetime(2026, 11, 2) + timedelta(days=i)).date().isoformat()
        add_case("normal", day, [(t(9), "IN", ""), (t(12), "BREAK_START", ""),
            (t(12,30), "BREAK_END", ""), (t(17), "OUT", "")],
            description="Scheduled 8-hour shift with a 30-minute break")

    cases = [
      ("missing_out", [(t(9),"IN","No clock-out")], True, "high","PUNCH-01","missed_punch","Missing clock-out"),
      ("missing_in", [(t(17),"OUT","No clock-in")], True, "high","PUNCH-02","missed_punch","Missing clock-in"),
      ("consecutive_in", [(t(9),"IN",""),(t(12),"IN","Second IN")], True, "high","PUNCH-01","missed_punch","Consecutive IN punches"),
      ("no_attendance", [], True, "high","PUNCH-02","missed_punch","Scheduled shift without punches"),
      ("daily_exact_8", [(t(9),"IN",""),(t(17),"OUT","")], True, None,None,None,"Exactly eight hours; no daily overtime"),
      ("daily_8_01", [(t(9),"IN",""),(t(17,1),"OUT","")], True, "medium","OT-01","overtime","8.02 hours after two-decimal rounding"),
      ("daily_10_5", [(t(8),"IN",""),(t(18,30),"OUT","")], True, "high","OT-01","overtime","2.5 daily overtime hours"),
      ("late_5", [(t(9,5),"IN",""),(t(17),"OUT","")], True, None,None,None,"Exactly five-minute grace boundary"),
      ("late_6", [(t(9,6),"IN",""),(t(17),"OUT","")], True, "medium","SCHED-01","schedule_conflict","Clock-in six minutes late"),
      ("early_6", [(t(9),"IN",""),(t(16,54),"OUT","")], True, "medium","SCHED-01","schedule_conflict","Clock-out six minutes early"),
      ("unscheduled", [(t(9),"IN",""),(t(17),"OUT","")], False, "medium","SCHED-02","schedule_conflict","Punches without assigned schedule"),
      ("meal_missing", [(t(9),"IN",""),(t(15),"OUT","")], True, "high","MEAL-01","meal_break","Six-hour shift without explicit meal break"),
      ("meal_short", [(t(9),"IN",""),(t(12),"BREAK_START",""),(t(12,20),"BREAK_END",""),(t(17),"OUT","")], True, "medium","MEAL-02","meal_break","Twenty-minute recorded break"),
      ("meal_valid", [(t(9),"IN",""),(t(12),"BREAK_START",""),(t(12,30),"BREAK_END",""),(t(17),"OUT","")], True, None,None,None,"Thirty-minute recorded break"),
      ("overnight", [(t(22),"IN",""),(t(30),"OUT","")], True, None,None,None,"Eight-hour overnight shift"),
    ]
    for i, (kind, ps, sched, sev, pol, typ, desc) in enumerate(cases):
        day = (datetime(2026, 11, 16) + timedelta(days=i)).date().isoformat()
        # overnight schedule uses same initial workday date and next-day end
        sch = (datetime.fromisoformat(day+"T22:00:00"), datetime.fromisoformat(day+"T06:00:00")+timedelta(days=1)) if kind=="overnight" else True
        add_case(kind, day, ps, sch if sched else False, sev, pol, typ, desc)

    # Split shifts and explicit schedule variants (normal cases)
    for i in range(5):
        day = (datetime(2026, 12, 5) + timedelta(days=i)).date().isoformat()
        add_case("split_shift", day, [(t(8),"IN",""),(t(12),"OUT",""),
             (t(13),"IN",""),(t(17),"OUT","")], True,
             description="Two completed work intervals on one workday")

    # Separate weekly overtime cases: expected labels are for the weekly calculator path.
    # Four 8-hour regular days plus a fifth 8.25-hour day => 40.25 regular hours.
    for i, hours in enumerate([40.0, 40.25]):
        day = (datetime(2027, 1, 4+i*7)).date().isoformat()
        add_case("weekly_overtime", day, [(t(9),"IN",""),(t(17, int((hours-40)*60)),"OUT","")],
                 True, "high" if hours > 40 else None, "OT-02" if hours > 40 else None,
                 "overtime" if hours > 40 else None,
                 f"Weekly calculator fixture; cumulative regular hours target {hours:.2f}. "
                 "This single-day row is a fixture marker; build the full 5/6-day week for execution.")

    # Deterministic scenario metadata and split 70/30 by scenario order.
    return

def write_csv(path, rows, fields):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)

def main():
    build()
    # Split by employee scenario; keep all rows for a scenario together.
    test_ids = {s["employee_id"] for i,s in enumerate(scenarios) if i % 5 == 0}
    for folder, ids in [(OUT, {s["employee_id"] for s in scenarios}-test_ids),
                        (OUT/"test", test_ids)]:
        emp_rows = [r for r in employees if r["id"] in ids]
        sch_rows = [r for r in schedules if r["employee_id"] in ids]
        punch_rows = [r for r in punches if r["employee_id"] in ids]
        truth_rows = [r for r in truth if r["employee_id"] in ids]
        write_csv(folder/"employees.csv", emp_rows, ["id","name","department","shift","shift_start","shift_end"])
        write_csv(folder/"schedules.csv", sch_rows, ["id","employee_id","date","start_time","end_time","department_id","scheduled_break_minutes"])
        write_csv(folder/"punches.csv", punch_rows, ["id","employee_id","timestamp","punch_type","source","notes"])
        write_csv(folder/"ground_truth.csv", truth_rows, ["scenario_id","employee_id","date","exception_type","severity","policy_reference","expected","description"])
    write_csv(OUT/"scenario_manifest.csv", scenarios, ["scenario_id","kind","employee_id","date"])
    print(f"Generated {len(scenarios)} scenarios: {len(scenarios)-len(test_ids)} development, {len(test_ids)} test.")

if __name__ == "__main__":
    main()
