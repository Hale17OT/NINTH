"""Train and temporally validate calibrated player-prop probability models."""
from __future__ import annotations

import argparse
import json
import math
import time
from collections import defaultdict
from pathlib import Path

import joblib
import lightgbm as lgb
import numpy as np
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss

from ml.player_props_features import (
    BATTER_PROPS, PITCHER_PROPS, build_features, feature_names, fresh_state,
    load_games, load_statcast, replay_samples, retarget_line, serializable_state,
)


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "ml" / "artifacts" / "player_props.joblib"
REPORT = ROOT / "ml" / "artifacts" / "player_props_report.json"


def _metric(y, p):
    p = np.clip(np.asarray(p, dtype=float), 1e-5, 1 - 1e-5)
    y = np.asarray(y, dtype=int)
    return {"brier": float(brier_score_loss(y, p)), "log_loss": float(log_loss(y, p, labels=[0, 1]))}


def _sigmoid(value):
    return 1.0 / (1.0 + np.exp(-np.clip(value, -30, 30)))


def _logit(value):
    value = np.clip(value, 1e-5, 1 - 1e-5)
    return np.log(value / (1 - value))


def _apply_calibration(spec, values):
    values = np.asarray(values, dtype=float)
    if spec["method"] == "isotonic":
        return spec["model"].predict(values)
    if spec["method"] == "sigmoid":
        return spec["model"].predict_proba(_logit(values).reshape(-1, 1))[:, 1]
    return values


def _choose_calibration(y, model_probability, distribution_probability):
    candidates = []
    for blend in (0.65, 0.8, 0.9, 1.0):
        raw = blend * model_probability + (1 - blend) * distribution_probability
        candidates.append(({"method": "raw", "blend": blend, "model": None}, raw))
        if len(np.unique(y)) > 1:
            sigmoid = LogisticRegression(C=1.0, max_iter=500).fit(_logit(raw).reshape(-1, 1), y)
            candidates.append(({"method": "sigmoid", "blend": blend, "model": sigmoid}, sigmoid.predict_proba(_logit(raw).reshape(-1, 1))[:, 1]))
            if len(y) >= 1500:
                isotonic = IsotonicRegression(y_min=.001, y_max=.999, out_of_bounds="clip").fit(raw, y)
                candidates.append(({"method": "isotonic", "blend": blend, "model": isotonic}, isotonic.predict(raw)))
    return min(candidates, key=lambda pair: brier_score_loss(y, pair[1]))[0]


def _kind_dataset(games, statcast, kind, props):
    state = fresh_state(); base_rows, years = [], []
    outcomes = {prop: [] for prop in props}
    extras = {prop: [] for prop in props}
    base_prop = next(iter(props)); base_line = props[base_prop][0]
    for sample in replay_samples(games, statcast, state=state):
        if sample["kind"] != kind:
            continue
        base = build_features(
            sample["state"], kind, sample["player_id"], sample["team_id"], sample["opponent_id"],
            sample["date"], sample["season"], base_prop, base_line, sample["home"], sample["lineup_slot"],
            sample.get("opponent_starter_id"),
        )
        base_rows.append(base); years.append(sample["season"])
        for prop, lines in props.items():
            outcomes[prop].append(sample["outcomes"][prop])
            threshold_rows = []
            for line in lines:
                row = retarget_line(base, sample["state"], kind, sample["player_id"], sample["season"], prop, line)
                threshold_rows.append(row[[0, 15, 16, 17, 18, 19]])
            extras[prop].append(threshold_rows)
    return {
        "base": np.asarray(base_rows, dtype=np.float32), "years": np.asarray(years),
        "outcomes": {key: np.asarray(value, dtype=np.float32) for key, value in outcomes.items()},
        "extras": {key: np.asarray(value, dtype=np.float32) for key, value in extras.items()},
    }


def _expand_dataset(dataset, prop, lines):
    count = len(lines)
    x = np.repeat(dataset["base"], count, axis=0)
    threshold = dataset["extras"][prop].reshape(-1, 6)
    x[:, [0, 15, 16, 17, 18, 19]] = threshold
    outcome = np.repeat(dataset["outcomes"][prop], count)
    line_values = np.tile(np.asarray(lines, dtype=np.float32), len(dataset["base"]))
    y = (outcome > line_values).astype(np.uint8)
    years = np.repeat(dataset["years"], count)
    return x, y, years, x[:, 15].copy()


def _climatology(train_y, train_x, x):
    table = defaultdict(list)
    for line, outcome in zip(train_x[:, 0], train_y): table[round(float(line), 1)].append(int(outcome))
    overall = float(np.mean(train_y))
    rates = {key: (sum(values) + 20 * overall) / (len(values) + 20) for key, values in table.items()}
    return np.asarray([rates.get(round(float(line), 1), overall) for line in x[:, 0]])


def train_one(dataset, kind, prop, lines):
    started = time.time()
    x, y, years, distribution = _expand_dataset(dataset, prop, lines)
    train = years <= 2023; calibration = years == 2024; test = years >= 2025
    if min(train.sum(), calibration.sum(), test.sum()) == 0:
        raise RuntimeError(f"insufficient temporal split for {kind} {prop}")
    candidates = [
        {"learning_rate": .04, "num_leaves": 15, "reg_lambda": 6.0, "min_child_samples": 120, "feature_fraction": .85},
        {"learning_rate": .025, "num_leaves": 31, "reg_lambda": 10.0, "min_child_samples": 180, "feature_fraction": .75},
    ]
    fitted = []
    for params in candidates:
        model = lgb.LGBMClassifier(
            objective="binary", n_estimators=450, random_state=42, n_jobs=-1,
            verbosity=-1, **params,
        ).fit(
            x[train], y[train], eval_set=[(x[calibration], y[calibration])],
            callbacks=[lgb.early_stopping(35, verbose=False)],
        )
        raw = model.predict_proba(x[calibration])[:, 1]
        spec = _choose_calibration(y[calibration], raw, distribution[calibration])
        blend_raw = spec["blend"] * raw + (1 - spec["blend"]) * distribution[calibration]
        calibrated = _apply_calibration(spec, blend_raw)
        fitted.append((brier_score_loss(y[calibration], calibrated), model, spec, params))
    _, model, calibrator, params = min(fitted, key=lambda row: row[0])
    raw_test = model.predict_proba(x[test])[:, 1]
    blended_test = calibrator["blend"] * raw_test + (1 - calibrator["blend"]) * distribution[test]
    probability = _apply_calibration(calibrator, blended_test)
    climate = _climatology(y[train], x[train], x[test])
    climate_metrics, model_metrics = _metric(y[test], climate), _metric(y[test], probability)
    confident = np.maximum(probability, 1 - probability) >= .60
    correct = (probability >= .5) == y[test]
    report = {
        "kind": kind, "prop": prop, "lines": list(lines), "features": len(feature_names(kind)),
        "samples": {"train_through_2023": int(train.sum()), "calibration_2024": int(calibration.sum()), "untouched_2025_2026": int(test.sum())},
        "calibration": {"method": calibrator["method"], "model_weight": calibrator["blend"]},
        "parameters": params, "climatology": climate_metrics, "unseen": model_metrics,
        "brier_skill_vs_climatology": float(1 - model_metrics["brier"] / climate_metrics["brier"]),
        "side_accuracy": float(np.mean(correct)),
        "confidence_60": {"coverage": float(np.mean(confident)), "accuracy": float(np.mean(correct[confident])) if confident.any() else None},
        "elapsed_seconds": round(time.time() - started, 1),
    }
    bundle = {"model": model, "calibrator": calibrator, "lines": list(lines), "kind": kind, "prop": prop}
    print(f"{kind:7} {prop:18} Brier {model_metrics['brier']:.5f} baseline {climate_metrics['brier']:.5f} skill {report['brier_skill_vs_climatology']:.1%}", flush=True)
    return bundle, report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--props", nargs="*", help="Optional prop keys for a partial research run")
    args = parser.parse_args()
    games = load_games(); statcast = load_statcast()
    print(f"loaded {len(games)} official box scores and {len(statcast)} Statcast games", flush=True)
    requested = set(args.props or [])
    models, reports, final_state = {}, {}, None
    groups = (("batter", BATTER_PROPS), ("pitcher", PITCHER_PROPS))
    for kind, props in groups:
        active_props = {prop: lines for prop, lines in props.items() if not requested or prop in requested or f"{kind}:{prop}" in requested}
        if not active_props:
            continue
        print(f"building shared {kind} point-in-time matrix for {len(active_props)} props", flush=True)
        dataset = _kind_dataset(games, statcast, kind, active_props)
        print(f"{kind} matrix contains {len(dataset['base'])} player-games", flush=True)
        for prop, lines in active_props.items():
            if requested and prop not in requested and f"{kind}:{prop}" not in requested:
                continue
            bundle, report = train_one(dataset, kind, prop, lines)
            key = f"{kind}:{prop}"; models[key] = bundle; reports[key] = report
        del dataset
    # A final replay is required when a partial run's last model did not span all player kinds.
    final_state = fresh_state()
    for _ in replay_samples(games, statcast, minimum_history=10**9, state=final_state):
        pass
    artifact = {
        "version": 1, "trained_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "models": models, "state": serializable_state(final_state),
        "feature_names": {kind: feature_names(kind) for kind in ("batter", "pitcher")},
    }
    report = {
        "version": 1, "trained_at": artifact["trained_at"], "data": {
            "source": "Official MLB box scores plus Baseball Savant Statcast; no sportsbook prices",
            "games": len(games), "first_date": games[0]["date"], "last_date": games[-1]["date"],
            "split": "Train through 2023; calibration on 2024; untouched evaluation on 2025-2026",
        }, "models": reports,
    }
    ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(artifact, ARTIFACT, compress=3)
    REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"saved {ARTIFACT} and {REPORT}", flush=True)


if __name__ == "__main__":
    main()
