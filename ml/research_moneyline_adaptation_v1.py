"""Select a recency-adaptive moneyline model on 2025 and confirm on 2026."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from ml.starter_statcast_experiment import starter_matrix
from ml.train_v3 import fit as incumbent_fit
from ml.v2_experiment import DATA, matrix, read_jsonl


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "ml" / "artifacts" / "moneyline_adaptation_v1_research.json"


def score(y, p):
    p = np.clip(np.asarray(p), 1e-5, 1 - 1e-5)
    return {
        "games": int(len(y)),
        "brier": round(float(brier_score_loss(y, p)), 7),
        "log_loss": round(float(log_loss(y, p)), 7),
        "accuracy": round(float(np.mean((p >= .5) == y)), 7),
        "auc": round(float(roc_auc_score(y, p)), 7),
    }


def candidate_probability(x, y, margins, dates, train, test, config):
    half_life, alpha, histogram_weight = config
    age = (
        np.max(dates[train]) - dates[train]
    ).astype("timedelta64[D]").astype(float)
    weights = (
        None if half_life == 0
        else np.exp2(-np.maximum(age, 0) / half_life)
    )
    margin = Pipeline([
        ("scale", StandardScaler()), ("ridge", Ridge(alpha=alpha)),
    ]).fit(x[train], margins[train], ridge__sample_weight=weights)
    fitted = margin.predict(x[train])
    calibrator = LogisticRegression(C=.1, max_iter=2500).fit(
        fitted.reshape(-1, 1), y[train], sample_weight=weights,
    )
    margin_probability = calibrator.predict_proba(
        margin.predict(x[test]).reshape(-1, 1),
    )[:, 1]
    if histogram_weight:
        histogram = HistGradientBoostingClassifier(
            learning_rate=.035, max_iter=160, max_leaf_nodes=11,
            min_samples_leaf=120, l2_regularization=12, random_state=42,
        ).fit(x[train], y[train], sample_weight=weights)
        probability = (
            (1 - histogram_weight) * margin_probability
            + histogram_weight * histogram.predict_proba(x[test])[:, 1]
        )
    else:
        probability = margin_probability
    return probability


def main():
    base, _, _, y, years, _, _ = matrix()
    starters, _ = starter_matrix()
    x = np.column_stack([base, starters[:, 6:]])
    games = sorted(read_jsonl(DATA), key=lambda row: (row["date"], row["game_id"]))
    dates = np.asarray([np.datetime64(game["date"]) for game in games])
    margins = np.clip(np.asarray([
        game["home_score"] - game["away_score"] for game in games
    ], float), -8, 8)
    train_2025, validation = years < 2025, years == 2025
    incumbent_2025 = incumbent_fit(
        x[train_2025], y[train_2025], margins[train_2025],
    ).predict_proba(x[validation])[:, 1]
    configs = [
        (half_life, alpha, histogram_weight)
        for half_life in (0, 365, 730, 1095, 1460, 2190)
        for alpha in (50, 100, 200, 300)
        for histogram_weight in (0, .1, .2, .3)
    ]
    ranked = []
    for index, config in enumerate(configs):
        raw_probability = candidate_probability(
            x, y, margins, dates, train_2025, validation, config,
        )
        for shrink in (.8, .85, .9, .95, 1.0):
            probability = .5 + shrink * (raw_probability - .5)
            value = score(y[validation], probability)
            # Selection requires no material accuracy loss relative to incumbent.
            if value["accuracy"] >= score(y[validation], incumbent_2025)["accuracy"] - .002:
                ranked.append((value["brier"], (*config, shrink), value))
        if index % 20 == 0:
            print(f"tested {index + 1}/{len(configs)}", flush=True)
    ranked.sort(key=lambda row: row[0])
    _, selected, validation_score = ranked[0]
    train_2026, confirmation = years < 2026, years == 2026
    candidate_2026 = .5 + selected[3] * (
        candidate_probability(
            x, y, margins, dates, train_2026, confirmation, selected[:3],
        ) - .5
    )
    incumbent_2026 = incumbent_fit(
        x[train_2026], y[train_2026], margins[train_2026],
    ).predict_proba(x[confirmation])[:, 1]
    report = {
        "research_only": True,
        "selection_period": "2025",
        "confirmation_period": "2026",
        "selected": {
            "half_life_days": selected[0], "ridge_alpha": selected[1],
            "histogram_weight": selected[2], "shrink": selected[3],
        },
        "2025": {
            "incumbent": score(y[validation], incumbent_2025),
            "candidate": validation_score,
        },
        "2026": {
            "incumbent": score(y[confirmation], incumbent_2026),
            "candidate": score(y[confirmation], candidate_2026),
        },
        "top_2025": [
            {"config": config, **value} for _, config, value in ranked[:15]
        ],
    }
    OUTPUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
