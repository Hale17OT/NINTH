"""Leakage-safe starter Statcast shadow experiment.

Every feature for a game is calculated before that game's Statcast line is added
to a pitcher's history.  The Statcast starter identifier must also match MLB's
official starter identifier; bulk relievers are never silently treated as the
starter.
"""
import json
from collections import defaultdict, deque
from pathlib import Path

import numpy as np
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from ml.v2_experiment import DATA, CONTEXTS, extra_trees, logistic, matrix, read_jsonl, score

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "ml" / "data" / "statcast_rich_games.jsonl"
STARTER_CONTEXTS = ROOT / "ml" / "data" / "contexts_v3.jsonl"
OUTPUT = ROOT / "ml" / "artifacts" / "starter_statcast_experiment.json"

RATE_NAMES = ("xwoba", "hard_hit_rate", "barrel_rate", "whiff_rate", "kbb_rate", "avg_velocity")
FEATURE_NAMES = [f"starter_statcast_recent_{name}_advantage" for name in RATE_NAMES]
FEATURE_NAMES += [f"starter_statcast_long_{name}_advantage" for name in RATE_NAMES]
FEATURE_NAMES += ["starter_statcast_joint_reliability", "starter_statcast_start_count_difference"]
BULLPEN_FEATURE_NAMES = [
    "bullpen_recent_run_prevention_advantage",
    "bullpen_long_run_prevention_advantage",
    "bullpen_quality_joint_reliability",
]
PLATOON_FEATURE_NAMES = [
    "platoon_xwoba_advantage", "platoon_woba_advantage",
    "platoon_hard_hit_advantage", "platoon_barrel_advantage",
    "platoon_discipline_advantage", "platoon_joint_reliability",
]


def empty_history():
    return deque(maxlen=15)


def finite(value):
    try:
        result = float(value)
        return result if np.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def weighted(rows, field, weight_field, fallback):
    numerator = denominator = 0.0
    for row in rows:
        value, weight = finite(row.get(field)), finite(row.get(weight_field))
        if value is not None and weight is not None and weight > 0:
            numerator += value * weight
            denominator += weight
    return numerator / denominator if denominator else fallback


def summary(history, limit):
    rows = list(history)[-limit:]
    pa = sum(finite(row.get("plate_appearances")) or 0 for row in rows)
    pitches = sum(finite(row.get("pitches")) or 0 for row in rows)
    balls_in_play = sum(finite(row.get("balls_in_play")) or 0 for row in rows)
    strikeouts = sum(finite(row.get("strikeouts")) or 0 for row in rows)
    walks = sum(finite(row.get("walks")) or 0 for row in rows)
    def shrink(value, prior, sample, stabilization):
        weight = sample / (sample + stabilization)
        return prior + weight * (value - prior)
    return {
        "xwoba": shrink(weighted(rows, "xwoba", "plate_appearances", .320), .320, pa, 100),
        "hard_hit_rate": shrink(weighted(rows, "hard_hit_rate", "balls_in_play", .385), .385, balls_in_play, 80),
        "barrel_rate": shrink(weighted(rows, "barrel_rate", "balls_in_play", .075), .075, balls_in_play, 80),
        "whiff_rate": shrink(weighted(rows, "whiff_rate", "pitches", .105), .105, pitches, 500),
        "kbb_rate": shrink((strikeouts - walks) / pa if pa else .12, .12, pa, 100),
        "avg_velocity": shrink(weighted(rows, "avg_velocity", "pitches", 92.5), 92.5, pitches, 200),
        "starts": len(rows),
        "pitches": pitches,
    }


def advantages(home, away):
    # Lower contact quality allowed is good; higher whiff/K-BB/velocity is good.
    return [
        away["xwoba"] - home["xwoba"],
        away["hard_hit_rate"] - home["hard_hit_rate"],
        away["barrel_rate"] - home["barrel_rate"],
        home["whiff_rate"] - away["whiff_rate"],
        home["kbb_rate"] - away["kbb_rate"],
        home["avg_velocity"] - away["avg_velocity"],
    ]


def starter_matrix():
    games = sorted(read_jsonl(DATA), key=lambda row: (row["date"], row["game_id"]))
    contexts = {str(row["game_id"]): row for row in read_jsonl(STARTER_CONTEXTS if STARTER_CONTEXTS.exists() else CONTEXTS)}
    raw = {str(row["game_id"]): row for row in read_jsonl(RAW)}
    histories = defaultdict(empty_history)
    rows, matched_sides, available_sides, complete_games = [], 0, 0, 0
    for game in games:
        context, current = contexts.get(str(game["game_id"]), {}), raw.get(str(game["game_id"]), {})
        home_id = (context.get("home") or {}).get("starter_id")
        away_id = (context.get("away") or {}).get("starter_id")
        home_history, away_history = histories[str(home_id)], histories[str(away_id)]
        home_recent, away_recent = summary(home_history, 5), summary(away_history, 5)
        home_long, away_long = summary(home_history, 15), summary(away_history, 15)
        reliability = min(1.0, min(home_long["pitches"], away_long["pitches"]) / 750.0)
        rows.append(advantages(home_recent, away_recent) + advantages(home_long, away_long) + [reliability, home_long["starts"] - away_long["starts"]])

        both_match = True
        for side, official_id in (("home_starter", home_id), ("away_starter", away_id)):
            observed = current.get(side)
            if observed:
                available_sides += 1
                observed_id = observed.get("pitcher_id")
                if official_id and str(observed_id) == str(official_id):
                    matched_sides += 1
                else:
                    both_match = False
                # Keep the Statcast identity.  A mismatched bulk pitcher must not
                # contaminate the official starter's record.
                if observed_id:
                    histories[str(observed_id)].append(observed)
            else:
                both_match = False
        complete_games += int(both_match)
    return np.asarray(rows, dtype=float), {
        "raw_games": len(raw),
        "first_raw_date": min((row.get("date") for row in raw.values()), default=None),
        "last_raw_date": max((row.get("date") for row in raw.values()), default=None),
        "available_starter_sides": available_sides,
        "matched_starter_sides": matched_sides,
        "starter_id_match_rate": round(matched_sides / available_sides, 5) if available_sides else 0,
        "games_with_both_starters_matched": complete_games,
    }


def bullpen_matrix():
    """Estimate relief run prevention from only already-completed games.

    Starter earned runs are removed from the opponent final score.  It is an
    intentionally conservative proxy because inherited/unearned-run ownership
    is not reliably available in the historical feed.
    """
    games = sorted(read_jsonl(DATA), key=lambda row: (row["date"], row["game_id"]))
    contexts = {str(row["game_id"]): row for row in read_jsonl(CONTEXTS)}
    histories = defaultdict(lambda: deque(maxlen=20))
    output = []

    def rate(history, limit):
        values = list(history)[-limit:]
        pitches = sum(item[1] for item in values)
        return (100 * sum(item[0] for item in values) / pitches if pitches else 3.4), pitches

    for game in games:
        home_history, away_history = histories[str(game["home_id"])], histories[str(game["away_id"])]
        home_recent, home_recent_pitches = rate(home_history, 5)
        away_recent, away_recent_pitches = rate(away_history, 5)
        home_long, home_long_pitches = rate(home_history, 20)
        away_long, away_long_pitches = rate(away_history, 20)
        output.append([
            away_recent - home_recent,
            away_long - home_long,
            min(1.0, min(home_long_pitches, away_long_pitches) / 1200.0),
        ])
        context = contexts.get(str(game["game_id"]))
        if not context:
            continue
        for side, opponent_score in (("home", game["away_score"]), ("away", game["home_score"])):
            current = context.get(side) or {}
            pitches = finite(current.get("bullpen_pitches")) or 0
            starter_earned = finite(current.get("starter_game_earned_runs")) or 0
            relief_runs = max(0.0, float(opponent_score) - starter_earned)
            if pitches > 0:
                team_id = game["home_id"] if side == "home" else game["away_id"]
                histories[str(team_id)].append((relief_runs, pitches))
    return np.asarray(output, dtype=float)


def platoon_matrix():
    """Rolling team offense versus the confirmed starters' throwing hands."""
    games = sorted(read_jsonl(DATA), key=lambda row: (row["date"], row["game_id"]))
    contexts = {str(row["game_id"]): row for row in read_jsonl(CONTEXTS)}
    raw = {str(row["game_id"]): row for row in read_jsonl(RAW)}
    histories, pitcher_hands = defaultdict(lambda: deque(maxlen=30)), {}
    output = []

    def offense_summary(history):
        rows = list(history)
        pa = sum(finite(row.get("plate_appearances")) or 0 for row in rows)
        strikeouts = sum(finite(row.get("strikeouts")) or 0 for row in rows)
        walks = sum(finite(row.get("walks")) or 0 for row in rows)
        reliability = pa / (pa + 300.0)
        def shrink(value, prior):
            return prior + reliability * (value - prior)
        return {
            "xwoba": shrink(weighted(rows, "xwoba", "plate_appearances", .320), .320),
            "woba": shrink(weighted(rows, "woba", "plate_appearances", .315), .315),
            "hard": shrink(weighted(rows, "hard_hit_rate", "balls_in_play", .385), .385),
            "barrel": shrink(weighted(rows, "barrel_rate", "balls_in_play", .075), .075),
            "discipline": shrink((walks - strikeouts) / pa if pa else -.12, -.12),
            "pa": pa,
        }

    for game in games:
        context, current = contexts.get(str(game["game_id"]), {}), raw.get(str(game["game_id"]), {})
        home_id = (context.get("home") or {}).get("starter_id")
        away_id = (context.get("away") or {}).get("starter_id")

        def confirmed_hand(side, official_id):
            observed = current.get(side) or {}
            if official_id and str(observed.get("pitcher_id")) == str(official_id):
                return observed.get("pitcher_hand") or pitcher_hands.get(str(official_id))
            return pitcher_hands.get(str(official_id))

        home_pitcher_hand = confirmed_hand("home_starter", home_id)
        away_pitcher_hand = confirmed_hand("away_starter", away_id)
        home = offense_summary(histories[(str(game["home_id"]), away_pitcher_hand or "R")])
        away = offense_summary(histories[(str(game["away_id"]), home_pitcher_hand or "R")])
        output.append([
            home["xwoba"] - away["xwoba"], home["woba"] - away["woba"],
            home["hard"] - away["hard"], home["barrel"] - away["barrel"],
            home["discipline"] - away["discipline"], min(1.0, min(home["pa"], away["pa"]) / 750.0),
        ])

        for side in ("home_starter", "away_starter"):
            observed = current.get(side) or {}
            if observed.get("pitcher_id") and observed.get("pitcher_hand"):
                pitcher_hands[str(observed["pitcher_id"])] = observed["pitcher_hand"]
        for side, team_id in (("home", game["home_id"]), ("away", game["away_id"])):
            for hand, suffix in (("L", "left"), ("R", "right")):
                observed = current.get(f"{side}_vs_{suffix}")
                if observed and (finite(observed.get("plate_appearances")) or 0) > 0:
                    histories[(str(team_id), hand)].append(observed)
    return np.asarray(output, dtype=float)


def rolling_predictions(X, y, years, factory):
    probabilities, labels, per_year = [], [], {}
    for year in sorted(set(years)):
        if year < 2022 or np.sum(years < year) < 4000:
            continue
        train, test = years < year, years == year
        probability = factory().fit(X[train], y[train]).predict_proba(X[test])[:, 1]
        probabilities.extend(probability)
        labels.extend(y[test])
        per_year[str(int(year))] = score(y[test], probability)
    return np.asarray(probabilities), np.asarray(labels), per_year


def margin_probability(X, y, margins, train, test, cap=None):
    target = np.clip(margins, -cap, cap) if cap else margins
    regressor = Pipeline([("scale", StandardScaler()), ("ridge", Ridge(alpha=100))]).fit(X[train], target[train])
    fitted_margin = regressor.predict(X[train])
    calibrator = LogisticRegression(C=.1, max_iter=2000).fit(fitted_margin.reshape(-1, 1), y[train])
    return calibrator.predict_proba(regressor.predict(X[test]).reshape(-1, 1))[:, 1]


def rolling_margin_predictions(X, y, years, margins):
    probabilities, labels, per_year = [], [], {}
    for year in sorted(set(years)):
        if year < 2022 or np.sum(years < year) < 4000:
            continue
        train, test = years < year, years == year
        probability = margin_probability(X, y, margins, train, test)
        probabilities.extend(probability); labels.extend(y[test])
        per_year[str(int(year))] = score(y[test], probability)
    return np.asarray(probabilities), np.asarray(labels), per_year


def main():
    base, v2, _, y, years, context_count, _ = matrix()
    games = sorted(read_jsonl(DATA), key=lambda row: (row["date"], row["game_id"]))
    margins = np.asarray([float(game["home_score"] - game["away_score"]) for game in games])
    starter, coverage = starter_matrix()
    bullpen = bullpen_matrix()
    platoon = platoon_matrix()
    if coverage["raw_games"] < 13000 or (coverage.get("last_raw_date") or "") < "2026-07-12":
        raise SystemExit(f"starter Statcast backfill incomplete: {coverage['raw_games']} games")
    if len(starter) != len(base):
        raise SystemExit(f"matrix alignment failed: {len(starter)} != {len(base)}")
    lean = np.delete(v2, [1, 3], axis=1)
    sets = {
        "lean": np.column_stack([base, lean]),
        "lean_starter_recent": np.column_stack([base, lean, starter[:, :6], starter[:, 12:]]),
        "lean_starter_long": np.column_stack([base, lean, starter[:, 6:]]),
        "lean_starter_full": np.column_stack([base, lean, starter]),
        "lean_platoon": np.column_stack([base, lean, platoon]),
        "lean_starter_platoon": np.column_stack([base, lean, starter, platoon]),
    }
    results, predictions, labels = {}, {}, {}
    for feature_set, X in sets.items():
        for model_name, factory in (("calibrated", lambda: logistic(.35, True)), ("extra", extra_trees)):
            key = f"{feature_set}_{model_name}"
            probability, actual, per_year = rolling_predictions(X, y, years, factory)
            predictions[key], labels[key] = probability, actual
            results[key] = {"aggregate": score(actual, probability), "per_year": per_year}
            print(key, results[key]["aggregate"], flush=True)
        key = f"{feature_set}_margin"
        probability, actual, per_year = rolling_margin_predictions(X, y, years, margins)
        predictions[key], labels[key] = probability, actual
        results[key] = {"aggregate": score(actual, probability), "per_year": per_year}
        print(key, results[key]["aggregate"], flush=True)
        left, right = f"{feature_set}_calibrated", f"{feature_set}_extra"
        for weight in (.8, .7, .6, .55, .5):
            key = f"{feature_set}_blend_{round(weight*100)}_{round((1-weight)*100)}"
            probability = weight * predictions[left] + (1 - weight) * predictions[right]
            results[key] = {"aggregate": score(labels[left], probability), "components": [left, right], "left_weight": weight}
            print(key, results[key]["aggregate"], flush=True)
    report = {
        "status": "shadow_only",
        "policy": "Features are strictly pregame rolling histories; no production write.",
        "context_games": context_count,
        "coverage": coverage,
        "starter_statcast_features": FEATURE_NAMES,
        "bullpen_features": BULLPEN_FEATURE_NAMES,
        "platoon_features": PLATOON_FEATURE_NAMES,
        "results": results,
    }
    OUTPUT.write_text(json.dumps(report, indent=2), encoding="utf8")


if __name__ == "__main__":
    main()
