"""Point-in-time multi-season hitter talent used by moneyline inference."""
from __future__ import annotations

from collections import deque

import numpy as np


FEATURE_NAMES = [
    "lineup_talent_woba_advantage", "lineup_talent_top_four_advantage",
    "lineup_talent_depth_advantage", "lineup_talent_power_advantage",
    "lineup_talent_discipline_advantage", "lineup_talent_joint_reliability",
]
TOTAL_FEATURE_NAMES = [
    "lineup_talent_woba_sum", "lineup_talent_power_sum",
    "lineup_talent_discipline_sum", "lineup_talent_joint_reliability",
]
ORDER_WEIGHTS = np.asarray([1.12, 1.10, 1.08, 1.06, 1.02, .98, .93, .88, .83])
ORDER_WEIGHTS /= ORDER_WEIGHTS.sum()


def empty_counts():
    return {
        "pa": 0.0, "ab": 0.0, "hits": 0.0, "doubles": 0.0,
        "triples": 0.0, "hr": 0.0, "walks": 0.0, "hbp": 0.0,
        "sf": 0.0, "strikeouts": 0.0,
    }


def fresh_state():
    return {"season": None, "players": {}}


def _player(state, player_id):
    key = str(player_id)
    if key not in state["players"]:
        state["players"][key] = {"career": empty_counts(), "recent": []}
    return state["players"][key]


def start_season(state, season):
    if state.get("season") is not None and state["season"] != season:
        for player in state["players"].values():
            for key in player["career"]:
                player["career"][key] *= .78
            player["recent"] = []
    state["season"] = int(season)


def _add(target, batting):
    mapping = {
        "pa": "plateAppearances", "ab": "atBats", "hits": "hits",
        "doubles": "doubles", "triples": "triples", "hr": "homeRuns",
        "walks": "baseOnBalls", "hbp": "hitByPitch", "sf": "sacFlies",
        "strikeouts": "strikeOuts",
    }
    for key, source in mapping.items():
        target[key] += float(batting.get(source, 0) or 0)


def apply_boxscore(state, boxscore):
    start_season(state, int(boxscore["season"]))
    for side in ("home", "away"):
        for row in (boxscore.get(side) or {}).get("players", []):
            batting = row.get("batting")
            if not batting or not row.get("player_id"):
                continue
            player = _player(state, row["player_id"])
            game = empty_counts()
            _add(game, batting)
            _add(player["career"], batting)
            player["recent"].append(game)
            player["recent"] = player["recent"][-40:]


def _rates(player):
    recent = empty_counts()
    for game in player["recent"]:
        for key, value in game.items():
            recent[key] += value
    counts = {
        key: .7 * player["career"][key] + .3 * recent[key]
        for key in recent
    }
    pa = counts["pa"]
    singles = max(0, counts["hits"] - counts["doubles"] - counts["triples"] - counts["hr"])
    denominator = max(1, counts["ab"] + counts["walks"] + counts["hbp"] + counts["sf"])
    woba = (
        .69 * counts["walks"] + .72 * counts["hbp"] + .89 * singles
        + 1.27 * counts["doubles"] + 1.62 * counts["triples"] + 2.10 * counts["hr"]
    ) / denominator
    reliability = pa / (pa + 180)
    return {
        "woba": .315 + reliability * (woba - .315),
        "power": .032 + reliability * (counts["hr"] / max(1, pa) - .032),
        "discipline": -.13 + reliability * (
            (counts["walks"] - counts["strikeouts"]) / max(1, pa) + .13
        ),
        "reliability": reliability,
    }


def _summaries(state, context):
    context = context or {}
    sides = []
    for side in ("home", "away"):
        ids = list((context.get(side) or {}).get("lineup_ids") or [])[:9]
        values = [_rates(_player(state, player_id)) for player_id in ids]
        while len(values) < 9:
            values.append(_rates({"career": empty_counts(), "recent": []}))
        sides.append({
            "woba": float(sum(weight * row["woba"] for weight, row in zip(ORDER_WEIGHTS, values))),
            "top": float(np.mean([row["woba"] for row in values[:4]])),
            "depth": float(np.mean([row["woba"] for row in values[4:]])),
            "power": float(sum(weight * row["power"] for weight, row in zip(ORDER_WEIGHTS, values))),
            "discipline": float(sum(weight * row["discipline"] for weight, row in zip(ORDER_WEIGHTS, values))),
            "reliability": float(np.mean([row["reliability"] for row in values])),
        })
    return sides


def features(state, context):
    home, away = _summaries(state, context)
    return [
        home["woba"] - away["woba"], home["top"] - away["top"],
        home["depth"] - away["depth"], home["power"] - away["power"],
        home["discipline"] - away["discipline"],
        min(home["reliability"], away["reliability"]),
    ]


def totals_features(state, context):
    home, away = _summaries(state, context)
    return [
        home["woba"] + away["woba"], home["power"] + away["power"],
        home["discipline"] + away["discipline"],
        min(home["reliability"], away["reliability"]),
    ]
