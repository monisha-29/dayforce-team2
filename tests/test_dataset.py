import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
def test_generator_outputs():
    import subprocess, sys
    subprocess.run([sys.executable, str(ROOT/"scripts"/"generate_dataset.py")], check=True)
    for name in ["employees.csv","schedules.csv","punches.csv","ground_truth.csv"]:
        assert (ROOT/"data"/name).exists()
        assert (ROOT/"data"/"test"/name).exists()
def test_ground_truth_has_expected_labels():
    rows=list(csv.DictReader((ROOT/"data"/"ground_truth.csv").open(encoding="utf-8")))
    assert rows
    assert {"no_exception","exception"} <= {r["expected"] for r in rows}
    assert {"missed_punch","overtime","schedule_conflict","meal_break"} <= {
        r["exception_type"] for r in rows if r["expected"]=="exception"
    }
