"""Leakage-safe experiment for MelBet-shaped full-game totals ranges.

MelBet's current MLB feed commonly exposes seven contiguous half-run steps
centered on a half line. Historical feeds are unavailable, so this experiment
reconstructs only the *shape* of that grid. Its center comes from a model fitted
strictly on earlier seasons; the final score is never used to select a range.
Results are research evidence and must not be described as historical MelBet
performance.
"""
import json
from pathlib import Path

import numpy as np
from scipy.stats import nbinom
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression, PoissonRegressor
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from ml.train_totals import matrix


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "ml" / "artifacts" / "totals_melbet_range_experiment.json"
INCUMBENT_BOUNDARIES = np.asarray([6.5, 7.5, 8.5, 9.5, 10.5, 11.5])
EXPANDED_BOUNDARIES = np.asarray([5.5, 6.5, 7.5, 8.5, 9.5, 10.5, 11.5, 12.5])
GRID_OFFSETS = np.arange(-1.5, 1.51, .5)


def mean_model():
    return Pipeline([
        ("scale", StandardScaler()),
        ("poisson", PoissonRegressor(alpha=2, max_iter=1500)),
    ])


def fold_components(X, total, train, test, boundaries):
    legacy = X[:, :21]
    fitted = mean_model().fit(legacy[train], total[train])
    mu_train = np.clip(fitted.predict(legacy[train]), .1, 30)
    mu_test = np.clip(fitted.predict(legacy[test]), .1, 30)
    dispersion = float(np.clip(
        np.mean(
            ((total[train] - mu_train) ** 2 - mu_train)
            / np.maximum(mu_train ** 2, 1e-6)
        ),
        .01, 1,
    ))
    size = 1 / dispersion
    count = np.column_stack([
        nbinom.sf(int(line), size, size / (size + mu_test))
        for line in boundaries
    ])
    isotonic = np.minimum.accumulate(np.column_stack([
        IsotonicRegression(
            increasing=True, out_of_bounds="clip", y_min=.01, y_max=.99,
        ).fit(mu_train, (total[train] > line).astype(int)).predict(mu_test)
        for line in boundaries
    ]), axis=1)
    direct = np.minimum.accumulate(np.column_stack([
        Pipeline([
            ("scale", StandardScaler()),
            ("logistic", LogisticRegression(C=.03, max_iter=2500)),
        ]).fit(X[train], (total[train] > line).astype(int)).predict_proba(X[test])[:, 1]
        for line in boundaries
    ]), axis=1)
    return count, isotonic, direct, mu_test


def oof_components(X, total, years, boundaries):
    parts = {"count": [], "isotonic": [], "direct": [], "mu": [], "total": [], "year": []}
    for year in sorted(set(years)):
        if year < 2022 or np.sum(years < year) < 4000:
            continue
        train, test = years < year, years == year
        count, isotonic, direct, mu = fold_components(
            X, total, train, test, boundaries,
        )
        parts["count"].append(count)
        parts["isotonic"].append(isotonic)
        parts["direct"].append(direct)
        parts["mu"].append(mu)
        parts["total"].append(total[test])
        parts["year"].append(years[test])
        print(f"completed {len(boundaries)}-boundary rolling origin {year}", flush=True)
    return {key: np.concatenate(value) if key in ("mu", "total", "year") else np.vstack(value)
            for key, value in parts.items()}


def tune_blend(parts):
    development = parts["year"] <= 2024
    actual = np.column_stack([
        parts["total"] > boundary for boundary in parts["boundaries"]
    ]).astype(int)
    choices = []
    for count_weight in np.arange(0, 1.001, .05):
        for isotonic_weight in np.arange(0, 1.001 - count_weight, .05):
            direct_weight = 1 - count_weight - isotonic_weight
            probability = (
                count_weight * parts["count"]
                + isotonic_weight * parts["isotonic"]
                + direct_weight * parts["direct"]
            )
            choices.append((
                float(np.mean((probability[development] - actual[development]) ** 2)),
                count_weight, isotonic_weight, direct_weight, probability,
            ))
    return min(choices, key=lambda row: row[0])


def survival_at(probability, boundaries, cutoff):
    """Return P(total > cutoff), clamping like the current production model."""
    return float(np.interp(float(cutoff), boundaries, probability))


def market_probability(probability, boundaries, line):
    line = float(line)
    if abs(line - round(line)) > 1e-9:
        over = survival_at(probability, boundaries, line)
        return over, 1 - over, 0.0
    over = survival_at(probability, boundaries, line + .5)
    at_or_above = survival_at(probability, boundaries, line - .5)
    under = 1 - at_or_above
    return over, under, max(0.0, at_or_above - over)


def inferred_grid(expected):
    # Today's observed centers are 7.5, 8.5, or 9.5, each with +/- 1.5 runs.
    center = float(np.clip(round(float(expected) - .5) + .5, 7.5, 9.5))
    return center + GRID_OFFSETS


def evaluate(parts, probability, boundaries, mask):
    all_probabilities, all_outcomes = [], []
    selected_probabilities, selected_outcomes, selected_lines = [], [], []
    pushes = 0
    indexes = np.flatnonzero(mask)
    for index in indexes:
        final_total = int(parts["total"][index])
        candidates = []
        for line in inferred_grid(parts["mu"][index]):
            over, under, push = market_probability(
                probability[index], boundaries, line,
            )
            if final_total == line:
                pushes += 1
                continue
            denominator = max(1e-9, 1 - push)
            over_conditional = over / denominator
            actual_over = int(final_total > line)
            all_probabilities.append(over_conditional)
            all_outcomes.append(actual_over)
            side_probability = max(over_conditional, 1 - over_conditional)
            side_outcome = actual_over if over_conditional >= .5 else 1 - actual_over
            candidates.append((side_probability, side_outcome, float(line)))
        if candidates:
            selected = max(candidates, key=lambda row: row[0])
            selected_probabilities.append(selected[0])
            selected_outcomes.append(selected[1])
            selected_lines.append(selected[2])
    all_probability = np.asarray(all_probabilities)
    all_outcome = np.asarray(all_outcomes)
    selected_probability = np.asarray(selected_probabilities)
    selected_outcome = np.asarray(selected_outcomes)
    return {
        "games": int(len(selected_outcome)),
        "offered_non_push_rows": int(len(all_outcome)),
        "integer_push_rows_voided": int(pushes),
        "all_offered_brier": round(float(np.mean((all_probability - all_outcome) ** 2)), 6),
        "selected_accuracy": round(float(np.mean(selected_outcome)), 6),
        "selected_brier": round(float(np.mean((selected_probability - selected_outcome) ** 2)), 6),
        "selected_mean_probability": round(float(np.mean(selected_probability)), 6),
        "selected_line_counts": {
            str(line): int(np.sum(np.asarray(selected_lines) == line))
            for line in sorted(set(selected_lines))
        },
    }


def main():
    _, X, total, years, _, _, _ = matrix()
    variants = {}
    for name, boundaries in (
        ("incumbent_clamped_grid", INCUMBENT_BOUNDARIES),
        ("expanded_push_aware_grid", EXPANDED_BOUNDARIES),
    ):
        parts = oof_components(X, total, years, boundaries)
        parts["boundaries"] = boundaries
        dev_brier, count_weight, iso_weight, direct_weight, probability = tune_blend(parts)
        variants[name] = {
            "boundaries": boundaries.tolist(),
            "weights": {
                "count": round(float(count_weight), 2),
                "isotonic": round(float(iso_weight), 2),
                "direct": round(float(direct_weight), 2),
            },
            "development_boundary_brier": round(dev_brier, 6),
            "development_simulated_ranges": evaluate(
                parts, probability, boundaries, parts["year"] <= 2024,
            ),
            "audit_2025_2026_simulated_ranges": evaluate(
                parts, probability, boundaries, parts["year"] >= 2025,
            ),
        }
    incumbent = variants["incumbent_clamped_grid"]["audit_2025_2026_simulated_ranges"]
    challenger = variants["expanded_push_aware_grid"]["audit_2025_2026_simulated_ranges"]
    report = {
        "status": "research_only",
        "historical_market_data": False,
        "observed_2026_07_24_grid_shape": "Seven half-run steps; center in {7.5, 8.5, 9.5}; range center +/- 1.5.",
        "reconstruction_rule": "Grid center is derived only from rolling-origin pregame expected runs and clipped to today's observed centers.",
        "promotion_rule": "Do not promote from simulated ranges alone. Archive real MelBet grids and require a later temporal audit.",
        "variants": variants,
        "audit_change": {
            "all_offered_brier": round(
                challenger["all_offered_brier"] - incumbent["all_offered_brier"], 6,
            ),
            "selected_brier": round(
                challenger["selected_brier"] - incumbent["selected_brier"], 6,
            ),
            "selected_accuracy": round(
                challenger["selected_accuracy"] - incumbent["selected_accuracy"], 6,
            ),
        },
    }
    OUTPUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
