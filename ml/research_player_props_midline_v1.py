"""Train threshold-specialist models for commonly offered pitcher lines."""
from __future__ import annotations

import json
from pathlib import Path

import lightgbm as lgb
import numpy as np
from sklearn.metrics import brier_score_loss

from ml.player_props_features import PITCHER_PROPS, load_games, load_statcast
from ml.train_player_props import (
    _apply_calibration, _choose_calibration, _expand_dataset, _kind_dataset,
)


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "ml" / "artifacts" / "player_props_midline_v1_research.json"
TARGETS = {
    "strikeouts": (3.5, 4.5, 5.5, 6.5, 7.5),
    "outs": (14.5, 15.5, 16.5, 17.5, 18.5, 19.5),
}


def metric(y, p):
    return {
        "samples": int(len(y)),
        "brier": round(float(brier_score_loss(y, p)), 7),
        "accuracy": round(float(np.mean((p >= .5) == y)), 7),
        "coverage_60": round(float(np.mean(np.maximum(p, 1 - p) >= .6)), 7),
        "accuracy_60": round(float(np.mean(
            ((p >= .5) == y)[np.maximum(p, 1 - p) >= .6]
        )), 7),
    }


def main():
    games, statcast = load_games(), load_statcast()
    active = {prop: PITCHER_PROPS[prop] for prop in TARGETS}
    dataset = _kind_dataset(games, statcast, "pitcher", active)
    report = {}
    params = [
        {"learning_rate": .04, "num_leaves": 15, "reg_lambda": 6.0, "min_child_samples": 120, "feature_fraction": .85},
        {"learning_rate": .025, "num_leaves": 31, "reg_lambda": 10.0, "min_child_samples": 180, "feature_fraction": .75},
        {"learning_rate": .02, "num_leaves": 15, "reg_lambda": 18.0, "min_child_samples": 250, "feature_fraction": .8},
    ]
    for prop, lines in active.items():
        x, y, years, distribution = _expand_dataset(dataset, prop, lines)
        x = x.reshape(-1, len(lines), x.shape[1])
        y = y.reshape(-1, len(lines))
        distribution = distribution.reshape(-1, len(lines))
        base_years = dataset["years"]
        train, calibration = base_years <= 2023, base_years == 2024
        prop_report = {}
        for line in TARGETS[prop]:
            index = list(lines).index(line)
            fitted = []
            for values in params:
                model = lgb.LGBMClassifier(
                    objective="binary", n_estimators=450, random_state=42,
                    n_jobs=-1, verbosity=-1, **values,
                ).fit(
                    x[train, index], y[train, index],
                    eval_set=[(x[calibration, index], y[calibration, index])],
                    callbacks=[lgb.early_stopping(35, verbose=False)],
                )
                raw = model.predict_proba(x[calibration, index])[:, 1]
                spec = _choose_calibration(
                    y[calibration, index], raw,
                    distribution[calibration, index], 1,
                )
                blended = spec["blend"] * raw + (1 - spec["blend"]) * distribution[calibration, index]
                probability = _apply_calibration(spec, blended)
                fitted.append((
                    brier_score_loss(y[calibration, index], probability),
                    model, spec, values,
                ))
            _, model, spec, selected = min(fitted, key=lambda row: row[0])
            evaluations = {}
            for year in (2025, 2026):
                mask = base_years == year
                raw = model.predict_proba(x[mask, index])[:, 1]
                blended = spec["blend"] * raw + (1 - spec["blend"]) * distribution[mask, index]
                evaluations[str(year)] = metric(
                    y[mask, index], _apply_calibration(spec, blended),
                )
            prop_report[str(line)] = {
                "parameters": selected,
                "calibration": {"method": spec["method"], "model_weight": spec["blend"]},
                "evaluation": evaluations,
            }
            print(f"completed specialist pitcher:{prop} {line}", flush=True)
        report[f"pitcher:{prop}"] = prop_report
    result = {
        "research_only": True,
        "selection": "Train through 2023; select model and calibration on 2024.",
        "confirmation": "Report 2025 and 2026 separately.",
        "models": report,
    }
    OUTPUT.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
