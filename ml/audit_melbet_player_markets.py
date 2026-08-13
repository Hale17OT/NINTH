"""Inventory current MelBet MLB player-market shapes without retaining prices."""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "stats-service"))

import app  # noqa: E402


def audit():
    championship = app._melbet_champ_payload()
    groups = defaultdict(lambda: {
        "events": 0, "players": set(), "thresholds": set(),
        "selection_types": set(), "decimal_odds": [], "shape_counts": Counter(),
    })
    games_checked = 0
    for game in championship.get("G", []):
        if not game.get("CI"):
            continue
        try:
            main = app._melbet_game_payload(game["CI"])
            linked = [*main.get("SG", []), *main.get("BIG", [])]
            subgame = next((
                row for row in linked
                if "player" in str(row.get("TG", "")).lower() and row.get("CI")
            ), None)
            if not subgame:
                continue
            payload = app._melbet_complete_player_payload(subgame["CI"])
            games_checked += 1
            for group in payload.get("GE", []):
                group_id = int(group.get("G", 0))
                rows = app._melbet_event_rows(group.get("E", []))
                summary = groups[group_id]
                summary["events"] += 1
                by_player_line = defaultdict(set)
                for row in rows:
                    player = (row.get("PL") or {}).get("N")
                    if player:
                        summary["players"].add(app._normalize_player_market_name(player))
                    if row.get("P") is not None:
                        summary["thresholds"].add(float(row["P"]))
                    if row.get("T") is not None:
                        summary["selection_types"].add(int(row["T"]))
                    if row.get("C") is not None and float(row["C"]) > 1:
                        summary["decimal_odds"].append(float(row["C"]))
                    by_player_line[(player, row.get("P"))].add(row.get("T"))
                two_sided = sum(len(types) >= 2 for types in by_player_line.values())
                one_sided = sum(len(types) == 1 for types in by_player_line.values())
                unthresholded = sum(line is None for _, line in by_player_line)
                summary["shape_counts"].update({
                    "two_sided_player_lines": two_sided,
                    "one_sided_player_lines": one_sided,
                    "unthresholded_player_selections": unthresholded,
                })
        except Exception as exc:  # noqa: BLE001 - an audit should continue past one event
            print(f"WARNING event {game.get('CI')} skipped: {exc}", file=sys.stderr)
    return {
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "source_hosts": [championship.get("_ninth_melbet_host")],
        "individual_prices_retained": False,
        "decimal_odds_audited": True,
        "decimal_odds_used_as_model_inputs": False,
        "games_checked": games_checked,
        "groups": {
            str(group_id): {
                "mapped_prop": app.MELBET_PLAYER_PROP_GROUPS.get(group_id),
                "melbet_market_name": (app.MELBET_PLAYER_PROP_MARKETS.get(group_id) or {}).get("name"),
                "player_kind": (app.MELBET_PLAYER_PROP_MARKETS.get(group_id) or {}).get("kind"),
                "selection_format": (app.MELBET_PLAYER_PROP_MARKETS.get(group_id) or {}).get("format"),
                "known_selection_sides": (app.MELBET_PLAYER_PROP_MARKETS.get(group_id) or {}).get("types", {}),
                "events": value["events"],
                "players": len(value["players"]),
                "thresholds": sorted(value["thresholds"]),
                "selection_types": sorted(value["selection_types"]),
                "priced_selections": len(value["decimal_odds"]),
                "decimal_odds_range": [min(value["decimal_odds"]), max(value["decimal_odds"])] if value["decimal_odds"] else None,
                **dict(value["shape_counts"]),
            }
            for group_id, value in sorted(groups.items())
        },
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        default=str(ROOT / "ml" / "artifacts" / "melbet_player_market_audit.json"),
    )
    args = parser.parse_args()
    report = audit()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({
        "output": str(output),
        "games_checked": report["games_checked"],
        "groups": len(report["groups"]),
    }))


if __name__ == "__main__":
    main()
