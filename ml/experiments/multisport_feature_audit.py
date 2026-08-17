"""Read-only chronological feature-group audit for NINTH research models.

This never writes into production artifact directories and never changes a
builder eligibility flag. It compares each full candidate with a climatology
baseline and leave-one-group-out variants on the same untouched final 20%.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from sklearn.base import clone
from sklearn.impute import SimpleImputer
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from ml.multisport.evaluation import binary_metrics
from ml.multisport.train import candidate_models, chronological_slices, load_rows, matrix

ROOT = Path(__file__).resolve().parents[2]
DATASETS = {
    "basketball": (ROOT / "ml/data/multisport/basketball/home_win.jsonl", "home win"),
    "american-football": (ROOT / "ml/data/multisport/american-football/home_win.jsonl", "home win"),
    "football": (ROOT / "ml/data/multisport/football/home_win.jsonl", "home win"),
}
TOKENS = {
    "rating": ("elo", "rating"),
    "recent_form": ("_5", "_10", "win_rate", "points_"),
    "advanced_efficiency": ("epa", "success", "explosive", "efg", "turnover", "rebound", "shot", "xg", "pressure", "progressive", "pace", "rim", "assist_rate"),
    "availability_context": ("rest", "temperature", "wind", "outdoors", "neutral", "divisional", "matches_seen", "games_seen"),
}


def feature_names(rows):
    forbidden = ("odds", "price", "market_", "spread_line", "total_line")
    return sorted({name for row in rows for name, value in row["features"].items()
        if (value is None or isinstance(value, (int, float, bool))) and not any(token in name.lower() for token in forbidden)})


def grouped(names):
    result = {group: [] for group in TOKENS}
    result["other"] = []
    for name in names:
        assigned = False
        for group, tokens in TOKENS.items():
            if any(token in name.lower() for token in tokens):
                result[group].append(name); assigned = True; break
        if not assigned:
            result["other"].append(name)
    return {key: value for key, value in result.items() if value}


def fit_score(rows, names, family=None):
    x, y = matrix(rows, names), np.asarray([int(row["label"]) for row in rows])
    train_slice, validation_slice, test_slice = chronological_slices(len(rows))
    models = candidate_models() if family is None else {family: candidate_models()[family]}
    validation, fitted = {}, {}
    for name, model in models.items():
        fitted[name] = clone(model).fit(x[train_slice], y[train_slice])
        validation[name] = binary_metrics(y[validation_slice], fitted[name].predict_proba(x[validation_slice])[:, 1])
    selected = min(validation, key=lambda name: validation[name]["brier"])
    model = fitted[selected]
    validation_probability = model.predict_proba(x[validation_slice])[:, 1]
    uncalibrated_probability = model.predict_proba(x[test_slice])[:, 1]
    calibrator = IsotonicRegression(out_of_bounds="clip").fit(validation_probability, y[validation_slice])
    probability = calibrator.predict(uncalibrated_probability)
    baseline = np.full(len(y[test_slice]), float(y[train_slice].mean()))
    return selected, validation, binary_metrics(y[test_slice], probability), binary_metrics(y[test_slice], uncalibrated_probability), binary_metrics(y[test_slice], baseline), (train_slice, validation_slice, test_slice)


def stability(rows, names, slices):
    x, y = matrix(rows, names), np.asarray([int(row["label"]) for row in rows])
    train_slice, _, test_slice = slices
    model = Pipeline([("imputer", SimpleImputer(strategy="median")), ("scale", StandardScaler()), ("model", LogisticRegression(C=.35, max_iter=3000, class_weight="balanced"))]).fit(x[train_slice], y[train_slice])
    coefficient = np.abs(model.named_steps["model"].coef_[0])
    train = model.named_steps["imputer"].transform(x[train_slice]); test = model.named_steps["imputer"].transform(x[test_slice])
    pooled = np.sqrt((np.nanvar(train, axis=0) + np.nanvar(test, axis=0)) / 2)
    drift = np.divide(np.abs(np.nanmean(test, axis=0) - np.nanmean(train, axis=0)), pooled, out=np.zeros_like(pooled), where=pooled > 1e-9)
    ranked = np.argsort(-coefficient)[:12]
    return [{"feature": names[index], "importance": round(float(coefficient[index]), 5), "standardized_train_test_drift": round(float(drift[index]), 4)} for index in ranked]


def audit(sport, path, target):
    rows = load_rows(path); names = feature_names(rows); groups = grouped(names)
    selected, validation, full, uncalibrated, baseline, slices = fit_score(rows, names)
    ablations = {}
    for group, members in groups.items():
        remaining = [name for name in names if name not in set(members)]
        if len(remaining) < 2:
            continue
        _, _, score, _, _, _ = fit_score(rows, remaining, selected)
        ablations[group] = {"removed_features": len(members), "metrics": score, "brier_delta_vs_full": round(score["brier"] - full["brier"], 6), "log_loss_delta_vs_full": round(score["log_loss"] - full["log_loss"], 6)}
    return {
        "sport": sport, "target": target, "source": str(path.relative_to(ROOT)), "knowledge_time_enforced": True,
        "samples": len(rows), "features": len(names), "feature_groups": {key: len(value) for key, value in groups.items()},
        "time_range": {"first": rows[0]["event_time"], "last": rows[-1]["event_time"]},
        "split": {"train": slices[0].stop, "validation": slices[1].stop - slices[1].start, "untouched_test": slices[2].stop - slices[2].start},
        "selected_family": selected, "validation_candidates": validation,
        "untouched_full": full, "untouched_uncalibrated": uncalibrated, "untouched_climatology": baseline,
        "calibration_delta": {
            "brier": round(full["brier"] - uncalibrated["brier"], 6),
            "log_loss": round(full["log_loss"] - uncalibrated["log_loss"], 6),
            "expected_calibration_error": round(full["expected_calibration_error"] - uncalibrated["expected_calibration_error"], 6),
        },
        "ablations": ablations, "feature_stability": stability(rows, names, slices),
        "research_decision": "retain_full" if all(row["brier_delta_vs_full"] >= 0 for row in ablations.values()) else "candidate_pruning_requires_new_locked_audit",
    }


def main():
    parser = argparse.ArgumentParser(); parser.add_argument("--output", type=Path, default=ROOT / "ml/artifacts/experiments/multisport_feature_audit_20260814.json")
    args = parser.parse_args()
    report = {"status": "research_only_no_production_change", "generated_at": datetime.now(timezone.utc).isoformat(), "policy": "Chronological 60/20/20 selection and calibration; final 20% untouched; odds and market lines excluded as features.", "experiments": []}
    for sport, (path, target) in DATASETS.items():
        print(f"auditing {sport}", flush=True); report["experiments"].append(audit(sport, path, target))
    mlb_report = ROOT / "ml/artifacts/accuracy_experiments.json"
    if mlb_report.exists():
        payload = json.loads(mlb_report.read_text(encoding="utf-8")); results = payload.get("results", {})
        report["mlb_reference"] = {"source": str(mlb_report.relative_to(ROOT)), "status": payload.get("status"), "policy": payload.get("policy"), "base_features": payload.get("base_features"), "statcast_features": payload.get("statcast_features"), "structural_features": payload.get("structural_features"), "results": results}
    args.output.parent.mkdir(parents=True, exist_ok=True); args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(args.output), "sports": [row["sport"] for row in report["experiments"]]}, indent=2))


if __name__ == "__main__": main()
