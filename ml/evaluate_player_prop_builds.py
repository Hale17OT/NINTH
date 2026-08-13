"""Audit the exact Player Props Build Best selections against official results.

Unlike the projection-board audit, this report preserves the selection process:
odds floor, card style, direction, market filter, within-game rank and rotation
depth. Repeated clicks on the same selection do not create extra evidence.
"""
from __future__ import annotations

import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BUILDS = ROOT / "ml" / "data" / "player_prop_build_snapshots.jsonl"
BOXES = ROOT / "ml" / "data" / "player_boxscores.jsonl"
OUTPUT = ROOT / "ml" / "artifacts" / "live_player_prop_build_audit.json"

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


def jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    values = []
    for raw in path.read_bytes().replace(b"\x00", b"").decode("utf-8-sig").splitlines():
        if not raw.strip():
            continue
        try:
            values.append(json.loads(raw))
        except json.JSONDecodeError:
            continue
    return values


def odds_bucket(value) -> str:
    if value in (None, "", "all"):
        return "all"
    try:
        floor = float(value)
    except (TypeError, ValueError):
        return "all"
    if floor < 1.2:
        return "under_1.20"
    if floor < 1.3:
        return "1.20"
    if floor < 1.4:
        return "1.30"
    if floor < 1.5:
        return "1.40"
    return "1.50_plus"


def rotation_bucket(value) -> str:
    depth = max(0, int(value or 0))
    return "0" if depth == 0 else "1" if depth == 1 else "2_plus"


def rank_bucket(value) -> str:
    rank = max(1, int(value or 1))
    return "1" if rank == 1 else "2" if rank == 2 else "3_plus"


def filter_bucket(build: dict) -> str:
    preset = str(build.get("prop_preset") or "").lower()
    if preset in ("strongest", "included"):
        return preset
    selected = build.get("selected_prop_types") or []
    return "focused" if 0 < len(selected) <= 7 else "broad"


def process_keys(row: dict) -> dict[str, str]:
    style = row["build_style"]
    odds = row["odds_bucket"]
    rotation = row["rotation_bucket"]
    rank = row["rank_bucket"]
    market = f"{row['kind']}:{row['prop']}:{row['side']}"
    filter_name = row["filter_bucket"]
    action = row["selection_action"]
    return {
        "by_action_style_odds_rotation": f"{action}|{style}|{odds}|{rotation}",
        "by_market_action_style_odds_rotation": f"{market}|{action}|{style}|{odds}|{rotation}",
        "by_style": style,
        "by_style_odds": f"{style}|{odds}",
        "by_style_odds_rotation": f"{style}|{odds}|{rotation}",
        "by_style_odds_rotation_rank": f"{style}|{odds}|{rotation}|{rank}",
        "by_filter_style_odds": f"{filter_name}|{style}|{odds}",
        "by_market_style_odds_rotation": f"{market}|{style}|{odds}|{rotation}",
    }


def _outcome(section: dict, kind: str, prop: str) -> float | None:
    if kind == "batter" and prop == "singles":
        return float(section.get("hits", 0)) - float(section.get("doubles", 0)) \
            - float(section.get("triples", 0)) - float(section.get("homeRuns", 0))
    if kind == "batter" and prop == "hits_runs_rbi":
        return sum(float(section.get(key, 0)) for key in ("hits", "runs", "rbi"))
    field = (BATTER if kind == "batter" else PITCHER).get(prop)
    return None if not field else float(section.get(field, 0))


def settle(entry: dict, boxes: dict[int, dict]) -> dict:
    box = boxes.get(int(entry["game_id"]))
    if not box:
        return {"status": "unresolved", "reason": "exact game box score unavailable"}
    player = next((
        player for side in ("home", "away")
        for player in (box.get(side) or {}).get("players", [])
        if int(player.get("player_id") or 0) == int(entry["player_id"])
    ), None)
    if not player:
        return {"status": "unresolved", "reason": "player absent from exact game box score"}
    kind = entry["kind"]
    section = player.get("batting" if kind == "batter" else "pitching") or {}
    participation = section.get("plateAppearances") if kind == "batter" else section.get("battersFaced")
    if int(participation or 0) <= 0:
        return {"status": "unresolved", "reason": "no player participation"}
    if kind == "pitcher" and int(section.get("gamesStarted") or 0) != 1:
        return {"status": "unresolved", "reason": "listed pitcher did not start"}
    value = _outcome(section, kind, entry["prop"])
    if value is None:
        return {"status": "unresolved", "reason": "unsupported settlement field"}
    line = float(entry["line"])
    if value == line:
        return {"status": "push", "value": value}
    won = (value > line) == (entry["side"] == "over")
    return {"status": "win" if won else "loss", "value": value}


def wilson_lower(wins: int, samples: int, z: float = 1.645) -> float | None:
    if samples <= 0:
        return None
    rate = wins / samples
    denominator = 1 + z * z / samples
    centre = rate + z * z / (2 * samples)
    margin = z * math.sqrt(rate * (1 - rate) / samples + z * z / (4 * samples * samples))
    return max(0.0, (centre - margin) / denominator)


def calibration_ratio(accuracy: float, confidence: float) -> float:
    if accuracy <= .5 or confidence <= .5:
        return .5
    return max(.5, min(1.0, (accuracy - .5) / (confidence - .5)))


def summarize(values: list[dict]) -> dict:
    samples = len(values)
    if not samples:
        return {"samples": 0}
    wins = sum(row["actual"] for row in values)
    accuracy = wins / samples
    mean_confidence = sum(row["probability"] for row in values) / samples
    brier = sum((row["probability"] - row["actual"]) ** 2 for row in values) / samples
    sportsbook = [row["sportsbook_probability"] for row in values if row.get("sportsbook_probability") is not None]
    return {
        "samples": samples,
        "wins": wins,
        "accuracy": round(accuracy, 6),
        "mean_confidence": round(mean_confidence, 6),
        "mean_sportsbook_probability": round(sum(sportsbook) / len(sportsbook), 6) if sportsbook else None,
        "paired_price_samples": len(sportsbook),
        "brier": round(brier, 6),
        "lower_bound": round(wilson_lower(wins, samples), 6),
        "confidence_multiplier": round(calibration_ratio(accuracy, mean_confidence), 6),
    }


def evaluated_rows(builds: list[dict], boxes: dict[int, dict], before_date: str | None = None) -> list[dict]:
    rotations = defaultdict(int)
    unique = {}
    for build in sorted(builds, key=lambda row: row.get("recorded_at") or ""):
        if build.get("shadow_test"):
            continue
        official_date = str(build.get("start_date") or "")[:10]
        if before_date and official_date >= before_date:
            continue
        style = str(build.get("build_style") or "balanced").lower()
        configuration = (
            official_date, style, str(build.get("build_side") or "both"),
            str(build.get("minimum_odds") or "all"),
            str(build.get("recommendation_cutoff") or "0.65"),
            tuple(sorted(build.get("selected_prop_types") or [])),
            tuple(sorted((build.get("selected_prop_sides") or {}).items())),
            str(build.get("prop_preset") or "included"),
        )
        inferred_rotation = rotations[configuration]
        depth = int(build.get("rotation_depth") if build.get("rotation_depth") is not None else inferred_rotation)
        rotations[configuration] += 1
        for entry in build.get("entries") or []:
            result = settle(entry, boxes)
            if result["status"] not in ("win", "loss"):
                continue
            row = {
                **entry,
                "official_date": entry.get("official_date") or official_date,
                "build_style": style,
                "build_side": str(build.get("build_side") or "both"),
                "minimum_odds": str(build.get("minimum_odds") or "all"),
                "odds_bucket": odds_bucket(build.get("minimum_odds")),
                "rotation_depth": depth,
                "rotation_bucket": rotation_bucket(depth),
                "candidate_rank": int(entry.get("candidate_rank") or 1),
                "rank_bucket": rank_bucket(entry.get("candidate_rank")),
                "filter_bucket": filter_bucket(build),
                "selection_action": str(entry.get("selection_action") or build.get("selection_action") or "build_best"),
                "forward_test_policy_id": build.get("forward_test_policy_id"),
                "probability": float(entry.get("process_probability") or entry.get("robust_probability") or entry.get("recommendation_probability") or .5),
                "sportsbook_probability": entry.get("sportsbook_probability"),
                "actual": int(result["status"] == "win"),
                "value": result.get("value"),
            }
            # Repeated UI actions for the same process/selection are one trial.
            key = (
                row["official_date"], int(row["game_id"]), int(row["player_id"]),
                row["kind"], row["prop"], row["side"], float(row["line"]),
                row["build_style"], row["odds_bucket"], row["rotation_bucket"],
                row["rank_bucket"], row["filter_bucket"],
                row["selection_action"],
                row.get("forward_test_policy_id"),
            )
            unique.setdefault(key, row)
    return list(unique.values())


def build_report(values: list[dict]) -> dict:
    groups = {name: defaultdict(list) for name in (
        "by_action_style_odds_rotation", "by_market_action_style_odds_rotation",
        "by_style", "by_style_odds", "by_style_odds_rotation",
        "by_style_odds_rotation_rank", "by_filter_style_odds",
        "by_market_style_odds_rotation",
    )}
    for row in values:
        for name, key in process_keys(row).items():
            groups[name][key].append(row)
    forward_groups = defaultdict(list)
    for row in values:
        forward_groups[str(row.get("forward_test_policy_id") or "legacy")].append(row)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "basis": "Unique exact Build Best selections settled from official MLB box scores",
        "selection_dimensions": ["odds_floor", "rank", "market_filter", "build_style", "rotation_depth", "selection_action", "forward_policy"],
        "overall": summarize(values),
        "by_forward_policy": {key: summarize(rows) for key, rows in sorted(forward_groups.items())},
        **{
            name: {key: summarize(rows) for key, rows in sorted(values_by_key.items())}
            for name, values_by_key in groups.items()
        },
        "rows": values,
    }


def main() -> None:
    builds = jsonl(BUILDS)
    boxes = {int(row["game_id"]): row for row in jsonl(BOXES)}
    report = build_report(evaluated_rows(builds, boxes))
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    temporary = OUTPUT.with_suffix(OUTPUT.suffix + ".tmp")
    temporary.write_text(json.dumps(report, indent=2), encoding="utf-8")
    temporary.replace(OUTPUT)
    print(json.dumps({key: value for key, value in report.items() if key != "rows"}, indent=2))


if __name__ == "__main__":
    main()
