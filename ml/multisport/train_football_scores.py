"""Train and audit NINTH's coherent Football score-distribution model.

Only pre-match, odds-independent features are fitted.  Football-Data prices are
retained outside the feature matrix and used after frozen predictions solely for
clearly-labelled closing-line evaluation.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import joblib
import numpy as np
from sklearn.base import clone
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import PoissonRegressor
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from .evaluation import binary_metrics, closing_line_betting_metrics, expected_calibration_error, no_vig_probabilities
from .score_models import dixon_coles_matrix
from .train import matrix, parse_time
from .train_nfl_scores import regression_metrics
from .windows import partition_fixed_window, window_metadata


def load_rows(path: Path) -> list[dict]:
    rows = []
    for line_number, raw in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        if not raw.strip():
            continue
        row = json.loads(raw)
        event_time = parse_time(row["event_time"])
        if parse_time(row["knowledge_time"]) > event_time:
            raise ValueError(f"Row {line_number} leaks future knowledge")
        if not isinstance(row.get("features"), dict):
            raise ValueError(f"Row {line_number} has no feature object")
        if not all(isinstance(row.get(key), (int, float)) for key in ("home_goals", "away_goals")):
            raise ValueError(f"Row {line_number} has no numeric score")
        row["_event_time"] = event_time
        rows.append(row)
    rows.sort(key=lambda row: (row["_event_time"], str(row.get("event_id") or "")))
    return rows


def candidates() -> dict[str, object]:
    return {
        "poisson_glm": Pipeline([
            ("imputer", SimpleImputer(strategy="median", add_indicator=True)),
            ("scale", StandardScaler()),
            ("model", PoissonRegressor(alpha=8.0, max_iter=500)),
        ]),
        "poisson_gradient_boosting": Pipeline([
            ("imputer", SimpleImputer(strategy="median", add_indicator=True)),
            ("model", HistGradientBoostingRegressor(
                loss="poisson", learning_rate=.035, max_iter=220,
                max_leaf_nodes=15, min_samples_leaf=45,
                l2_regularization=8.0, random_state=9,
            )),
        ]),
    }


def score_distributions(home_prediction, away_prediction) -> list[dict]:
    return [
        dixon_coles_matrix(max(.08, float(home)), max(.08, float(away)))
        for home, away in zip(home_prediction, away_prediction)
    ]


def _multiclass_metrics(rows: list[dict], distributions: list[dict]) -> dict:
    brier, losses, correct, top_three = [], [], [], []
    for row, distribution in zip(rows, distributions):
        actual = f"{int(row['home_goals'])}-{int(row['away_goals'])}"
        probabilities = distribution["matrix"]
        actual_probability = max(1e-12, float(probabilities.get(actual, 0.0)))
        brier.append(sum((value - int(score == actual)) ** 2 for score, value in probabilities.items()))
        losses.append(-math.log(actual_probability))
        ranked = sorted(probabilities, key=probabilities.get, reverse=True)
        correct.append(int(ranked[0] == actual))
        top_three.append(int(actual in ranked[:3]))
    return {
        "samples": len(rows),
        "multiclass_brier": float(np.mean(brier)),
        "log_loss": float(np.mean(losses)),
        "exact_score_accuracy": float(np.mean(correct)),
        "top_3_score_coverage": float(np.mean(top_three)),
    }


def _three_way_betting(rows: list[dict], distributions: list[dict]) -> dict:
    bets = []
    for row, distribution in zip(rows, distributions):
        closing = (row.get("archived_prices") or {}).get("closing") or {}
        prices = [closing.get("home"), closing.get("draw"), closing.get("away")]
        market = no_vig_probabilities(*prices)
        if any(value is None for value in market):
            continue
        model = [distribution["home_win"], distribution["draw"], distribution["away_win"]]
        edges = [probability - reference for probability, reference in zip(model, market)]
        selected = int(np.argmax(edges))
        if edges[selected] <= 0:
            continue
        actual = 0 if row["home_goals"] > row["away_goals"] else 1 if row["home_goals"] == row["away_goals"] else 2
        won = selected == actual
        bets.append({"won":won, "price":float(prices[selected]), "edge":float(edges[selected]), "profit":float(prices[selected])-1 if won else -1.0})
    cumulative = peak = drawdown = 0.0
    losing = longest = 0
    for bet in bets:
        cumulative += bet["profit"]; peak = max(peak, cumulative); drawdown = max(drawdown, peak - cumulative)
        losing = 0 if bet["won"] else losing + 1; longest = max(longest, losing)
    wins = sum(int(bet["won"]) for bet in bets); profit = sum(bet["profit"] for bet in bets)
    return {
        "strategy":"closing-line best positive model edge among Home/Draw/Away; no threshold optimization",
        "odds_at_prediction_available":False, "qualifying_bets":len(bets), "wins":wins, "losses":len(bets)-wins,
        "hit_rate":wins/len(bets) if bets else None,
        "average_market_odds":float(np.mean([bet["price"] for bet in bets])) if bets else None,
        "average_estimated_edge":float(np.mean([bet["edge"] for bet in bets])) if bets else None,
        "roi":profit/len(bets) if bets else None, "yield":profit/len(bets) if bets else None, "clv":None,
        "maximum_drawdown_units":drawdown, "longest_losing_streak":longest,
        "limitation":"Archived closing prices are available, but exact prediction-time prices are not; this is a closing-line strategy audit, not live-simulated ROI or CLV.",
    }


def _three_way_metrics(rows: list[dict], distributions: list[dict]) -> dict:
    probabilities = np.asarray([[item["home_win"], item["draw"], item["away_win"]] for item in distributions], dtype=float)
    actual = np.asarray([0 if row["home_goals"] > row["away_goals"] else 1 if row["home_goals"] == row["away_goals"] else 2 for row in rows], dtype=int)
    one_hot = np.eye(3)[actual]
    confidence = probabilities.max(axis=1); predicted = probabilities.argmax(axis=1)
    qualified = confidence >= .5
    return {
        "samples":len(rows), "accuracy":float(np.mean(predicted == actual)),
        "multiclass_brier":float(np.mean(np.sum((probabilities-one_hot)**2, axis=1))),
        "log_loss":float(np.mean(-np.log(np.clip(probabilities[np.arange(len(actual)), actual], 1e-12, 1)))),
        "expected_calibration_error":float(np.mean([expected_calibration_error((actual==index).astype(int), probabilities[:,index]) for index in range(3)])),
        "mean_confidence":float(np.mean(confidence)),
        "qualified":{"floor":.5, "samples":int(qualified.sum()), "coverage":float(qualified.mean()), "accuracy":float(np.mean(predicted[qualified] == actual[qualified])) if qualified.any() else None},
        "closing_line_betting":_three_way_betting(rows, distributions),
    }


def market_metrics(rows: list[dict], distributions: list[dict]) -> dict:
    home_actual = [int(row["home_goals"] > row["away_goals"]) for row in rows]
    over_actual = [int(row["home_goals"] + row["away_goals"] > 2.5) for row in rows]
    btts_actual = [int(row["home_goals"] > 0 and row["away_goals"] > 0) for row in rows]
    home_probability = [item["home_win"] for item in distributions]
    over_probability = [item["over_2_5"] for item in distributions]
    btts_probability = [item["both_teams_score"] for item in distributions]
    home_rows = [{**row, "label": label} for row, label in zip(rows, home_actual)]
    over_rows = [{**row, "label": label} for row, label in zip(rows, over_actual)]
    return {
        "score": _multiclass_metrics(rows, distributions),
        "match_result_1x2": _three_way_metrics(rows, distributions),
        "home_win": {
            **binary_metrics(home_actual, home_probability),
            "closing_line_betting": closing_line_betting_metrics(home_rows, home_probability, "home_win"),
        },
        "over_2_5": {
            **binary_metrics(over_actual, over_probability),
            "closing_line_betting": closing_line_betting_metrics(over_rows, over_probability, "over_2_5"),
        },
        "both_teams_score": binary_metrics(btts_actual, btts_probability),
    }


def _features(rows: list[dict]) -> list[str]:
    forbidden = ("odds", "price", "market_", "score", "result", "goal")
    return sorted({
        name for row in rows for name, value in row["features"].items()
        if (value is None or isinstance(value, (int, float, bool)))
        and not any(token in name.lower() for token in forbidden)
    })


def train(rows: list[dict], model_output: Path) -> dict:
    if len(rows) < 2_000:
        raise ValueError("At least 2,000 chronological Football matches are required")
    partition = partition_fixed_window(rows, "football")
    window = partition["window"]
    names = _features(rows)
    x = matrix(rows, names)
    row_index = {id(row): index for index, row in enumerate(rows)}
    development_index = np.asarray([row_index[id(row)] for row in partition["development"]], dtype=int)
    fitted, validations, oof_predictions = {}, {}, {}
    for target in ("home_goals", "away_goals"):
        y = np.asarray([float(row[target]) for row in rows])
        candidate_predictions = {name: [] for name in candidates()}
        actual, seasons, folds = [], [], []
        for season in window.development[1:]:
            history_rows = [row for value in window.development if value < season for row in partition["by_season"][value]]
            target_rows = partition["by_season"][season]
            history = np.asarray([row_index[id(row)] for row in history_rows], dtype=int)
            target_index = np.asarray([row_index[id(row)] for row in target_rows], dtype=int)
            scores = {}
            for name, candidate in candidates().items():
                estimator = clone(candidate).fit(x[history], y[history])
                prediction = np.maximum(.08, estimator.predict(x[target_index]))
                candidate_predictions[name].extend(float(value) for value in prediction)
                scores[name] = regression_metrics(y[target_index], prediction)
            actual.extend(float(value) for value in y[target_index])
            seasons.extend([season] * len(target_index))
            folds.append({
                "target_season": window.label(season),
                "training_seasons": [window.label(value) for value in window.development if value < season],
                "train_samples": len(history), "validation_samples": len(target_index),
                "candidates": scores,
            })
        comparison = {
            name: regression_metrics(actual, probability)
            for name, probability in candidate_predictions.items()
        }
        selected = min(comparison, key=lambda name: comparison[name]["mae"])
        fitted[target] = clone(candidates()[selected]).fit(x[development_index], y[development_index])
        oof_predictions[target] = candidate_predictions[selected]
        validations[target] = {
            "selected": selected, "candidate_comparison": comparison,
            "combined": comparison[selected], "folds": folds,
            "season_by_season": {
                window.label(season): regression_metrics(
                    [actual[index] for index, value in enumerate(seasons) if value == season],
                    [candidate_predictions[selected][index] for index, value in enumerate(seasons) if value == season],
                ) for season in sorted(set(seasons))
            },
        }

    development_oof_rows = [
        row for season in window.development[1:] for row in partition["by_season"][season]
    ]
    development_markets = market_metrics(
        development_oof_rows,
        score_distributions(oof_predictions["home_goals"], oof_predictions["away_goals"]),
    )
    holdout_by_season, combined_rows, combined_distributions = {}, [], []
    for season in window.holdout:
        season_rows = partition["by_season"][season]
        indices = np.asarray([row_index[id(row)] for row in season_rows], dtype=int)
        home_prediction = np.maximum(.08, fitted["home_goals"].predict(x[indices]))
        away_prediction = np.maximum(.08, fitted["away_goals"].predict(x[indices]))
        distributions = score_distributions(home_prediction, away_prediction)
        holdout_by_season[window.label(season)] = {
            "home_goals": regression_metrics([row["home_goals"] for row in season_rows], home_prediction),
            "away_goals": regression_metrics([row["away_goals"] for row in season_rows], away_prediction),
            "markets": market_metrics(season_rows, distributions),
        }
        combined_rows.extend(season_rows)
        combined_distributions.extend(distributions)
    combined_markets = market_metrics(combined_rows, combined_distributions)
    stable_markets = {}
    for market in ("home_win", "over_2_5", "both_teams_score", "match_result_1x2"):
        metric_name = "multiclass_brier" if market == "match_result_1x2" else "brier"
        season_briers = [values["markets"][market][metric_name] for values in holdout_by_season.values()]
        stable_markets[market] = {
            "assessment": "stable" if max(season_briers) - min(season_briers) <= .02 else "variable",
            "season_briers": season_briers,
        }
    bundle = {
        "sport": "football", "market": "score_distribution", "features": names,
        "models": fitted, "trained_through": partition["development"][-1]["event_time"],
        "development_seasons": list(window.development), "holdout_seasons": list(window.holdout),
        "holdouts_excluded_from_fit": True, "distribution": "Dixon-Coles adjusted independent Poisson",
    }
    model_output.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(bundle, model_output)
    return {
        "sport": "football", "market": "score_distribution", "status": "evaluation_complete",
        "method": "separate expected-home/away-goal regressors with Dixon-Coles score matrix",
        "algorithm": {target: values["selected"] for target, values in validations.items()},
        "features": names,
        "samples": {"all": len(rows), "development": len(partition["development"]), "holdout": len(partition["holdout"])},
        **window_metadata(partition),
        "development_validation": {"targets": validations, "derived_markets": development_markets},
        "holdout_results": {
            "season_by_season": holdout_by_season,
            "combined": {"markets": combined_markets},
            "sample_size": len(combined_rows), "stability_assessment": stable_markets,
        },
        "historical_readiness": {
            market: {
                "passed": combined_markets[market]["brier"] < .25,
                "reason": "combined untouched holdout Brier below 0.25" if combined_markets[market]["brier"] < .25 else "combined untouched holdout Brier did not beat 0.25",
            } for market in ("home_win", "over_2_5", "both_teams_score")
        },
        "promotion": {"passed": False, "reason": "Historical evaluation is complete; operational release remains separately gated."},
        "model_artifact": str(model_output), "odds_used_as_features": False,
        "odds_evaluation": "Archived prices were used only after frozen predictions in labelled closing-line audits.",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("ledger", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model-output", type=Path, required=True)
    args = parser.parse_args()
    report = train(load_rows(args.ledger), args.model_output)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
