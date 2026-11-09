"""Evaluate detector predictions against ground-truth CSV labels."""

import argparse
import csv
import json

KEY = ("employee_id", "date", "exception_type")


def load_truth(path):
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return {tuple(r[k] for k in KEY) for r in rows if r["expected"] == "exception"}


def load_predictions(path):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return {tuple(str(r[k]) for k in KEY) for r in data}


def scores(truth, pred):
    tp = len(truth & pred)
    fp = len(pred - truth)
    fn = len(truth - pred)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--truth", required=True)
    ap.add_argument("--predictions", required=True)
    args = ap.parse_args()
    truth = load_truth(args.truth)
    pred = load_predictions(args.predictions)
    print("OVERALL", json.dumps(scores(truth, pred), indent=2))
    for typ in sorted({x[2] for x in truth | pred}):
        print(
            typ.upper(),
            json.dumps(
                scores(
                    {x for x in truth if x[2] == typ}, {x for x in pred if x[2] == typ}
                )
            ),
        )


if __name__ == "__main__":
    main()
