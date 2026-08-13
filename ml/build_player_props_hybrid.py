"""Build a guarded per-market player-prop artifact.

The full challenger is never promoted as one indivisible package. A market is
replaced only when it improves Brier score in 2025 and 2026 separately while
keeping side accuracy stable. Markets that fail remain on the incumbent model,
but all models use the challenger's current point-in-time state at inference.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import joblib


def artifact_result(audit, path):
    wanted = Path(path).resolve()
    for row in audit["artifacts"]:
        if Path(row["artifact"]).resolve() == wanted:
            return row
    raise KeyError(f"no audit result for {wanted}")


def weighted(rows, key):
    total = sum(int(row.get("samples") or 0) for row in rows)
    if not total:
        return None
    return sum(
        int(row["samples"]) * float(row[key])
        for row in rows if row.get(key) is not None
    ) / total


def aggregate(rows):
    return {
        "samples": sum(int(row.get("samples") or 0) for row in rows),
        "brier": weighted(rows, "brier"),
        "log_loss": weighted(rows, "log_loss"),
        "side_accuracy": weighted(rows, "side_accuracy"),
        "mean_confidence": weighted(rows, "mean_confidence"),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--incumbent-artifact", required=True)
    parser.add_argument("--incumbent-report", required=True)
    parser.add_argument("--candidate-artifact", required=True)
    parser.add_argument("--candidate-report", required=True)
    parser.add_argument("--audit", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--accuracy-tolerance", type=float, default=.001)
    args = parser.parse_args()

    incumbent = joblib.load(args.incumbent_artifact)
    candidate = joblib.load(args.candidate_artifact)
    incumbent_report = json.loads(Path(args.incumbent_report).read_text(encoding="utf8"))
    candidate_report = json.loads(Path(args.candidate_report).read_text(encoding="utf8"))
    audit = json.loads(Path(args.audit).read_text(encoding="utf8"))
    incumbent_audit = artifact_result(audit, args.incumbent_artifact)
    candidate_audit = artifact_result(audit, args.candidate_artifact)

    models, reports, decisions = {}, {}, {}
    selected_temporal, incumbent_temporal = [], []
    selected_exact, incumbent_exact = [], []
    for key, incumbent_model in incumbent["models"].items():
        old_temporal = incumbent_audit["all_threshold_temporal"][key]
        if key not in candidate.get("models", {}):
            model = incumbent_model
            model["feature_names"] = (
                incumbent.get("feature_names") or {}
            ).get(model["kind"])
            models[key] = model
            reports[key] = {
                **incumbent_report["models"][key],
                "promotion_source": "incumbent",
                "guarded_temporal_audit": old_temporal,
                "challenger_clustered_brier_skill": (
                    (candidate_report.get("models") or {}).get(key, {}).get("clustered_brier_skill")
                ),
            }
            decisions[key] = {
                "promoted": False,
                "reason": "No challenger was trained for this market; incumbent retained.",
                "per_season": {},
            }
            selected_temporal.append(old_temporal["2025_2026"])
            incumbent_temporal.append(old_temporal["2025_2026"])
            old_exact = incumbent_audit["exact_listed_lines"]["by_prop"].get(key)
            if old_exact:
                selected_exact.append(old_exact)
                incumbent_exact.append(old_exact)
            continue
        new_temporal = candidate_audit["all_threshold_temporal"][key]
        per_season = {}
        stable = True
        for season in ("2025", "2026"):
            old = old_temporal[season]; new = new_temporal[season]
            season_pass = (
                new["brier"] < old["brier"]
                and new["side_accuracy"]
                >= old["side_accuracy"] - args.accuracy_tolerance
            )
            per_season[season] = {
                "incumbent_brier": old["brier"],
                "candidate_brier": new["brier"],
                "brier_improvement": old["brier"] - new["brier"],
                "incumbent_accuracy": old["side_accuracy"],
                "candidate_accuracy": new["side_accuracy"],
                "passed": season_pass,
            }
            stable &= season_pass
        aggregate_pass = (
            new_temporal["2025_2026"]["brier"]
            < old_temporal["2025_2026"]["brier"]
        )
        new_exact = candidate_audit["exact_listed_lines"]["by_prop"].get(key)
        old_exact = incumbent_audit["exact_listed_lines"]["by_prop"].get(key)
        exact_pass = True
        if old_exact and new_exact and min(old_exact["samples"], new_exact["samples"]) >= 80:
            exact_pass = (
                new_exact["brier"] <= old_exact["brier"]
                and new_exact["side_accuracy"] >= old_exact["side_accuracy"]
            )
        promote = bool(stable and aggregate_pass and exact_pass)
        source_artifact = candidate if promote else incumbent
        source_report = candidate_report if promote else incumbent_report
        model = source_artifact["models"][key]
        model["feature_names"] = (
            source_artifact.get("feature_names") or {}
        ).get(model["kind"])
        models[key] = model
        reports[key] = {
            **source_report["models"][key],
            "promotion_source": "candidate" if promote else "incumbent",
            "guarded_temporal_audit": new_temporal if promote else old_temporal,
            "challenger_clustered_brier_skill": (
                candidate_report["models"][key].get("clustered_brier_skill")
            ),
        }
        decisions[key] = {
            "promoted": promote,
            "reason": (
                "Candidate improved Brier in 2025 and 2026 with stable side accuracy."
                if promote else
                "Incumbent retained because the candidate failed a separate-season, accuracy, or exact-listed-line gate."
            ),
            "per_season": per_season,
            "exact_listed_line_gate": {
                "passed": exact_pass,
                "incumbent": old_exact,
                "candidate": new_exact,
            },
        }
        selected_temporal.append(
            (new_temporal if promote else old_temporal)["2025_2026"]
        )
        incumbent_temporal.append(old_temporal["2025_2026"])
        if (new_exact if promote else old_exact):
            selected_exact.append(new_exact if promote else old_exact)
        if old_exact:
            incumbent_exact.append(old_exact)

    selected_summary = aggregate(selected_temporal)
    incumbent_summary = aggregate(incumbent_temporal)
    promoted = [key for key, row in decisions.items() if row["promoted"]]
    if not promoted or selected_summary["brier"] >= incumbent_summary["brier"]:
        raise RuntimeError(
            "hybrid promotion gate failed: no material artifact-wide Brier improvement"
        )

    trained_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    artifact = {
        "version": 3,
        "trained_at": trained_at,
        "models": models,
        "state": candidate["state"],
        "feature_names": candidate["feature_names"],
    }
    report = {
        **candidate_report,
        "version": 3,
        "trained_at": trained_at,
        "research_basis": [
            "Point-in-time empirical-Bayes player shrinkage",
            "Explicit plate-appearance and batters-faced opportunity",
            "Opponent game-level tendencies and probable-starter quality",
            "Handedness-split prior Statcast contact quality",
            "Beta, sigmoid, isotonic, and raw calibration selected on 2024 only",
            "Monotone threshold probability enforcement",
            "Guarded per-market hybrid promotion on 2025 and 2026 separately",
            "Exact immutable listed-line replay for markets with sufficient samples",
            "Confirmed opponent-lineup contact, strikeout, walk, and power tendencies",
        ],
        "models": reports,
        "selection_policy": (
            "Per-market candidates must improve Brier in 2025 and 2026 "
            "separately, keep side accuracy within 0.1 percentage point, and "
            "avoid regressing sufficiently sampled exact listed lines."
        ),
        "hybrid_selection": decisions,
        "hybrid_audit": {
            "incumbent_all_thresholds": incumbent_summary,
            "selected_all_thresholds": selected_summary,
            "brier_improvement": (
                incumbent_summary["brier"] - selected_summary["brier"]
            ),
            "incumbent_exact_listed_lines": aggregate(incumbent_exact),
            "selected_exact_listed_lines": aggregate(selected_exact),
            "promoted_markets": promoted,
            "retained_markets": [
                key for key in decisions if key not in promoted
            ],
        },
    }
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    joblib.dump(artifact, output / "player_props.joblib", compress=3)
    (output / "player_props_report.json").write_text(
        json.dumps(report, indent=2), encoding="utf8",
    )
    print(json.dumps(report["hybrid_audit"], indent=2))


if __name__ == "__main__":
    main()
