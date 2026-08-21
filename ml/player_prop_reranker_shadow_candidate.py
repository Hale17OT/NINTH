"""Prospective audit for the single approved within-game reranker shadow lane.

This module deliberately evaluates one frozen configuration instead of searching
many configurations after results are known.  It reuses immutable pregame Build
Best candidates, calculates each slate from evidence available strictly before
that slate, and never changes the production ranking or promotes itself.
"""
from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from ml.evaluate_player_prop_builds import (
    BOXES,
    BUILDS,
    build_report as build_selection_report,
    evaluated_rows,
    jsonl,
)
from ml.player_prop_reranker_shadow_config import (
    BUILD_STYLE,
    MARKET_SIDE_CAP,
    MINIMUM_FORWARD_DATES,
    MINIMUM_ODDS,
    MINIMUM_PROCESS_PROBABILITY,
    OBSERVATION_STARTED_AT,
    ROTATIONS,
    TARGET_LEGS,
    candidate_definition,
)
from ml.shadow_player_prop_reranker_4_day import history, rerank, replay_cards
from ml.shadow_player_prop_selection_policy import candidates_by_date, scored_board


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "ml" / "artifacts" / "player_prop_reranker_shadow_candidate.json"

def _card_totals(cards: list[dict]) -> Counter:
    totals = Counter()
    for card in cards:
        totals.update({
            "cards": 1,
            "complete_cards": int(card["complete"]),
            "clean_cards": int(card["clean_sweep"]),
            "legs": int(card["legs"]),
            "wins": int(card["wins"]),
            "losses": int(card["losses"]),
            "unresolved": int(card["unresolved"]) + int(card["pushes"]),
        })
    return totals


def _metrics(values: Counter | dict) -> dict:
    values = Counter(values)
    for key in ("cards", "complete_cards", "clean_cards", "legs", "wins", "losses", "unresolved"):
        values.setdefault(key, 0)
    settled = values["wins"] + values["losses"]
    complete = values["complete_cards"]
    return {
        **dict(values),
        "leg_accuracy": round(values["wins"] / settled, 6) if settled else None,
        "clean_sweep_rate": round(values["clean_cards"] / complete, 6) if complete else None,
    }


def evaluate(
    builds: list[dict],
    boxes: dict[int, dict],
    through: str,
    historical_days: int = 4,
) -> dict:
    available = sorted({
        str(row.get("start_date") or "")[:10]
        for row in builds
        if str(row.get("start_date") or "")[:10]
        and str(row.get("start_date") or "")[:10] <= through
    })
    archived_dates = [value for value in available if value < OBSERVATION_STARTED_AT]
    recent_dates = archived_dates[-max(1, historical_days):]
    attempted_forward_dates = [value for value in available if value >= OBSERVATION_STARTED_AT]
    dates = archived_dates + attempted_forward_dates
    candidates = candidates_by_date(builds, boxes, dates)
    histories = history(boxes)
    daily = {}
    archived = {"baseline": Counter(), "reranker": Counter()}
    recent = {"baseline": Counter(), "reranker": Counter()}
    forward = {"baseline": Counter(), "reranker": Counter()}
    qualified_forward_dates = []

    for played in dates:
        # Every calibration row must precede the slate being evaluated.
        prior_report = build_selection_report(evaluated_rows(builds, boxes, before_date=played))
        raw = scored_board(candidates.get(played, []), prior_report, BUILD_STYLE, MINIMUM_ODDS)
        board = [
            rerank(row, played, histories)
            for row in raw
            if float(row["process_probability"]) >= MINIMUM_PROCESS_PROBABILITY
        ]
        baseline_cards = replay_cards(
            board, TARGET_LEGS, MARKET_SIDE_CAP, "process_probability", ROTATIONS,
        )
        reranker_cards = replay_cards(
            board, TARGET_LEGS, MARKET_SIDE_CAP, "rerank_score", ROTATIONS,
        )
        complete_comparison = (
            any(bool(card.get("complete")) for card in baseline_cards)
            and any(bool(card.get("complete")) for card in reranker_cards)
        )
        daily[played] = {
            "eligible_candidates": len(board),
            "eligible_games": len({int(row["game_id"]) for row in board}),
            "qualified_forward_date": played >= OBSERVATION_STARTED_AT and complete_comparison,
            "qualification_reason": (
                "At least one complete baseline and reranker card were available."
                if complete_comparison else
                f"A complete {TARGET_LEGS}-leg baseline and reranker comparison was not available."
            ),
            "baseline": baseline_cards,
            "reranker": reranker_cards,
        }
        for name, cards in (("baseline", baseline_cards), ("reranker", reranker_cards)):
            totals = _card_totals(cards)
            if played < OBSERVATION_STARTED_AT:
                archived[name].update(totals)
            if played in recent_dates:
                recent[name].update(totals)
            if played >= OBSERVATION_STARTED_AT and complete_comparison:
                forward[name].update(totals)
        if played >= OBSERVATION_STARTED_AT and complete_comparison:
            qualified_forward_dates.append(played)

    archived_metrics = {name: _metrics(values) for name, values in archived.items()}
    recent_metrics = {name: _metrics(values) for name, values in recent.items()}
    forward_metrics = {name: _metrics(values) for name, values in forward.items()}
    baseline = recent_metrics["baseline"]
    challenger = recent_metrics["reranker"]
    archived_baseline = archived_metrics["baseline"]
    archived_challenger = archived_metrics["reranker"]
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "through": through,
        "candidate": candidate_definition(),
        "method": (
            "Frozen within_game_v1 comparison on immutable pregame Build Best candidates; "
            "selection calibration and player history use only earlier settled dates"
        ),
        "dates": dates,
        "historical_context": {
            "dates": recent_dates,
            "baseline": baseline,
            "reranker": challenger,
            "leg_win_delta": challenger.get("wins", 0) - baseline.get("wins", 0),
            "clean_sweep_delta": challenger.get("clean_cards", 0) - baseline.get("clean_cards", 0),
        },
        "all_archived_context": {
            "dates": archived_dates,
            "baseline": archived_baseline,
            "reranker": archived_challenger,
            "leg_win_delta": archived_challenger.get("wins", 0) - archived_baseline.get("wins", 0),
            "clean_sweep_delta": archived_challenger.get("clean_cards", 0) - archived_baseline.get("clean_cards", 0),
        },
        "forward_observation": {
            "attempted_dates": attempted_forward_dates,
            "dates": qualified_forward_dates,
            "incomplete_dates": [
                value for value in attempted_forward_dates if value not in qualified_forward_dates
            ],
            "baseline": forward_metrics["baseline"],
            "reranker": forward_metrics["reranker"],
        },
        "promotion_gate": {
            "eligible": False,
            "automatic_promotion": False,
            "minimum_forward_dates": MINIMUM_FORWARD_DATES,
            "observed_forward_dates": len(qualified_forward_dates),
            "reason": (
                "Shadow evidence is observation-only. Promotion requires a separate manual review "
                f"after at least {MINIMUM_FORWARD_DATES} settled forward dates with a complete "
                f"{TARGET_LEGS}-leg baseline and reranker comparison."
            ),
        },
        "daily": daily,
        "limitations": [
            "Candidate membership comes from selections exposed by recorded Build Best actions; it is not the unrestricted priced board.",
            "Rotations from the same slate overlap and are not independent observations.",
            "The recent historical window selected this lane and is exploratory; the full older archive is reported separately.",
            "All historical dates before the observation start are context only and cannot satisfy the promotion gate.",
            f"A forward date counts only when both lanes can produce a complete {TARGET_LEGS}-leg card.",
        ],
    }


def write_report(report: dict, output: Path = OUTPUT) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(json.dumps(report, indent=2), encoding="utf-8")
    os.replace(temporary, output)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--through")
    parser.add_argument("--historical-days", "--days", type=int, default=4)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    builds = jsonl(BUILDS)
    boxes = {int(row["game_id"]): row for row in jsonl(BOXES)}
    available = sorted(str(row.get("start_date") or "")[:10] for row in builds if row.get("start_date"))
    through = args.through or (available[-1] if available else datetime.now(timezone.utc).date().isoformat())
    report = evaluate(builds, boxes, through, args.historical_days)
    write_report(report, args.output)
    print(json.dumps({
        "through": report["through"],
        "candidate": report["candidate"],
        "dates": report["dates"],
        "historical_context": report["historical_context"],
        "all_archived_context": report["all_archived_context"],
        "forward_observation": report["forward_observation"],
        "promotion_gate": report["promotion_gate"],
    }))


if __name__ == "__main__":
    main()
