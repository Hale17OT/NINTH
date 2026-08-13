"""Four-day shadow replay of the frozen within-game v1 reranker.

Historical build archives retain prices and probabilities but predate the full
priced-board ledger. Missing matchup-readiness fields are therefore neutral,
while recent form and batting-order position are reconstructed strictly from
box scores dated before each replay slate.
"""
from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

from ml.evaluate_player_prop_builds import BOXES, BUILDS, _outcome, build_report, evaluated_rows, jsonl
from ml.shadow_player_prop_selection_policy import candidates_by_date, market_key, scored_board


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "ml" / "artifacts" / "player_prop_reranker_shadow_4_day.json"


def history(boxes: dict[int, dict]) -> dict[tuple[str, int, str], list[tuple[str, float, int | None]]]:
    values = defaultdict(list)
    for box in boxes.values():
        played = str(box.get("date") or "")[:10]
        for side in ("away", "home"):
            for player in (box.get(side) or {}).get("players", []):
                player_id = int(player.get("player_id") or 0)
                for kind, section_name in (("batter", "batting"), ("pitcher", "pitching")):
                    section = player.get(section_name) or {}
                    if not section:
                        continue
                    props = (
                        ("hits", "total_bases", "home_runs", "runs", "rbi", "walks", "stolen_bases",
                         "doubles", "triples", "strikeouts", "singles", "hits_runs_rbi")
                        if kind == "batter" else
                        ("strikeouts", "walks", "hits_allowed", "outs", "earned_runs",
                         "home_runs_allowed", "pitches", "win")
                    )
                    batting_order = player.get("batting_order")
                    try:
                        lineup_slot = int(batting_order) // 100 if batting_order else None
                    except (TypeError, ValueError):
                        lineup_slot = None
                    for prop in props:
                        actual = _outcome(section, kind, prop)
                        if actual is not None:
                            values[(kind, player_id, prop)].append((played, actual, lineup_slot))
    return {key: sorted(rows, key=lambda value: value[0]) for key, rows in values.items()}


def pregame_history(row: dict, played: str, histories: dict) -> tuple[float | None, int | None]:
    prior = [value for value in histories.get((row["kind"], int(row["player_id"]), row["prop"]), [])
             if value[0] < played]
    recent = prior[-10:]
    average = sum(value[1] for value in recent) / len(recent) if recent else None
    lineup_slot = next((value[2] for value in reversed(prior) if value[2]), None)
    return average, lineup_slot


def rerank(row: dict, played: str, histories: dict) -> dict:
    probability = float(row["process_probability"])
    model_probability = float(row.get("model_probability") or row.get("recommendation_probability") or probability)
    over_probability = model_probability if row["side"] == "over" else 1 - model_probability
    line = float(row["line"])
    implied = line + (over_probability - .5) * 2
    recent, lineup_slot = pregame_history(row, played, histories)
    expected = implied * .7 + recent * .3 if recent is not None else implied
    raw_clearance = line - expected if row["side"] == "under" else expected - line
    normalized = raw_clearance / max(1, math.sqrt(abs(expected) + .5))
    reasons = []
    penalty = 0.0
    status = str(row.get("lineup_status") or "").lower()
    if status and status != "confirmed":
        value = .01 if row["kind"] == "pitcher" and status == "probable" else .025
        penalty += value; reasons.append("participant_not_confirmed")
    if row["kind"] == "batter" and row["prop"] == "rbi" and row["side"] == "under" \
            and line <= .5 and lineup_slot is not None and 3 <= lineup_slot <= 5:
        penalty += .04; reasons.append("middle_order_rbi_under")
    if row["kind"] == "batter" and row["prop"] == "walks" and row["side"] == "under" and line <= .5:
        if recent is not None and recent >= .45:
            penalty += .04; reasons.append("high_walk_rate_under")
        elif recent is not None and recent >= .3:
            penalty += .02; reasons.append("moderate_walk_rate_under")
    if row["kind"] == "pitcher" and row["prop"] == "strikeouts" and row["side"] == "over":
        if raw_clearance <= 0:
            penalty += .06; reasons.append("pitcher_k_projection_below_line")
        elif raw_clearance < .5:
            penalty += .04; reasons.append("pitcher_k_thin_clearance")
        elif raw_clearance < 1:
            penalty += .02; reasons.append("pitcher_k_limited_clearance")
    book = row.get("shadow_sportsbook_probability")
    if book is None:
        penalty += .015; reasons.append("unpaired_sportsbook_price")
    disagreement = abs(probability - float(book)) if book is not None else 0
    score = probability + .035 * max(-1.5, min(1.5, normalized)) - penalty - .35 * disagreement
    return {
        **row, "rerank_score": score, "expected_value": expected,
        "raw_line_clearance": raw_clearance, "normalized_line_clearance": normalized,
        "fragility_penalty": penalty, "fragility_reasons": reasons,
        "reconstructed_recent_10_average": recent,
        "reconstructed_lineup_slot": lineup_slot,
    }


def exposure_key(row: dict) -> str:
    return f"{row['game_id']}:{row['player_id']}:{row['prop']}:{row['side']}:{float(row['line']):g}"


def context_key(row: dict) -> str:
    return f"{row['game_id']}:{row.get('team_id') or 'team'}:{row['side']}"


def choose(board: list[dict], target: int, cap: int, score_name: str,
           prior_exact: set[str], prior_context: set[str]) -> list[dict]:
    remaining = list(board)
    selected, games, markets = [], set(), Counter()
    while len(selected) < target:
        eligible = [row for row in remaining
                    if int(row["game_id"]) not in games and markets[market_key(row)] < cap]
        if not eligible:
            break
        eligible.sort(key=lambda row: (
            float(row[score_name])
            - markets[market_key(row)] * .025
            - (0.25 if exposure_key(row) in prior_exact else 0)
            - (0.08 if context_key(row) in prior_context else 0),
            float(row["process_probability"]),
        ), reverse=True)
        choice = eligible[0]
        selected.append(choice); games.add(int(choice["game_id"])); markets[market_key(choice)] += 1
        remaining.remove(choice)
    return selected


def summary(rows: list[dict], target: int) -> dict:
    statuses = Counter(row["settlement"]["status"] for row in rows)
    return {
        "requested": target, "legs": len(rows), "complete": len(rows) == target,
        "wins": statuses["win"], "losses": statuses["loss"],
        "pushes": statuses["push"], "unresolved": statuses["unresolved"],
        "clean_sweep": len(rows) == target and statuses["win"] == target,
        "selections": [{
            "game_id": row["game_id"], "player": row["player_name"],
            "market": market_key(row), "line": row["line"], "odds": row.get("decimal_odds"),
            "process_probability": round(float(row["process_probability"]), 6),
            "rerank_score": round(float(row.get("rerank_score") or row["process_probability"]), 6),
            "raw_line_clearance": round(float(row.get("raw_line_clearance") or 0), 6),
            "fragility_reasons": row.get("fragility_reasons") or [],
            **row["settlement"],
        } for row in rows],
    }


def replay_cards(board: list[dict], target: int, cap: int, score_name: str, rotations: int = 3) -> list[dict]:
    cards, prior_exact, prior_context = [], set(), set()
    for rotation in range(rotations):
        selected = choose(board, target, cap, score_name, prior_exact, prior_context)
        card = summary(selected, target); card["rotation_depth"] = rotation
        cards.append(card)
        prior_exact.update(exposure_key(row) for row in selected)
        prior_context.update(context_key(row) for row in selected)
    return cards


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=4)
    parser.add_argument("--through", default="2026-08-07")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    builds = jsonl(BUILDS)
    boxes = {int(row["game_id"]): row for row in jsonl(BOXES)}
    available = sorted({str(row.get("start_date") or "")[:10] for row in builds
                        if str(row.get("start_date") or "")[:10] <= args.through})
    dates = available[-args.days:]
    candidates = candidates_by_date(builds, boxes, dates)
    histories = history(boxes)
    report_configs = []
    for style, target_name in (("balanced", "all_games"), ("sweep", "3"), ("sweep", "4"), ("sweep", "5")):
        for floor in (1.2, 1.3, 1.4, 1.5):
            for cutoff in (0, .55, .65):
                by_date = {}
                aggregate = {"baseline": Counter(), "reranker": Counter()}
                for played in dates:
                    prior_report = build_report(evaluated_rows(builds, boxes, before_date=played))
                    raw = scored_board(candidates.get(played, []), prior_report, style, floor)
                    board = [rerank(row, played, histories) for row in raw
                             if float(row["process_probability"]) >= cutoff]
                    games = len({int(row["game_id"]) for row in board})
                    target = games if target_name == "all_games" else int(target_name)
                    cap = 2 if style == "sweep" else 3
                    baseline = replay_cards(board, target, cap, "process_probability")
                    reranked = replay_cards(board, target, cap, "rerank_score")
                    by_date[played] = {"games": games, "target": target, "baseline": baseline, "reranker": reranked}
                    for name, cards in (("baseline", baseline), ("reranker", reranked)):
                        for card in cards:
                            aggregate[name].update({
                                "cards": 1, "complete_cards": int(card["complete"]),
                                "clean_cards": int(card["clean_sweep"]), "legs": card["legs"],
                                "wins": card["wins"], "losses": card["losses"],
                                "unresolved": card["unresolved"] + card["pushes"],
                            })
                report_configs.append({
                    "style": style, "target": target_name, "minimum_odds": floor,
                    "minimum_process_probability": cutoff,
                    "aggregate": {name: dict(values) for name, values in aggregate.items()},
                    "dates": by_date,
                })
    ranked = sorted(report_configs, key=lambda value: (
        value["aggregate"]["reranker"].get("clean_cards", 0),
        value["aggregate"]["reranker"].get("wins", 0)
        - value["aggregate"]["baseline"].get("wins", 0),
        -value["aggregate"]["reranker"].get("losses", 0),
    ), reverse=True)
    report = {
        "method": "Fixed within_game_v1 weights; point-in-time selection calibration uses only earlier settled dates",
        "limitations": [
            "The complete priced-board ledger begins August 8, so this replay uses candidates previously exposed by Build Best.",
            "Historical threshold curves, opponent confirmation and exact pregame lineup slots were not archived; line clearance uses the archived probability plus prior-ten-game outcomes, and unavailable readiness features remain neutral.",
            "Batting-order fragility uses the most recent earlier-game batting order, never the replay game's result.",
        ],
        "dates": dates, "configurations": len(report_configs),
        "best_configurations": ranked[:12], "all_configurations": report_configs,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({
        "dates": dates, "configurations": len(report_configs),
        "best": [{
            key: value for key, value in row.items() if key not in {"dates"}
        } for row in ranked[:8]],
    }, indent=2))


if __name__ == "__main__":
    main()
