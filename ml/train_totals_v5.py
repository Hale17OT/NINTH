"""Promote the leakage-safe pitcher workload and bullpen totals model."""
from __future__ import annotations

import json
import os
from pathlib import Path

import joblib
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from ml.lineup_talent import TOTAL_FEATURE_NAMES as LINEUP_TALENT_FEATURE_NAMES
from ml.pitching_availability import TOTAL_FEATURE_NAMES as PITCHING_FEATURE_NAMES, serializable_state as serializable_pitching_state
from ml.research_pitching_availability_v1 import pitching_matrix
from ml.totals_features import TOTAL_FEATURE_NAMES, serializable_totals_state
from ml.totals_modeling import CountDistributionTotalsModel, FeatureSubsetTotalsModel, MeanCalibratedTotalsModel, TotalsModelBlend, TotalsProbabilityModel
from ml.train_totals import LINES, DECISION_LINES, matrix
from ml.train_totals_v3 import fit_components, lineup_talent_matrix, mean_model


ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = Path(os.getenv("NINTH_ARTIFACT_DIR", ROOT / "ml" / "artifacts"))
RESEARCH = ARTIFACTS / "pitching_availability_v1_research.json"


def main():
    research = json.loads(RESEARCH.read_text(encoding="utf-8"))
    result = research["totals"]
    if result.get("selected_on_2022_2024") != "combined" or not result.get("promotion_gate", {}).get("passed"):
        raise SystemExit("Pitching totals candidate did not clear the recorded promotion gate")

    games, base, total, _, _, totals_state, context_count = matrix()
    lineup, lineup_state, lineup_coverage = lineup_talent_matrix(games)
    _, pitching, pitching_state = pitching_matrix(games, return_state=True)
    values = np.column_stack([base, lineup, pitching])
    actual = np.column_stack([total > line for line in LINES]).astype(int)

    weights = result["variants"]["combined"]["weights"]
    count_weight = float(weights["count"])
    isotonic_weight = float(weights["isotonic"])
    direct_weight = float(weights["direct"])

    fitted, calibrators = fit_components(values[:, :21], total)
    count_model = FeatureSubsetTotalsModel(
        CountDistributionTotalsModel(fitted, LINES, "negative_binomial", fitted.dispersion_),
        range(21),
    )
    isotonic_model = FeatureSubsetTotalsModel(
        MeanCalibratedTotalsModel(fitted, calibrators, LINES), range(21),
    )
    direct_mean = mean_model().fit(values, total)
    line_models = {
        str(line): Pipeline([
            ("scale", StandardScaler()),
            ("logistic", LogisticRegression(C=.03, max_iter=2500)),
        ]).fit(values, actual[:, index])
        for index, line in enumerate(LINES)
    }
    direct_model = TotalsProbabilityModel(direct_mean, line_models, LINES)
    model = TotalsModelBlend(
        [count_model, isotonic_model, direct_model],
        [count_weight, isotonic_weight, direct_weight],
    )

    incumbent = result["variants"]["incumbent"]
    candidate = result["variants"]["combined"]
    report = {
        "model": "market_free_pitching_availability_distribution_v5",
        "status": "promoted",
        "market_inputs": False,
        "selection_policy": "Starter-workload and individual-bullpen features were fixed before audit, selected on 2022-2024 rolling-origin folds, and promoted only after improving Brier and log loss in 2025 and 2026 separately with a positive paired game-bootstrap interval.",
        "training_games": len(games), "context_games": context_count,
        "trained_through_date": games[-1]["date"],
        "features": TOTAL_FEATURE_NAMES + LINEUP_TALENT_FEATURE_NAMES + PITCHING_FEATURE_NAMES,
        "lineup_talent_coverage": lineup_coverage,
        "lines": LINES, "decision_lines": DECISION_LINES,
        "count_weight": count_weight, "calibrated_weight": isotonic_weight,
        "direct_weight": direct_weight,
        "development_2022_2024": candidate["development"],
        "unseen_2025_2026": result["selected_audit"],
        "unseen_recommended": result["selected_audit_recommended"],
        "per_year": {"2025": candidate["2025"], "2026": candidate["2026"]},
        "incumbent_comparison": {
            "development": incumbent["development"],
            "2025": incumbent["2025"], "2026": incumbent["2026"],
        },
        "brier_improvement": {
            period: round(incumbent[period]["mean_brier"] - candidate[period]["mean_brier"], 5)
            for period in ("development", "2025", "2026")
        },
        "audit_bootstrap": result["selected_audit_bootstrap"],
        "yearly_bootstrap": result["selected_yearly_bootstrap"],
        "promotion_gate": result["promotion_gate"],
        "prediction_interval_residuals": {
            "lower_80": round(float(np.quantile(total - direct_mean.predict(values), .1)), 3),
            "upper_80": round(float(np.quantile(total - direct_mean.predict(values), .9)), 3),
        },
        "research_basis": [
            "Pregame-only individual pitcher histories",
            "Starter pitch-count, efficiency, velocity, xwOBA, and rest context",
            "Reliever-level regressed xwOBA/K-BB quality and recent workload",
            "Chronological rolling-origin selection",
            "Brier and binary log-loss scoring across six total lines",
        ],
    }
    bundle = {
        "model_version": 5, "model": model,
        "state": serializable_totals_state(totals_state),
        "lineup_talent_state": lineup_state,
        "pitching_availability_state": serializable_pitching_state(pitching_state),
        "trained_through_date": games[-1]["date"],
        "features": report["features"],
        "feature_reference": np.median(values, axis=0).tolist(),
        "report": report,
    }
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    candidate_path = ARTIFACTS / "totals_v5_candidate.joblib"
    joblib.dump(bundle, candidate_path)
    # Verify serialization and model shape before replacing the live artifact.
    loaded = joblib.load(candidate_path)
    sample = values[-5:]
    probability = loaded["model"].predict_over_probabilities(sample)
    if probability.shape != (5, len(LINES)) or not np.all(np.isfinite(probability)):
        raise RuntimeError("Serialized totals candidate failed prediction verification")
    os.replace(candidate_path, ARTIFACTS / "totals.joblib")
    (ARTIFACTS / "totals_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
