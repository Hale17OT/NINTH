"""Leakage-safe shadow experiments for improving NINTH moneyline accuracy.

Every candidate is trained only on seasons preceding its test season. Results
are diagnostic and never overwrite the production artifact.
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
from lightgbm import LGBMClassifier
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import ExtraTreesClassifier, HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, brier_score_loss, log_loss, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import SplineTransformer, StandardScaler

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ml.features import FEATURE_NAMES, apply_result, fresh_state, matchup_features, reset_season_records

DATA = ROOT / "ml" / "data" / "games.jsonl"
CONTEXTS = ROOT / "ml" / "data" / "contexts.jsonl"
STATCAST = ROOT / "ml" / "data" / "statcast_contexts.jsonl"
OUTPUT = ROOT / "ml" / "artifacts" / "accuracy_experiments.json"
STATCAST_FEATURES = [
    "statcast_xwoba_difference", "statcast_xwoba_allowed_advantage",
    "statcast_hard_hit_difference", "statcast_barrel_difference",
    "statcast_pitching_whiff_difference", "statcast_velocity_difference",
    "statcast_available",
]
STRUCTURAL_FEATURES = [
    "season_progress", "shrunk_season_win_pct_difference",
    "shrunk_pythagorean_difference", "shrunk_home_away_split_difference",
    "early_season_elo_interaction", "mature_season_form_interaction",
    "margin_elo_difference", "ewma_run_matchup_advantage",
]
LEAN_CORE_REMOVE = {"last_10_win_pct_difference", "home_away_split_difference", "context_available"}
LEAN_EXTENDED_REMOVE = LEAN_CORE_REMOVE | {"last_5_win_pct_difference", "rolling_runs_scored_difference", "rest_days_difference", "starter_era_difference", "bullpen_3day_pitches_difference"}


def calibrated_logistic(c=.35):
    base = Pipeline([("scale", StandardScaler()), ("model", LogisticRegression(C=c, max_iter=4000))])
    return CalibratedClassifierCV(base, method="sigmoid", cv=5)


def plain_logistic(c=.1):
    return Pipeline([("scale", StandardScaler()), ("model", LogisticRegression(C=c, max_iter=4000))])


def spline_logistic(c=.1):
    return Pipeline([
        ("spline", SplineTransformer(n_knots=4, degree=2, include_bias=False)),
        ("scale", StandardScaler()),
        ("model", LogisticRegression(C=c, max_iter=5000)),
    ])


def lightgbm():
    return LGBMClassifier(
        n_estimators=400, learning_rate=.02, num_leaves=9, max_depth=4,
        min_child_samples=100, subsample=.85, colsample_bytree=.8,
        reg_alpha=1.5, reg_lambda=5, random_state=42, n_jobs=-1, verbosity=-1,
    )


def candidates():
    return {
        "calibrated_logistic": (lambda: calibrated_logistic(.35), "base"),
        "logistic_c0.03": (lambda: plain_logistic(.03), "base"),
        "logistic_c0.1": (lambda: plain_logistic(.1), "base"),
        "recent2_calibrated": (lambda: calibrated_logistic(.35), "base"),
        "recent3_calibrated": (lambda: calibrated_logistic(.35), "base"),
        "recent2_logistic": (lambda: plain_logistic(.03), "base"),
        "lean_core_logistic": (lambda: plain_logistic(.03), "lean_core"),
        "lean_extended_logistic": (lambda: plain_logistic(.03), "lean_extended"),
        "lean_core_calibrated": (lambda: calibrated_logistic(.35), "lean_core"),
        "structural_logistic": (lambda: plain_logistic(.03), "structural"),
        "structural_calibrated": (lambda: calibrated_logistic(.35), "structural"),
        "lean_structural_calibrated": (lambda: calibrated_logistic(.35), "lean_structural"),
        "rating_logistic": (lambda: plain_logistic(.03), "rating"),
        "rating_calibrated": (lambda: calibrated_logistic(.35), "rating"),
        "lean_rating_calibrated": (lambda: calibrated_logistic(.35), "lean_rating"),
        "spline_logistic_c0.03": (lambda: spline_logistic(.03), "base"),
        "spline_logistic_c0.1": (lambda: spline_logistic(.1), "base"),
        "hist_gradient": (lambda: HistGradientBoostingClassifier(max_iter=300, learning_rate=.035, max_leaf_nodes=12, min_samples_leaf=80, l2_regularization=3, random_state=42), "base"),
        "extra_trees": (lambda: ExtraTreesClassifier(n_estimators=500, min_samples_leaf=35, max_features=.7, class_weight="balanced", n_jobs=-1, random_state=42), "base"),
        "lightgbm": (lightgbm, "base"),
        "statcast_logistic": (lambda: calibrated_logistic(.2), "statcast"),
        "statcast_spline": (lambda: spline_logistic(.03), "statcast"),
        "statcast_hist_gradient": (lambda: HistGradientBoostingClassifier(max_iter=300, learning_rate=.035, max_leaf_nodes=12, min_samples_leaf=80, l2_regularization=3, random_state=42), "statcast"),
        "statcast_extra_trees": (lambda: ExtraTreesClassifier(n_estimators=500, min_samples_leaf=35, max_features=.7, class_weight="balanced", n_jobs=-1, random_state=42), "statcast"),
        "statcast_lightgbm": (lightgbm, "statcast"),
    }


def read_jsonl(path):
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]


def rating_default():
    return {"elo":1500.0,"offense":4.5,"defense":4.5}


def matrix():
    games = sorted(read_jsonl(DATA), key=lambda row: (row["date"], row["game_id"]))
    contexts = {str(row["game_id"]): row for row in read_jsonl(CONTEXTS)}
    statcast = {str(row["game_id"]): row for row in read_jsonl(STATCAST)}
    state, ratings, base_rows, statcast_rows, structural_rows, labels, seasons, current = fresh_state(), defaultdict(rating_default), [], [], [], [], [], None
    for game in games:
        if game["season"] != current:
            if current is not None:
                reset_season_records(state)
                for rating in ratings.values():
                    rating["offense"] = .5 * rating["offense"] + 2.25
                    rating["defense"] = .5 * rating["defense"] + 2.25
            current = game["season"]
        context = contexts.get(str(game["game_id"]))
        base = matchup_features(state, game["home_id"], game["away_id"], game["date"], {**context, "context_available": 1} if context else None)
        base_rows.append(base)
        home, away = state["teams"][str(game["home_id"])], state["teams"][str(game["away_id"])]
        progress = min(1.0, (home["games"] + away["games"]) / 324.0)
        shrunk_win = (home["wins"] + 10) / (home["games"] + 20) - (away["wins"] + 10) / (away["games"] + 20)
        exponent = 1.83
        def shrunk_pythagorean(team):
            scored, allowed = team["runs_for_total"] + 90, team["runs_allowed_total"] + 90
            return scored ** exponent / (scored ** exponent + allowed ** exponent)
        shrunk_pythag = shrunk_pythagorean(home) - shrunk_pythagorean(away)
        shrunk_split = (home["home_wins"] + 5) / (home["home_games"] + 10) - (away["away_wins"] + 5) / (away["away_games"] + 10)
        home_rating,away_rating=ratings[str(game["home_id"])],ratings[str(game["away_id"])]
        run_matchup=.5*(home_rating["offense"]+away_rating["defense"])-.5*(away_rating["offense"]+home_rating["defense"])
        structural_rows.append([progress, shrunk_win, shrunk_pythag, shrunk_split, base[0] * (1 - progress), base[3] * progress,(home_rating["elo"]+35)-away_rating["elo"],run_matchup])
        stat = statcast.get(str(game["game_id"]), {})
        statcast_rows.append([float(stat.get(name, 0) or 0) for name in STATCAST_FEATURES[:-1]] + [float(bool(stat))])
        labels.append(int(game["home_score"] > game["away_score"]))
        seasons.append(game["season"])
        apply_result(state, game, context)
        home_score,away_score=int(game["home_score"]),int(game["away_score"]);home_win=int(home_score>away_score)
        expected=1/(1+10**((away_rating["elo"]-(home_rating["elo"]+35))/400));winner_gap=(home_rating["elo"]-away_rating["elo"])*(1 if home_win else -1)
        multiplier=np.log1p(abs(home_score-away_score))*(2.2/(winner_gap*.001+2.2));change=18*multiplier*(home_win-expected);home_rating["elo"]+=change;away_rating["elo"]-=change
        alpha=.08;home_rating["offense"]=(1-alpha)*home_rating["offense"]+alpha*home_score;home_rating["defense"]=(1-alpha)*home_rating["defense"]+alpha*away_score;away_rating["offense"]=(1-alpha)*away_rating["offense"]+alpha*away_score;away_rating["defense"]=(1-alpha)*away_rating["defense"]+alpha*home_score
    return np.asarray(base_rows, float), np.asarray(statcast_rows, float), np.asarray(structural_rows, float), np.asarray(labels), np.asarray(seasons), len(statcast)


def score(y, probability):
    prediction = probability >= .5
    qualified = (probability >= .6) | (probability <= .4)
    return {
        "games": int(len(y)),
        "accuracy": round(float(accuracy_score(y, prediction)), 5),
        "log_loss": round(float(log_loss(y, probability)), 5),
        "brier_score": round(float(brier_score_loss(y, probability)), 5),
        "roc_auc": round(float(roc_auc_score(y, probability)), 5),
        "qualified_games": int(qualified.sum()),
        "qualified_coverage": round(float(qualified.mean()), 5),
        "qualified_accuracy": round(float((prediction[qualified] == y[qualified]).mean()), 5) if qualified.any() else None,
    }


def main():
    base, statcast, structural, y, years, statcast_games = matrix()
    full = np.column_stack([base, statcast])
    structural_full = np.column_stack([base, structural])
    evaluation_years = [int(year) for year in sorted(set(years)) if year >= 2022 and np.sum(years < year) >= 4000]
    results, prediction_store, labels_store = {}, {}, None
    for name, (factory, feature_set) in candidates().items():
        fold_probabilities, fold_labels, per_year = [], [], {}
        if feature_set == "statcast":
            X = full
        elif feature_set == "lean_core":
            X = base[:, [index for index,name in enumerate(FEATURE_NAMES) if name not in LEAN_CORE_REMOVE]]
        elif feature_set == "lean_extended":
            X = base[:, [index for index,name in enumerate(FEATURE_NAMES) if name not in LEAN_EXTENDED_REMOVE]]
        elif feature_set == "structural":
            X = structural_full
        elif feature_set == "lean_structural":
            X = np.column_stack([base[:, [index for index,name in enumerate(FEATURE_NAMES) if name not in LEAN_CORE_REMOVE]], structural])
        elif feature_set == "rating":
            X = np.column_stack([base, structural[:, -2:]])
        elif feature_set == "lean_rating":
            X = np.column_stack([base[:, [index for index,name in enumerate(FEATURE_NAMES) if name not in LEAN_CORE_REMOVE]], structural[:, -2:]])
        else:
            X = base
        for year in evaluation_years:
            train, test = years < year, years == year
            fit_mask = train
            if name.startswith("recent2"):
                fit_mask = train & (years >= year - 2)
            elif name.startswith("recent3"):
                fit_mask = train & (years >= year - 3)
            model = factory().fit(X[fit_mask], y[fit_mask])
            probability = model.predict_proba(X[test])[:, 1]
            fold_probabilities.extend(probability.tolist())
            fold_labels.extend(y[test].tolist())
            per_year[str(year)] = score(y[test], probability)
        results[name] = {"aggregate": score(np.asarray(fold_labels), np.asarray(fold_probabilities)), "per_year": per_year, "feature_set": feature_set}
        prediction_store[name] = np.asarray(fold_probabilities)
        if labels_store is None:
            labels_store = np.asarray(fold_labels)
        print(name, results[name]["aggregate"], flush=True)
    blends = {
        "blend_logistic90_extra10": ("logistic_c0.03", "extra_trees", .9),
        "blend_logistic80_extra20": ("logistic_c0.03", "extra_trees", .8),
        "blend_logistic70_extra30": ("logistic_c0.03", "extra_trees", .7),
        "blend_logistic90_lgbm10": ("logistic_c0.03", "lightgbm", .9),
        "blend_logistic80_lgbm20": ("logistic_c0.03", "lightgbm", .8),
        "blend_logistic70_lgbm30": ("logistic_c0.03", "lightgbm", .7),
        "blend_statcast90_extra10": ("statcast_logistic", "statcast_extra_trees", .9),
        "blend_statcast80_extra20": ("statcast_logistic", "statcast_extra_trees", .8),
        "blend_statcast70_extra30": ("statcast_logistic", "statcast_extra_trees", .7),
        "blend_statcast90_lgbm10": ("statcast_logistic", "statcast_lightgbm", .9),
        "blend_statcast80_lgbm20": ("statcast_logistic", "statcast_lightgbm", .8),
        "blend_statcast70_lgbm30": ("statcast_logistic", "statcast_lightgbm", .7),
    }
    for name, (left, right, weight) in blends.items():
        probability = weight * prediction_store[left] + (1 - weight) * prediction_store[right]
        results[name] = {"aggregate": score(labels_store, probability), "feature_set": "blend", "components": [left, right], "left_weight": weight}
        print(name, results[name]["aggregate"], flush=True)
    report = {
        "status": "shadow_only",
        "policy": "Rolling-origin seasons; experiments never overwrite production.",
        "evaluation_years": evaluation_years,
        "base_features": FEATURE_NAMES,
        "statcast_features": STATCAST_FEATURES,
        "structural_features": STRUCTURAL_FEATURES,
        "statcast_context_games": statcast_games,
        "results": results,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
