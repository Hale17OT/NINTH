"""Settle the complete archived MelBet player-prop board.

This ledger is intentionally distinct from recommendation and Build Best audits:
it retains every priced candidate so future within-game rerankers can learn from
selected and unselected alternatives without selection bias.
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from ml.evaluate_player_prop_builds import jsonl, odds_bucket, settle, summarize


ROOT = Path(__file__).resolve().parents[1]
BOARDS = ROOT / "ml" / "data" / "player_prop_priced_board_snapshots.jsonl"
BOXES = ROOT / "ml" / "data" / "player_boxscores.jsonl"
OUTPUT = ROOT / "ml" / "artifacts" / "player_prop_priced_board_audit.json"


def parse_time(value: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def evaluated_rows() -> list[dict]:
    boxes = {int(row["game_id"]): row for row in jsonl(BOXES)}
    latest = {}
    for snapshot in jsonl(BOARDS):
        game_id = int(snapshot.get("game_id") or 0)
        recorded = parse_time(snapshot.get("recorded_at"))
        scheduled = parse_time(snapshot.get("scheduled_start"))
        if not game_id or not recorded or (scheduled and recorded > scheduled):
            continue
        if game_id not in latest or recorded > latest[game_id][0]:
            latest[game_id] = (recorded, snapshot)
    rows = []
    for game_id, (_, snapshot) in latest.items():
        for candidate in snapshot.get("candidates") or []:
            result = settle({**candidate, "game_id": game_id}, boxes)
            if result["status"] not in ("win", "loss"):
                continue
            probability = float(candidate.get("model_probability") or .5)
            rows.append({
                **candidate,
                "game_id": game_id,
                "official_date": snapshot.get("official_date") or snapshot.get("game_date"),
                "snapshot_at": snapshot.get("recorded_at"),
                "probability": probability,
                "actual": int(result["status"] == "win"),
                "value": result.get("value"),
            })
    return rows


def main() -> None:
    rows = evaluated_rows()
    groups = defaultdict(list)
    line_groups = defaultdict(list)
    odds_groups = defaultdict(list)
    line_odds_groups = defaultdict(list)
    for row in rows:
        market = f"{row['kind']}:{row['prop']}:{row['side']}"
        line = f"{float(row['line']):g}"
        odds = odds_bucket(row.get("decimal_odds"))
        groups[market].append(row)
        line_groups[f"{market}:{line}"].append(row)
        odds_groups[f"{market}:{odds}"].append(row)
        line_odds_groups[f"{market}:{line}:{odds}"].append(row)
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "basis": "Last complete priced MelBet board archived before first pitch",
        "overall": summarize(rows),
        "by_market_side": {key: summarize(values) for key, values in sorted(groups.items())},
        "by_market_side_line": {
            key: summarize(values) for key, values in sorted(line_groups.items())
        },
        "by_market_side_odds": {
            key: summarize(values) for key, values in sorted(odds_groups.items())
        },
        "by_market_side_line_odds": {
            key: summarize(values) for key, values in sorted(line_odds_groups.items())
        },
        "paired_price_samples": sum(row.get("sportsbook_probability") is not None for row in rows),
        "rows": rows,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    temporary = OUTPUT.with_suffix(OUTPUT.suffix + ".tmp")
    temporary.write_text(json.dumps(report, indent=2), encoding="utf-8")
    temporary.replace(OUTPUT)
    print(json.dumps({key: value for key, value in report.items() if key != "rows"}, indent=2))


if __name__ == "__main__":
    main()
