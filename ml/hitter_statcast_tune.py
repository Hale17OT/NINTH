"""Nested rolling-origin promotion gate for confirmed-lineup hitter Statcast."""
import json
from pathlib import Path

import numpy as np

from ml.hitter_statcast_experiment import bullpen_matrix, hitter_matrix, ordered_lineup_matrix
from ml.starter_statcast_experiment import margin_probability, starter_matrix
from ml.v2_experiment import DATA, logistic, matrix, read_jsonl, score

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "ml" / "artifacts" / "hitter_statcast_tuning_report.json"
CANDIDATES = ("lineup_margin", "recent_starter_margin", "recent_starter_lineup_margin", "long_starter_lineup_margin", "recent_starter_personnel_margin", "long_starter_personnel_margin")


def json_default(value):
    if isinstance(value, np.integer): return int(value)
    if isinstance(value, np.floating): return float(value)
    if isinstance(value, np.bool_): return bool(value)
    raise TypeError(type(value).__name__)


def build():
    base, v2, _, y, years, context_count, _ = matrix()
    starter, starter_coverage = starter_matrix(); hitters, hitter_coverage = hitter_matrix()
    if hitter_coverage["raw_games"] < 13000 or (hitter_coverage.get("last_raw_date") or "") < "2026-07-12":
        raise SystemExit(f"hitter Statcast backfill incomplete: {hitter_coverage['raw_games']} games")
    common = np.column_stack([base, np.delete(v2, [1, 3], axis=1)])
    ordered, v3_count = ordered_lineup_matrix(); bullpen = bullpen_matrix()
    if v3_count < 13000: raise SystemExit(f"contexts_v3 backfill incomplete: {v3_count} games")
    sets = {
        "lineup_margin": np.column_stack([common, hitters]),
        "recent_starter_margin": np.column_stack([common, starter[:, :6], starter[:, 12:]]),
        "recent_starter_lineup_margin": np.column_stack([common, starter[:, :6], starter[:, 12:], hitters]),
        "long_starter_lineup_margin": np.column_stack([common, starter[:, 6:], hitters]),
        "recent_starter_personnel_margin": np.column_stack([common, starter[:, :6], starter[:, 12:], hitters, ordered, bullpen]),
        "long_starter_personnel_margin": np.column_stack([common, starter[:, 6:], hitters, ordered, bullpen]),
    }
    games = sorted(read_jsonl(DATA), key=lambda row: (row["date"], row["game_id"]))
    margins = np.asarray([float(game["home_score"] - game["away_score"]) for game in games])
    return sets, base, y, years, margins, context_count, starter_coverage, hitter_coverage


def inner(candidate, outer, sets, y, years, margins):
    values, fold_years = [], []
    for year in sorted(set(years)):
        if year < 2022 or year >= outer or np.sum(years < year) < 4000: continue
        train, test = years < year, years == year
        values.append(score(y[test], margin_probability(sets[candidate], y, margins, train, test))); fold_years.append(int(year))
    return {
        "folds": fold_years,
        "mean_accuracy": round(float(np.mean([value["accuracy"] for value in values])), 5),
        "mean_log_loss": round(float(np.mean([value["log_loss"] for value in values])), 5),
        "mean_qualified_accuracy": round(float(np.mean([value["qualified_accuracy"] for value in values])), 5),
    }


def main():
    sets, base, y, years, margins, context_count, starter_coverage, hitter_coverage = build()
    candidate_p, incumbent_p, actual, folds = [], [], [], {}
    for outer in (2024, 2025, 2026):
        diagnostics = {name: inner(name, outer, sets, y, years, margins) for name in CANDIDATES}
        best_loss = min(value["mean_log_loss"] for value in diagnostics.values())
        eligible = [name for name, value in diagnostics.items() if value["mean_log_loss"] <= best_loss + .001 and value["mean_qualified_accuracy"] >= .60]
        if not eligible: eligible = [min(diagnostics, key=lambda name: diagnostics[name]["mean_log_loss"])]
        selected = max(eligible, key=lambda name: (diagnostics[name]["mean_accuracy"], -sets[name].shape[1]))
        train, test = years < outer, years == outer
        candidate = margin_probability(sets[selected], y, margins, train, test)
        incumbent = logistic(.35, True).fit(base[train], y[train]).predict_proba(base[test])[:, 1]
        candidate_p.extend(candidate); incumbent_p.extend(incumbent); actual.extend(y[test])
        folds[str(outer)] = {"selected": selected, "inner": diagnostics, "untouched_outer": score(y[test], candidate), "incumbent_outer": score(y[test], incumbent)}
        print(outer, selected, folds[str(outer)]["untouched_outer"], flush=True)
    actual = np.asarray(actual); candidate_score = score(actual, np.asarray(candidate_p)); incumbent_score = score(actual, np.asarray(incumbent_p))
    no_bad_year = all(value["untouched_outer"]["accuracy"] >= value["incumbent_outer"]["accuracy"] - .01 and value["untouched_outer"]["log_loss"] <= value["incumbent_outer"]["log_loss"] + .005 for value in folds.values())
    gate = candidate_score["accuracy"] >= .57 and candidate_score["accuracy"] >= incumbent_score["accuracy"] + .003 and candidate_score["log_loss"] < incumbent_score["log_loss"] and candidate_score["brier_score"] < incumbent_score["brier_score"] and candidate_score["qualified_accuracy"] >= .60 and no_bad_year
    report = {
        "status": "eligible_for_production_integration" if gate else "shadow_only_no_promotion", "production_changed": False,
        "policy": "Four candidate families fixed before hitter results. Nested rolling selection; promotion requires >=57% all-game accuracy, >=0.3-point gain, better log loss/Brier, >=60% qualified accuracy, and no badly regressing outer season.",
        "context_games": context_count, "starter_coverage": starter_coverage, "hitter_coverage": hitter_coverage,
        "outer_seasons": [2024, 2025, 2026], "candidate_count": len(CANDIDATES), "candidate_outer": candidate_score, "incumbent_outer": incumbent_score,
        "promotion_gate_passed": gate, "folds": folds,
    }
    OUTPUT.write_text(json.dumps(report, indent=2, default=json_default), encoding="utf8")
    print(json.dumps({key: report[key] for key in ("status", "candidate_outer", "incumbent_outer", "promotion_gate_passed")}, indent=2, default=json_default))


if __name__ == "__main__": main()
