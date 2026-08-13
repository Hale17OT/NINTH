"""Score immutable pregame prop snapshots against official MLB box scores."""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
SNAPSHOTS = ROOT / "ml" / "data" / "player_prop_projection_snapshots.jsonl"
BOXES = ROOT / "ml" / "data" / "player_boxscores.jsonl"
OUTPUT = ROOT / "ml" / "artifacts" / "live_player_prop_audit.json"

BATTER = {
    "hits": "hits", "total_bases": "totalBases", "home_runs": "homeRuns",
    "runs": "runs", "rbi": "rbi", "walks": "baseOnBalls",
    "stolen_bases": "stolenBases", "doubles": "doubles",
    "triples": "triples", "strikeouts": "strikeOuts",
}
PITCHER = {
    "strikeouts": "strikeOuts", "walks": "baseOnBalls",
    "hits_allowed": "hits", "outs": "outs", "earned_runs": "earnedRuns",
    "home_runs_allowed": "homeRuns", "pitches": "numberOfPitches", "win": "wins",
}


def outcome(section, kind, prop):
    if kind == "batter" and prop == "singles":
        return float(section.get("hits", 0)) - float(section.get("doubles", 0)) \
            - float(section.get("triples", 0)) - float(section.get("homeRuns", 0))
    if kind == "batter" and prop == "hits_runs_rbi":
        return float(section.get("hits", 0)) + float(section.get("runs", 0)) \
            + float(section.get("rbi", 0))
    mapping = BATTER if kind == "batter" else PITCHER
    key = mapping.get(prop)
    return None if not key else float(section.get(key, 0))


def rows(path):
    if not path.exists():
        return []
    return [
        json.loads(line) for line in path.open(encoding="utf-8-sig")
        if line.strip()
    ]


def score(values):
    if not values:
        return {"selections": 0, "brier": None, "accuracy": None, "mean_confidence": None}
    probability = np.asarray([row["probability"] for row in values])
    actual = np.asarray([row["actual"] for row in values])
    return {
        "selections": len(values),
        "brier": round(float(np.mean((probability - actual) ** 2)), 6),
        "accuracy": round(float(np.mean(actual)), 6),
        "mean_confidence": round(float(np.mean(probability)), 6),
    }


def main():
    # Retain the last snapshot recorded before first pitch for each game.
    snapshots = {}
    for row in rows(SNAPSHOTS):
        if row.get("recorded_at", "") < row.get("scheduled_start", ""):
            current = snapshots.get(str(row["game_id"]))
            if current is None or row["recorded_at"] > current["recorded_at"]:
                snapshots[str(row["game_id"])] = row
    boxes = {str(row["game_id"]): row for row in rows(BOXES)}
    evaluated = []
    for game_id, snapshot in snapshots.items():
        box = boxes.get(game_id)
        if not box:
            continue
        players = {}
        for side in ("home", "away"):
            for player in (box.get(side) or {}).get("players", []):
                players[str(player["player_id"])] = player
        for selection in snapshot.get("selections", []):
            player = players.get(str(selection["player_id"]))
            if not player:
                continue
            kind, prop = selection["kind"], selection["prop"]
            section = player.get("batting" if kind == "batter" else "pitching")
            value = outcome(section or {}, kind, prop)
            if not section or value is None:
                continue
            # Pitcher props refer to the starter; invalidate changed starters.
            if kind == "pitcher" and int(section.get("gamesStarted", 0)) != 1:
                continue
            over = value > float(selection["line"])
            actual = int(over if selection["side"] == "over" else not over)
            evaluated.append({
                "game_id": int(game_id), "date": snapshot["game_date"],
                "official_date": box.get("date"),
                "player_id": int(selection["player_id"]),
                "kind": kind, "prop": prop, "player": selection["player_name"],
                "line": selection["line"], "side": selection["side"],
                "probability": float(selection["probability"]), "value": value,
                "actual": actual,
            })
    summaries = {}
    groups = defaultdict(list)
    for row in evaluated:
        groups[f"{row['kind']}:{row['prop']}"].append(row)
    for key, values in sorted(groups.items()):
        summaries[key] = score(values)
    confidence_bands = {}
    one_per_game = {}
    one_per_game_without_home_runs = {}
    for floor in (0, .60, .65, .70):
        eligible = [row for row in evaluated if row["probability"] >= floor]
        confidence_bands[str(floor)] = {
            **score(eligible),
            "coverage": round(len(eligible) / len(evaluated), 6) if evaluated else 0,
        }
        best = {}
        for row in eligible:
            current = best.get(row["game_id"])
            if current is None or row["probability"] > current["probability"]:
                best[row["game_id"]] = row
        one_per_game[str(floor)] = {
            **score(list(best.values())),
            "game_coverage": round(
                len(best) / len({row["game_id"] for row in evaluated}), 6,
            ) if evaluated else 0,
        }
        best_without_home_runs = {}
        for row in eligible:
            if row["prop"] == "home_runs":
                continue
            current = best_without_home_runs.get(row["game_id"])
            if current is None or row["probability"] > current["probability"]:
                best_without_home_runs[row["game_id"]] = row
        one_per_game_without_home_runs[str(floor)] = {
            **score(list(best_without_home_runs.values())),
            "game_coverage": round(
                len(best_without_home_runs) / len({row["game_id"] for row in evaluated}), 6,
            ) if evaluated else 0,
        }
    report = {
        "snapshot_rule": "Last recorded projection before first pitch",
        "completed_games": len({row["game_id"] for row in evaluated}),
        "selections": len(evaluated),
        "overall": score(evaluated),
        "confidence_bands": confidence_bands,
        "automatic_one_per_game": one_per_game,
        "automatic_one_per_game_excluding_home_runs": one_per_game_without_home_runs,
        "by_prop": summaries,
        "rows": evaluated,
    }
    OUTPUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "rows"}, indent=2))


if __name__ == "__main__":
    main()
