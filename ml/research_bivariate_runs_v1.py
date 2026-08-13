"""Partially pooled home/away run-distribution research.

Each game contributes a home-score and away-score row. Shared coefficients plus
regularized team offense and defense effects pool information across teams while
retaining matchup identity. The same two run distributions produce coherent
moneyline and totals probabilities.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from scipy.sparse import csr_matrix, hstack
from scipy.stats import nbinom, skellam
from sklearn.linear_model import LogisticRegression, PoissonRegressor
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score
from sklearn.preprocessing import StandardScaler

from ml.research_v6 import apply_beta, beta_columns
from ml.totals_features import TOTAL_FEATURE_NAMES
from ml.train_totals import LINES, matrix


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "ml" / "artifacts" / "bivariate_runs_v1_research.json"


def metrics(y, p):
    y = np.asarray(y, int)
    p = np.clip(np.asarray(p, float), 1e-5, 1 - 1e-5)
    return {
        "samples": int(len(y)),
        "brier": round(float(brier_score_loss(y, p)), 7),
        "log_loss": round(float(log_loss(y, p, labels=[0, 1])), 7),
        "accuracy": round(float(np.mean((p >= .5) == y)), 7),
        "auc": round(float(roc_auc_score(y, p)), 7),
    }


def feature_index(name):
    return TOTAL_FEATURE_NAMES.index(name)


def scoring_numeric(x):
    """Return alternating home/away scoring rows from matchup totals features."""
    common = [
        feature_index("league_recent_runs"),
        feature_index("venue_recent_total"),
        feature_index("temperature_f"),
        feature_index("wind_speed_mph"),
        feature_index("month_sin"),
        feature_index("month_cos"),
        feature_index("context_available"),
        feature_index("prior_matchup_expected_total"),
        feature_index("shrunk_matchup_expected_total"),
        feature_index("prior_strength_reliability"),
    ]
    home_columns = [
        feature_index("home_offense_20"),
        feature_index("away_runs_allowed_20"),
        feature_index("home_recent_total_10"),
        feature_index("home_total_volatility_20"),
        feature_index("away_starter_era"),
        feature_index("away_starter_whip"),
        feature_index("away_starter_fip"),
        feature_index("away_starter_k_minus_bb_per_inning"),
        feature_index("away_starter_prior_innings"),
        feature_index("home_lineup_ops"),
        feature_index("home_lineup_ops_spread"),
        feature_index("home_lineup_bottom_ops"),
        feature_index("away_bullpen_3day_pitches"),
        feature_index("home_rest"),
        feature_index("away_rest"),
    ]
    away_columns = [
        feature_index("away_offense_20"),
        feature_index("home_runs_allowed_20"),
        feature_index("away_recent_total_10"),
        feature_index("away_total_volatility_20"),
        feature_index("home_starter_era"),
        feature_index("home_starter_whip"),
        feature_index("home_starter_fip"),
        feature_index("home_starter_k_minus_bb_per_inning"),
        feature_index("home_starter_prior_innings"),
        feature_index("away_lineup_ops"),
        feature_index("away_lineup_ops_spread"),
        feature_index("away_lineup_bottom_ops"),
        feature_index("home_bullpen_3day_pitches"),
        feature_index("away_rest"),
        feature_index("home_rest"),
    ]
    output = np.empty((2 * len(x), len(common) + len(home_columns) + 1))
    output[0::2, :-1] = np.column_stack([x[:, common], x[:, home_columns]])
    output[1::2, :-1] = np.column_stack([x[:, common], x[:, away_columns]])
    output[0::2, -1] = 1.0
    output[1::2, -1] = 0.0
    return output


def identity_matrix(games):
    team_ids = sorted({str(game[key]) for game in games for key in ("home_id", "away_id")})
    lookup = {team: index for index, team in enumerate(team_ids)}
    rows, columns, values = [], [], []
    width = 2 * len(team_ids)
    for game_index, game in enumerate(games):
        home, away = lookup[str(game["home_id"])], lookup[str(game["away_id"])]
        # Separate partially pooled offensive and defensive effects.
        for row, offense, defense in (
            (2 * game_index, home, away),
            (2 * game_index + 1, away, home),
        ):
            rows.extend((row, row))
            columns.extend((offense, len(team_ids) + defense))
            values.extend((1.0, 1.0))
    return csr_matrix((values, (rows, columns)), shape=(2 * len(games), width))


def calibrate_binary(probability, y, development):
    choices = []
    for c in (.003, .01, .03, .1, .3, 1.0):
        fitted = LogisticRegression(C=c, max_iter=2500).fit(
            beta_columns(probability[development]), y[development],
        )
        calibrated = apply_beta(fitted, probability)
        choices.append((
            brier_score_loss(y[development], calibrated[development]), c, calibrated,
        ))
    return min(choices, key=lambda row: row[0])


def calibrate_totals(probability, actual, development):
    calibrated = np.empty_like(probability)
    cs = []
    for index in range(probability.shape[1]):
        _, c, values = calibrate_binary(
            probability[:, index], actual[:, index], development,
        )
        calibrated[:, index] = values
        cs.append(c)
    return np.minimum.accumulate(calibrated, axis=1), cs


def main():
    games, x, total, years, _, _, _ = matrix()
    numeric = scoring_numeric(x)
    identities = identity_matrix(games)
    score_targets = np.empty(2 * len(games))
    score_targets[0::2] = [game["home_score"] for game in games]
    score_targets[1::2] = [game["away_score"] for game in games]
    actual_moneyline = np.asarray([
        game["home_score"] > game["away_score"] for game in games
    ], int)
    actual_totals = np.column_stack([total > line for line in LINES]).astype(int)

    fold_years, fold_moneyline, fold_totals = [], [], []
    streams = {
        alpha: {"moneyline": [], "totals": []}
        for alpha in (.03, .1, .3, 1.0, 3.0, 10.0)
    }
    for year in sorted(set(years)):
        if year < 2022 or np.sum(years < year) < 4000:
            continue
        train_games, test_games = years < year, years == year
        train_rows = np.repeat(train_games, 2)
        test_rows = np.repeat(test_games, 2)
        scaler = StandardScaler().fit(numeric[train_rows])
        z_train = hstack([
            csr_matrix(scaler.transform(numeric[train_rows])),
            identities[train_rows],
        ], format="csr")
        z_test = hstack([
            csr_matrix(scaler.transform(numeric[test_rows])),
            identities[test_rows],
        ], format="csr")
        for alpha in streams:
            model = PoissonRegressor(alpha=alpha, max_iter=1800).fit(
                z_train, score_targets[train_rows],
            )
            train_mu = np.clip(model.predict(z_train), .05, 20)
            test_mu = np.clip(model.predict(z_test), .05, 20)
            home_mu, away_mu = test_mu[0::2], test_mu[1::2]
            moneyline = (
                skellam.sf(0, home_mu, away_mu)
                + .5 * skellam.pmf(0, home_mu, away_mu)
            )
            total_mu = home_mu + away_mu
            train_total_mu = train_mu[0::2] + train_mu[1::2]
            train_total = total[train_games]
            dispersion = float(np.clip(np.mean(
                ((train_total - train_total_mu) ** 2 - train_total_mu)
                / np.maximum(train_total_mu ** 2, 1e-5)
            ), .005, 1.5))
            size = 1 / dispersion
            total_probability = np.column_stack([
                nbinom.sf(int(line), size, size / (size + total_mu))
                for line in LINES
            ])
            streams[alpha]["moneyline"].append(moneyline)
            streams[alpha]["totals"].append(total_probability)
        fold_years.extend(years[test_games])
        fold_moneyline.extend(actual_moneyline[test_games])
        fold_totals.append(actual_totals[test_games])
        print(f"completed partially pooled run fold {year}", flush=True)

    fold_years = np.asarray(fold_years)
    moneyline_y = np.asarray(fold_moneyline)
    totals_y = np.vstack(fold_totals)
    development = fold_years <= 2024
    results = {}
    for alpha, parts in streams.items():
        raw_moneyline = np.concatenate(parts["moneyline"])
        raw_totals = np.vstack(parts["totals"])
        _, moneyline_c, moneyline = calibrate_binary(
            raw_moneyline, moneyline_y, development,
        )
        totals_probability, totals_cs = calibrate_totals(
            raw_totals, totals_y, development,
        )
        results[str(alpha)] = {
            "moneyline_beta_c": moneyline_c,
            "totals_beta_cs": totals_cs,
            "development": {
                "moneyline": metrics(moneyline_y[development], moneyline[development]),
                "totals_mean_brier": round(float(np.mean(
                    (totals_probability[development] - totals_y[development]) ** 2
                )), 7),
            },
            "2025": {
                "moneyline": metrics(moneyline_y[fold_years == 2025], moneyline[fold_years == 2025]),
                "totals_mean_brier": round(float(np.mean(
                    (totals_probability[fold_years == 2025] - totals_y[fold_years == 2025]) ** 2
                )), 7),
            },
            "2026": {
                "moneyline": metrics(moneyline_y[fold_years == 2026], moneyline[fold_years == 2026]),
                "totals_mean_brier": round(float(np.mean(
                    (totals_probability[fold_years == 2026] - totals_y[fold_years == 2026]) ** 2
                )), 7),
            },
        }
    best = min(
        results,
        key=lambda key: (
            results[key]["development"]["moneyline"]["brier"]
            + results[key]["development"]["totals_mean_brier"]
        ),
    )
    report = {
        "research_only": True,
        "selection_period": "2022-2024 rolling-origin",
        "selected_alpha": best,
        "variants": results,
    }
    OUTPUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
