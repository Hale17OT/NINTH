"""Train and audit the market-free NINTH total-runs distribution model."""
import json
import os
from pathlib import Path

import joblib
import numpy as np
from scipy.stats import nbinom, poisson
from sklearn.ensemble import ExtraTreesClassifier, ExtraTreesRegressor, HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.linear_model import LogisticRegression, PoissonRegressor, Ridge
from sklearn.metrics import brier_score_loss, mean_absolute_error, mean_squared_error
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from ml.totals_features import (
    TOTAL_FEATURE_NAMES, apply_totals_result, fresh_totals_state, reset_totals_season,
    serializable_totals_state, totals_features,
)
from ml.totals_modeling import CountDistributionTotalsModel, FeatureSubsetTotalsModel, TeamRunDistributionTotalsModel, TotalsModelBlend, TotalsProbabilityModel

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "ml" / "data" / "games.jsonl"
CONTEXTS = ROOT / "ml" / "data" / "contexts_v3.jsonl"
ARTIFACTS = Path(os.getenv("NINTH_ARTIFACT_DIR", ROOT / "ml" / "artifacts"))
LINES = [6.5, 7.5, 8.5, 9.5, 10.5, 11.5]
DECISION_LINES = [7.5, 8.5, 9.5, 10.5]


def read_jsonl(path):
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]


def matrix():
    games = sorted(read_jsonl(DATA), key=lambda row: (row["date"], row["game_id"]))
    contexts = {str(row["game_id"]): row for row in read_jsonl(CONTEXTS)}
    state, current = fresh_totals_state(), None
    rows, targets, years, dates = [], [], [], []
    for game in games:
        if game["season"] != current:
            if current is not None:
                reset_totals_season(state)
            current = game["season"]
        context = contexts.get(str(game["game_id"]))
        rows.append(totals_features(state, game["home_id"], game["away_id"], game["date"], context))
        targets.append(int(game["home_score"]) + int(game["away_score"]))
        years.append(int(game["season"])); dates.append(game["date"])
        apply_totals_result(state, game, context)
    return games, np.asarray(rows, float), np.asarray(targets, int), np.asarray(years, int), dates, state, len(contexts)


def classifier(kind):
    if kind == "logistic":
        return Pipeline([("scale", StandardScaler()), ("model", LogisticRegression(C=.06, max_iter=3000))])
    if kind == "histogram":
        return HistGradientBoostingClassifier(
        learning_rate=.035, max_iter=180, max_leaf_nodes=11, min_samples_leaf=120,
        l2_regularization=12, random_state=42,
        )
    return ExtraTreesClassifier(n_estimators=350, min_samples_leaf=100, max_features=.8, n_jobs=-1, random_state=42)


def regressor(kind):
    if kind == "ridge":
        return Pipeline([("scale", StandardScaler()), ("model", Ridge(alpha=120))])
    if kind == "poisson":
        return Pipeline([("scale", StandardScaler()), ("model", PoissonRegressor(alpha=2.0, max_iter=1000))])
    if kind == "histogram":
        return HistGradientBoostingRegressor(
        loss="poisson", learning_rate=.035, max_iter=200, max_leaf_nodes=11,
        min_samples_leaf=120, l2_regularization=12, random_state=42,
        )
    return ExtraTreesRegressor(n_estimators=400, min_samples_leaf=80, max_features=.8, n_jobs=-1, random_state=42)


def brier_summary(actual, probability):
    per_line = {}
    scores = []
    for index, line in enumerate(LINES):
        value = float(brier_score_loss(actual[:, index], probability[:, index]))
        per_line[str(line)] = round(value, 5); scores.append(value)
    return {"mean_brier": round(float(np.mean(scores)), 5), "per_line": per_line}


def recommend(probability, actual):
    indexes = [LINES.index(line) for line in DECISION_LINES]
    p = probability[:, indexes]
    side_p = np.maximum(p, 1 - p)
    chosen = np.argmax(side_p, axis=1)
    row = np.arange(len(p)); selected_p = side_p[row, chosen]
    over = p[row, chosen] >= .5
    selected_actual = np.where(over, actual[:, indexes][row, chosen], 1 - actual[:, indexes][row, chosen])
    return {
        "games": int(len(selected_p)), "accuracy": round(float(np.mean(selected_actual)), 5),
        "brier_score": round(float(np.mean((selected_p - selected_actual) ** 2)), 5),
        "mean_probability": round(float(np.mean(selected_p)), 5),
        "line_counts": {str(line): int(np.sum(np.asarray(DECISION_LINES)[chosen] == line)) for line in DECISION_LINES},
    }


def main():
    games, X, total, years, dates, final_state, context_count = matrix()
    actual = np.column_stack([total > line for line in LINES]).astype(int)
    folds = [year for year in sorted(set(years)) if year >= 2022 and np.sum(years < year) >= 4000]
    candidates = {kind: [] for kind in ("logistic", "histogram", "extra_trees", "poisson_distribution", "negative_binomial", "legacy_negative_binomial", "team_poisson", "team_negative_binomial")}
    baselines, fold_actual, fold_years = [], [], []
    regression_candidates = {kind: [] for kind in ("ridge", "poisson", "histogram", "extra_trees")}
    regression_actual = []
    for year in folds:
        train, test = years < year, years == year
        fold_actual.append(actual[test]); fold_years.extend([year] * int(np.sum(test))); regression_actual.extend(total[test])
        baselines.append(np.tile(np.mean(actual[train], axis=0), (int(np.sum(test)), 1)))
        for kind in ("logistic", "histogram", "extra_trees"):
            probability = []
            for index, line in enumerate(LINES):
                fitted = classifier(kind).fit(X[train], actual[train, index])
                probability.append(fitted.predict_proba(X[test])[:, 1])
            candidates[kind].append(np.column_stack(probability))
        count_mean_model = regressor("poisson").fit(X[train], total[train])
        count_mean = np.clip(count_mean_model.predict(X[test]), .1, 30)
        candidates["poisson_distribution"].append(np.column_stack([poisson.sf(int(line), count_mean) for line in LINES]))
        train_mean = np.clip(count_mean_model.predict(X[train]), .1, 30)
        pearson = np.mean(((total[train] - train_mean) ** 2 - train_mean) / np.maximum(train_mean ** 2, 1e-6))
        alpha = float(np.clip(pearson, .01, 1.0)); size = 1 / alpha
        candidates["negative_binomial"].append(np.column_stack([nbinom.sf(int(line), size, size / (size + count_mean)) for line in LINES]))
        legacy_mean_model = regressor("poisson").fit(X[train, :21], total[train])
        legacy_mean = np.clip(legacy_mean_model.predict(X[test, :21]), .1, 30); legacy_train_mean = np.clip(legacy_mean_model.predict(X[train, :21]), .1, 30)
        legacy_alpha = float(np.clip(np.mean(((total[train]-legacy_train_mean)**2-legacy_train_mean)/np.maximum(legacy_train_mean**2, 1e-6)), .01, 1.0)); legacy_size = 1/legacy_alpha
        candidates["legacy_negative_binomial"].append(np.column_stack([nbinom.sf(int(line), legacy_size, legacy_size/(legacy_size+legacy_mean)) for line in LINES]))
        home_model = regressor("poisson").fit(X[train], np.asarray([game["home_score"] for game in games])[train])
        away_model = regressor("poisson").fit(X[train], np.asarray([game["away_score"] for game in games])[train])
        team_mean = np.clip(home_model.predict(X[test]), .1, 20) + np.clip(away_model.predict(X[test]), .1, 20)
        candidates["team_poisson"].append(np.column_stack([poisson.sf(int(line), team_mean) for line in LINES]))
        team_train_mean = np.clip(home_model.predict(X[train]), .1, 20) + np.clip(away_model.predict(X[train]), .1, 20)
        team_alpha = float(np.clip(np.mean(((total[train] - team_train_mean) ** 2 - team_train_mean) / np.maximum(team_train_mean ** 2, 1e-6)), .01, 1.0)); team_size = 1 / team_alpha
        candidates["team_negative_binomial"].append(np.column_stack([nbinom.sf(int(line), team_size, team_size / (team_size + team_mean)) for line in LINES]))
        for kind in regression_candidates:
            fitted = regressor(kind).fit(X[train], total[train])
            regression_candidates[kind].extend(fitted.predict(X[test]))
        print(f"completed rolling-origin {year}", flush=True)
    y_oof = np.vstack(fold_actual); baseline = np.vstack(baselines); fold_years = np.asarray(fold_years)
    development = fold_years <= 2024
    blend_scores = []
    count_all = np.vstack(candidates["legacy_negative_binomial"]); logistic_all = np.vstack(candidates["logistic"])
    for count_weight in np.arange(.5, 1.01, .05):
        probability = count_weight * count_all + (1-count_weight) * logistic_all
        blend_scores.append((float(np.mean([(probability[development, index]-y_oof[development, index])**2 for index in range(len(LINES))])), float(count_weight)))
    _, count_blend_weight = min(blend_scores)
    candidates["count_logistic_blend"] = [count_blend_weight*count + (1-count_blend_weight)*direct for count, direct in zip(candidates["legacy_negative_binomial"], candidates["logistic"])]
    team_all = np.vstack(candidates["team_negative_binomial"]); team_blend_scores = []
    for count_weight in np.arange(.5, 1.01, .05):
        probability = count_weight*count_all + (1-count_weight)*team_all
        team_blend_scores.append((float(np.mean((probability[development]-y_oof[development])**2)), float(count_weight)))
    _, count_team_weight = min(team_blend_scores)
    candidates["count_team_blend"] = [count_team_weight*count + (1-count_team_weight)*team for count, team in zip(candidates["legacy_negative_binomial"], candidates["team_negative_binomial"])]
    candidate_report = {}
    for kind, parts in candidates.items():
        probability = np.vstack(parts)
        candidate_report[kind] = {
            "development": brier_summary(y_oof[development], probability[development]),
            "unseen_2025_2026": brier_summary(y_oof[~development], probability[~development]),
            "all_walk_forward": brier_summary(y_oof, probability),
        }
    selected = min(candidate_report, key=lambda key: candidate_report[key]["development"]["mean_brier"])
    selected_probability = np.vstack(candidates[selected])
    regression_actual = np.asarray(regression_actual)
    regression_report = {}
    for kind, predicted in regression_candidates.items():
        predicted = np.asarray(predicted)
        regression_report[kind] = {
            "development_mae": round(float(mean_absolute_error(regression_actual[development], predicted[development])), 5),
            "unseen_2025_2026_mae": round(float(mean_absolute_error(regression_actual[~development], predicted[~development])), 5),
            "unseen_2025_2026_rmse": round(float(mean_squared_error(regression_actual[~development], predicted[~development]) ** .5), 5),
        }
    selected_regressor = min(regression_report, key=lambda key: regression_report[key]["development_mae"])
    selected_mean_oof = np.asarray(regression_candidates[selected_regressor])
    residuals = regression_actual - selected_mean_oof
    baseline_unseen = brier_summary(y_oof[~development], baseline[~development])
    unseen = brier_summary(y_oof[~development], selected_probability[~development])
    per_year = {}
    for year in folds:
        mask = fold_years == year
        per_year[str(year)] = brier_summary(y_oof[mask], selected_probability[mask])
        per_year[str(year)]["recommended"] = recommend(selected_probability[mask], y_oof[mask])
    mean_model = regressor(selected_regressor).fit(X, total)
    team_residual_correlation = None
    if selected == "count_team_blend":
        legacy_mean_model = regressor("poisson").fit(X[:, :21], total); legacy_mean = np.clip(legacy_mean_model.predict(X[:, :21]), .1, 30)
        legacy_dispersion = float(np.clip(np.mean(((total-legacy_mean)**2-legacy_mean)/np.maximum(legacy_mean**2, 1e-6)), .01, 1.0))
        legacy_model = FeatureSubsetTotalsModel(CountDistributionTotalsModel(legacy_mean_model, LINES, "negative_binomial", legacy_dispersion), range(21))
        home_target=np.asarray([game["home_score"] for game in games]);away_target=np.asarray([game["away_score"] for game in games])
        home_model=regressor("poisson").fit(X,home_target);away_model=regressor("poisson").fit(X,away_target);team_mean=np.clip(home_model.predict(X),.1,20)+np.clip(away_model.predict(X),.1,20)
        team_dispersion=float(np.clip(np.mean(((total-team_mean)**2-team_mean)/np.maximum(team_mean**2,1e-6)),.01,1.0));team_model=TeamRunDistributionTotalsModel(home_model,away_model,LINES,"negative_binomial",team_dispersion)
        model=TotalsModelBlend([legacy_model,team_model],[count_team_weight,1-count_team_weight])
    elif selected == "count_logistic_blend":
        distribution_mean_model = regressor("poisson").fit(X[:, :21], total)
        fitted_mean = np.clip(distribution_mean_model.predict(X[:, :21]), .1, 30)
        dispersion = float(np.clip(np.mean(((total - fitted_mean) ** 2 - fitted_mean) / np.maximum(fitted_mean ** 2, 1e-6)), .01, 1.0))
        count_model = FeatureSubsetTotalsModel(CountDistributionTotalsModel(distribution_mean_model, LINES, "negative_binomial", dispersion), range(21))
        direct_mean_model = regressor(selected_regressor).fit(X, total)
        line_models = {str(line): classifier("logistic").fit(X, actual[:, index]) for index, line in enumerate(LINES)}
        direct_model = TotalsProbabilityModel(direct_mean_model, line_models, LINES)
        model = TotalsModelBlend([count_model, direct_model], [count_blend_weight, 1-count_blend_weight])
    elif selected == "legacy_negative_binomial":
        legacy_mean_model = regressor("poisson").fit(X[:, :21], total); fitted_mean = np.clip(legacy_mean_model.predict(X[:, :21]), .1, 30)
        dispersion = float(np.clip(np.mean(((total-fitted_mean)**2-fitted_mean)/np.maximum(fitted_mean**2, 1e-6)), .01, 1.0))
        model = FeatureSubsetTotalsModel(CountDistributionTotalsModel(legacy_mean_model, LINES, "negative_binomial", dispersion), range(21))
    elif selected in ("team_poisson", "team_negative_binomial"):
        home_target = np.asarray([game["home_score"] for game in games])
        away_target = np.asarray([game["away_score"] for game in games])
        home_model = regressor("poisson").fit(X, home_target); away_model = regressor("poisson").fit(X, away_target)
        home_mean = np.clip(home_model.predict(X), .1, 20); away_mean = np.clip(away_model.predict(X), .1, 20)
        fitted_mean = home_mean + away_mean
        dispersion = float(np.clip(np.mean(((total - fitted_mean) ** 2 - fitted_mean) / np.maximum(fitted_mean ** 2, 1e-6)), .01, 1.0))
        team_residual_correlation = float(np.corrcoef(home_target-home_mean, away_target-away_mean)[0, 1])
        model = TeamRunDistributionTotalsModel(home_model, away_model, LINES, "poisson" if selected == "team_poisson" else "negative_binomial", dispersion)
    elif selected in ("poisson_distribution", "negative_binomial"):
        distribution_mean_model = regressor("poisson").fit(X, total)
        fitted_mean = np.clip(distribution_mean_model.predict(X), .1, 30)
        dispersion = float(np.clip(np.mean(((total - fitted_mean) ** 2 - fitted_mean) / np.maximum(fitted_mean ** 2, 1e-6)), .01, 1.0))
        model = CountDistributionTotalsModel(distribution_mean_model, LINES, "poisson" if selected == "poisson_distribution" else "negative_binomial", dispersion)
    else:
        line_models = {str(line): classifier(selected).fit(X, actual[:, index]) for index, line in enumerate(LINES)}
        model = TotalsProbabilityModel(mean_model, line_models, LINES)
    report = {
        "model": "market_free_team_run_distribution_v2", "status": "promoted",
        "selection_policy": "Architecture selected on 2022-2024 rolling-origin folds; 2025-2026 remained unseen until the final audit.",
        "market_inputs": False, "training_games": len(games), "context_games": context_count,
        "trained_through_date": games[-1]["date"], "features": TOTAL_FEATURE_NAMES,
        "candidate_models": candidate_report, "selected_classifier": selected,
        "count_blend_weight": round(count_blend_weight, 2),
        "count_team_weight": round(count_team_weight, 2),
        "team_residual_correlation": None if team_residual_correlation is None else round(team_residual_correlation, 5),
        "regression_models": regression_report, "selected_regressor": selected_regressor,
        "lines": LINES, "decision_lines": DECISION_LINES, "unseen_2025_2026": unseen,
        "unseen_baseline": baseline_unseen,
        "unseen_brier_skill": round(1 - unseen["mean_brier"] / baseline_unseen["mean_brier"], 5),
        "unseen_recommended": recommend(selected_probability[~development], y_oof[~development]),
        "prediction_interval_residuals": {
            "lower_80": round(float(np.quantile(residuals, .10)), 3),
            "upper_80": round(float(np.quantile(residuals, .90)), 3),
        },
        "walk_forward": brier_summary(y_oof, selected_probability), "per_year": per_year,
        "research_basis": [
            "Count-distribution baselines (Poisson and overdispersion-aware alternatives)",
            "Full-distribution validation rather than mean-score accuracy alone",
            "Chronological rolling-origin evaluation and explicit leakage prevention",
            "Direct threshold probabilities scored with Brier loss",
        ],
    }
    bundle = {
        "model_version": 2, "model": model, "state": serializable_totals_state(final_state),
        "trained_through_date": games[-1]["date"], "features": TOTAL_FEATURE_NAMES,
        "feature_reference": np.median(X, axis=0).tolist(), "report": report,
    }
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    joblib.dump(bundle, ARTIFACTS / "totals.joblib")
    (ARTIFACTS / "totals_report.json").write_text(json.dumps(report, indent=2), encoding="utf8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
