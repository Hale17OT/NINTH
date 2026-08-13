"""Four-day point-in-time shadow replay for the exact Build Best policy.

Candidate membership and forecasts are frozen pregame from recorded Build Best
actions. Each day's process calibration uses only settled build selections from
earlier dates. The configuration search is exploratory/post-hoc and is never a
production-promotion test.
"""
from __future__ import annotations

import argparse
import itertools
import json
from collections import Counter, defaultdict
from pathlib import Path

from ml.evaluate_player_prop_builds import (
    BOXES, BUILDS, build_report, evaluated_rows, jsonl, odds_bucket, settle,
)


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "ml" / "artifacts" / "player_prop_selection_shadow_4_day.json"
SEARCH_MARKETS = (
    "pitcher:strikeouts:over",
    "batter:rbi:under",
    "batter:walks:under",
    "batter:total_bases:under",
    "batter:hits_runs_rbi:over",
    "batter:runs:under",
    "batter:strikeouts:over",
    "batter:strikeouts:under",
    "batter:stolen_bases:under",
    "batter:home_runs:under",
)


def market_key(row: dict) -> str:
    return f"{row['kind']}:{row['prop']}:{row['side']}"


def _rank_bucket(value: int) -> str:
    return "1" if value <= 1 else "2" if value == 2 else "3_plus"


def _evidence(report: dict, row: dict, style: str, floor: float, rank: int) -> tuple[str | None, dict | None]:
    odds = odds_bucket(floor)
    market = market_key(row)
    lookups = (
        ("market_style_odds_rotation", report.get("by_market_style_odds_rotation", {}).get(f"{market}|{style}|{odds}|0")),
        ("style_odds_rotation_rank", report.get("by_style_odds_rotation_rank", {}).get(f"{style}|{odds}|0|{_rank_bucket(rank)}")),
        ("style_odds_rotation", report.get("by_style_odds_rotation", {}).get(f"{style}|{odds}|0")),
        ("style_odds", report.get("by_style_odds", {}).get(f"{style}|{odds}")),
        ("style", report.get("by_style", {}).get(style)),
    )
    available = [(name, value) for name, value in lookups if value and int(value.get("samples") or 0) > 0]
    return next(((name, value) for name, value in available if int(value.get("samples") or 0) >= 20), available[0] if available else (None, None))


def sportsbook_probability(row: dict) -> tuple[float | None, str | None]:
    if row.get("sportsbook_probability") is not None:
        return float(row["sportsbook_probability"]), "paired_no_vig"
    odds = row.get("decimal_odds")
    if odds is not None and float(odds) > 1:
        # August 4-5 archives predate paired-price capture. This is a
        # conservative, vig-inclusive proxy and is labelled in the report.
        return min(.95, 1 / float(odds)), "single_price_implied_proxy"
    return None, None


def process_score(row: dict, prior_report: dict, style: str, floor: float, rank: int) -> dict:
    base = float(row.get("robust_probability") or row.get("recommendation_probability") or .5)
    level, evidence = _evidence(prior_report, row, style, floor, rank)
    samples = int((evidence or {}).get("samples") or 0)
    book, price_source = sportsbook_probability(row)
    if evidence and samples >= 20:
        multiplier = max(.5, min(1.0, float(evidence.get("confidence_multiplier") or .5)))
        score = .5 + (base - .5) * multiplier
        lower = evidence.get("lower_bound")
        if lower is not None:
            score = min(score, score * .35 + max(.5, float(lower)) * .65)
    elif book is not None:
        book_weight = .75 * (1 - min(1, samples / 20))
        score = base * (1 - book_weight) + book * book_weight
    else:
        score = .5 + (base - .5) * .5
    return {
        **row, "process_probability": max(.01, min(.99, score)),
        "post_selection_samples": samples, "post_selection_level": level,
        "shadow_sportsbook_probability": book, "shadow_price_source": price_source,
        "candidate_rank": rank,
    }


def candidates_by_date(builds: list[dict], boxes: dict[int, dict], dates: list[str]) -> dict[str, list[dict]]:
    latest = {}
    for build in builds:
        played = str(build.get("start_date") or "")[:10]
        if played not in dates:
            continue
        recorded = build.get("recorded_at") or ""
        for entry in build.get("entries") or []:
            key = (
                played, int(entry["game_id"]), int(entry["player_id"]), entry["kind"],
                entry["prop"], entry["side"], float(entry["line"]),
            )
            if key not in latest or recorded > latest[key][0]:
                latest[key] = (recorded, {**entry, "official_date": entry.get("official_date") or played})
    output = defaultdict(list)
    for (played, *_), (_, entry) in latest.items():
        result = settle(entry, boxes)
        output[played].append({**entry, "settlement": result})
    return output


def scored_board(values: list[dict], prior_report: dict, style: str, floor: float) -> list[dict]:
    eligible = [row for row in values if row.get("decimal_odds") is not None and float(row["decimal_odds"]) >= floor]
    by_game = defaultdict(list)
    for row in eligible:
        by_game[int(row["game_id"])].append(row)
    output = []
    for rows in by_game.values():
        ranked = sorted(rows, key=lambda row: float(row.get("robust_probability") or .5), reverse=True)
        output.extend(process_score(row, prior_report, style, floor, rank) for rank, row in enumerate(ranked, 1))
    return output


def choose(board: list[dict], target: int, markets: set[str], cutoff: float,
           disagreement: float, cap: int) -> list[dict]:
    eligible = []
    for row in board:
        if market_key(row) not in markets or float(row["process_probability"]) < cutoff:
            continue
        book = row.get("shadow_sportsbook_probability")
        if book is None or float(row["process_probability"]) - float(book) > disagreement:
            continue
        eligible.append(row)
    eligible.sort(key=lambda row: (
        float(row["process_probability"]),
        float(row.get("robust_probability") or .5),
    ), reverse=True)
    selected, games, exposures = [], set(), Counter()
    for row in eligible:
        game_id = int(row["game_id"]); market = market_key(row)
        if game_id in games or exposures[market] >= cap:
            continue
        selected.append(row); games.add(game_id); exposures[market] += 1
        if len(selected) == target:
            break
    return selected


def card_summary(rows: list[dict], target: int) -> dict:
    counts = Counter(row["settlement"]["status"] for row in rows)
    return {
        "target": target, "legs": len(rows), "complete": len(rows) == target,
        "wins": counts["win"], "losses": counts["loss"],
        "pushes": counts["push"], "unresolved": counts["unresolved"],
        "clean_sweep": len(rows) == target and counts["loss"] == 0
            and counts["push"] == 0 and counts["unresolved"] == 0,
        "selections": [{
            "game_id": row["game_id"], "player": row["player_name"],
            "market": market_key(row), "line": row["line"], "odds": row.get("decimal_odds"),
            "process_probability": round(row["process_probability"], 6),
            "price_source": row.get("shadow_price_source"),
            **row["settlement"],
        } for row in rows],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=4)
    parser.add_argument("--through", default="2026-08-07")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    builds = jsonl(BUILDS)
    boxes = {int(row["game_id"]): row for row in jsonl(BOXES)}
    available = sorted({str(row.get("start_date") or "")[:10] for row in builds if str(row.get("start_date") or "")[:10] <= args.through})
    dates = available[-max(1, args.days):]
    candidates = candidates_by_date(builds, boxes, dates)
    boards = {}
    prior_reports = {}
    for played in dates:
        prior = evaluated_rows(builds, boxes, before_date=played)
        prior_reports[played] = build_report(prior)
        boards[played] = {
            floor: scored_board(candidates.get(played, []), prior_reports[played], "sweep", floor)
            for floor in (1.2, 1.3, 1.4, 1.5)
        }

    market_sets = []
    for size in range(2, 6):
        market_sets.extend(set(values) for values in itertools.combinations(SEARCH_MARKETS, size))
    successful = []
    tested = 0
    for target in (5, 4, 3):
        for floor in (1.5, 1.4, 1.3, 1.2):
            for cutoff in (.70, .65, .60, .55):
                for disagreement in (.05, .10, .15):
                    for cap in (1, 2):
                        for markets in market_sets:
                            tested += 1
                            cards = {
                                played: card_summary(choose(boards[played][floor], target, markets, cutoff, disagreement, cap), target)
                                for played in dates
                            }
                            if all(card["clean_sweep"] for card in cards.values()):
                                successful.append({
                                    "target": target, "minimum_odds": floor,
                                    "minimum_process_probability": cutoff,
                                    "sportsbook_disagreement_tolerance": disagreement,
                                    "market_side_cap": cap, "markets": sorted(markets),
                                    "cards": cards,
                                })
        if successful:
            # Prefer the largest target that succeeds; smaller targets remain
            # available only when no larger fixed configuration sweeps.
            break
    successful.sort(key=lambda row: (
        row["target"], row["minimum_odds"], row["minimum_process_probability"],
        -row["sportsbook_disagreement_tolerance"], -len(row["markets"]),
    ), reverse=True)

    strongest = set(SEARCH_MARKETS[:7])
    benchmark = {}
    for target in (3, 4, 5):
        benchmark[str(target)] = {
            played: card_summary(choose(boards[played][1.3], target, strongest, .65, .10, 2), target)
            for played in dates
        }
    balanced = {}
    all_markets = {market_key(row) for values in candidates.values() for row in values}
    for played in dates:
        board = scored_board(candidates.get(played, []), prior_reports[played], "balanced", 1.3)
        target = len({int(row["game_id"]) for row in board})
        balanced[played] = card_summary(choose(board, target, all_markets, .55, .15, 3), target)

    report = {
        "method": "Pregame archived candidates; each day's calibration uses only earlier settled dates",
        "warning": "Configuration search is exploratory and post-hoc. A four-day 100% result is not a promotion test or future guarantee.",
        "limitations": [
            "The archive contains candidates exposed by recorded builds, not every displayed board candidate.",
            "August 4-5 did not retain paired prices; their single displayed decimal price is used as a vig-inclusive sportsbook proxy.",
        ],
        "dates": dates, "configurations_tested": tested,
        "successful_configuration_count": len(successful),
        "best_successful_configurations": successful[:10],
        "strongest_preset_benchmark": benchmark,
        "balanced_all_games_coverage": balanced,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({
        "dates": dates, "configurations_tested": tested,
        "successful_configuration_count": len(successful),
        "best": successful[:3], "strongest_preset_benchmark": benchmark,
        "balanced_all_games_coverage": balanced,
    }, indent=2))


if __name__ == "__main__":
    main()
