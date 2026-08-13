"""All-games Player Props shadow replay with an explicit oracle boundary.

The oracle answers only whether the archived, priced candidate pool contained a
winning selection for every covered game.  The policy search is separate: it
uses one fixed set of rules on every replay date, scores each date using only
earlier settled evidence, and never reads outcomes while selecting a card.
"""
from __future__ import annotations

import argparse
import itertools
import json
from collections import Counter, defaultdict
from dataclasses import dataclass, asdict
from pathlib import Path

import numpy as np

from ml.evaluate_player_prop_builds import BOXES, BUILDS, build_report, evaluated_rows, jsonl
from ml.shadow_player_prop_selection_policy import (
    candidates_by_date,
    market_key,
    scored_board,
)


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "ml" / "artifacts" / "player_prop_all_games_shadow_3_day.json"


@dataclass(frozen=True)
class Policy:
    minimum_odds: float
    minimum_probability: float
    maximum_rank: int
    disagreement_tolerance: float
    rank_penalty: float
    sportsbook_penalty: float
    market_exposure_penalty: float
    direction_exposure_penalty: float
    odds_penalty: float


def _candidate_id(row: dict) -> tuple:
    return (
        int(row["game_id"]), int(row["player_id"]), row["kind"], row["prop"],
        row["side"], float(row["line"]), float(row.get("decimal_odds") or 0),
    )


def _eligible(row: dict, policy: Policy) -> bool:
    if float(row.get("decimal_odds") or 0) < policy.minimum_odds:
        return False
    if float(row.get("process_probability") or 0) < policy.minimum_probability:
        return False
    if int(row.get("candidate_rank") or 999) > policy.maximum_rank:
        return False
    book = row.get("shadow_sportsbook_probability")
    return book is not None and abs(float(row["process_probability"]) - float(book)) <= policy.disagreement_tolerance


def _base_utility(row: dict, policy: Policy) -> float:
    process = float(row.get("process_probability") or .5)
    book = float(row.get("shadow_sportsbook_probability") or .5)
    rank = int(row.get("candidate_rank") or 1)
    odds = float(row.get("decimal_odds") or policy.minimum_odds)
    return (
        process
        - policy.rank_penalty * max(0, rank - 1)
        - policy.sportsbook_penalty * abs(process - book)
        - policy.odds_penalty * max(0, odds - policy.minimum_odds)
    )


def select_card(board: list[dict], policy: Policy, market_cap: int = 3) -> list[dict]:
    """Deterministic portfolio selection without settlement access.

    Constrained games are handled first. Within a game the policy discounts
    repeated market-side and statistical-direction exposure. A bounded repair
    pass replaces an earlier selection when needed to preserve all-game
    coverage under the hard market-side cap.
    """
    by_game = defaultdict(list)
    for row in board:
        if _eligible(row, policy):
            by_game[int(row["game_id"])].append(row)
    if not by_game:
        return []
    for values in by_game.values():
        values.sort(key=lambda row: (_base_utility(row, policy), -int(row["player_id"])), reverse=True)

    selected: dict[int, dict] = {}
    markets = Counter()
    directions = Counter()
    # Fewest usable market-sides first prevents a flexible game from consuming
    # the only cap slot available to a constrained game.
    order = sorted(by_game, key=lambda game_id: (
        len({market_key(row) for row in by_game[game_id]}), len(by_game[game_id]), game_id,
    ))
    for game_id in order:
        ranked = sorted(by_game[game_id], key=lambda row: (
            _base_utility(row, policy)
            - policy.market_exposure_penalty * markets[market_key(row)]
            - policy.direction_exposure_penalty * directions[row["side"]],
            _base_utility(row, policy),
        ), reverse=True)
        choice = next((row for row in ranked if markets[market_key(row)] < market_cap), None)
        if choice is None:
            continue
        selected[game_id] = choice
        markets[market_key(choice)] += 1
        directions[choice["side"]] += 1
    return list(selected.values())


def summarize(rows: list[dict], expected_games: set[int]) -> dict:
    counts = Counter(row["settlement"]["status"] for row in rows)
    selected_games = {int(row["game_id"]) for row in rows}
    return {
        "requested_legs": len(expected_games),
        "legs": len(rows),
        "complete": selected_games == expected_games,
        "wins": counts["win"], "losses": counts["loss"],
        "pushes": counts["push"], "unresolved": counts["unresolved"],
        "clean_sweep": selected_games == expected_games and counts["win"] == len(expected_games),
        "market_side_counts": dict(Counter(market_key(row) for row in rows)),
        "direction_counts": dict(Counter(row["side"] for row in rows)),
        "selections": [{
            "game_id": row["game_id"], "player": row["player_name"],
            "market": market_key(row), "line": row["line"],
            "odds": row.get("decimal_odds"),
            "candidate_rank": row.get("candidate_rank"),
            "process_probability": round(float(row["process_probability"]), 6),
            **row["settlement"],
        } for row in sorted(rows, key=lambda value: int(value["game_id"]))],
    }


def oracle_card(board: list[dict], floor: float, market_cap: int = 3) -> list[dict] | None:
    """Return a cap-compliant all-win witness, if one exists.

    Settlement is intentionally used here because this is labelled an oracle
    feasibility ceiling, never a deployable selection policy.
    """
    by_game = defaultdict(list)
    for row in board:
        if float(row.get("decimal_odds") or 0) >= floor and row["settlement"]["status"] == "win":
            by_game[int(row["game_id"])].append(row)
    all_games = {int(row["game_id"]) for row in board}
    if set(by_game) != all_games:
        return None
    order = sorted(all_games, key=lambda game_id: (len({market_key(row) for row in by_game[game_id]}), len(by_game[game_id])))
    counts = Counter()
    chosen = []

    def visit(index: int) -> bool:
        if index == len(order):
            return True
        game_id = order[index]
        values = sorted(by_game[game_id], key=lambda row: (
            float(row.get("process_probability") or 0), float(row.get("decimal_odds") or 0)
        ), reverse=True)
        for row in values:
            market = market_key(row)
            if counts[market] >= market_cap:
                continue
            counts[market] += 1; chosen.append(row)
            if visit(index + 1):
                return True
            chosen.pop(); counts[market] -= 1
        return False

    return list(chosen) if visit(0) else None


def search_market_compositions(boards: dict, dates: list[str], market_cap: int = 3) -> dict:
    """Exhaust fixed market whitelists with the same rules on every date.

    Within each permitted market-side the highest point-in-time process score is
    selected for a game. This explores composition without introducing player,
    team, game, or outcome-specific exceptions.
    """
    configurations = itertools.product(
        (1.2, 1.3, 1.35), (.50, .60),
        (5, 999), (.10, .25),
    )
    searched_masks = 0
    complete_masks = 0
    perfect = []
    best = None
    for floor, cutoff, maximum_rank, disagreement in configurations:
        markets = sorted({market_key(row) for played in dates for row in boards[played][floor]})
        market_index = {market: index for index, market in enumerate(markets)}
        games = [(date_index, played, game_id)
                 for date_index, played in enumerate(dates)
                 for game_id in sorted({int(row["game_id"]) for row in boards[played][floor]})]
        utilities = np.full((len(games), len(markets)), -99.0, dtype=np.float32)
        statuses = np.full((len(games), len(markets)), -1, dtype=np.int8)
        references: list[list[dict | None]] = [[None] * len(markets) for _ in games]
        for game_index, (_, played, game_id) in enumerate(games):
            for row in boards[played][floor]:
                if int(row["game_id"]) != game_id:
                    continue
                if float(row["process_probability"]) < cutoff or int(row["candidate_rank"]) > maximum_rank:
                    continue
                book = row.get("shadow_sportsbook_probability")
                if book is None or abs(float(row["process_probability"]) - float(book)) > disagreement:
                    continue
                index = market_index[market_key(row)]
                utility = float(row["process_probability"])
                if utility > utilities[game_index, index]:
                    utilities[game_index, index] = utility
                    statuses[game_index, index] = {
                        "loss": 0, "win": 1, "push": 2, "unresolved": 3,
                    }.get(row["settlement"]["status"], 3)
                    references[game_index][index] = row

        bit_positions = np.arange(len(markets), dtype=np.uint64)
        total_masks = 1 << len(markets)
        date_rows = [np.array([game[0] == date_index for game in games])
                     for date_index in range(len(dates))]
        for lower in range(1, total_masks, 16384):
            masks = np.arange(lower, min(total_masks, lower + 16384), dtype=np.uint64)
            included = ((masks[:, None] >> bit_positions) & 1).astype(bool)
            scores = np.where(included[:, None, :], utilities[None, :, :], -99.0)
            choices = scores.argmax(axis=2)
            complete = (scores.max(axis=2) > -90).all(axis=1)
            chosen_statuses = np.take_along_axis(
                statuses[None, :, :], choices[:, :, None], axis=2,
            )[:, :, 0]
            cap_compliant = complete.copy()
            for rows in date_rows:
                for market_index_value in range(len(markets)):
                    cap_compliant &= (choices[:, rows] == market_index_value).sum(axis=1) <= market_cap
            valid = np.flatnonzero(cap_compliant)
            searched_masks += len(masks)
            complete_masks += len(valid)
            if not len(valid):
                continue
            wins = (chosen_statuses[valid] == 1).sum(axis=1)
            losses = (chosen_statuses[valid] == 0).sum(axis=1)
            nonwins = len(games) - wins
            ordering = np.lexsort((losses, nonwins))
            for valid_index in valid[ordering[:1]]:
                selected = [references[game_index][int(choices[valid_index, game_index])]
                            for game_index in range(len(games))]
                result = {
                    "minimum_odds": floor, "minimum_probability": cutoff,
                    "maximum_rank": maximum_rank,
                    "disagreement_tolerance": disagreement,
                    "markets": [market for index, market in enumerate(markets)
                                if int(masks[valid_index]) >> index & 1],
                    "wins": int((chosen_statuses[valid_index] == 1).sum()),
                    "losses": int((chosen_statuses[valid_index] == 0).sum()),
                    "unresolved_or_push": int((chosen_statuses[valid_index] >= 2).sum()),
                    "cards": {
                        played: summarize(
                            [row for row in selected if str(row.get("official_date") or "")[:10] == played],
                            {game_id for _, date, game_id in games if date == played},
                        ) for played in dates
                    },
                }
                if best is None or (result["wins"], -result["losses"], -result["unresolved_or_push"]) > (
                    best["wins"], -best["losses"], -best["unresolved_or_push"]
                ):
                    best = result
                if result["wins"] == len(games):
                    perfect.append(result)
            if perfect:
                break
        if perfect:
            break
    return {
        "configuration_count": 3 * 2 * 2 * 2,
        "market_masks_evaluated": searched_masks,
        "cap_compliant_complete_masks": complete_masks,
        "perfect_composition_count": len(perfect),
        "best_perfect_compositions": perfect[:10],
        "best_nonperfect_composition": None if perfect else best,
    }


def policy_grid():
    # Joint ranking profiles keep the search broad without wasting hundreds of
    # thousands of evaluations on nearly equivalent Cartesian combinations.
    ranking_profiles = [
        (0, 0, 0, 0, 0),
        (.005, 0, 0, 0, 0), (.01, 0, 0, 0, 0), (.02, 0, 0, 0, 0),
        (0, .25, 0, 0, 0), (0, .50, 0, 0, 0), (0, 1.0, 0, 0, 0),
        (0, 0, .01, .0025, 0), (0, 0, .025, .005, 0), (0, 0, .05, .01, 0),
        (0, 0, 0, 0, .01), (0, 0, 0, 0, .025),
        (.005, .25, .01, .0025, 0), (.01, .50, .025, .005, 0),
        (.02, 1.0, .05, .01, 0),
        (.005, .25, .01, .0025, .01), (.01, .50, .025, .005, .01),
        (.02, 1.0, .05, .01, .025),
        (.02, .25, .025, .0025, 0), (.005, 1.0, .01, .01, 0),
        (.01, .25, .05, .005, .025), (.005, .50, .025, .01, .01),
        (.02, .50, .01, .005, .01), (.01, 1.0, .05, .0025, .025),
    ]
    for floor, cutoff, rank, disagreement in itertools.product(
        (1.2, 1.25, 1.3, 1.35, 1.4, 1.5),
        (.50, .55, .60, .65, .70),
        (1, 2, 3, 5, 10, 999),
        (.05, .10, .15, .25, .50),
    ):
        for profile in ranking_profiles:
            yield (floor, cutoff, rank, disagreement, *profile)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=3)
    parser.add_argument("--through", default="2026-08-07")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()

    builds = jsonl(BUILDS)
    boxes = {int(row["game_id"]): row for row in jsonl(BOXES)}
    available = sorted({
        str(row.get("start_date") or "")[:10] for row in builds
        if str(row.get("start_date") or "")[:10] <= args.through
    })
    dates = available[-max(1, args.days):]
    candidates = candidates_by_date(builds, boxes, dates)
    boards: dict[str, dict[float, list[dict]]] = {}
    for played in dates:
        prior_report = build_report(evaluated_rows(builds, boxes, before_date=played))
        boards[played] = {
            floor: scored_board(candidates.get(played, []), prior_report, "balanced", floor)
            for floor in (1.2, 1.25, 1.3, 1.35, 1.4, 1.5)
        }

    oracle = {}
    for floor in (1.2, 1.3, 1.4, 1.5):
        oracle[str(floor)] = {}
        for played in dates:
            witness = oracle_card(boards[played][floor], floor)
            expected = {int(row["game_id"]) for row in boards[played][floor]}
            oracle[str(floor)][played] = None if witness is None else summarize(witness, expected)

    composition_search = search_market_compositions(boards, dates)

    tested = 0
    complete_policies = 0
    perfect = []
    best = []
    for values in policy_grid():
        policy = Policy(*values)
        tested += 1
        cards = {}
        total_wins = total_losses = total_unresolved = total_legs = 0
        complete = True
        for played in dates:
            board = boards[played][policy.minimum_odds]
            expected = {int(row["game_id"]) for row in board}
            card = summarize(select_card(board, policy), expected)
            cards[played] = card
            complete = complete and card["complete"]
            total_wins += card["wins"]; total_losses += card["losses"]
            total_unresolved += card["unresolved"] + card["pushes"]
            total_legs += card["legs"]
        if complete:
            complete_policies += 1
        result = {
            "policy": asdict(policy), "cards": cards,
            "complete_all_dates": complete,
            "total_legs": total_legs, "wins": total_wins,
            "losses": total_losses, "unresolved_or_push": total_unresolved,
            "clean_sweep_all_dates": complete and total_losses == 0 and total_unresolved == 0,
        }
        if result["clean_sweep_all_dates"]:
            perfect.append(result)
        best.append(result)

    best.sort(key=lambda row: (
        row["clean_sweep_all_dates"], row["complete_all_dates"],
        row["wins"], -row["losses"], -row["unresolved_or_push"], row["total_legs"],
    ), reverse=True)
    perfect.sort(key=lambda row: (
        row["policy"]["minimum_odds"], row["policy"]["minimum_probability"],
        -row["policy"]["maximum_rank"], -row["policy"]["disagreement_tolerance"],
    ), reverse=True)
    report = {
        "method": "One fixed outcome-blind policy across all dates; each date uses only earlier-date build calibration",
        "warning": "The policy grid was searched after these outcomes. Any apparent winner remains shadow-only until validated on unseen slates.",
        "limitations": [
            "Priced candidates come from selections exposed by recorded Build Best actions, not an independently archived full sportsbook board.",
            "The full projection archive has broader candidates but did not retain historical sportsbook odds, so it cannot support an odds-floor replay.",
            "August 5 lacks paired prices; its single displayed price is a vig-inclusive sportsbook-probability proxy.",
            "August 6 has only 11 archived games with priced Build Best candidates, so its all-games card contains 11 rather than 15 legs.",
        ],
        "dates": dates, "market_side_cap": 3,
        "configurations_tested": tested,
        "complete_policy_count": complete_policies,
        "perfect_policy_count": len(perfect),
        "oracle_feasibility": oracle,
        "fixed_market_composition_search": composition_search,
        "best_perfect_policies": perfect[:10],
        "best_nonperfect_policies": best[:10] if not perfect else [],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({
        "dates": dates, "configurations_tested": tested,
        "complete_policy_count": complete_policies,
        "perfect_policy_count": len(perfect),
        "oracle_possible_at_1_30": {
            played: oracle["1.3"][played] is not None for played in dates
        },
        "fixed_market_composition_search": {
            key: value for key, value in composition_search.items()
            if key not in {"best_perfect_compositions", "best_nonperfect_composition"}
        },
        "best": (perfect or best)[:1],
    }, indent=2))


if __name__ == "__main__":
    main()
