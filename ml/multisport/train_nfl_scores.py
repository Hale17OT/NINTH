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
from sklearn.base import clone

from .train import matrix, parse_time
from .windows import partition_fixed_window, window_metadata
from .evaluation import no_vig_probabilities


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


def betting_audit(bets: list[dict]) -> dict:
    cumulative = peak = drawdown = 0.0
    losing = longest_losing = 0
    for bet in bets:
        cumulative += bet["profit"]
        peak = max(peak, cumulative)
        drawdown = max(drawdown, peak - cumulative)
        losing = 0 if bet["won"] else losing + 1
        longest_losing = max(longest_losing, losing)
    wins = sum(int(bet["won"]) for bet in bets)
    profit = sum(bet["profit"] for bet in bets)
    return {
        "strategy": "closing-line positive model edge; no threshold optimization",
        "odds_at_prediction_available": False,
        "qualifying_bets": len(bets), "wins": wins, "losses": len(bets) - wins,
        "hit_rate": wins / len(bets) if bets else None,
        "average_market_odds": float(np.mean([bet["price"] for bet in bets])) if bets else None,
        "average_estimated_edge": float(np.mean([bet["edge"] for bet in bets])) if bets else None,
        "roi": profit / len(bets) if bets else None, "yield": profit / len(bets) if bets else None,
        "clv": None, "maximum_drawdown_units": drawdown,
        "longest_losing_streak": longest_losing,
        "limitation": "The archive supplies closing prices, not exact prediction-time prices; ROI is a closing-line audit and CLV is unavailable.",
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
    reports = {
        key: binary_metrics(value["actual"], value["probability"], value["pushes"])
        for key, value in markets.items()
    }
    price_bets = {key: [] for key in markets}
    for row, predicted_total, predicted_margin in zip(rows, total_prediction, margin_prediction):
        closing = (row.get("archived_prices") or {}).get("closing") or {}
        choices = {
            "moneyline": (
                probability_above(float(predicted_margin), 0, margin_residuals),
                float(row["home_margin"]) > 0, closing.get("home"), closing.get("away"), False,
            ),
        }
        spread = row.get("market_spread_line")
        if isinstance(spread, (int, float)) and float(row["home_margin"]) != float(spread):
            choices["spread"] = (
                probability_above(float(predicted_margin), float(spread), margin_residuals),
                float(row["home_margin"]) > float(spread), closing.get("home_spread"), closing.get("away_spread"), False,
            )
        line = row.get("market_total_line")
        if isinstance(line, (int, float)) and float(row["total_points"]) != float(line):
            choices["total"] = (
                probability_above(float(predicted_total), float(line), total_residuals),
                float(row["total_points"]) > float(line), closing.get("over"), closing.get("under"), False,
            )
        for market, (positive_probability, actual_positive, positive_price, negative_price, _) in choices.items():
            no_vig = no_vig_probabilities(positive_price, negative_price)
            positive = positive_probability >= .5
            selected_probability = positive_probability if positive else 1 - positive_probability
            price = positive_price if positive else negative_price
            market_probability = no_vig[0] if positive else no_vig[1]
            if price is None or market_probability is None or selected_probability <= market_probability:
                continue
            won = bool(actual_positive) == positive
            price_bets[market].append({
                "won": won, "price": float(price),
                "edge": selected_probability - float(market_probability),
                "profit": float(price) - 1 if won else -1.0,
            })
    for market in reports:
        reports[market]["closing_line_betting"] = betting_audit(price_bets[market])
    return reports


def train(rows: list[dict], output: Path) -> dict:
    if len(rows) < 500:
        raise ValueError("At least 500 chronological NFL games are required")
    forbidden = ("odds", "price", "market_", "spread_line", "total_line", "score", "result")
    names = sorted({
        name for row in rows for name, value in row["features"].items()
        if (value is None or isinstance(value, (int, float, bool)))
        and not any(token in name.lower() for token in forbidden)
    })
    partition = partition_fixed_window(rows, "american-football")
    window = partition["window"]
    x = matrix(rows, names)
    row_index = {id(row): index for index, row in enumerate(rows)}
    development_index = np.asarray([row_index[id(row)] for row in partition["development"]], dtype=int)
    fitted, validation_reports, residuals, development_diagnostics = {}, {}, {}, {}
    for target in ("total_points", "home_margin"):
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
                model = clone(candidate).fit(x[history], y[history])
                prediction = model.predict(x[target_index])
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
        comparison = {name: regression_metrics(actual, prediction) for name, prediction in candidate_predictions.items()}
        selected_name = min(comparison, key=lambda name: comparison[name]["mae"])
        selected_oof = np.asarray(candidate_predictions[selected_name], dtype=float)
        model = clone(candidates()[selected_name]).fit(x[development_index], y[development_index])
        fitted[target] = model
        residuals[target] = np.asarray(actual, dtype=float) - selected_oof
        validation_reports[target] = {
            "selected": selected_name, "candidate_comparison": comparison,
            "combined": regression_metrics(actual, selected_oof), "folds": folds,
        }
        development_diagnostics[target] = {
            window.label(season): regression_metrics(
                [actual[index] for index, value in enumerate(seasons) if value == season],
                [selected_oof[index] for index, value in enumerate(seasons) if value == season],
            )
            for season in sorted(set(seasons))
        }

    holdout_by_season = {}
    combined_rows, combined_total, combined_margin = [], [], []
    for season in window.holdout:
        season_rows = partition["by_season"][season]
        season_index = np.asarray([row_index[id(row)] for row in season_rows], dtype=int)
        total_prediction = fitted["total_points"].predict(x[season_index])
        margin_prediction = fitted["home_margin"].predict(x[season_index])
        home_prediction = (total_prediction + margin_prediction) / 2
        away_prediction = (total_prediction - margin_prediction) / 2
        holdout_by_season[window.label(season)] = {
            "total_points": regression_metrics(
                [row["total_points"] for row in season_rows], total_prediction,
            ),
            "home_margin": regression_metrics(
                [row["home_margin"] for row in season_rows], margin_prediction,
            ),
            "home_team_points": regression_metrics([row["home_score"] for row in season_rows], home_prediction),
            "away_team_points": regression_metrics([row["away_score"] for row in season_rows], away_prediction),
            "markets": market_audit(
                season_rows, total_prediction, margin_prediction,
                residuals["total_points"], residuals["home_margin"],
            ),
        }
        combined_rows.extend(season_rows)
        combined_total.extend(float(value) for value in total_prediction)
        combined_margin.extend(float(value) for value in margin_prediction)
    audits = market_audit(
        combined_rows, combined_total, combined_margin,
        residuals["total_points"], residuals["home_margin"],
    )
    combined_test = {
        "total_points": regression_metrics([row["total_points"] for row in combined_rows], combined_total),
        "home_margin": regression_metrics([row["home_margin"] for row in combined_rows], combined_margin),
        "home_team_points": regression_metrics([row["home_score"] for row in combined_rows], (np.asarray(combined_total)+np.asarray(combined_margin))/2),
        "away_team_points": regression_metrics([row["away_score"] for row in combined_rows], (np.asarray(combined_total)-np.asarray(combined_margin))/2),
    }
    total_ready = bool(
        audits["total"]["samples"] >= 300
        and audits["total"]["brier"] is not None
        and audits["total"]["brier"] < .25
        and abs(combined_test["total_points"]["bias"]) <= 1.5
    )
    spread_ready = bool(
        audits["spread"]["samples"] >= 300
        and audits["spread"]["brier"] is not None
        and audits["spread"]["brier"] < .25
        and abs(combined_test["home_margin"]["bias"]) <= 1.5
    )
    bundle = {
        "sport": "american-football", "features": names,
        "models": fitted,
        "residuals": {key: [float(value) for value in values] for key, values in residuals.items()},
        "trained_through": partition["development"][-1]["event_time"],
        "development_seasons": list(window.development),
        "holdout_seasons": list(window.holdout),
        "holdouts_excluded_from_fit": True,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(bundle, output)
    return {
        "sport": "american-football", "market": "joint_score_distribution", "status": "evaluation_complete",
        "method": "separate total-points and home-margin regressors with empirical residual CDF",
        "features": names,
        "samples": {"all": len(rows), "development": len(partition["development"]), "holdout": len(partition["holdout"])},
        **window_metadata(partition),
        "development_validation": validation_reports,
        "development_season_diagnostics": development_diagnostics,
        "holdout_results": {
            "season_by_season": holdout_by_season,
            "combined": {**combined_test, "markets": audits},
            "sample_size": len(combined_rows),
            "stability_assessment": {
                market: (
                    "stable_across_both_holdouts"
                    if all((values["markets"][market].get("brier") or 1) < .25 for values in holdout_by_season.values())
                    else "not_stable_across_both_holdouts"
                ) for market in ("moneyline", "spread", "total")
            },
        },
        "line_aware_audit": audits,
        "historical_readiness": {"moneyline": True, "spread": spread_ready, "total": total_ready},
        "promotion": {"passed": False, "reason": "Historical holdout evaluation is separate by market; operational release remains separately gated."},
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
