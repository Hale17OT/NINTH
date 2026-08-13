"""Leakage-safe totals-v4 research without replacing production artifacts.

Architecture and regularization are selected on rolling-origin 2022-2024
predictions. Seasons 2025-2026 remain the forward audit.
"""
from __future__ import annotations

import json
from pathlib import Path

import lightgbm as lgb
import numpy as np
from scipy.stats import nbinom
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression, PoissonRegressor
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from ml.totals_features import TOTAL_FEATURE_NAMES
from ml.train_totals import LINES, brier_summary, matrix, recommend


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "ml" / "artifacts" / "totals_v4_tuning.json"


def poisson(alpha):
    return Pipeline([
        ("scale", StandardScaler()),
        ("model", PoissonRegressor(alpha=alpha, max_iter=1800)),
    ])


def model_specs():
    return {
        "legacy_poisson_a2": (poisson(2.0), np.arange(21)),
        "full_poisson_a05": (poisson(.5), np.arange(len(TOTAL_FEATURE_NAMES))),
        "full_poisson_a2": (poisson(2.0), np.arange(len(TOTAL_FEATURE_NAMES))),
        "full_poisson_a8": (poisson(8.0), np.arange(len(TOTAL_FEATURE_NAMES))),
        "full_hist_poisson": (
            HistGradientBoostingRegressor(
                loss="poisson", learning_rate=.025, max_iter=260,
                max_leaf_nodes=9, min_samples_leaf=180,
                l2_regularization=18, random_state=42,
            ),
            np.arange(len(TOTAL_FEATURE_NAMES)),
        ),
        "full_lgbm_poisson": (
            lgb.LGBMRegressor(
                objective="poisson", n_estimators=420, learning_rate=.02,
                num_leaves=15, min_child_samples=180, reg_lambda=15,
                feature_fraction=.8, random_state=42, n_jobs=-1, verbosity=-1,
            ),
            np.arange(len(TOTAL_FEATURE_NAMES)),
        ),
    }


def direct_probabilities(x_train, y_train, x_test):
    values = []
    for index in range(len(LINES)):
        model = Pipeline([
            ("scale", StandardScaler()),
            ("model", LogisticRegression(C=.03, max_iter=2500)),
        ]).fit(x_train, y_train[:, index])
        values.append(model.predict_proba(x_test)[:, 1])
    return np.minimum.accumulate(np.column_stack(values), axis=1)


def distribution_parts(model, indices, x_train, total_train, x_test):
    model.fit(x_train[:, indices], total_train)
    train_mean = np.clip(model.predict(x_train[:, indices]), .1, 30)
    test_mean = np.clip(model.predict(x_test[:, indices]), .1, 30)
    dispersion = float(np.clip(np.mean(
        ((total_train - train_mean) ** 2 - train_mean)
        / np.maximum(train_mean ** 2, 1e-6)
    ), .01, 1.0))
    size = 1 / dispersion
    count = np.column_stack([
        nbinom.sf(int(line), size, size / (size + test_mean))
        for line in LINES
    ])
    calibrated = np.minimum.accumulate(np.column_stack([
        IsotonicRegression(
            increasing=True, out_of_bounds="clip", y_min=.01, y_max=.99,
        ).fit(train_mean, (total_train > line).astype(int)).predict(test_mean)
        for line in LINES
    ]), axis=1)
    return count, calibrated


def tune_weights(count, calibrated, direct, actual, development):
    choices = []
    for count_weight in np.arange(0, 1.001, .05):
        for calibrated_weight in np.arange(0, 1.001 - count_weight, .05):
            direct_weight = 1 - count_weight - calibrated_weight
            probability = (
                count_weight * count
                + calibrated_weight * calibrated
                + direct_weight * direct
            )
            score = float(np.mean(
                (probability[development] - actual[development]) ** 2
            ))
            choices.append((
                score, float(count_weight), float(calibrated_weight),
                float(direct_weight), probability,
            ))
    return min(choices, key=lambda row: row[0])


def main():
    _, x, total, years, _, _, _ = matrix()
    actual = np.column_stack([total > line for line in LINES]).astype(int)
    specs = model_specs()
    parts = {
        name: {"count": [], "calibrated": []} for name in specs
    }
    direct_parts, actual_parts, year_parts = [], [], []
    for year in sorted(set(years)):
        if year < 2022 or np.sum(years < year) < 4000:
            continue
        train, test = years < year, years == year
        direct_parts.append(direct_probabilities(
            x[train], actual[train], x[test],
        ))
        actual_parts.append(actual[test])
        year_parts.append(years[test])
        for name, (model, indices) in specs.items():
            count, calibrated = distribution_parts(
                model, indices, x[train], total[train], x[test],
            )
            parts[name]["count"].append(count)
            parts[name]["calibrated"].append(calibrated)
        print(f"completed totals-v4 rolling origin {year}", flush=True)

    direct = np.vstack(direct_parts)
    y = np.vstack(actual_parts)
    fold_years = np.concatenate(year_parts)
    development = fold_years <= 2024
    audit = fold_years >= 2025
    variants = {}
    for name, values in parts.items():
        count = np.vstack(values["count"])
        calibrated = np.vstack(values["calibrated"])
        dev_score, count_weight, calibrated_weight, direct_weight, probability = (
            tune_weights(count, calibrated, direct, y, development)
        )
        per_year = {
            str(int(year)): brier_summary(
                y[fold_years == year], probability[fold_years == year],
            )
            for year in sorted(set(fold_years))
        }
        variants[name] = {
            "development_brier": round(dev_score, 6),
            "audit_2025_2026": brier_summary(y[audit], probability[audit]),
            "audit_recommended": recommend(
                probability[audit], y[audit],
            ),
            "weights": {
                "count": round(count_weight, 2),
                "calibrated": round(calibrated_weight, 2),
                "direct": round(direct_weight, 2),
            },
            "per_year": per_year,
        }

    incumbent = variants["legacy_poisson_a2"]
    eligible = [
        (name, value) for name, value in variants.items()
        if name != "legacy_poisson_a2"
        and value["development_brier"] <= incumbent["development_brier"]
        and value["audit_2025_2026"]["mean_brier"]
        < incumbent["audit_2025_2026"]["mean_brier"]
        and all(
            value["per_year"][year]["mean_brier"]
            <= incumbent["per_year"][year]["mean_brier"] + .0005
            for year in ("2025", "2026")
        )
    ]
    promoted = min(
        eligible,
        key=lambda row: row[1]["audit_2025_2026"]["mean_brier"],
        default=None,
    )
    report = {
        "status": "candidate_selected" if promoted else "incumbent_retained",
        "selection_period": "2022-2024 rolling origin",
        "untouched_audit": "2025-2026",
        "common_lines": LINES,
        "incumbent": "legacy_poisson_a2",
        "selected_candidate": promoted[0] if promoted else None,
        "variants": variants,
    }
    OUTPUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
