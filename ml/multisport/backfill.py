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
    current_football_season = current_year if now.month >= 7 else current_year - 1
    if args.refresh_sources and "football" in selected:
        run(sys.executable, "-m", "ml.multisport.collect_football_statsbomb", "--start-year", str(current_year - args.years), "--end-year", str(current_year))
        run(sys.executable, "-m", "ml.multisport.collect_football_open", "--start-season", str(current_year - 6), "--end-season", str(current_football_season))
    if args.refresh_sources and "american-football" in selected:
        run(sys.executable, "-m", "ml.multisport.collect_nfl_open", "--start-season", str(current_year - 12), "--advanced-start", str(current_year - args.years))
    if args.refresh_sources and "basketball" in selected:
        run(sys.executable, "-m", "ml.multisport.collect_nba_open", "--start-season", str(current_year - 7), "--end-season", str(current_year))
    if args.refresh_sources and "esports" in selected:
        run("node", "ml/multisport/collect_esports_liquipedia.mjs", "--years", str(args.years), "--max-pages-per-year", str(args.esports_pages_per_year))

    ledgers = []
    for sport in selected - {"esports"}:
        for path in (DATA / sport).glob("*.jsonl"):
            if path.name in {"raw_matches.jsonl", "over_total.jsonl", "live_prediction_audit.jsonl", "score.jsonl"}:
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
    output = ARTIFACTS / "historical_readiness.json"
    previous = json.loads(output.read_text(encoding="utf-8")) if output.exists() else {"models": []}
    updated_sports = {row["sport"] for row in reports}
    prior_models = [row for row in previous.get("models", []) if row.get("sport") not in updated_sports]
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(), "odds_independent": True,
        "models": prior_models + [{
            "sport": row["sport"], "market": row["market"],
            "samples": row.get("historical_walk_forward", {}).get("samples", 0),
            "brier": row.get("historical_walk_forward", {}).get("candidate", {}).get("brier"),
            "accuracy": row.get("historical_walk_forward", {}).get("candidate", {}).get("accuracy"),
            "historical_ready": row.get("historical_readiness", {}).get("passed", False),
            "production_ready": row.get("promotion", {}).get("passed", False),
        } for row in reports],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
