"""Point-in-time multi-season lineup true-talent research.

Player batting outcomes are carried across seasons with regression to league
means. Features are built before applying the current game box score, and use
only the submitted batting order recorded in the official MLB context.
"""
from __future__ import annotations

import json
from collections import defaultdict, deque
from pathlib import Path

import numpy as np
from scipy.optimize import minimize
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score

from ml.player_props_features import BOX_PATH
from ml.starter_statcast_experiment import starter_matrix
from ml.train_v3 import fit as moneyline_fit
from ml.v2_experiment import DATA, matrix as moneyline_matrix, read_jsonl


ROOT = Path(__file__).resolve().parents[1]
CONTEXTS = ROOT / "ml" / "data" / "contexts_v3.jsonl"
OUTPUT = ROOT / "ml" / "artifacts" / "lineup_talent_v1_research.json"
ORDER_WEIGHTS = np.asarray([1.12, 1.10, 1.08, 1.06, 1.02, .98, .93, .88, .83])
ORDER_WEIGHTS /= ORDER_WEIGHTS.sum()


def score(y, p):
    p = np.clip(np.asarray(p), 1e-5, 1 - 1e-5)
    return {
        "games": int(len(y)),
        "brier": round(float(brier_score_loss(y, p)), 7),
        "log_loss": round(float(log_loss(y, p)), 7),
        "accuracy": round(float(np.mean((p >= .5) == y)), 7),
        "auc": round(float(roc_auc_score(y, p)), 7),
    }


def empty_counts():
    return {
        "pa": 0.0, "ab": 0.0, "hits": 0.0, "doubles": 0.0,
        "triples": 0.0, "hr": 0.0, "walks": 0.0, "hbp": 0.0,
        "sf": 0.0, "strikeouts": 0.0,
    }


def add_counts(target, batting, weight=1.0):
    mapping = {
        "pa": "plateAppearances", "ab": "atBats", "hits": "hits",
        "doubles": "doubles", "triples": "triples", "hr": "homeRuns",
        "walks": "baseOnBalls", "hbp": "hitByPitch", "sf": "sacFlies",
        "strikeouts": "strikeOuts",
    }
    for key, source in mapping.items():
        target[key] += weight * float(batting.get(source, 0) or 0)


def rates(counts, stabilization=180):
    pa = counts["pa"]
    singles = max(0, counts["hits"] - counts["doubles"] - counts["triples"] - counts["hr"])
    denominator = max(1, counts["ab"] + counts["walks"] + counts["hbp"] + counts["sf"])
    woba = (
        .69 * counts["walks"] + .72 * counts["hbp"] + .89 * singles
        + 1.27 * counts["doubles"] + 1.62 * counts["triples"] + 2.10 * counts["hr"]
    ) / denominator
    reliability = pa / (pa + stabilization)
    return {
        "woba": .315 + reliability * (woba - .315),
        "power": .032 + reliability * (counts["hr"] / max(1, pa) - .032),
        "discipline": -.13 + reliability * (
            (counts["walks"] - counts["strikeouts"]) / max(1, pa) + .13
        ),
        "reliability": reliability,
    }


def blend_counts(long_term, recent):
    output = empty_counts()
    for key in output:
        output[key] = .7 * long_term[key] + .3 * recent[key]
    return output


def lineup_talent_matrix(games):
    contexts = {str(row["game_id"]): row for row in read_jsonl(CONTEXTS)}
    boxes = {str(row["game_id"]): row for row in read_jsonl(BOX_PATH)}
    career = defaultdict(empty_counts)
    recent = defaultdict(lambda: deque(maxlen=40))
    output = []
    current_season = None
    for game in games:
        if game["season"] != current_season:
            if current_season is not None:
                # Offseason aging/roster uncertainty regresses accumulated
                # evidence without discarding proven player skill.
                for value in career.values():
                    for key in value:
                        value[key] *= .78
                for history in recent.values():
                    history.clear()
            current_season = game["season"]
        context = contexts.get(str(game["game_id"]), {})
        sides = []
        for side in ("home", "away"):
            ids = list((context.get(side) or {}).get("lineup_ids") or [])[:9]
            summaries = []
            for player_id in ids:
                recent_counts = empty_counts()
                for game_counts in recent[str(player_id)]:
                    for key, value in game_counts.items():
                        recent_counts[key] += value
                summaries.append(rates(blend_counts(career[str(player_id)], recent_counts)))
            while len(summaries) < 9:
                summaries.append(rates(empty_counts()))
            sides.append({
                "woba": float(sum(weight * row["woba"] for weight, row in zip(ORDER_WEIGHTS, summaries))),
                "top_woba": float(np.mean([row["woba"] for row in summaries[:4]])),
                "depth_woba": float(np.mean([row["woba"] for row in summaries[4:]])),
                "power": float(sum(weight * row["power"] for weight, row in zip(ORDER_WEIGHTS, summaries))),
                "discipline": float(sum(weight * row["discipline"] for weight, row in zip(ORDER_WEIGHTS, summaries))),
                "reliability": float(np.mean([row["reliability"] for row in summaries])),
            })
        home, away = sides
        output.append([
            home["woba"] - away["woba"],
            home["top_woba"] - away["top_woba"],
            home["depth_woba"] - away["depth_woba"],
            home["power"] - away["power"],
            home["discipline"] - away["discipline"],
            min(home["reliability"], away["reliability"]),
            home["woba"] + away["woba"],
            home["power"] + away["power"],
        ])
        box = boxes.get(str(game["game_id"]), {})
        for side in ("home", "away"):
            for player in (box.get(side) or {}).get("players", []):
                batting = player.get("batting")
                if not batting or not player.get("player_id"):
                    continue
                game_counts = empty_counts()
                add_counts(game_counts, batting)
                add_counts(career[str(player["player_id"])], batting)
                recent[str(player["player_id"])].append(game_counts)
    return np.asarray(output, float), {
        "contexts": len(contexts), "boxscores": len(boxes),
    }


def main():
    base, _, _, y, years, _, _ = moneyline_matrix()
    starters, _ = starter_matrix()
    games = sorted(read_jsonl(DATA), key=lambda row: (row["date"], row["game_id"]))
    lineup, coverage = lineup_talent_matrix(games)
    margins = np.clip(np.asarray([
        game["home_score"] - game["away_score"] for game in games
    ], float), -8, 8)
    incumbent_x = np.column_stack([base, starters[:, 6:]])
    candidate_x = np.column_stack([incumbent_x, lineup[:, :6]])
    labels, fold_years, incumbent_parts, candidate_parts = [], [], [], []
    for year in sorted(set(years)):
        if year < 2022 or np.sum(years < year) < 4000:
            continue
        train, test = years < year, years == year
        incumbent_parts.extend(
            moneyline_fit(incumbent_x[train], y[train], margins[train]).predict_proba(incumbent_x[test])[:, 1]
        )
        candidate_parts.extend(
            moneyline_fit(candidate_x[train], y[train], margins[train]).predict_proba(candidate_x[test])[:, 1]
        )
        labels.extend(y[test])
        fold_years.extend(years[test])
        print(f"completed lineup talent fold {year}", flush=True)
    labels, fold_years = np.asarray(labels), np.asarray(fold_years)
    incumbent, candidate = np.asarray(incumbent_parts), np.asarray(candidate_parts)
    development = fold_years <= 2024
    matrix = np.column_stack([incumbent, candidate])
    objective = lambda weights: float(np.mean(  # noqa: E731
        (matrix[development] @ weights - labels[development]) ** 2
    ))
    fit = minimize(
        objective, [.5, .5], method="SLSQP", bounds=[(0, 1)] * 2,
        constraints={"type": "eq", "fun": lambda weights: weights.sum() - 1},
    )
    weights = np.clip(fit.x, 0, 1)
    weights /= weights.sum()
    ensemble = matrix @ weights
    report = {
        "research_only": True,
        "coverage": coverage,
        "features": [
            "lineup_woba_advantage", "top_four_woba_advantage",
            "lineup_depth_woba_advantage", "lineup_power_advantage",
            "lineup_discipline_advantage", "lineup_joint_reliability",
        ],
        "selection_period": "2022-2024 rolling-origin",
        "weights": {"incumbent": float(weights[0]), "lineup_candidate": float(weights[1])},
        "development": {
            "incumbent": score(labels[development], incumbent[development]),
            "candidate": score(labels[development], candidate[development]),
            "ensemble": score(labels[development], ensemble[development]),
        },
        "2025": {
            "incumbent": score(labels[fold_years == 2025], incumbent[fold_years == 2025]),
            "candidate": score(labels[fold_years == 2025], candidate[fold_years == 2025]),
            "ensemble": score(labels[fold_years == 2025], ensemble[fold_years == 2025]),
        },
        "2026": {
            "incumbent": score(labels[fold_years == 2026], incumbent[fold_years == 2026]),
            "candidate": score(labels[fold_years == 2026], candidate[fold_years == 2026]),
            "ensemble": score(labels[fold_years == 2026], ensemble[fold_years == 2026]),
        },
    }
    OUTPUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
