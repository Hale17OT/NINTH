"""Research dynamic rating systems as diverse moneyline ensemble members.

The rating streams are updated only after each completed game. Hyperparameters,
calibration and blend weights are selected on rolling-origin 2022-2024
predictions, then frozen for separate 2025 and 2026 reporting.
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import numpy as np
from scipy.optimize import minimize
from scipy.stats import skellam
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score

from ml.research_v6 import apply_beta, beta_columns
from ml.starter_statcast_experiment import starter_matrix
from ml.train_v3 import fit as production_fit
from ml.v2_experiment import DATA, matrix as moneyline_matrix, read_jsonl


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "ml" / "artifacts" / "moneyline_ratings_v1_research.json"


def score(y, p):
    y = np.asarray(y, int)
    p = np.clip(np.asarray(p, float), 1e-5, 1 - 1e-5)
    return {
        "games": int(len(y)),
        "brier": round(float(brier_score_loss(y, p)), 7),
        "log_loss": round(float(log_loss(y, p)), 7),
        "accuracy": round(float(np.mean((p >= .5) == y)), 7),
        "auc": round(float(roc_auc_score(y, p)), 7),
    }


def elo_stream(games, home_advantage, k_factor, carry, margin_multiplier):
    ratings = defaultdict(lambda: 1500.0)
    current_season = None
    output = []
    for game in games:
        if game["season"] != current_season:
            if current_season is not None:
                for team in list(ratings):
                    ratings[team] = 1500 + carry * (ratings[team] - 1500)
            current_season = game["season"]
        home, away = str(game["home_id"]), str(game["away_id"])
        gap = ratings[home] + home_advantage - ratings[away]
        expected = 1 / (1 + 10 ** (-gap / 400))
        output.append(expected)
        actual = float(game["home_score"] > game["away_score"])
        if margin_multiplier:
            margin = abs(float(game["home_score"]) - float(game["away_score"]))
            winner_gap = gap if actual else -gap
            multiplier = np.log1p(max(1, margin)) * 2.2 / (2.2 + .001 * winner_gap)
        else:
            multiplier = 1.0
        change = k_factor * multiplier * (actual - expected)
        ratings[home] += change
        ratings[away] -= change
    return np.asarray(output)


def run_stream(games, alpha, carry, home_runs):
    offense = defaultdict(lambda: 4.5)
    defense = defaultdict(lambda: 4.5)
    current_season = None
    output = []
    for game in games:
        if game["season"] != current_season:
            if current_season is not None:
                for team in set(offense) | set(defense):
                    offense[team] = 4.5 + carry * (offense[team] - 4.5)
                    defense[team] = 4.5 + carry * (defense[team] - 4.5)
            current_season = game["season"]
        home, away = str(game["home_id"]), str(game["away_id"])
        home_mu = np.clip(.5 * (offense[home] + defense[away]) + home_runs, .2, 15)
        away_mu = np.clip(.5 * (offense[away] + defense[home]), .2, 15)
        output.append(
            skellam.sf(0, home_mu, away_mu) + .5 * skellam.pmf(0, home_mu, away_mu)
        )
        hs, aws = float(game["home_score"]), float(game["away_score"])
        offense[home] = (1 - alpha) * offense[home] + alpha * hs
        defense[home] = (1 - alpha) * defense[home] + alpha * aws
        offense[away] = (1 - alpha) * offense[away] + alpha * aws
        defense[away] = (1 - alpha) * defense[away] + alpha * hs
    return np.asarray(output)


def calibrate_on_development(probability, y, development):
    candidates = []
    for c in (.003, .01, .03, .1, .3, 1.0):
        model = LogisticRegression(C=c, max_iter=2000).fit(
            beta_columns(probability[development]), y[development],
        )
        calibrated = apply_beta(model, probability)
        candidates.append((brier_score_loss(y[development], calibrated[development]), c, calibrated))
    return min(candidates, key=lambda row: row[0])


def main():
    base, _, _, y_all, years_all, _, _ = moneyline_matrix()
    starters, _ = starter_matrix()
    games = sorted(read_jsonl(DATA), key=lambda row: (row["date"], row["game_id"]))
    x = np.column_stack([base, starters[:, 6:]])
    labels, fold_years, production_parts, indices = [], [], [], []
    for year in sorted(set(years_all)):
        if year < 2022 or np.sum(years_all < year) < 4000:
            continue
        train, test = years_all < year, years_all == year
        margins = np.clip(np.asarray([
            game["home_score"] - game["away_score"] for game in games
        ], float), -8, 8)
        production_parts.extend(
            production_fit(x[train], y_all[train], margins[train]).predict_proba(x[test])[:, 1]
        )
        labels.extend(y_all[test])
        fold_years.extend(years_all[test])
        indices.extend(np.flatnonzero(test))
    y = np.asarray(labels)
    fold_years = np.asarray(fold_years)
    indices = np.asarray(indices)
    production = np.asarray(production_parts)
    development = fold_years <= 2024

    streams = {}
    for home_advantage in (20, 35, 50, 65):
        for k_factor in (8, 12, 16, 20, 24, 32):
            for carry in (.65, .8, .9, 1.0):
                for margin in (False, True):
                    name = f"elo_h{home_advantage}_k{k_factor}_c{carry}_m{int(margin)}"
                    streams[name] = elo_stream(
                        games, home_advantage, k_factor, carry, margin,
                    )[indices]
    for alpha in (.025, .04, .06, .08, .12, .18):
        for carry in (.4, .65, .8, 1.0):
            for home_runs in (.1, .2, .3, .4):
                name = f"runs_a{alpha}_c{carry}_h{home_runs}"
                streams[name] = run_stream(games, alpha, carry, home_runs)[indices]

    calibrated = {}
    development_rank = []
    for name, probability in streams.items():
        dev_brier, c, values = calibrate_on_development(
            probability, y, development,
        )
        calibrated[name] = values
        development_rank.append((dev_brier, name, c))
    development_rank.sort()
    best_elo = next(name for _, name, _ in development_rank if name.startswith("elo_"))
    best_runs = next(name for _, name, _ in development_rank if name.startswith("runs_"))
    components = np.column_stack([
        production, calibrated[best_elo], calibrated[best_runs],
    ])
    objective = lambda weights: float(  # noqa: E731
        np.mean((components[development] @ weights - y[development]) ** 2)
        + 1e-5 * np.sum((weights - 1 / 3) ** 2)
    )
    result = minimize(
        objective, np.full(3, 1 / 3), method="SLSQP",
        bounds=[(0, 1)] * 3,
        constraints={"type": "eq", "fun": lambda weights: np.sum(weights) - 1},
        options={"ftol": 1e-12, "maxiter": 500},
    )
    weights = np.clip(result.x, 0, 1)
    weights /= weights.sum()
    ensemble = components @ weights
    robustness = []
    for elo_weight in np.arange(0, .301, .025):
        probability = (1 - elo_weight) * production + elo_weight * calibrated[best_elo]
        robustness.append({
            "elo_weight": round(float(elo_weight), 3),
            "development_brier": round(float(brier_score_loss(
                y[development], probability[development],
            )), 7),
            "2025_brier": round(float(brier_score_loss(
                y[fold_years == 2025], probability[fold_years == 2025],
            )), 7),
            "2026_brier": round(float(brier_score_loss(
                y[fold_years == 2026], probability[fold_years == 2026],
            )), 7),
        })
    report = {
        "research_only": True,
        "selection_period": "2022-2024 rolling-origin",
        "components": ["production_v5", best_elo, best_runs],
        "weights": [round(float(value), 7) for value in weights],
        "development": {
            "production": score(y[development], production[development]),
            "ensemble": score(y[development], ensemble[development]),
        },
        "2025": {
            "production": score(y[fold_years == 2025], production[fold_years == 2025]),
            "ensemble": score(y[fold_years == 2025], ensemble[fold_years == 2025]),
        },
        "2026": {
            "production": score(y[fold_years == 2026], production[fold_years == 2026]),
            "ensemble": score(y[fold_years == 2026], ensemble[fold_years == 2026]),
        },
        "top_rating_streams": [
            {"name": name, "development_brier": round(float(value), 7), "beta_c": c}
            for value, name, c in development_rank[:12]
        ],
        "elo_weight_robustness": robustness,
    }
    OUTPUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
