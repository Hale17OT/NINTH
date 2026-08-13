"""Blind, point-in-time replay of recorded Player Props Build Best candidates.

The replay never substitutes an adjacent game for a missing settlement. It uses
only exact MLB game/player identifiers, applies calibration evidence dated
strictly before the game being replayed, and leaves unavailable opposite-side
prices or non-participants unresolved instead of inferring an outcome.
"""
from __future__ import annotations

import argparse
import bisect
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BUILDS = ROOT / "ml" / "data" / "player_prop_build_snapshots.jsonl"
PROJECTIONS = ROOT / "ml" / "data" / "player_prop_projection_snapshots.jsonl"
BOXES = ROOT / "ml" / "data" / "player_boxscores.jsonl"
AUDIT = ROOT / "ml" / "artifacts" / "live_player_prop_audit.json"
MODEL_REPORT = ROOT / "ml" / "artifacts" / "player_props_report.json"
OUTPUT = ROOT / "ml" / "artifacts" / "player_prop_builder_blind_replay.json"

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
        if raw.strip():
            values.append(json.loads(raw))
    return values


def segment_key(row: dict) -> str:
    return f"{row['kind']}:{row['prop']}:{row['side']}:{float(row['line']):g}"


def calibration_ratio(values: list[dict]) -> float:
    if not values:
        return .5
    accuracy = sum(int(row.get("actual") or 0) for row in values) / len(values)
    confidence = sum(float(row.get("probability") or 0) for row in values) / len(values)
    if accuracy <= .5 or confidence <= .5:
        return .5
    return max(.5, min(1.0, (accuracy - .5) / (confidence - .5)))


def wilson(values: list[dict], z: float = 1.645) -> float | None:
    if not values:
        return None
    samples = len(values)
    rate = sum(int(row.get("actual") or 0) for row in values) / samples
    denominator = 1 + z * z / samples
    centre = rate + z * z / (2 * samples)
    margin = z * math.sqrt(rate * (1 - rate) / samples + z * z / (4 * samples * samples))
    return max(0.0, (centre - margin) / denominator)


def outcome(section: dict, kind: str, prop: str) -> float | None:
    if kind == "batter" and prop == "singles":
        return float(section.get("hits", 0)) - float(section.get("doubles", 0)) \
            - float(section.get("triples", 0)) - float(section.get("homeRuns", 0))
    if kind == "batter" and prop == "hits_runs_rbi":
        return float(section.get("hits", 0)) + float(section.get("runs", 0)) \
            + float(section.get("rbi", 0))
    field = (BATTER if kind == "batter" else PITCHER).get(prop)
    return None if not field else float(section.get(field, 0))


def settle(entry: dict, boxes: dict[int, dict]) -> dict:
    box = boxes.get(int(entry["game_id"]))
    if not box:
        return {"status": "unresolved", "reason": "exact game box score unavailable"}
    player = next((player for side in ("home", "away")
                   for player in (box.get(side) or {}).get("players", [])
                   if int(player.get("player_id") or 0) == int(entry["player_id"])), None)
    if not player:
        return {"status": "unresolved", "reason": "player absent from exact game box score"}
    kind = entry["kind"]
    section = player.get("batting" if kind == "batter" else "pitching") or {}
    if not section:
        return {"status": "unresolved", "reason": f"no {kind} participation"}
    if kind == "pitcher" and int(section.get("gamesStarted") or 0) != 1:
        return {"status": "unresolved", "reason": "listed pitcher did not start"}
    value = outcome(section, kind, entry["prop"])
    if value is None:
        return {"status": "unresolved", "reason": "unsupported settlement field"}
    line = float(entry["line"])
    if value == line:
        status = "push"
    elif entry["side"] == "over":
        status = "win" if value > line else "loss"
    else:
        status = "win" if value < line else "loss"
    return {"status": status, "value": value, "official_date": box.get("date")}


def point_in_time_policy(prior: list[dict], deployed: set[str]) -> dict:
    markets = defaultdict(list)
    exact = defaultdict(list)
    for row in prior:
        market = f"{row.get('kind')}:{row.get('prop')}"
        if market not in deployed:
            continue
        markets[market].append(row)
        exact[(market, segment_key(row))].append(row)

    top_by_game = {}
    for row in prior:
        if row.get("prop") == "home_runs":
            continue
        current = top_by_game.get(row.get("game_id"))
        if current is None or float(row.get("probability") or 0) > float(current.get("probability") or 0):
            top_by_game[row.get("game_id")] = row
    selected_rows = list(top_by_game.values())
    selected_exact = defaultdict(list)
    for row in selected_rows:
        market = f"{row.get('kind')}:{row.get('prop')}"
        if market in deployed:
            selected_exact[(market, segment_key(row))].append(row)
    global_selected = [row for row in selected_rows if float(row.get("probability") or 0) >= .65]
    return {
        "markets": markets,
        "exact": exact,
        "selected_exact": selected_exact,
        "selection_multiplier": calibration_ratio(global_selected),
    }


def blind_score(entry: dict, policy: dict, history_games: int) -> dict:
    base = float(entry.get("recommendation_probability") or entry.get("model_probability") or .5)
    market = f"{entry['kind']}:{entry['prop']}"
    market_rows = policy["markets"].get(market, [])
    exact = policy["exact"].get((market, segment_key(entry)), [])
    selected = policy["selected_exact"].get((market, segment_key(entry)), [])
    market_multiplier = calibration_ratio(market_rows) if market_rows else .5
    ratios = [min(policy["selection_multiplier"], market_multiplier)]
    lower = []
    if len(exact) >= 30:
        ratios.append(calibration_ratio(exact))
        lower.append(wilson(exact))
    if len(selected) >= 10:
        ratios.append(calibration_ratio(selected))
        lower.append(wilson(selected))
    history_multiplier = min(1.0, .72 + max(0, history_games) / 180)
    history_adjusted = .5 + (base - .5) * history_multiplier
    adjusted = .5 + (history_adjusted - .5) * min(ratios)
    robust = adjusted
    if lower:
        audited_lower = max(.5, min(value for value in lower if value is not None))
        robust = min(adjusted, adjusted * .35 + audited_lower * .65)
    return {
        "recommendation_probability": round(base, 6),
        "history_adjusted_probability": round(history_adjusted, 6),
        "robust_probability": round(robust, 6),
        "market_samples": len(market_rows),
        "automatic_eligible": len(market_rows) >= 100,
        "exact_samples": len(exact),
        "selection_samples": len(selected),
    }


def choose(entries: list[dict], target: int, new_rules: bool, sweep: bool = False) -> list[dict]:
    ranked = sorted(entries, key=lambda row: (
        row["blind"]["robust_probability"] if new_rules else row["blind"]["recommendation_probability"],
        row["blind"]["recommendation_probability"],
    ), reverse=True)
    selected = []
    games = set()
    markets = defaultdict(int)
    share_limit = max(1, math.ceil(target * .30))
    market_limit = min(2 if sweep else 3, share_limit) if new_rules else target
    for row in ranked:
        if not row["blind"]["automatic_eligible"]:
            continue
        if new_rules and row["kind"] == "batter" and row["prop"] == "home_runs" and row["side"] == "over":
            continue
        score = row["blind"]["robust_probability"] if new_rules else row["blind"]["recommendation_probability"]
        if score < .65:
            continue
        game_id = int(row["game_id"])
        market = f"{row['kind']}:{row['prop']}:{row['side']}"
        if game_id in games or markets[market] >= market_limit:
            continue
        selected.append(row)
        games.add(game_id)
        markets[market] += 1
        if len(selected) == target:
            break
    return selected


def choose_coverage_first_balanced(entries: list[dict]) -> list[dict]:
    """Diagnostic all-game card with a soft, rather than blocking, diversity cost."""
    by_game = defaultdict(list)
    for row in entries:
        if not row["blind"]["automatic_eligible"] or row["blind"]["robust_probability"] < .65:
            continue
        if row["kind"] == "batter" and row["prop"] == "home_runs" and row["side"] == "over":
            continue
        by_game[int(row["game_id"])].append(row)
    selected = []
    exposure = defaultdict(int)
    while by_game:
        choices = []
        for game_id, values in by_game.items():
            def score(candidate):
                market = f"{candidate['kind']}:{candidate['prop']}:{candidate['side']}"
                return (
                    candidate["blind"]["robust_probability"] - .025 * exposure[market],
                    candidate["blind"]["recommendation_probability"],
                )
            best = max(values, key=score)
            choices.append((score(best), game_id, best))
        _, game_id, best = max(choices, key=lambda value: value[0])
        selected.append(best)
        exposure[f"{best['kind']}:{best['prop']}:{best['side']}"] += 1
        del by_game[game_id]
    return selected


def summarize_card(entries: list[dict], requested: int) -> dict:
    counts = {value: sum(row["settlement"]["status"] == value for row in entries)
              for value in ("win", "loss", "push", "unresolved")}
    settled = counts["win"] + counts["loss"]
    return {
        "requested_legs": requested, "legs": len(entries),
        "complete_target": len(entries) == requested, **counts,
        "settled_accuracy": round(counts["win"] / settled, 6) if settled else None,
        "settled_sweep": settled > 0 and counts["loss"] == 0,
        "clean_card_sweep": len(entries) == requested and counts["loss"] == 0 and counts["unresolved"] == 0,
        "market_side_counts": dict(sorted({
            f"{row['kind']}:{row['prop']}:{row['side']}": sum(
                other["kind"] == row["kind"] and other["prop"] == row["prop"] and other["side"] == row["side"]
                for other in entries
            ) for row in entries
        }.items())),
        "selections": [{
            "game_id": row["game_id"], "player_id": row["player_id"],
            "player": row["player_name"], "kind": row["kind"], "prop": row["prop"],
            "side": row["side"], "line": row["line"], "odds": row.get("decimal_odds"),
            **row["blind"], **row["settlement"],
        } for row in entries],
    }


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def projection_boards(boxes: dict[int, dict]) -> dict[str, list[dict]]:
    latest = {}
    for row in jsonl(PROJECTIONS):
        game_id = int(row.get("game_id") or 0)
        recorded = parse_time(row.get("recorded_at"))
        scheduled = parse_time(row.get("scheduled_start"))
        if not game_id or not recorded or (scheduled and recorded > scheduled):
            continue
        current = latest.get(game_id)
        if current is None or recorded > current[0]:
            latest[game_id] = (recorded, row)
    boards = defaultdict(list)
    for game_id, (_, row) in latest.items():
        # Completed-game settlement is keyed to MLB's authoritative official
        # date. UI calendar dates can differ around UTC/day boundaries.
        replay_date = (boxes.get(game_id) or {}).get("date") or row.get("official_date") or row.get("game_date")
        if replay_date:
            boards[str(replay_date)[:10]].append(row)
    return boards


def history_index(boxes: dict[int, dict]) -> dict[tuple[str, int], list[str]]:
    values = defaultdict(set)
    for box in boxes.values():
        played = str(box.get("date") or "")[:10]
        if not played:
            continue
        for side in ("home", "away"):
            for player in (box.get(side) or {}).get("players", []):
                player_id = int(player.get("player_id") or 0)
                if player_id and player.get("batting"):
                    values[("batter", player_id)].add(played)
                if player_id and player.get("pitching"):
                    values[("pitcher", player_id)].add(played)
    return {key: sorted(dates) for key, dates in values.items()}


def projection_candidates(board: list[dict], replay_date: str, policy: dict,
                          boxes: dict[int, dict], histories: dict) -> list[dict]:
    candidates = {}
    for game in board:
        game_id = int(game["game_id"])
        for selection in game.get("selections") or []:
            entry = {
                **selection,
                "game_id": game_id,
                "model_probability": selection.get("probability"),
                "recommendation_probability": selection.get("probability"),
                "decimal_odds": None,
            }
            key = (game_id, int(entry["player_id"]), entry["kind"], entry["prop"],
                   float(entry["line"]), entry["side"])
            candidates[key] = entry
    values = []
    for entry in candidates.values():
        dates = histories.get((entry["kind"], int(entry["player_id"])), [])
        games = bisect.bisect_left(dates, replay_date)
        entry["blind"] = blind_score(entry, policy, games)
        entry["settlement"] = settle(entry, boxes)
        values.append(entry)
    return values


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", action="append", dest="dates")
    parser.add_argument("--last-days", type=int, default=2)
    parser.add_argument("--through", help="Last replay date, inclusive (YYYY-MM-DD)")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    boxes = {int(row["game_id"]): row for row in jsonl(BOXES)}
    boards = projection_boards(boxes)
    available_dates = sorted(boards)
    if args.dates:
        dates = args.dates
    else:
        through = args.through or available_dates[-1]
        dates = [value for value in available_dates if value <= through][-max(1, args.last_days):]
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    audit_rows = audit.get("rows") or []
    deployed = set(json.loads(MODEL_REPORT.read_text(encoding="utf-8")).get("models") or {})
    histories = history_index(boxes)
    box_dates = {game_id: row.get("date") for game_id, row in boxes.items()}
    for row in audit_rows:
        row["official_date"] = row.get("official_date") or box_dates.get(int(row["game_id"])) or row.get("date")

    report = {
        "method": "Exact game/player settlement; calibration rows strictly predate each replay date",
        "limitations": [
            "Historic displayed-board snapshots did not retain decimal or paired opposite-side prices, so the 1.20 odds floor and new no-vig sportsbook-disagreement guard cannot be counterfactually scored.",
            "Each slate uses the last immutable displayed MelBet-restricted recommendation board captured before first pitch.",
            "Participant confirmation is not required and is not used in this replay.",
        ],
        "dates": {},
    }
    for replay_date in dates:
        prior = [row for row in audit_rows if str(row.get("official_date") or "") < replay_date]
        policy = point_in_time_policy(prior, deployed)
        values = projection_candidates(boards.get(replay_date, []), replay_date, policy, boxes, histories)
        board_games = {int(row["game_id"]) for row in boards.get(replay_date, [])}
        policy_games = {
            int(row["game_id"]) for row in values
            if row["blind"]["automatic_eligible"]
            and not (row["kind"] == "batter" and row["prop"] == "home_runs" and row["side"] == "over")
        }
        balanced_target = len(policy_games)
        date_report = {
            "candidate_pool": len(values),
            "exactly_settled_candidates": sum(row["settlement"]["status"] != "unresolved" for row in values),
            "archived_board_games": len(board_games),
            "policy_eligible_games": balanced_target,
            "prior_audit_rows": len(prior),
            "cards": {},
        }
        date_report["cards"]["balanced_all_games"] = {
            "raw_probability_control": summarize_card(choose(values, balanced_target, False), balanced_target),
            "new_balanced_rules": summarize_card(choose(values, balanced_target, True), balanced_target),
            "coverage_first_soft_diversity": summarize_card(
                choose_coverage_first_balanced(values), balanced_target,
            ),
        }
        for target in (5, 8):
            date_report["cards"][f"sweep_{target}"] = {
                "raw_probability_control": summarize_card(choose(values, target, False, True), target),
                "new_sweep_rules": summarize_card(choose(values, target, True, True), target),
            }
        report["dates"][replay_date] = date_report
    variants = {
        "balanced_raw_probability_control": ("balanced_all_games", "raw_probability_control"),
        "balanced_current_hard_diversity": ("balanced_all_games", "new_balanced_rules"),
        "balanced_coverage_first_soft_diversity": ("balanced_all_games", "coverage_first_soft_diversity"),
        "sweep_5_raw_probability_control": ("sweep_5", "raw_probability_control"),
        "sweep_5_new_rules": ("sweep_5", "new_sweep_rules"),
        "sweep_8_raw_probability_control": ("sweep_8", "raw_probability_control"),
        "sweep_8_new_rules": ("sweep_8", "new_sweep_rules"),
    }
    report["aggregate"] = {}
    for label, (card_name, variant) in variants.items():
        cards = [value["cards"][card_name][variant] for value in report["dates"].values()]
        totals = {key: sum(card[key] for card in cards) for key in ("requested_legs", "legs", "win", "loss", "push", "unresolved")}
        settled = totals["win"] + totals["loss"]
        report["aggregate"][label] = {
            **totals,
            "coverage": round(totals["legs"] / totals["requested_legs"], 6) if totals["requested_legs"] else None,
            "settled_accuracy": round(totals["win"] / settled, 6) if settled else None,
            "complete_cards": sum(card["complete_target"] for card in cards),
            "clean_card_sweeps": sum(card["clean_card_sweep"] for card in cards),
        }
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
