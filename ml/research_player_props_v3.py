"""Leakage-safe player-prop calibration and count-model experiments.

This module is research-only. It never overwrites the deployed prop artifact.
Model and calibration choices use 2024, while 2025 and 2026 are reported
separately so a short-lived improvement cannot pass the promotion gate.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import lightgbm as lgb
import numpy as np
from scipy.stats import nbinom, poisson
from sklearn.metrics import brier_score_loss, log_loss

from ml.player_props_features import (
    BATTER_PROPS, PITCHER_PROPS, load_games, load_statcast,
)
from ml.train_player_props import (
    _apply_calibration, _choose_calibration, _expand_dataset, _kind_dataset,
    _monotone,
)


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "ml" / "artifacts" / "player_props_v3_research.json"
OBSERVED_MELBET_LINES = {
    "batter:hits": (0.5, 1.5),
    "pitcher:strikeouts": (3.5, 4.5, 5.5, 6.5, 7.5),
    "pitcher:outs": (14.5, 15.5, 16.5, 17.5, 18.5, 19.5),
    "pitcher:walks": (0.5, 1.5, 2.5),
    "pitcher:hits_allowed": (2.5, 3.5, 4.5, 5.5, 6.5),
}


def metric(y, probability):
    y = np.asarray(y, int)
    probability = np.clip(np.asarray(probability, float), 1e-5, 1 - 1e-5)
    side = probability >= .5
    confidence = np.maximum(probability, 1 - probability)
    return {
        "samples": int(len(y)),
        "brier": round(float(brier_score_loss(y, probability)), 7),
        "log_loss": round(float(log_loss(y, probability, labels=[0, 1])), 7),
        "side_accuracy": round(float(np.mean(side == y)), 7),
        "accuracy_at_60": round(float(np.mean((side == y)[confidence >= .6])), 7)
        if np.any(confidence >= .6) else None,
        "coverage_at_60": round(float(np.mean(confidence >= .6)), 7),
    }


def recommendation_metric(y, probability, lines, offered_lines):
    """Score the same maximum-confidence choice made by the live builder."""
    line_count = len(lines)
    y = np.asarray(y).reshape(-1, line_count)
    probability = np.asarray(probability).reshape(-1, line_count)
    indexes = [
        index for index, line in enumerate(lines)
        if float(line) in {float(value) for value in offered_lines}
    ]
    candidate = probability[:, indexes]
    confidence = np.maximum(candidate, 1 - candidate)
    chosen = np.argmax(confidence, axis=1)
    row = np.arange(len(y))
    selected_index = np.asarray(indexes)[chosen]
    selected_probability = probability[row, selected_index]
    selected_y = y[row, selected_index]
    selected_side = selected_probability >= .5
    correct = selected_side == selected_y
    selected_confidence = np.maximum(selected_probability, 1 - selected_probability)
    return {
        "player_games": int(len(y)),
        "brier": round(float(np.mean((selected_confidence - correct) ** 2)), 7),
        "accuracy": round(float(np.mean(correct)), 7),
        "mean_confidence": round(float(np.mean(selected_confidence)), 7),
        "line_counts": {
            str(line): int(np.sum(np.asarray(lines)[selected_index] == line))
            for line in offered_lines
        },
    }


def line_metrics(y, probability, lines):
    y = np.asarray(y).reshape(-1, len(lines))
    probability = np.asarray(probability).reshape(-1, len(lines))
    return {
        str(line): metric(y[:, index], probability[:, index])
        for index, line in enumerate(lines)
    }


def linewise_fit(y, raw, distribution, line_count):
    """Select an independent calibration/blend for each offered threshold."""
    y = np.asarray(y).reshape(-1, line_count)
    raw = np.asarray(raw).reshape(-1, line_count)
    distribution = np.asarray(distribution).reshape(-1, line_count)
    return [
        _choose_calibration(y[:, index], raw[:, index], distribution[:, index], 1)
        for index in range(line_count)
    ]


def linewise_apply(specs, raw, distribution, line_count):
    raw = np.asarray(raw).reshape(-1, line_count)
    distribution = np.asarray(distribution).reshape(-1, line_count)
    columns = []
    for index, spec in enumerate(specs):
        blended = spec["blend"] * raw[:, index] + (1 - spec["blend"]) * distribution[:, index]
        columns.append(_apply_calibration(spec, blended))
    return np.minimum.accumulate(np.column_stack(columns), axis=1).reshape(-1)


def distribution_matrix(mean, alpha, lines):
    mean = np.clip(np.asarray(mean, float), .01, 100)
    if alpha <= .002:
        return np.column_stack([poisson.sf(int(line), mean) for line in lines])
    size = 1 / alpha
    return np.column_stack([
        nbinom.sf(int(line), size, size / (size + mean)) for line in lines
    ])


def evaluate_prop(dataset, kind, prop, lines):
    x, y, years, distribution = _expand_dataset(dataset, prop, lines)
    train, calibration = years <= 2023, years == 2024
    test_2025, test_2026 = years == 2025, years == 2026
    line_count = len(lines)
    params = {
        "objective": "binary", "n_estimators": 450, "learning_rate": .025,
        "num_leaves": 31, "reg_lambda": 10.0, "min_child_samples": 180,
        "feature_fraction": .75, "random_state": 42, "n_jobs": -1, "verbosity": -1,
    }
    direct = lgb.LGBMClassifier(**params).fit(
        x[train], y[train], eval_set=[(x[calibration], y[calibration])],
        callbacks=[lgb.early_stopping(35, verbose=False)],
    )
    raw_cal = direct.predict_proba(x[calibration])[:, 1]
    shared = _choose_calibration(
        y[calibration], raw_cal, distribution[calibration], line_count,
    )
    per_line = linewise_fit(
        y[calibration], raw_cal, distribution[calibration], line_count,
    )
    offered = OBSERVED_MELBET_LINES.get(f"{kind}:{prop}")
    focus_model = focus_specs = None
    if offered:
        line_weights = np.asarray([
            1.0 if float(line) in {float(value) for value in offered} else .15
            for line in lines
        ])
        focus_weight = np.tile(line_weights, len(dataset["base"]))
        focus_model = lgb.LGBMClassifier(**params).fit(
            x[train], y[train], sample_weight=focus_weight[train],
            eval_set=[(x[calibration], y[calibration])],
            callbacks=[lgb.early_stopping(35, verbose=False)],
        )
        focus_cal = focus_model.predict_proba(x[calibration])[:, 1]
        focus_specs = linewise_fit(
            y[calibration], focus_cal, distribution[calibration], line_count,
        )

    # A single count forecast creates coherent probabilities for every line.
    # Use one row per player-game; prop-specific history replaces the generic
    # columns before fitting.
    base_x = x[::line_count].copy()
    counts = dataset["outcomes"][prop]
    base_years = dataset["years"]
    count_train, count_cal = base_years <= 2023, base_years == 2024
    count_model = lgb.LGBMRegressor(
        objective="poisson", n_estimators=500, learning_rate=.025,
        num_leaves=23, reg_lambda=15.0, min_child_samples=220,
        feature_fraction=.8, random_state=42, n_jobs=-1, verbosity=-1,
    ).fit(
        base_x[count_train], counts[count_train],
        eval_set=[(base_x[count_cal], counts[count_cal])],
        callbacks=[lgb.early_stopping(40, verbose=False)],
    )
    mu_train = np.clip(count_model.predict(base_x[count_train]), .01, 100)
    pearson = ((counts[count_train] - mu_train) ** 2 - mu_train) / np.maximum(mu_train ** 2, 1e-5)
    alpha = float(np.clip(np.mean(pearson), .002, 2.0))
    count_cal_probability = distribution_matrix(
        count_model.predict(base_x[count_cal]), alpha, lines,
    ).reshape(-1)
    # Count predictions are passed as both inputs: calibration is selected
    # without an artificial blend back to the existing heuristic distribution.
    count_specs = linewise_fit(
        y[calibration], count_cal_probability, count_cal_probability, line_count,
    )

    candidates = {}
    for label, mask, base_mask in (
        ("2025", test_2025, base_years == 2025),
        ("2026", test_2026, base_years == 2026),
    ):
        raw = direct.predict_proba(x[mask])[:, 1]
        shared_raw = shared["blend"] * raw + (1 - shared["blend"]) * distribution[mask]
        shared_probability = _monotone(
            _apply_calibration(shared, shared_raw), line_count,
        )
        line_probability = linewise_apply(
            per_line, raw, distribution[mask], line_count,
        )
        count_raw = distribution_matrix(
            count_model.predict(base_x[base_mask]), alpha, lines,
        ).reshape(-1)
        count_probability = linewise_apply(
            count_specs, count_raw, count_raw, line_count,
        )
        candidates[label] = {
            "shared_calibration": metric(y[mask], shared_probability),
            "linewise_calibration": metric(y[mask], line_probability),
            "count_distribution": metric(y[mask], count_probability),
            "linewise_per_line": line_metrics(
                y[mask], line_probability, lines,
            ),
            "shared_per_line": line_metrics(
                y[mask], shared_probability, lines,
            ),
            "count_per_line": line_metrics(
                y[mask], count_probability, lines,
            ),
        }
        if focus_model is not None:
            focus_raw = focus_model.predict_proba(x[mask])[:, 1]
            focus_probability = linewise_apply(
                focus_specs, focus_raw, distribution[mask], line_count,
            )
            candidates[label]["offered_focus"] = metric(
                y[mask], focus_probability,
            )
            candidates[label]["offered_focus_per_line"] = line_metrics(
                y[mask], focus_probability, lines,
            )
        if offered:
            candidates[label]["live_builder_selection"] = {
                "shared_calibration": recommendation_metric(
                    y[mask], shared_probability, lines, offered,
                ),
                "linewise_calibration": recommendation_metric(
                    y[mask], line_probability, lines, offered,
                ),
                "count_distribution": recommendation_metric(
                    y[mask], count_probability, lines, offered,
                ),
            }
            if focus_model is not None:
                candidates[label]["live_builder_selection"]["offered_focus"] = recommendation_metric(
                    y[mask], focus_probability, lines, offered,
                )
    return {
        "kind": kind,
        "prop": prop,
        "lines": list(lines),
        "negative_binomial_alpha": round(alpha, 6),
        "linewise_methods": [
            {"line": line, "method": spec["method"], "direct_weight": spec["blend"]}
            for line, spec in zip(lines, per_line)
        ],
        "count_calibration_methods": [
            {"line": line, "method": spec["method"]}
            for line, spec in zip(lines, count_specs)
        ],
        "evaluation": candidates,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--props", nargs="*",
        default=["batter:hits", "pitcher:strikeouts", "pitcher:outs"],
    )
    args = parser.parse_args()
    requested = set(args.props)
    games, statcast = load_games(), load_statcast()
    results = {}
    for kind, available in (("batter", BATTER_PROPS), ("pitcher", PITCHER_PROPS)):
        active = {
            prop: lines for prop, lines in available.items()
            if f"{kind}:{prop}" in requested
        }
        if not active:
            continue
        dataset = _kind_dataset(games, statcast, kind, active)
        for prop, lines in active.items():
            key = f"{kind}:{prop}"
            print(f"researching {key}", flush=True)
            results[key] = evaluate_prop(dataset, kind, prop, lines)
    report = {
        "research_only": True,
        "selection": "Train through 2023; select models/calibration on 2024 only.",
        "promotion_gate": "Must improve Brier on 2025 and 2026 separately.",
        "games": len(games),
        "last_game_date": games[-1]["date"],
        "models": results,
    }
    OUTPUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
