"""Run NINTH's odds-independent historical research pipeline."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "ml" / "data" / "multisport"
ARTIFACTS = ROOT / "ml" / "artifacts" / "multisport"


def run(*parts: str) -> None:
    subprocess.run(list(parts), cwd=ROOT, check=True)


def train_ledger(path: Path, sport: str, market: str) -> dict:
    output = ARTIFACTS / sport / f"{market}.json"
    run(sys.executable, "-m", "ml.multisport.train", str(path), "--sport", sport, "--market", market, "--output", str(output))
    return json.loads(output.read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sports", default="football,american-football,basketball,esports")
    parser.add_argument("--years", type=int, default=3)
    parser.add_argument("--refresh-sources", action="store_true")
    parser.add_argument("--esports-pages-per-year", type=int, default=4)
    args = parser.parse_args()
    selected = set(args.sports.split(","))
    now = datetime.now()
    current_year = now.year
    if args.refresh_sources and "football" in selected:
        run(sys.executable, "-m", "ml.multisport.collect_football_statsbomb", "--start-year", "2018", "--end-year", "2025")
        run(sys.executable, "-m", "ml.multisport.collect_football_open", "--start-season", "2018", "--end-season", "2025")
    if args.refresh_sources and "american-football" in selected:
        run(sys.executable, "-m", "ml.multisport.collect_nfl_open", "--start-season", "2018", "--advanced-start", "2018")
    if args.refresh_sources and "basketball" in selected:
        run(sys.executable, "-m", "ml.multisport.collect_nba_open", "--start-season", str(current_year - 7), "--end-season", str(current_year))
    if args.refresh_sources and "esports" in selected:
        run("node", "ml/multisport/collect_esports_liquipedia.mjs", "--years", str(args.years), "--max-pages-per-year", str(args.esports_pages_per_year))

    ledgers = []
    for sport in selected - {"esports"}:
        for path in (DATA / sport).glob("*.jsonl"):
            if path.name in {"raw_matches.jsonl", "over_total.jsonl", "live_prediction_audit.jsonl", "score.jsonl"}:
                continue
            if sport == "american-football" and path.stem != "home_win":
                # Fixed-line classifiers such as over_44_5 are superseded by the
                # score distribution's line-aware probability calculation.
                continue
            ledgers.append((path, sport, path.stem))
    if "esports" in selected:
        for discipline in ("valorant", "cs2", "lol"):
            path = DATA / "esports-history" / f"{discipline}_match_winner.jsonl"
            if path.exists() and path.stat().st_size:
                ledgers.append((path, discipline, "match_winner"))
    reports = [train_ledger(*ledger) for ledger in ledgers]
    nfl_score_ledger = DATA / "american-football" / "score.jsonl"
    if "american-football" in selected and nfl_score_ledger.exists() and nfl_score_ledger.stat().st_size:
        nfl_score_report = ARTIFACTS / "american-football" / "score.json"
        run(
            sys.executable, "-m", "ml.multisport.train_nfl_scores", str(nfl_score_ledger),
            "--output", str(nfl_score_report),
            "--model-output", str(nfl_score_report.with_suffix(".joblib")),
        )
        reports.append(json.loads(nfl_score_report.read_text(encoding="utf-8")))
    football_score_ledger = DATA / "football" / "score.jsonl"
    if "football" in selected and football_score_ledger.exists() and football_score_ledger.stat().st_size:
        football_score_report = ARTIFACTS / "football" / "score_distribution.json"
        run(
            sys.executable, "-m", "ml.multisport.train_football_scores", str(football_score_ledger),
            "--output", str(football_score_report),
            "--model-output", str(football_score_report.with_suffix(".joblib")),
        )
        reports.append(json.loads(football_score_report.read_text(encoding="utf-8")))
    output = ARTIFACTS / "historical_readiness.json"
    previous = json.loads(output.read_text(encoding="utf-8")) if output.exists() else {"models": []}
    updated_sports = {row["sport"] for row in reports}
    prior_models = [row for row in previous.get("models", []) if row.get("sport") not in updated_sports]
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(), "odds_independent": True,
        "models": prior_models + [{
            "sport": row["sport"], "market": row["market"],
            "samples": row.get("holdout_results", {}).get("sample_size", row.get("historical_walk_forward", {}).get("samples", 0)),
            "brier": row.get("holdout_results", {}).get("combined", {}).get("candidate", {}).get("brier"),
            "accuracy": row.get("holdout_results", {}).get("combined", {}).get("candidate", {}).get("accuracy"),
            "historical_ready": (
                row.get("historical_readiness", {}).get("passed", False)
                if isinstance(row.get("historical_readiness"), dict)
                else False
            ),
            "production_ready": row.get("promotion", {}).get("passed", False),
        } for row in reports],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
