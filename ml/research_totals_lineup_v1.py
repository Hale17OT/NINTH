"""Test multi-season confirmed-lineup talent in the totals architecture."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression, PoissonRegressor
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from scipy.stats import nbinom

from ml.lineup_talent import (
    apply_boxscore, fresh_state, start_season, totals_features,
)
from ml.player_props_features import BOX_PATH
from ml.train_totals import LINES, brier_summary, matrix, recommend, read_jsonl


ROOT = Path(__file__).resolve().parents[1]
CONTEXTS = ROOT / "ml" / "data" / "contexts_v3.jsonl"
OUTPUT = ROOT / "ml" / "artifacts" / "totals_lineup_v1_research.json"


def lineup_matrix(games):
    contexts = {str(row["game_id"]): row for row in read_jsonl(CONTEXTS)}
    boxes = {str(row["game_id"]): row for row in read_jsonl(BOX_PATH)}
    state, rows = fresh_state(), []
    for game in games:
        start_season(state, game["season"])
        rows.append(totals_features(state, contexts.get(str(game["game_id"]))))
        if str(game["game_id"]) in boxes:
            apply_boxscore(state, boxes[str(game["game_id"])])
    return np.asarray(rows, float)


def count_parts(x_train, total_train, x_test):
    model = Pipeline([
        ("scale", StandardScaler()),
        ("poisson", PoissonRegressor(alpha=2, max_iter=1500)),
    ]).fit(x_train[:, :21], total_train)
    train_mu = np.clip(model.predict(x_train[:, :21]), .1, 30)
    test_mu = np.clip(model.predict(x_test[:, :21]), .1, 30)
    dispersion = float(np.clip(np.mean(
        ((total_train - train_mu) ** 2 - train_mu)
        / np.maximum(train_mu ** 2, 1e-6)
    ), .01, 1.0))
    size = 1 / dispersion
    count = np.column_stack([
        nbinom.sf(int(line), size, size / (size + test_mu))
        for line in LINES
    ])
    calibrated = np.minimum.accumulate(np.column_stack([
        IsotonicRegression(
            increasing=True, out_of_bounds="clip", y_min=.01, y_max=.99,
        ).fit(train_mu, (total_train > line).astype(int)).predict(test_mu)
        for line in LINES
    ]), axis=1)
    return count, calibrated


def direct(x_train, y_train, x_test):
    columns = []
    for index in range(len(LINES)):
        model = Pipeline([
            ("scale", StandardScaler()),
            ("logistic", LogisticRegression(C=.03, max_iter=2500)),
        ]).fit(x_train, y_train[:, index])
        columns.append(model.predict_proba(x_test)[:, 1])
    return np.minimum.accumulate(np.column_stack(columns), axis=1)


def tune(count, calibrated, direct_probability, y, development):
    choices = []
    for count_weight in np.arange(0, 1.001, .05):
        for iso_weight in np.arange(0, 1.001 - count_weight, .05):
            direct_weight = 1 - count_weight - iso_weight
            probability = (
                count_weight * count + iso_weight * calibrated
                + direct_weight * direct_probability
            )
            choices.append((
                float(np.mean((probability[development] - y[development]) ** 2)),
                count_weight, iso_weight, direct_weight, probability,
            ))
    return min(choices, key=lambda row: row[0])


def main():
    games, x, total, years, _, _, _ = matrix()
    lineup = lineup_matrix(games)
    augmented = np.column_stack([x, lineup])
    actual = np.column_stack([total > line for line in LINES]).astype(int)
    count_rows, iso_rows, base_rows, augmented_rows = [], [], [], []
    y_rows, year_rows = [], []
    for year in sorted(set(years)):
        if year < 2022 or np.sum(years < year) < 4000:
            continue
        train, test = years < year, years == year
        count, calibrated = count_parts(x[train], total[train], x[test])
        count_rows.append(count)
        iso_rows.append(calibrated)
        base_rows.append(direct(x[train], actual[train], x[test]))
        augmented_rows.append(direct(augmented[train], actual[train], augmented[test]))
        y_rows.append(actual[test])
        year_rows.extend(years[test])
        print(f"completed totals lineup fold {year}", flush=True)
    count, calibrated = np.vstack(count_rows), np.vstack(iso_rows)
    baseline_direct, lineup_direct = np.vstack(base_rows), np.vstack(augmented_rows)
    y, fold_years = np.vstack(y_rows), np.asarray(year_rows)
    development = fold_years <= 2024
    variants = {}
    for name, direct_probability in (
        ("incumbent", baseline_direct), ("lineup_talent", lineup_direct),
    ):
        dev, cw, iw, dw, probability = tune(
            count, calibrated, direct_probability, y, development,
        )
        variants[name] = {
            "weights": {"count": cw, "isotonic": iw, "direct": dw},
            "development": {
                **brier_summary(y[development], probability[development]),
                "recommended": recommend(probability[development], y[development]),
            },
            "2025": {
                **brier_summary(y[fold_years == 2025], probability[fold_years == 2025]),
                "recommended": recommend(probability[fold_years == 2025], y[fold_years == 2025]),
            },
            "2026": {
                **brier_summary(y[fold_years == 2026], probability[fold_years == 2026]),
                "recommended": recommend(probability[fold_years == 2026], y[fold_years == 2026]),
            },
        }
    report = {
        "research_only": True,
        "selection_period": "2022-2024 rolling-origin",
        "lineup_features": [
            "lineup_talent_woba_sum", "lineup_talent_power_sum",
            "lineup_talent_discipline_sum", "lineup_talent_joint_reliability",
        ],
        "variants": variants,
    }
    OUTPUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
