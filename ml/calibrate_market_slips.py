"""Backtest joint moneyline, totals and mixed cards without sportsbook inputs."""
import json
import os
from collections import defaultdict
from datetime import date, timedelta
from math import sqrt
from pathlib import Path

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from ml.starter_statcast_experiment import starter_matrix
from ml.research_pitching_availability_v1 import pitching_matrix
from ml.totals_modeling import (
    CountDistributionTotalsModel, FeatureSubsetTotalsModel,
    MeanCalibratedTotalsModel, TotalsModelBlend, TotalsProbabilityModel,
)
from ml.train_totals import DECISION_LINES, LINES, matrix as totals_matrix
from ml.train_totals_v3 import (
    fit_components, lineup_talent_matrix as totals_lineup_talent_matrix,
    mean_model,
)
from ml.train_v3 import (
    fit as fit_moneyline,
    lineup_talent_matrix as moneyline_lineup_talent_matrix,
)
from ml.v2_experiment import matrix as moneyline_matrix

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = Path(os.getenv("NINTH_ARTIFACT_DIR", ROOT / "ml" / "artifacts")) / "market_slip_calibration.json"
PRODUCTION_ARTIFACTS = ROOT / "ml" / "artifacts"


def logit(value):
    value = float(np.clip(value, 1e-6, 1-1e-6))
    return np.log(value/(1-value))


def card_samples(rows, horizon, legs):
    by_date = defaultdict(list)
    for row in rows:
        by_date[row["date"]].append(row)
    available_dates = sorted(by_date)
    output = []
    for value in available_dates:
        start = date.fromisoformat(value); pool = []
        for offset in range(horizon):
            pool.extend(by_date.get((start+timedelta(days=offset)).isoformat(), []))
        if len(pool) < legs:
            continue
        selected = sorted(pool, key=lambda item: item["probability"], reverse=True)[:legs]
        output.append({"year": start.year, "raw": float(np.prod([item["probability"] for item in selected])), "won": int(all(item["won"] for item in selected))})
    return output


def calibration(rows):
    train = [row for row in rows if row["year"] <= 2024]
    audit = [row for row in rows if row["year"] >= 2025]
    if len(train) < 200 or len(audit) < 80 or len({row["won"] for row in train}) < 2:
        return {"promoted": False, "status": "insufficient", "training_samples": len(train), "validation_samples": len(audit)}
    x = lambda values: np.asarray([[logit(row["raw"])] for row in values])
    y = lambda values: np.asarray([row["won"] for row in values], int)
    candidate = LogisticRegression(C=.05, max_iter=2000).fit(x(train), y(train))
    audit_probability = candidate.predict_proba(x(audit))[:, 1]
    raw_brier = float(np.mean([(row["raw"]-row["won"])**2 for row in audit]))
    calibrated_brier = float(np.mean((audit_probability-y(audit))**2))
    stable = True; per_year = {}
    for year in (2025, 2026):
        values = [row for row in audit if row["year"] == year]
        if len(values) < 30:
            continue
        probability = candidate.predict_proba(x(values))[:, 1]
        raw = float(np.mean([(row["raw"]-row["won"])**2 for row in values])); calibrated = float(np.mean((probability-y(values))**2))
        per_year[str(year)] = {"samples": len(values), "raw_brier": round(raw, 5), "calibrated_brier": round(calibrated, 5), "improvement": round(raw-calibrated, 5)}
        stable &= calibrated <= raw+.001
    promoted = calibrated_brier < raw_brier and stable
    final = LogisticRegression(C=.05, max_iter=2000).fit(x(rows), y(rows))
    wins = sum(row["won"] for row in audit); n = len(audit); observed = wins/n
    z=1.96; denom=1+z*z/n; center=(observed+z*z/(2*n))/denom; margin=z*sqrt((observed*(1-observed)+z*z/(4*n))/n)/denom
    return {
        "promoted": bool(promoted), "status": "promoted" if promoted else "rejected",
        "intercept": round(float(final.intercept_[0]), 6), "logit_slope": round(float(final.coef_[0, 0]), 6),
        "training_samples": len(train), "training_days": len(train), "validation_samples": n,
        "validation_brier_raw": round(raw_brier, 5), "validation_brier_calibrated": round(calibrated_brier, 5),
        "validation_improvement": round(raw_brier-calibrated_brier, 5),
        "validation_observed_all_correct": round(observed, 5),
        "validation_wilson_low": round(max(0, center-margin), 5), "validation_wilson_high": round(min(1, center+margin), 5),
        "top_five": {"samples": len(rows), "observed_all_correct": round(float(np.mean([row["won"] for row in rows])), 5), "mean_raw": round(float(np.mean([row["raw"] for row in rows])), 5)},
        "per_year": per_year,
    }


def totals_production_model(rows, total, weights):
    legacy = rows[:, :21]
    fitted, calibrators = fit_components(legacy, total)
    count = FeatureSubsetTotalsModel(
        CountDistributionTotalsModel(
            fitted, LINES, "negative_binomial", fitted.dispersion_,
        ),
        range(21),
    )
    calibrated = FeatureSubsetTotalsModel(
        MeanCalibratedTotalsModel(fitted, calibrators, LINES),
        range(21),
    )
    direct_mean = mean_model().fit(rows, total)
    actual = np.column_stack([total > line for line in LINES]).astype(int)
    line_models = {
        str(line): Pipeline([
            ("scale", StandardScaler()),
            ("logistic", LogisticRegression(C=.03, max_iter=2500)),
        ]).fit(rows, actual[:, index])
        for index, line in enumerate(LINES)
    }
    direct = TotalsProbabilityModel(direct_mean, line_models, LINES)
    return TotalsModelBlend([count, calibrated, direct], weights)


def main():
    artifacts = Path(os.getenv(
        "NINTH_DEPLOYED_ARTIFACT_DIR",
        os.getenv("NINTH_ARTIFACT_DIR", PRODUCTION_ARTIFACTS),
    ))
    moneyline_report = json.loads((artifacts / "report.json").read_text(encoding="utf8"))
    totals_report = json.loads((artifacts / "totals_report.json").read_text(encoding="utf8"))
    base, _, _, outcome, years, _, _ = moneyline_matrix()
    starter, _ = starter_matrix()
    games, totals_x, total_runs, totals_years, dates, _, _ = totals_matrix()
    moneyline_lineup, _, _ = moneyline_lineup_talent_matrix(games)
    totals_lineup, _, _ = totals_lineup_talent_matrix(games)
    moneyline_x = np.column_stack([base, starter[:, 6:], moneyline_lineup])
    totals_x = np.column_stack([totals_x, totals_lineup])
    if "pitching_availability" in totals_report.get("model", ""):
        _, pitching = pitching_matrix(games)
        totals_x = np.column_stack([totals_x, pitching])
    totals_weights = [
        float(totals_report["count_weight"]),
        float(totals_report["calibrated_weight"]),
        float(totals_report["direct_weight"]),
    ]
    if len(games) != len(outcome) or not np.array_equal(years, totals_years):
        raise RuntimeError("Moneyline and totals histories are not aligned")
    margins = np.asarray([game["home_score"]-game["away_score"] for game in games], float)
    market_rows = {market: [] for market in ("moneyline", "totals", "mixed")}
    for year in sorted(set(years)):
        if year < 2022 or np.sum(years < year) < 4000:
            continue
        train, test = years < year, years == year
        moneyline_probability = fit_moneyline(moneyline_x[train], outcome[train], margins[train]).predict_proba(moneyline_x[test])[:, 1]
        total_model = totals_production_model(
            totals_x[train], total_runs[train], totals_weights,
        )
        total_over = total_model.predict_over_probabilities(totals_x[test])
        for local_index, game_index in enumerate(np.flatnonzero(test)):
            home_p=float(moneyline_probability[local_index]); ml_p=max(home_p,1-home_p); ml_won=int((home_p>=.5)==bool(outcome[game_index]))
            candidates=[]
            for line in DECISION_LINES:
                line_index=LINES.index(line); over_p=float(total_over[local_index,line_index]); is_over=over_p>=.5
                candidates.append((max(over_p,1-over_p),int((total_runs[game_index]>line)==is_over)))
            total_p,total_won=max(candidates,key=lambda item:item[0])
            values={"moneyline":(ml_p,ml_won),"totals":(total_p,total_won),"mixed":(ml_p,ml_won) if ml_p>=total_p else (total_p,total_won)}
            for market,(probability,won) in values.items():
                market_rows[market].append({"date":dates[game_index],"year":int(year),"probability":probability,"won":won})
        print(f"completed rolling-origin {year}", flush=True)
    report={
        "model": "market_aware_joint_card_calibration_v2",
        "moneyline_model": moneyline_report["model"],
        "totals_model": totals_report["model"],
        "selection_policy": "Card calibrators replay the deployed moneyline and totals architectures in rolling-origin folds, fit on 2022-2024 cards, and promote only after a 2025-2026 temporal audit.",
        "markets": {},
    }
    for market,rows in market_rows.items():
        report["markets"][market]={"daily":{},"multiday":{}}
        for legs in range(2,9):
            report["markets"][market]["daily"][str(legs)]=calibration(card_samples(rows,1,legs))
        for horizon in range(2,15):
            report["markets"][market]["multiday"][str(horizon)]={str(legs):calibration(card_samples(rows,horizon,legs)) for legs in range(2,9)}
    OUTPUT.parent.mkdir(parents=True,exist_ok=True);OUTPUT.write_text(json.dumps(report,indent=2),encoding="utf8")
    print(json.dumps(report,indent=2))


if __name__ == "__main__":
    main()
