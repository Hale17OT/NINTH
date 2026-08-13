"""Promotion-gated research for workload and individual bullpen context."""
from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score

from ml.pitching_availability import apply_game, features, fresh_state
from ml.research_totals_lineup_v1 import count_parts, direct, tune
from ml.starter_statcast_experiment import RAW, STARTER_CONTEXTS, read_jsonl, starter_matrix
from ml.train_totals import LINES, brier_summary, matrix as totals_matrix, recommend
from ml.train_totals_v3 import lineup_talent_matrix as totals_lineup_matrix
from ml.train_v3 import fit as moneyline_fit, lineup_talent_matrix as moneyline_lineup_matrix
from ml.v2_experiment import DATA, matrix as moneyline_matrix


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = Path(os.getenv("NINTH_ARTIFACT_DIR", ROOT / "ml" / "artifacts")) / "pitching_availability_v1_research.json"


def pitching_matrix(games, return_state=False):
    contexts = {str(row["game_id"]): row for row in read_jsonl(STARTER_CONTEXTS)}
    statcast = {str(row["game_id"]): row for row in read_jsonl(RAW)}
    state, moneyline, totals = fresh_state(), [], []
    for game in games:
        context = contexts.get(str(game["game_id"]))
        money, total = features(state, game, context)
        moneyline.append(money); totals.append(total)
        apply_game(state, game, context, statcast.get(str(game["game_id"])))
    values = (np.asarray(moneyline, float), np.asarray(totals, float))
    return (*values, state) if return_state else values


def binary_score(actual, probability):
    probability = np.clip(np.asarray(probability), 1e-5, 1 - 1e-5)
    return {
        "games": int(len(actual)),
        "brier": round(float(brier_score_loss(actual, probability)), 7),
        "log_loss": round(float(log_loss(actual, probability)), 7),
        "accuracy": round(float(np.mean((probability >= .5) == actual)), 7),
        "auc": round(float(roc_auc_score(actual, probability)), 7),
    }


def totals_score(actual, probability):
    probability = np.clip(np.asarray(probability), 1e-5, 1 - 1e-5)
    actual = np.asarray(actual)
    return {
        **brier_summary(actual, probability),
        "mean_log_loss": round(float(np.mean([
            log_loss(actual[:, index], probability[:, index], labels=[0, 1])
            for index in range(actual.shape[1])
        ])), 7),
    }


def paired_bootstrap(actual, incumbent, candidate, seed=20260801, samples=4000):
    rng = np.random.default_rng(seed)
    incumbent_loss = (np.asarray(incumbent) - np.asarray(actual)) ** 2
    candidate_loss = (np.asarray(candidate) - np.asarray(actual)) ** 2
    improvement = incumbent_loss - candidate_loss
    # Sample games, not individual total thresholds: the six line outcomes for
    # one game are strongly dependent and must stay in the same bootstrap row.
    row_improvement = improvement.reshape(len(improvement), -1).mean(axis=1)
    draws = np.asarray([
        np.mean(row_improvement[rng.integers(0, len(row_improvement), len(row_improvement))])
        for _ in range(samples)
    ])
    return {
        "mean_brier_improvement": round(float(np.mean(row_improvement)), 7),
        "ci95": [round(float(np.quantile(draws, .025)), 7), round(float(np.quantile(draws, .975)), 7)],
        "probability_improvement_positive": round(float(np.mean(draws > 0)), 4),
    }


def evaluate_moneyline(games, base, starters, lineup, pitching, labels, years):
    incumbent_x = np.column_stack([base, starters[:, 6:], lineup])
    groups = {
        "incumbent": incumbent_x,
        "starter_workload": np.column_stack([incumbent_x, pitching[:, :6]]),
        "bullpen_availability": np.column_stack([incumbent_x, pitching[:, 6:]]),
        "combined": np.column_stack([incumbent_x, pitching]),
    }
    margins = np.asarray([game["home_score"] - game["away_score"] for game in games], float)
    predictions = {name: [] for name in groups}; actual_parts, year_parts = [], []
    for year in sorted(set(years)):
        if year < 2022 or np.sum(years < year) < 4000:
            continue
        train, test = years < year, years == year
        for name, values in groups.items():
            model = moneyline_fit(values[train], labels[train], margins[train])
            predictions[name].extend(model.predict_proba(values[test])[:, 1])
        actual_parts.extend(labels[test]); year_parts.extend(years[test])
        print(f"completed moneyline pitching fold {year}", flush=True)
    actual, fold_years = np.asarray(actual_parts), np.asarray(year_parts)
    predictions = {name: np.asarray(value) for name, value in predictions.items()}
    development = fold_years <= 2024
    selected = min(groups, key=lambda name: brier_score_loss(actual[development], predictions[name][development]))
    report = {"selected_on_2022_2024": selected, "variants": {}}
    for name, probability in predictions.items():
        report["variants"][name] = {
            "development": binary_score(actual[development], probability[development]),
            "2025": binary_score(actual[fold_years == 2025], probability[fold_years == 2025]),
            "2026": binary_score(actual[fold_years == 2026], probability[fold_years == 2026]),
        }
    audit = fold_years >= 2025
    report["selected_audit_bootstrap"] = paired_bootstrap(
        actual[audit], predictions["incumbent"][audit], predictions[selected][audit],
    )
    return report


def evaluate_totals(base, lineup, pitching, total, years):
    incumbent_x = np.column_stack([base, lineup])
    groups = {
        "incumbent": incumbent_x,
        "starter_workload": np.column_stack([incumbent_x, pitching[:, :6]]),
        "bullpen_availability": np.column_stack([incumbent_x, pitching[:, 6:]]),
        "combined": np.column_stack([incumbent_x, pitching]),
    }
    actual = np.column_stack([total > line for line in LINES]).astype(int)
    count_rows, iso_rows = [], []
    direct_rows = {name: [] for name in groups}; actual_rows, year_rows = [], []
    for year in sorted(set(years)):
        if year < 2022 or np.sum(years < year) < 4000:
            continue
        train, test = years < year, years == year
        count, calibrated = count_parts(base[train], total[train], base[test])
        count_rows.append(count); iso_rows.append(calibrated)
        for name, values in groups.items():
            direct_rows[name].append(direct(values[train], actual[train], values[test]))
        actual_rows.append(actual[test]); year_rows.extend(years[test])
        print(f"completed totals pitching fold {year}", flush=True)
    count, calibrated, labels = np.vstack(count_rows), np.vstack(iso_rows), np.vstack(actual_rows)
    fold_years = np.asarray(year_rows); development = fold_years <= 2024
    probabilities, variants = {}, {}
    for name in groups:
        _, cw, iw, dw, probability = tune(
            count, calibrated, np.vstack(direct_rows[name]), labels, development,
        )
        probabilities[name] = probability
        variants[name] = {
            "weights": {"count": cw, "isotonic": iw, "direct": dw},
            "development": totals_score(labels[development], probability[development]),
            "2025": totals_score(labels[fold_years == 2025], probability[fold_years == 2025]),
            "2026": totals_score(labels[fold_years == 2026], probability[fold_years == 2026]),
        }
    selected = min(groups, key=lambda name: variants[name]["development"]["mean_brier"])
    audit = fold_years >= 2025
    bootstrap = paired_bootstrap(
        labels[audit], probabilities["incumbent"][audit], probabilities[selected][audit],
        seed=20260802,
    )
    yearly_bootstrap = {
        str(year): paired_bootstrap(
            labels[fold_years == year], probabilities["incumbent"][fold_years == year],
            probabilities[selected][fold_years == year], seed=20260802 + year,
        )
        for year in (2025, 2026)
    }
    incumbent, candidate = variants["incumbent"], variants[selected]
    promotion_gate = {
        "development_brier_improved": candidate["development"]["mean_brier"] < incumbent["development"]["mean_brier"],
        "both_audit_seasons_brier_improved": all(candidate[str(year)]["mean_brier"] < incumbent[str(year)]["mean_brier"] for year in (2025, 2026)),
        "both_audit_seasons_log_loss_improved": all(candidate[str(year)]["mean_log_loss"] < incumbent[str(year)]["mean_log_loss"] for year in (2025, 2026)),
        "pooled_bootstrap_ci_above_zero": bootstrap["ci95"][0] > 0,
    }
    promotion_gate["passed"] = all(promotion_gate.values())
    return {
        "selected_on_2022_2024": selected, "variants": variants,
        "selected_audit": totals_score(labels[audit], probabilities[selected][audit]),
        "selected_audit_recommended": recommend(probabilities[selected][audit], labels[audit]),
        "selected_audit_bootstrap": bootstrap,
        "selected_yearly_bootstrap": yearly_bootstrap,
        "promotion_gate": promotion_gate,
    }


def main():
    base, _, _, labels, years, _, _ = moneyline_matrix()
    games = sorted(read_jsonl(DATA), key=lambda row: (row["date"], row["game_id"]))
    starters, starter_coverage = starter_matrix()
    moneyline_lineup, _, lineup_coverage = moneyline_lineup_matrix(games)
    moneyline_lineup = moneyline_lineup[:, :6]
    pitching_moneyline, pitching_totals = pitching_matrix(games)
    total_games, totals_base, total, total_years, _, _, _ = totals_matrix()
    if [game["game_id"] for game in games] != [game["game_id"] for game in total_games]:
        raise RuntimeError("Moneyline and totals game ordering differs")
    totals_lineup, _, _ = totals_lineup_matrix(games)
    report = {
        "research_only": True,
        "selection_period": "2022-2024 rolling-origin",
        "audit_period": "2025-2026; previously observed, so bootstrap uncertainty is also required",
        "feature_policy": "All pitcher and bullpen histories are updated after the current game only; bullpen membership comes from prior appearances.",
        "starter_coverage": starter_coverage,
        "lineup_coverage": lineup_coverage,
        "moneyline": evaluate_moneyline(games, base, starters, moneyline_lineup, pitching_moneyline, labels, years),
        "totals": evaluate_totals(totals_base, totals_lineup, pitching_totals, total, total_years),
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
