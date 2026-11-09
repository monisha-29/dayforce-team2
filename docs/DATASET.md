# Evaluation datasets

Two synthetic datasets, both generated deterministically. No real employee data.

| Folder | Generator | Size | Purpose |
|---|---|---|---|
| `data/` | `scripts/generate_dataset.py` | 32 hand-made scenarios | Boundary cases (5-minute grace, 8.01 h, midnight shift, split shift) |
| `data/bulk/` | `scripts/generate_bulk_dataset.py` | 50 employees x 20 working days (2 pay periods), 150 planted exceptions | Main evaluation set |

## Bulk dataset rules

* Every clean day has a 30-minute meal break, so it is clean under MEAL-01 / MEAL-02.
* Each planted exception changes one thing and carries one label.
* At most one planted exception per employee per week, so weekly totals never trip OT-02 by accident.
* 5 night-shift employees (shifts crossing midnight) have clean days, to test overnight handling.
* `ground_truth.csv` lists planted exceptions only. Any employee-day not listed is clean.

| Type | Count | Variants |
|---|---|---|
| missed_punch | 40 | missing OUT, missing IN, consecutive IN, no attendance (10 each) |
| overtime | 35 | 8.25 to 9.75 net hours |
| schedule_conflict | 40 | late in (14), early out (13), unscheduled (13) |
| meal_break | 35 | no break (18), break under 30 minutes (17) |

## Scoring the detectors

```
python scripts/make_predictions.py --data data/bulk --out predictions.json
python eval/evaluate.py --truth data/bulk/ground_truth.csv --predictions predictions.json
```

## Note on the small dataset (`data/`)

Several non-meal cases in `data/` (for example daily_exact_8, late_5, early_6) have no break
punches. Under MEAL-01 (a shift over 5 h needs a 30-minute break) the detectors flag them for
meal_break, which shows up as false positives against the labels. Use `data/bulk/` for headline
numbers.

## Detector results on `data/bulk/` (rules code at the time of writing)

* 150 of 150 planted exceptions found (recall 1.0), 1 extra flag (precision 0.993).
* The extra flag is a missing-clock-in day whose first punch is an 11:00 break start, which is
  also flagged for meal_break (EMP2028, 2026-11-24). Ambiguous; left for Person 3 to decide.
* All 10 "consecutive IN" days produce two missed_punch exceptions (two "missing clock-out"
  messages for one issue). Scoring counts them once, but the manager queue would show duplicates.
