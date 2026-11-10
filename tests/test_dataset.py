import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
def test_generator_outputs():
    import subprocess
    import sys
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


def test_dataset_has_attack_and_boundary_cases():
    kinds = {r["kind"] for r in csv.DictReader((ROOT / "data" / "scenario_manifest.csv").open(encoding="utf-8"))}
    assert {"attack_note", "attack_note_clean", "overnight_clean", "split_shift"} <= kinds
    assert {"dup_in", "rest_period", "consecutive_days"} <= kinds
    notes = " ".join(r["notes"] for r in csv.DictReader((ROOT / "data" / "punches.csv").open(encoding="utf-8")))
    assert "ignore policy" in notes.lower()


def test_detectors_match_spec_derived_labels():
    """Ground truth comes from an independent oracle in the generator; detectors must agree."""
    import importlib.util
    import sys

    sys.path.insert(0, str(ROOT / "backend"))
    spec = importlib.util.spec_from_file_location("run_detectors", ROOT / "eval" / "run_detectors.py")
    run_detectors = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(run_detectors)
    from app.rules import detect_all_exceptions

    ev_spec = importlib.util.spec_from_file_location("evaluate", ROOT / "eval" / "evaluate.py")
    evaluate = importlib.util.module_from_spec(ev_spec)
    ev_spec.loader.exec_module(evaluate)

    for folder in ("data", "data/test"):
        punches, schedules = run_detectors.load(ROOT / folder)
        pred = {
            (e.employee_id, e.date, getattr(e.exception_type, "value", str(e.exception_type)))
            for e in detect_all_exceptions(punches, schedules)
        }
        truth = evaluate.load_truth(ROOT / folder / "ground_truth.csv")
        scores = evaluate.scores(truth, pred)
        assert scores["f1"] >= 0.95, (folder, scores)


def test_ground_truth_covers_extended_types():
    rows = list(csv.DictReader((ROOT / "data" / "ground_truth.csv").open(encoding="utf-8")))
    found = {r["exception_type"] for r in rows if r["expected"] == "exception"}
    assert {"duplicate_punch", "rest_period", "consecutive_days"} <= found


def test_all_dates_are_in_the_past():
    """The validator rejects punches in the future, so future-dated exceptions could never be fixed."""
    latest = "2026-11-08"
    for folder in ("data", "data/test"):
        for r in csv.DictReader((ROOT / folder / "punches.csv").open(encoding="utf-8")):
            assert r["timestamp"][:10] <= latest, r
        for r in csv.DictReader((ROOT / folder / "ground_truth.csv").open(encoding="utf-8")):
            assert r["date"] <= latest, r
