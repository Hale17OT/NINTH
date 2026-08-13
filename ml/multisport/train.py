"""Train a binary sport-market candidate from canonical point-in-time JSONL.

Input rows must contain:
  event_id, event_time, knowledge_time, label, features

`knowledge_time <= event_time` is enforced. The final 20% of events are never
used for fitting, model choice or calibration. Artifacts are always born in
shadow status; a later live ledger supplies the final promotion evidence.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import joblib
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.base import clone

from .evaluation import binary_metrics, historical_readiness, promotion_decision


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def load_rows(path: Path) -> list[dict]:
    rows = []
    for number, raw in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        if not raw.strip():
            continue
        row = json.loads(raw)
        event_time, knowledge_time = parse_time(row["event_time"]), parse_time(row["knowledge_time"])
        if knowledge_time > event_time:
            raise ValueError(f"Row {number} leaks future knowledge ({knowledge_time} > {event_time})")
        if int(row["label"]) not in (0, 1) or not isinstance(row.get("features"), dict):
            raise ValueError(f"Row {number} must have a binary label and feature object")
        row["_event_time"] = event_time
        rows.append(row)
    rows.sort(key=lambda row: (row["_event_time"], str(row.get("event_id") or "")))
    return rows


def matrix(rows: list[dict], names: list[str]) -> np.ndarray:
    return np.asarray([[row["features"].get(name, np.nan) for name in names] for row in rows], dtype=float)


def chronological_slices(samples: int) -> tuple[slice, slice, slice]:
    if samples < 100:
        raise ValueError("At least 100 chronological rows are required for a research candidate")
    train_end, validation_end = max(60, int(samples * .60)), max(80, int(samples * .80))
    return slice(0, train_end), slice(train_end, validation_end), slice(validation_end, samples)


def candidate_models() -> dict[str, object]:
    return {
        "regularized_logistic": Pipeline([
            ("imputer", SimpleImputer(strategy="median", add_indicator=True)),
            ("scale", StandardScaler()),
            ("model", LogisticRegression(C=.35, max_iter=3000, class_weight="balanced")),
        ]),
        "hist_gradient_boosting": Pipeline([
            ("imputer", SimpleImputer(strategy="median", add_indicator=True)),
            ("model", HistGradientBoostingClassifier(
                learning_rate=.04, max_iter=240, max_leaf_nodes=15,
                min_samples_leaf=30, l2_regularization=2.0, random_state=9,
            )),
        ]),
    }


def _quarter(value: datetime) -> tuple[int, int]:
    return value.year, (value.month - 1) // 3 + 1


def historical_walk_forward(rows: list[dict], names: list[str], years: int = 3) -> dict:
    """Replay the latest three years one quarter at a time.

    Every target-quarter forecast is produced by models and a calibrator fitted
    only on earlier events.  Older rows are warm-up history and are never
    scored as if they had been genuinely out of sample.
    """
    x, y = matrix(rows, names), np.asarray([int(row["label"]) for row in rows])
    last_time = rows[-1]["_event_time"]
    audit_start = last_time - timedelta(days=365 * years)
    groups: dict[tuple[int, int], list[int]] = {}
    for index, row in enumerate(rows):
        if row["_event_time"] >= audit_start:
            groups.setdefault(_quarter(row["_event_time"]), []).append(index)

    probabilities: list[float] = []
    baselines: list[float] = []
    labels: list[int] = []
    timestamps: list[datetime] = []
    folds = []
    for key in sorted(groups):
        target = np.asarray(groups[key], dtype=int)
        history = np.asarray([index for index, row in enumerate(rows) if row["_event_time"] < rows[target[0]]["_event_time"]], dtype=int)
        if len(history) < 300 or len(target) < 10:
            continue
        validation_size = min(500, max(80, int(len(history) * .15)))
        fit_index, validation_index = history[:-validation_size], history[-validation_size:]
        if len(fit_index) < 200 or len(np.unique(y[fit_index])) < 2 or len(np.unique(y[validation_index])) < 2:
            continue
        scores, fitted = {}, {}
        for name, candidate in candidate_models().items():
            model = clone(candidate).fit(x[fit_index], y[fit_index])
            score = binary_metrics(y[validation_index], model.predict_proba(x[validation_index])[:, 1])
            scores[name], fitted[name] = score, model
        selected_name = min(scores, key=lambda name: scores[name]["brier"])
        selected = fitted[selected_name]
        validation_probability = selected.predict_proba(x[validation_index])[:, 1]
        calibrator = IsotonicRegression(out_of_bounds="clip").fit(validation_probability, y[validation_index])
        target_probability = calibrator.predict(selected.predict_proba(x[target])[:, 1])
        prevalence = float(y[fit_index].mean())
        probabilities.extend(float(value) for value in target_probability)
        baselines.extend([prevalence] * len(target))
        labels.extend(int(value) for value in y[target])
        timestamps.extend(rows[index]["_event_time"] for index in target)
        folds.append({
            "period": f"{key[0]}-Q{key[1]}", "train": int(len(fit_index)),
            "validation": int(len(validation_index)), "test": int(len(target)),
            "selected": selected_name,
        })
    if not labels:
        return {"samples": 0, "folds": [], "candidate": {"samples": 0}, "baseline": {"samples": 0}}
    recent_cutoff = last_time - timedelta(days=365)
    recent = [index for index, value in enumerate(timestamps) if value >= recent_cutoff]
    return {
        "years": years, "start": min(timestamps).isoformat(), "end": max(timestamps).isoformat(),
        "samples": len(labels), "folds": folds,
        "candidate": binary_metrics(labels, probabilities),
        "baseline": binary_metrics(labels, baselines),
        "recent_candidate": binary_metrics([labels[index] for index in recent], [probabilities[index] for index in recent]),
        "recent_baseline": binary_metrics([labels[index] for index in recent], [baselines[index] for index in recent]),
    }


def train(rows: list[dict], sport: str, market: str, model_output: Path | None = None) -> dict:
    forbidden = ("odds", "price", "market_", "spread_line", "total_line")
    names = sorted({
        name for row in rows for name, value in row["features"].items()
        if (value is None or isinstance(value, (int, float, bool))) and not any(token in name.lower() for token in forbidden)
    })
    if not names:
        raise ValueError("No numeric features were found")
    x, y = matrix(rows, names), np.asarray([int(row["label"]) for row in rows])
    train_slice, validation_slice, test_slice = chronological_slices(len(rows))
    candidates = {}
    fitted = {}
    for name, model in candidate_models().items():
        model.fit(x[train_slice], y[train_slice])
        probability = model.predict_proba(x[validation_slice])[:, 1]
        candidates[name] = binary_metrics(y[validation_slice], probability)
        fitted[name] = model
    selected_name = min(candidates, key=lambda name: candidates[name]["brier"])
    selected = fitted[selected_name]
    validation_probability = selected.predict_proba(x[validation_slice])[:, 1]
    calibrator = IsotonicRegression(out_of_bounds="clip").fit(validation_probability, y[validation_slice])
    test_raw = selected.predict_proba(x[test_slice])[:, 1]
    test_probability = calibrator.predict(test_raw)
    prevalence = float(y[train_slice].mean())
    baseline_probability = np.full(len(y[test_slice]), prevalence)
    candidate_metrics = binary_metrics(y[test_slice], test_probability)
    baseline_metrics = binary_metrics(y[test_slice], baseline_probability)
    walk_forward = historical_walk_forward(rows, names)
    readiness = historical_readiness(
        walk_forward.get("candidate", {}), walk_forward.get("baseline", {}),
        walk_forward.get("recent_candidate", {}), walk_forward.get("recent_baseline", {}),
    ) if walk_forward.get("samples") else {"passed": False, "checks": {"historical_audit": False}}
    if model_output is not None:
        model_output.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump({
            "sport": sport, "market": market, "features": names,
            "model": selected, "calibrator": calibrator,
        }, model_output)
    return {
        "sport": sport, "market": market, "status": "shadow_only",
        "method": selected_name, "features": names,
        "samples": {"all": len(rows), "train": len(y[train_slice]), "validation": len(y[validation_slice]), "untouched_test": len(y[test_slice])},
        "time_range": {"first": rows[0]["event_time"], "training_through": rows[train_slice.stop - 1]["event_time"], "validation_through": rows[validation_slice.stop - 1]["event_time"], "test_through": rows[-1]["event_time"]},
        "validation_candidates": candidates, "untouched_candidate": candidate_metrics,
        "untouched_climatology": baseline_metrics,
        "historical_walk_forward": walk_forward,
        "historical_readiness": readiness,
        "promotion": promotion_decision(candidate_metrics, baseline_metrics, live=None),
        "calibration": {"type": "isotonic", "x": [float(v) for v in calibrator.X_thresholds_], "y": [float(v) for v in calibrator.y_thresholds_]},
        "odds_independent": True,
        "note": "Three-year walk-forward evidence can establish statistical readiness. A short immutable live shadow remains mandatory to verify the operational pipeline.",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("--sport", required=True)
    parser.add_argument("--market", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model-output", type=Path)
    args = parser.parse_args()
    raw = args.input.read_bytes()
    model_output = args.model_output or args.output.with_suffix(".joblib")
    report = train(load_rows(args.input), args.sport, args.market, model_output=model_output)
    report["model_artifact"] = str(model_output)
    report["dataset_sha256"] = hashlib.sha256(raw).hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("sport", "market", "status", "samples", "untouched_candidate", "promotion")}, indent=2))


if __name__ == "__main__":
    main()
