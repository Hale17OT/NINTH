"""Freeze one Player Props selection policy per Eastern-date slate.

The file is immutable for the date unless --force is explicitly supplied. This
keeps live cards as honest forward observations while audits and models continue
to learn after settlement.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from ml.player_prop_reranker_shadow_config import candidate_definition


ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "ml" / "artifacts"
OUTPUT = ARTIFACTS / "player_prop_forward_policy.json"
HISTORY = ROOT / "ml" / "data" / "player_prop_forward_policies.jsonl"
AUDITS = (
    ARTIFACTS / "live_player_prop_audit.json",
    ARTIFACTS / "live_player_prop_build_audit.json",
    ARTIFACTS / "player_props_report.json",
    ARTIFACTS / "player_prop_reranker_shadow_candidate.json",
)


def digest(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def freeze(force: bool = False, policy_date: str | None = None) -> dict:
    eastern_now = datetime.now(timezone.utc).astimezone(ZoneInfo("America/New_York"))
    policy_date = policy_date or eastern_now.date().isoformat()
    if OUTPUT.exists() and not force:
        try:
            current = json.loads(OUTPUT.read_text(encoding="utf-8"))
            if current.get("policy_date") == policy_date:
                return {**current, "reused": True}
        except (OSError, json.JSONDecodeError):
            pass
    hashes = {path.name: digest(path) for path in AUDITS}
    identity = hashlib.sha256(json.dumps({
        "policy_date": policy_date, "hashes": hashes,
        "version": "within_game_v1-shadow-sweep3-odds1.30-probability0.65",
    }, sort_keys=True).encode()).hexdigest()[:16]
    report = {
        "policy_id": f"{policy_date}-within-game-v1-{identity}",
        "policy_date": policy_date,
        "frozen_at": eastern_now.isoformat(),
        "training_through": (datetime.fromisoformat(policy_date).date() - timedelta(days=1)).isoformat(),
        "reranker_version": "within_game_v1",
        "reranker_promoted": False,
        "shadow_candidate": candidate_definition(),
        "line_clearance_ranking_weight": .035,
        "sportsbook_disagreement_ranking_weight": .35,
        "unpaired_price_fragility_penalty": .015,
        "market_side_caps": {"sweep": 2, "balanced": 3},
        "audit_sha256": hashes,
        "reused": False,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    temporary = OUTPUT.with_suffix(OUTPUT.suffix + ".tmp")
    temporary.write_text(json.dumps(report, indent=2), encoding="utf-8")
    temporary.replace(OUTPUT)
    HISTORY.parent.mkdir(parents=True, exist_ok=True)
    with HISTORY.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(report, separators=(",", ":")) + "\n")
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--date")
    args = parser.parse_args()
    print(json.dumps(freeze(args.force, args.date)))


if __name__ == "__main__":
    main()
