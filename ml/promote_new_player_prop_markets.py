"""Guard and merge newly supported MelBet player-prop models into production."""
from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path

import joblib


NEW_MARKETS = {
    "batter:singles", "batter:triples", "batter:hits_runs_rbi", "pitcher:win",
}


def _load_candidate(directory: Path):
    artifact = joblib.load(directory / "player_props.joblib")
    report = json.loads((directory / "player_props_report.json").read_text(encoding="utf-8"))
    return artifact, report


def _eligible(key, report):
    row = report["models"][key]
    unseen = row["unseen"]
    climate = row["climatology"]
    seasons = row.get("unseen_by_season") or {}
    return (
        int(row["samples"]["untouched_2025_2026"]) >= 1000
        and math.isfinite(float(unseen["brier"]))
        and float(unseen["brier"]) < float(climate["brier"])
        and float(row["brier_skill_vs_climatology"]) > 0
        and all(
            int(seasons.get(str(season), {}).get("samples") or 0) >= 250
            for season in (2025, 2026)
        )
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--incumbent-dir", required=True)
    parser.add_argument("--candidate-dir", action="append", required=True)
    parser.add_argument("--state-source", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    incumbent_dir = Path(args.incumbent_dir)
    incumbent = joblib.load(incumbent_dir / "player_props.joblib")
    report = json.loads((incumbent_dir / "player_props_report.json").read_text(encoding="utf-8"))
    candidates = [_load_candidate(Path(value)) for value in args.candidate_dir]
    state_artifact, state_report = _load_candidate(Path(args.state_source))

    selected = {}
    decisions = {}
    for key in sorted(NEW_MARKETS):
        choices = [
            (candidate_report["models"][key]["unseen"]["brier"], candidate, candidate_report)
            for candidate, candidate_report in candidates
            if key in candidate.get("models", {}) and _eligible(key, candidate_report)
        ]
        if not choices:
            raise RuntimeError(f"{key} failed the untouched temporal/climatology promotion gate")
        _, artifact, candidate_report = min(choices, key=lambda value: value[0])
        selected[key] = artifact["models"][key]
        row = candidate_report["models"][key]
        report["models"][key] = {**row, "promotion_source": "new_melbet_market"}
        decisions[key] = {
            "promoted": True,
            "model_type": row["model_type"],
            "unseen_brier": row["unseen"]["brier"],
            "climatology_brier": row["climatology"]["brier"],
            "brier_skill_vs_climatology": row["brier_skill_vs_climatology"],
            "side_accuracy": row["side_accuracy"],
            "unseen_by_season": row.get("unseen_by_season"),
        }

    overlap = NEW_MARKETS & incumbent["models"].keys()
    if overlap:
        raise RuntimeError(f"refusing to overwrite existing markets: {sorted(overlap)}")
    trained_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    output_artifact = {
        **incumbent,
        "trained_at": trained_at,
        "models": {**incumbent["models"], **selected},
        "state": state_artifact["state"],
        "feature_names": state_artifact["feature_names"],
    }
    report.update({
        "trained_at": trained_at,
        "data": state_report["data"],
        "new_market_promotion": {
            "policy": (
                "New markets require at least 1,000 untouched 2025-2026 samples, "
                "at least 250 samples in each season, and lower Brier score than "
                "line-specific climatology. The best passing count/classifier head is selected."
            ),
            "markets": decisions,
        },
    })
    basis = report.setdefault("research_basis", [])
    for item in (
        "Official scorer-awarded pitcher decisions from MLB box scores",
        "Derived official-box-score singles, triples, and hits + runs + RBIs outcomes",
        "Separate untouched 2025 and 2026 temporal reporting for new markets",
    ):
        if item not in basis:
            basis.append(item)

    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    joblib.dump(output_artifact, output / "player_props.joblib", compress=3)
    (output / "player_props_report.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8",
    )
    print(json.dumps(decisions, indent=2))


if __name__ == "__main__":
    main()
