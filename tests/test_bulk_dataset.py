"""Checks for the bulk evaluation dataset (data/bulk)."""
import csv
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BULK = ROOT / "data" / "bulk"


def _rows(name):
    with (BULK / name).open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def test_bulk_generator_is_deterministic():
    script = str(ROOT / "scripts" / "generate_bulk_dataset.py")
    subprocess.run([sys.executable, script], check=True)
    first = (BULK / "ground_truth.csv").read_text(encoding="utf-8")
    subprocess.run([sys.executable, script], check=True)
    assert first == (BULK / "ground_truth.csv").read_text(encoding="utf-8")


def test_bulk_dataset_size_and_mix():
    assert len(_rows("employees.csv")) == 50
    truth = _rows("ground_truth.csv")
    assert 140 <= len(truth) <= 160
    counts = Counter(r["exception_type"] for r in truth)
    assert set(counts) == {"missed_punch", "overtime", "schedule_conflict", "meal_break"}
    assert all(n >= 30 for n in counts.values())


def test_at_most_one_label_per_employee_day():
    keys = [(r["employee_id"], r["date"]) for r in _rows("ground_truth.csv")]
    assert len(keys) == len(set(keys))


def test_labels_refer_to_real_employees():
    emp = {r["id"] for r in _rows("employees.csv")}
    assert all(r["employee_id"] in emp for r in _rows("ground_truth.csv"))
