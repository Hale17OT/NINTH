"""Development-only search for a better calibrated moneyline margin model."""
import json
from pathlib import Path

import numpy as np
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from ml.modeling import MarginProbabilityModel
from ml.accuracy_experiments import matrix as structural_matrix
from ml.starter_statcast_experiment import starter_matrix
from ml.v2_experiment import DATA, matrix, score
from ml.starter_statcast_experiment import read_jsonl

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "ml" / "artifacts" / "moneyline_v5_tuning.json"


def transformed_margin(margins, kind, cap):
    clipped = np.clip(margins, -cap, cap)
    if kind == "log1p":
        return np.sign(clipped) * np.log1p(np.abs(clipped))
    if kind == "sqrt":
        return np.sign(clipped) * np.sqrt(np.abs(clipped))
    return clipped


def probability(X_train, y_train, margins_train, X_test, alpha, cap, kind, c, sample_weight=None):
    regressor = Pipeline([("scale", StandardScaler()), ("ridge", Ridge(alpha=alpha))])
    target = transformed_margin(margins_train, kind, cap)
    regressor.fit(X_train, target, ridge__sample_weight=sample_weight)
    fitted = regressor.predict(X_train)
    calibrator = LogisticRegression(C=c, max_iter=2000).fit(fitted.reshape(-1, 1), y_train, sample_weight=sample_weight)
    return MarginProbabilityModel(regressor, calibrator).predict_proba(X_test)[:, 1]


def main():
    base, _, _, y, years, _, _ = matrix(); starter, _ = starter_matrix()
    _, _, structural, _, _, _ = structural_matrix()
    feature_sets = {"current": np.column_stack([base, starter[:, 6:]]), "structural": np.column_stack([base, starter[:, 6:], structural])}
    games = sorted(read_jsonl(DATA), key=lambda row: (row["date"], row["game_id"]))
    margins = np.asarray([game["home_score"] - game["away_score"] for game in games], float)
    configs = []
    for alpha in (30, 60, 100, 180, 300):
        for cap in (4, 6, 8, 12):
            for kind in ("linear", "log1p", "sqrt"):
                for c in (.03, .1, .3):
                    configs.append((alpha, cap, kind, c, "all", "current"))
                    configs.append((alpha, cap, kind, c, "all", "structural"))
    # Recency challengers are deliberately narrower to keep the search stable.
    for window in (4, 5, 6):
        for alpha in (60, 100, 180):
            configs.append((alpha, 8, "linear", .1, f"recent{window}", "current"))
            configs.append((alpha, 8, "linear", .1, f"recent{window}", "structural"))
    development_years = (2022, 2023, 2024)
    results = []
    for config_index, (alpha, cap, kind, c, window, feature_set) in enumerate(configs):
        X = feature_sets[feature_set]
        probabilities, labels = [], []
        for year in development_years:
            train, test = years < year, years == year
            if window != "all":
                train &= years >= year-int(window.replace("recent", ""))
            p = probability(X[train], y[train], margins[train], X[test], alpha, cap, kind, c)
            probabilities.extend(p); labels.extend(y[test])
        probabilities, labels = np.asarray(probabilities), np.asarray(labels)
        for shrink in (.75, .8, .85, .9, .95, 1.0):
            adjusted = .5 + shrink * (probabilities-.5)
            metrics = score(labels, adjusted)
            results.append({"alpha": alpha, "cap": cap, "target": kind, "c": c, "window": window, "feature_set": feature_set, "shrink": shrink, **metrics})
        if config_index % 50 == 0:
            print(f"searched {config_index+1}/{len(configs)}", flush=True)
    results.sort(key=lambda row: (row["brier_score"], -row["accuracy"]))
    best = results[0]
    X = feature_sets[best["feature_set"]]
    audit_p, audit_y = [], []
    for year in (2025, 2026):
        train, test = years < year, years == year
        if best["window"] != "all":
            train &= years >= year-int(best["window"].replace("recent", ""))
        p = probability(X[train], y[train], margins[train], X[test], best["alpha"], best["cap"], best["target"], best["c"])
        audit_p.extend(.5+best["shrink"]*(p-.5)); audit_y.extend(y[test])
    report = {"selection_policy": "Hyperparameters selected only on 2022-2024 rolling-origin folds.", "target_brier": .24, "best_development": best, "temporal_audit_2025_2026": score(np.asarray(audit_y), np.asarray(audit_p)), "top_development": results[:20]}
    OUTPUT.write_text(json.dumps(report, indent=2), encoding="utf8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
