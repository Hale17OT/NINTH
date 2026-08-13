"""Train NFL score-distribution models with chronological, line-aware audits.

The regressors forecast total points and home margin without sportsbook inputs.
Archived pregame lines are used only after prediction to audit moneyline, spread,
and total probabilities.  Residual distributions come from a disjoint validation
period, so current lines can be evaluated without retraining a classifier for
every half point.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import joblib
import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from .train import chronological_slices, matrix, parse_time


def load_rows(path: Path) -> list[dict]:
    rows = []
    for number, raw in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        if not raw.strip():
            continue
        row = json.loads(raw)
        event_time = parse_time(row["event_time"])
        if parse_time(row["knowledge_time"]) > event_time:
            raise ValueError(f"Row {number} leaks future knowledge")
        if not isinstance(row.get("features"), dict):
            raise ValueError(f"Row {number} has no feature object")
        for target in ("total_points", "home_margin"):
            if not isinstance(row.get(target), (int, float)):
                raise ValueError(f"Row {number} has no numeric {target}")
        row["_event_time"] = event_time
        rows.append(row)
    rows.sort(key=lambda row: (row["_event_time"], str(row.get("event_id") or "")))
    return rows


def candidates() -> dict[str, object]:
    return {
        "ridge": Pipeline([
            ("imputer", SimpleImputer(strategy="median", add_indicator=True)),
            ("scale", StandardScaler()),
            ("model", Ridge(alpha=18.0)),
        ]),
        "hist_gradient_boosting": Pipeline([
            ("imputer", SimpleImputer(strategy="median", add_indicator=True)),
            ("model", HistGradientBoostingRegressor(
                loss="squared_error", learning_rate=.035, max_iter=240,
                max_leaf_nodes=15, min_samples_leaf=35,
                l2_regularization=5.0, random_state=9,
            )),
        ]),
    }


def regression_metrics(actual, predicted) -> dict:
    actual, predicted = np.asarray(actual, dtype=float), np.asarray(predicted, dtype=float)
    error = predicted - actual
    return {
        "samples": int(len(actual)),
        "mae": float(np.mean(np.abs(error))),
        "rmse": float(np.sqrt(np.mean(error ** 2))),
        "bias": float(np.mean(error)),
    }


def probability_above(prediction: float, threshold: float, residuals: np.ndarray) -> float:
    # Symmetric pseudo-observations prevent 0/1 probabilities in finite samples.
    prior = 8.0
    successes = float(np.sum(prediction + residuals > threshold))
    return (successes + prior / 2) / (len(residuals) + prior)


def binary_metrics(actual: list[int], probability: list[float], pushes: int = 0) -> dict:
    if not actual:
        return {"samples": 0, "pushes": pushes, "accuracy": None, "brier": None, "mean_probability": None}
    y, p = np.asarray(actual, dtype=float), np.asarray(probability, dtype=float)
    selected = np.maximum(p, 1 - p)
    correct = ((p >= .5) == (y == 1)).astype(float)
    return {
        "samples": int(len(y)), "pushes": int(pushes),
        "accuracy": float(np.mean(correct)), "brier": float(np.mean((p - y) ** 2)),
        "mean_probability": float(np.mean(selected)),
        "qualified_60": {
            "samples": int(np.sum(selected >= .60)),
            "accuracy": float(np.mean(correct[selected >= .60])) if np.any(selected >= .60) else None,
        },
    }


def market_audit(rows: list[dict], total_prediction, margin_prediction, total_residuals, margin_residuals) -> dict:
    markets = {key: {"actual": [], "probability": [], "pushes": 0} for key in ("moneyline", "spread", "total")}
    for row, predicted_total, predicted_margin in zip(rows, total_prediction, margin_prediction):
        margin = float(row["home_margin"])
        total = float(row["total_points"])
        home_probability = probability_above(float(predicted_margin), 0, margin_residuals)
        markets["moneyline"]["actual"].append(int(margin > 0))
        markets["moneyline"]["probability"].append(home_probability)
        spread = row.get("market_spread_line")
        if isinstance(spread, (int, float)) and math.isfinite(float(spread)):
            if margin == float(spread):
                markets["spread"]["pushes"] += 1
            else:
                markets["spread"]["actual"].append(int(margin > float(spread)))
                markets["spread"]["probability"].append(probability_above(float(predicted_margin), float(spread), margin_residuals))
        line = row.get("market_total_line")
        if isinstance(line, (int, float)) and math.isfinite(float(line)):
            if total == float(line):
                markets["total"]["pushes"] += 1
            else:
                markets["total"]["actual"].append(int(total > float(line)))
                markets["total"]["probability"].append(probability_above(float(predicted_total), float(line), total_residuals))
    return {
        key: binary_metrics(value["actual"], value["probability"], value["pushes"])
        for key, value in markets.items()
    }


def train(rows: list[dict], output: Path) -> dict:
    if len(rows) < 500:
        raise ValueError("At least 500 chronological NFL games are required")
    forbidden = ("odds", "price", "market_", "spread_line", "total_line", "score", "result")
    names = sorted({
        name for row in rows for name, value in row["features"].items()
        if (value is None or isinstance(value, (int, float, bool)))
        and not any(token in name.lower() for token in forbidden)
    })
    x = matrix(rows, names)
    train_slice, validation_slice, test_slice = chronological_slices(len(rows))
    fitted, validation_reports, test_reports, residuals = {}, {}, {}, {}
    for target in ("total_points", "home_margin"):
        y = np.asarray([float(row[target]) for row in rows])
        choices = {}
        for name, model in candidates().items():
            model.fit(x[train_slice], y[train_slice])
            choices[name] = (model, regression_metrics(y[validation_slice], model.predict(x[validation_slice])))
        selected_name = min(choices, key=lambda name: choices[name][1]["mae"])
        model, validation_report = choices[selected_name]
        validation_prediction = model.predict(x[validation_slice])
        test_prediction = model.predict(x[test_slice])
        fitted[target] = model
        validation_reports[target] = {"selected": selected_name, **validation_report}
        test_reports[target] = regression_metrics(y[test_slice], test_prediction)
        residuals[target] = y[validation_slice] - validation_prediction

    test_rows = rows[test_slice]
    total_test = fitted["total_points"].predict(x[test_slice])
    margin_test = fitted["home_margin"].predict(x[test_slice])
    audits = market_audit(
        test_rows, total_test, margin_test,
        residuals["total_points"], residuals["home_margin"],
    )
    total_ready = bool(
        audits["total"]["samples"] >= 300
        and audits["total"]["brier"] is not None
        and audits["total"]["brier"] < .25
        and abs(test_reports["total_points"]["bias"]) <= 1.5
    )
    spread_ready = bool(
        audits["spread"]["samples"] >= 300
        and audits["spread"]["brier"] is not None
        and audits["spread"]["brier"] < .25
        and abs(test_reports["home_margin"]["bias"]) <= 1.5
    )
    bundle = {
        "sport": "american-football", "features": names,
        "models": fitted,
        "residuals": {key: [float(value) for value in values] for key, values in residuals.items()},
        "trained_through": rows[train_slice.stop - 1]["event_time"],
        "calibrated_through": rows[validation_slice.stop - 1]["event_time"],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(bundle, output)
    return {
        "sport": "american-football", "market": "joint_score_distribution", "status": "shadow_only",
        "method": "separate total-points and home-margin regressors with empirical residual CDF",
        "samples": {"all": len(rows), "train": train_slice.stop, "validation": validation_slice.stop - validation_slice.start, "untouched_test": len(rows) - test_slice.start},
        "time_range": {"first": rows[0]["event_time"], "training_through": rows[train_slice.stop - 1]["event_time"], "validation_through": rows[validation_slice.stop - 1]["event_time"], "test_through": rows[-1]["event_time"]},
        "validation": validation_reports, "untouched_test": test_reports,
        "line_aware_audit": audits,
        "historical_readiness": {"moneyline": True, "spread": spread_ready, "total": total_ready},
        "promotion": {"passed": False, "reason": "Historical readiness is separate by market; immutable live observation remains required."},
        "model_artifact": str(output), "odds_used_as_features": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model-output", type=Path)
    args = parser.parse_args()
    raw = args.input.read_bytes()
    model_output = args.model_output or args.output.with_suffix(".joblib")
    report = train(load_rows(args.input), model_output)
    report["dataset_sha256"] = hashlib.sha256(raw).hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
