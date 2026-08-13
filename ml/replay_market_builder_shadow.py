"""Leakage-safe shadow replay of proposed moneyline and totals Builder ranking.

The replay uses the last archived pregame projection, the last MelBet line grid
observed before first pitch, and only calibration evidence settled before the
date being replayed. Historical MelBet prices were not archived, so odds-floor
and no-vig disagreement gates are reported as unavailable rather than inferred.
"""
from __future__ import annotations

import argparse
import json
import math
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from evaluate_deployment_selection import (
    TOTALS_CONSISTENCY_OVERRIDE,
    TOTALS_DECISION_LINES,
    _calibrated_line_probabilities,
    _line_side_evidence,
    _materially_contradicts,
    totals_calibration_report,
    wilson_lower,
)


ROOT = Path(__file__).resolve().parents[1]
PROJECTIONS = ROOT / "ml" / "data" / "projection_snapshots.jsonl"
GAMES = ROOT / "ml" / "data" / "games.jsonl"
MELBET = ROOT / "ml" / "data" / "melbet_totals_snapshots.jsonl"
OUTPUT = ROOT / "ml" / "artifacts" / "market_builder_shadow_replay_2_day.json"


def read_jsonl(path):
    with path.open(encoding="utf-8-sig") as handle:
        for line in handle:
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def timestamp(value):
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def normalize_team(value):
    value = re.sub(r"[^a-z0-9]+", "", str(value).lower())
    return value.replace("stlouis", "saintlouis")


def latest_pregame_snapshots():
    selected = {}
    for row in read_jsonl(PROJECTIONS):
        try:
            game_id = int(row["game_id"])
            recorded, starts = timestamp(row["recorded_at"]), timestamp(row["scheduled_start"])
        except (KeyError, TypeError, ValueError):
            continue
        if row.get("phase") != "pregame" or recorded > starts:
            continue
        if game_id not in selected or recorded > timestamp(selected[game_id]["recorded_at"]):
            selected[game_id] = row
    return selected


def completed_games():
    return {int(row["game_id"]): row for row in read_jsonl(GAMES) if row.get("home_score") is not None}


def melbet_grids():
    return list(read_jsonl(MELBET))


def match_grid(game, snapshot, grids):
    teams = {normalize_team(game["home_name"]), normalize_team(game["away_name"])}
    starts = timestamp(snapshot["scheduled_start"])
    candidates = []
    for grid in grids:
        try:
            if timestamp(grid["observed_at"]) > starts:
                continue
            grid_teams = {normalize_team(grid["home_name"]), normalize_team(grid["away_name"])}
            distance = abs((timestamp(grid["starts_at"]) - starts).total_seconds())
        except (KeyError, TypeError, ValueError):
            continue
        if grid_teams == teams and distance <= 3 * 60 * 60:
            candidates.append(grid)
    return max(candidates, key=lambda row: timestamp(row["observed_at"])) if candidates else None


def threshold_rows(snapshot, score, offered_lines=None):
    projection = snapshot.get("totals_projection") or {}
    offered = None if offered_lines is None else {float(line) for line in offered_lines}
    total = int(score["home_score"]) + int(score["away_score"])
    rows = []
    for threshold in projection.get("thresholds") or []:
        try:
            line = float(threshold["line"])
            over = float(threshold["over_probability"])
        except (KeyError, TypeError, ValueError):
            continue
        if line not in TOTALS_DECISION_LINES or (offered is not None and line not in offered):
            continue
        rows.append({"line": line, "over_probability": over, "actual_over": int(total > line)})
    return rows


def calibration_game(game_id, snapshot, game):
    rows = threshold_rows(snapshot, game)
    if not rows:
        return None
    projection = snapshot.get("totals_projection") or {}
    return {
        "game_id": game_id,
        "scheduled_start": snapshot["scheduled_start"],
        "expected_total_runs": projection.get("expected_total_runs"),
        "thresholds": rows,
    }


def settle(side, line, game):
    total = int(game["home_score"]) + int(game["away_score"])
    if float(line).is_integer() and total == line:
        return "push"
    return "win" if ((total > line) == (side == "over")) else "loss"


def card_summary(legs):
    settled = [leg for leg in legs if leg["result"] != "push"]
    wins = sum(leg["result"] == "win" for leg in settled)
    losses = len(settled) - wins
    return {
        "legs": len(legs), "wins": wins, "losses": losses,
        "pushes": len(legs) - len(settled),
        "accuracy_excluding_pushes": round(wins / len(settled), 6) if settled else None,
        "swept": bool(legs) and losses == 0,
        "selections": legs,
    }


def force_side_diversity(chosen, ranked):
    if len(chosen) < 4:
        return chosen
    chosen = list(chosen)
    for required in ("over", "under"):
        if any(row["side"] == required for row in chosen):
            continue
        replacements = [row for row in ranked if row["side"] == required and row["game_id"] not in {x["game_id"] for x in chosen}]
        if replacements:
            replace_at = min(range(len(chosen)), key=lambda index: chosen[index]["score"])
            chosen[replace_at] = replacements[0]
    return chosen


def proposed_totals_candidate(game_id, snapshot, game, grid, calibration, evidence):
    projection = snapshot.get("totals_projection") or {}
    candidates = []
    for row in threshold_rows(snapshot, game, grid["lines"]):
        over, under = _calibrated_line_probabilities(row["over_probability"], row["line"], calibration)
        for side, probability in (("over", over), ("under", under)):
            rule = evidence.get(f"{row['line']:g}:{side}", {})
            contradiction = _materially_contradicts(projection.get("expected_total_runs"), row["line"], side)
            override = probability >= TOTALS_CONSISTENCY_OVERRIDE and rule.get("automatic_eligible") is True
            if probability < .5 or (contradiction and not override):
                continue
            lower = float(rule.get("wilson_95_lower") or .5)
            # Exact-line evidence dominates when it is mature; sparse evidence
            # shrinks the ranking toward a neutral 50%, never toward hindsight.
            robust = min(probability, .35 * probability + .65 * max(.5, lower))
            candidates.append((robust, probability, side, row["line"], rule))
    if not candidates:
        return None
    robust, probability, side, line, rule = max(candidates)
    return {
        "game_id": game_id, "matchup": f"{game['away_name']} @ {game['home_name']}",
        "side": side, "line": line, "probability": round(probability, 6),
        "score": round(robust, 6), "exact_evidence_eligible": rule.get("automatic_eligible") is True,
        "result": settle(side, line, game),
    }


def baseline_totals_candidate(game_id, snapshot, game, grid):
    candidates = []
    for row in threshold_rows(snapshot, game, grid["lines"]):
        candidates.extend(((row["over_probability"], "over", row["line"]), (1 - row["over_probability"], "under", row["line"])))
    if not candidates:
        return None
    probability, side, line = max(candidates)
    return {
        "game_id": game_id, "matchup": f"{game['away_name']} @ {game['home_name']}",
        "side": side, "line": line, "probability": round(probability, 6),
        "score": round(probability, 6), "result": settle(side, line, game),
    }


def moneyline_candidate(game_id, snapshot, game, adjusted=False):
    home = float(snapshot["home_win_probability"])
    side, probability = ("home", home) if home >= .5 else ("away", 1 - home)
    projection = snapshot.get("projection") or {}
    completeness = float(projection.get("input_completeness") or 0)
    score = .5 + (probability - .5) * (.75 + .25 * completeness) if adjusted else probability
    actual_home = int(game["home_score"]) > int(game["away_score"])
    return {
        "game_id": game_id, "matchup": f"{game['away_name']} @ {game['home_name']}",
        "side": side, "probability": round(probability, 6), "input_completeness": completeness,
        "score": round(score, 6), "result": "win" if (actual_home == (side == "home")) else "loss",
    }


def replay(dates, legs):
    snapshots, games, grids = latest_pregame_snapshots(), completed_games(), melbet_grids()
    all_calibration = {
        game_id: calibration_game(game_id, snapshot, games[game_id])
        for game_id, snapshot in snapshots.items() if game_id in games
    }
    all_calibration = {key: value for key, value in all_calibration.items() if value}
    report = {
        "method": "last pregame projection + last MelBet grid observed before first pitch",
        "historical_price_limitation": "Aug. 4-5 snapshots contain lines but no odds; the 1.20 floor and no-vig sportsbook disagreement gate cannot be replayed.",
        "card_size": legs, "dates": {},
    }
    for date in dates:
        eligible_ids = sorted(game_id for game_id, game in games.items() if game.get("date") == date and game_id in snapshots)
        prior = [row for game_id, row in all_calibration.items() if games[game_id].get("date") < date]
        calibration_report = totals_calibration_report(prior)
        calibration = calibration_report if calibration_report.get("promoted") else None
        evidence = _line_side_evidence(prior, calibration) if calibration else {}
        base_ml, shadow_ml, base_totals, shadow_totals, missing_grid = [], [], [], [], []
        for game_id in eligible_ids:
            snapshot, game = snapshots[game_id], games[game_id]
            base_ml.append(moneyline_candidate(game_id, snapshot, game))
            shadow_ml.append(moneyline_candidate(game_id, snapshot, game, adjusted=True))
            grid = match_grid(game, snapshot, grids)
            if not grid:
                missing_grid.append(f"{game['away_name']} @ {game['home_name']}")
                continue
            baseline = baseline_totals_candidate(game_id, snapshot, game, grid)
            proposed = proposed_totals_candidate(game_id, snapshot, game, grid, calibration, evidence)
            if baseline:
                base_totals.append(baseline)
            if proposed:
                shadow_totals.append(proposed)
        base_ml.sort(key=lambda row: row["score"], reverse=True)
        shadow_ml.sort(key=lambda row: row["score"], reverse=True)
        base_totals.sort(key=lambda row: row["score"], reverse=True)
        shadow_totals.sort(key=lambda row: row["score"], reverse=True)
        base_total_card = force_side_diversity(base_totals[:legs], base_totals)
        # Proposed diversity is conditional: do not replace a stronger pick unless
        # an evidence-qualified opposite-side candidate is close (<= 2 points).
        shadow_card = shadow_totals[:legs]
        if len(shadow_card) >= 4:
            for required in ("over", "under"):
                if any(row["side"] == required for row in shadow_card):
                    continue
                choices = [row for row in shadow_totals if row["side"] == required and row["exact_evidence_eligible"] and row["game_id"] not in {x["game_id"] for x in shadow_card}]
                if choices:
                    weakest = min(shadow_card, key=lambda row: row["score"])
                    if weakest["score"] - choices[0]["score"] <= .02:
                        shadow_card = [choices[0] if row is weakest else row for row in shadow_card]
        report["dates"][date] = {
            "available_completed_games": len(eligible_ids), "matched_melbet_grids": len(eligible_ids) - len(missing_grid),
            "missing_melbet_grids": missing_grid, "prior_calibration_games": len(prior),
            "calibration_promoted_without_future_results": bool(calibration),
            "moneyline": {
                "current_top_card": card_summary(base_ml[:legs]), "shadow_top_card": card_summary(shadow_ml[:legs]),
                "current_all_games": card_summary(base_ml), "shadow_all_games": card_summary(shadow_ml),
            },
            "totals": {
                "current_raw_forced_diversity_card": card_summary(base_total_card),
                "shadow_calibrated_evidence_card": card_summary(shadow_card),
                "current_all_available": card_summary(base_totals), "shadow_all_available": card_summary(shadow_totals),
            },
        }
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dates", nargs="+", default=["2026-08-04", "2026-08-05"])
    parser.add_argument("--legs", type=int, default=5)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    report = replay(args.dates, args.legs)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
