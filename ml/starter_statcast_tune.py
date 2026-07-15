"""Nested rolling-origin gate for starter Statcast and platoon candidates."""
import json
from pathlib import Path

import numpy as np

from ml.starter_statcast_experiment import margin_probability, platoon_matrix, starter_matrix
from ml.v2_experiment import DATA, extra_trees, logistic, matrix, read_jsonl, score

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "ml" / "artifacts" / "starter_statcast_tuning_report.json"

# Candidate families and blend weights are fixed before outer-fold evaluation.
CANDIDATES = {
    "lean_calibrated": ("lean", "calibrated", 1.0),
    "lean_blend_70_30": ("lean", "blend", .70),
    "lean_margin": ("lean", "margin", 1.0),
    "recent_calibrated": ("recent", "calibrated", 1.0),
    "recent_blend_70_30": ("recent", "blend", .70),
    "recent_margin": ("recent", "margin", 1.0),
    "long_calibrated": ("long", "calibrated", 1.0),
    "long_blend_70_30": ("long", "blend", .70),
    "long_margin": ("long", "margin", 1.0),
    "full_calibrated": ("full", "calibrated", 1.0),
    "full_blend_70_30": ("full", "blend", .70),
    "full_margin": ("full", "margin", 1.0),
    "platoon_calibrated": ("platoon", "calibrated", 1.0),
    "platoon_blend_70_30": ("platoon", "blend", .70),
    "platoon_margin": ("platoon", "margin", 1.0),
    "combined_calibrated": ("combined", "calibrated", 1.0),
    "combined_blend_70_30": ("combined", "blend", .70),
    "combined_margin": ("combined", "margin", 1.0),
}


def json_default(value):
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    if isinstance(value, np.bool_):
        return bool(value)
    raise TypeError(type(value).__name__)


def build_sets():
    base, v2, _, y, years, context_count, _ = matrix()
    starter, coverage = starter_matrix()
    platoon = platoon_matrix()
    lean = np.delete(v2, [1, 3], axis=1)
    common = np.column_stack([base, lean])
    sets = {
        "lean": common,
        "recent": np.column_stack([common, starter[:, :6], starter[:, 12:]]),
        "long": np.column_stack([common, starter[:, 6:]]),
        "full": np.column_stack([common, starter]),
        "platoon": np.column_stack([common, platoon]),
        "combined": np.column_stack([common, starter, platoon]),
    }
    games = sorted(read_jsonl(DATA), key=lambda row: (row["date"], row["game_id"]))
    margins = np.asarray([float(game["home_score"] - game["away_score"]) for game in games])
    return sets, base, y, years, margins, context_count, coverage


def probability(candidate, sets, y, margins, train, test):
    feature_set, model_kind, weight = CANDIDATES[candidate]
    X = sets[feature_set]
    if model_kind == "margin":
        return margin_probability(X, y, margins, train, test)
    calibrated = logistic(.35, True).fit(X[train], y[train])
    left = calibrated.predict_proba(X[test])[:, 1]
    if model_kind == "calibrated":
        return left
    right = extra_trees().fit(X[train], y[train]).predict_proba(X[test])[:, 1]
    return weight * left + (1 - weight) * right


def inner(candidate, outer, sets, y, years, margins):
    fold_scores, fold_years = [], []
    for year in sorted(set(years)):
        if year < 2022 or year >= outer or np.sum(years < year) < 4000:
            continue
        train, test = years < year, years == year
        fold_years.append(int(year))
        fold_scores.append(score(y[test], probability(candidate, sets, y, margins, train, test)))
    return {
        "folds": fold_years,
        "mean_accuracy": round(float(np.mean([item["accuracy"] for item in fold_scores])), 5),
        "mean_log_loss": round(float(np.mean([item["log_loss"] for item in fold_scores])), 5),
        "mean_qualified_accuracy": round(float(np.mean([item["qualified_accuracy"] for item in fold_scores])), 5),
    }


def main():
    sets, base, y, years, margins, context_count, coverage = build_sets()
    if coverage["raw_games"] < 13000 or (coverage.get("last_raw_date") or "") < "2026-07-12":
        raise SystemExit(f"starter Statcast backfill incomplete: {coverage['raw_games']} games")
    outer_years = [year for year in (2024, 2025, 2026) if np.any(years == year)]
    candidate_p, incumbent_p, actual, folds = [], [], [], {}
    for outer in outer_years:
        diagnostics = {name: inner(name, outer, sets, y, years, margins) for name in CANDIDATES}
        best_loss = min(value["mean_log_loss"] for value in diagnostics.values())
        eligible = [name for name, value in diagnostics.items() if value["mean_log_loss"] <= best_loss + .001 and value["mean_qualified_accuracy"] >= .60]
        if not eligible:
            eligible = [min(diagnostics, key=lambda name: diagnostics[name]["mean_log_loss"])]
        # Accuracy wins within the probability-quality band; ties prefer fewer
        # inputs and then the more linear blend.
        selected = max(eligible, key=lambda name: (diagnostics[name]["mean_accuracy"], -sets[CANDIDATES[name][0]].shape[1], CANDIDATES[name][2]))
        train, test = years < outer, years == outer
        candidate = probability(selected, sets, y, margins, train, test)
        incumbent = logistic(.35, True).fit(base[train], y[train]).predict_proba(base[test])[:, 1]
        candidate_p.extend(candidate); incumbent_p.extend(incumbent); actual.extend(y[test])
        folds[str(outer)] = {
            "selected": selected,
            "inner": diagnostics,
            "untouched_outer": score(y[test], candidate),
            "incumbent_outer": score(y[test], incumbent),
        }
        print(outer, selected, folds[str(outer)]["untouched_outer"], flush=True)
    actual = np.asarray(actual)
    candidate_score = score(actual, np.asarray(candidate_p))
    incumbent_score = score(actual, np.asarray(incumbent_p))
    no_bad_year = all(
        value["untouched_outer"]["accuracy"] >= value["incumbent_outer"]["accuracy"] - .01
        and value["untouched_outer"]["log_loss"] <= value["incumbent_outer"]["log_loss"] + .005
        for value in folds.values()
    )
    gate = (
        candidate_score["accuracy"] >= .57
        and candidate_score["accuracy"] >= incumbent_score["accuracy"] + .003
        and candidate_score["log_loss"] < incumbent_score["log_loss"]
        and candidate_score["brier_score"] < incumbent_score["brier_score"]
        and candidate_score["qualified_accuracy"] >= .60
        and no_bad_year
    )
    report = {
        "status": "eligible_for_production_integration" if gate else "shadow_only_no_promotion",
        "production_changed": False,
        "policy": "Nested rolling-origin selection with fixed candidate families and untouched outer seasons. Promotion requires >=57% all-game accuracy, >=0.3-point gain, better log loss and Brier, >=60% qualified accuracy, and no badly regressing outer season.",
        "context_games": context_count,
        "coverage": coverage,
        "outer_seasons": outer_years,
        "candidate_count": len(CANDIDATES),
        "candidate_outer": candidate_score,
        "incumbent_outer": incumbent_score,
        "promotion_gate_passed": gate,
        "folds": folds,
    }
    OUTPUT.write_text(json.dumps(report, indent=2, default=json_default), encoding="utf8")
    print(json.dumps({key: report[key] for key in ("status", "candidate_outer", "incumbent_outer", "promotion_gate_passed")}, indent=2, default=json_default))


if __name__ == "__main__":
    main()
