"""Frozen scope for the prospective within-game reranker observation."""
from __future__ import annotations


RERANKER_VERSION = "within_game_v1"
BUILD_STYLE = "sweep"
TARGET_LEGS = 3
MINIMUM_ODDS = 1.30
MINIMUM_PROCESS_PROBABILITY = 0.65
ROTATIONS = 3
MARKET_SIDE_CAP = 2
OBSERVATION_STARTED_AT = "2026-08-17"
MINIMUM_FORWARD_DATES = 10


def candidate_definition() -> dict:
    """Return a fresh copy so callers cannot mutate the shared definition."""
    return {
        "candidate_id": "within_game_v1-sweep-3-odds-1.30-probability-0.65",
        "reranker_version": RERANKER_VERSION,
        "status": "shadow_only",
        "promoted": False,
        "build_style": BUILD_STYLE,
        "target_legs": TARGET_LEGS,
        "minimum_odds": MINIMUM_ODDS,
        "minimum_process_probability": MINIMUM_PROCESS_PROBABILITY,
        "rotations": ROTATIONS,
        "market_side_cap": MARKET_SIDE_CAP,
        "observation_started_at": OBSERVATION_STARTED_AT,
        "automatic_promotion": False,
    }
