"""Leakage-safe starter workload and reliever availability features.

The state is updated only after a completed game.  Historical bullpen rosters
are inferred from prior relief appearances rather than a final boxscore's list
of relievers, which would reveal managerial decisions made after first pitch.
"""
from __future__ import annotations

from collections import defaultdict, deque
from copy import deepcopy
from datetime import date
from math import exp

import numpy as np


MONEYLINE_FEATURE_NAMES = [
    "starter_recent_outs_advantage",
    "starter_recent_run_prevention_advantage",
    "starter_pitch_efficiency_advantage",
    "starter_workload_rest_advantage",
    "starter_velocity_trend_advantage",
    "starter_xwoba_trend_advantage",
    "bullpen_available_quality_advantage",
    "bullpen_lost_quality_advantage",
    "bullpen_fresh_depth_advantage",
    "bullpen_individual_load_advantage",
]

TOTAL_FEATURE_NAMES = [
    "starter_recent_outs_sum",
    "starter_recent_run_rate_sum",
    "starter_pitch_efficiency_sum",
    "starter_workload_rest_sum",
    "starter_velocity_decline_sum",
    "starter_recent_xwoba_sum",
    "bullpen_available_quality_sum",
    "bullpen_lost_quality_sum",
    "bullpen_fresh_depth_sum",
    "bullpen_individual_load_sum",
]


def fresh_state():
    return {
        "starters": defaultdict(lambda: deque(maxlen=15)),
        "relievers": defaultdict(lambda: deque(maxlen=30)),
        "team_relievers": defaultdict(dict),
    }


def serializable_state(state):
    return {
        "starters": {key: list(value) for key, value in state["starters"].items()},
        "relievers": {key: list(value) for key, value in state["relievers"].items()},
        "team_relievers": {key: dict(value) for key, value in state["team_relievers"].items()},
    }


def hydrate_state(value):
    source = deepcopy(value or {})
    state = fresh_state()
    for key, rows in source.get("starters", {}).items():
        state["starters"][str(key)] = deque(rows, maxlen=15)
    for key, rows in source.get("relievers", {}).items():
        state["relievers"][str(key)] = deque(rows, maxlen=30)
    for key, rows in source.get("team_relievers", {}).items():
        state["team_relievers"][str(key)] = dict(rows)
    return state


def _number(value, default=0.0):
    try:
        result = float(value)
        return result if np.isfinite(result) else float(default)
    except (TypeError, ValueError):
        return float(default)


def _days(previous, current, default=5):
    if not previous:
        return float(default)
    return float(max(1, min(14, (date.fromisoformat(current) - date.fromisoformat(previous)).days)))


def _weighted(rows, field, weight, default):
    denominator = sum(_number(row.get(weight)) for row in rows)
    if denominator <= 0:
        return float(default)
    return sum(_number(row.get(field), default) * _number(row.get(weight)) for row in rows) / denominator


def _starter_summary(rows, game_date):
    rows = list(rows)
    recent = rows[-3:]
    long = rows[-15:]
    outs = sum(_number(row.get("outs")) for row in recent)
    pitches = sum(_number(row.get("pitches")) for row in recent)
    earned = sum(_number(row.get("earned_runs")) for row in recent)
    recent_xwoba = _weighted(recent, "xwoba", "plate_appearances", .320)
    long_xwoba = _weighted(long, "xwoba", "plate_appearances", .320)
    recent_velocity = _weighted(recent, "avg_velocity", "pitches", 92.5)
    long_velocity = _weighted(long, "avg_velocity", "pitches", 92.5)
    reliability = outs / (outs + 45.0)
    average_outs = outs / len(recent) if recent else 15.0
    run_rate = 27.0 * earned / outs if outs else 4.5
    efficiency = pitches / outs if outs else 5.4
    last_pitches = _number(recent[-1].get("pitches"), 80) if recent else 80.0
    rest = _days(recent[-1].get("date") if recent else None, game_date)
    return {
        "outs": 15.0 + reliability * (average_outs - 15.0),
        "run_rate": 4.5 + reliability * (run_rate - 4.5),
        "efficiency": 5.4 + reliability * (efficiency - 5.4),
        "fatigue": last_pitches / rest,
        "velocity_trend": reliability * (recent_velocity - long_velocity),
        "xwoba_trend": reliability * (recent_xwoba - long_xwoba),
        "xwoba": .320 + reliability * (recent_xwoba - .320),
    }


def _reliever_summary(rows, game_date):
    rows = list(rows)
    recent_date = date.fromisoformat(game_date)
    active = [
        row for row in rows
        if 0 < (recent_date - date.fromisoformat(row["date"])).days <= 30
    ]
    pa = sum(_number(row.get("plate_appearances")) for row in active)
    xwoba = _weighted(active, "xwoba", "plate_appearances", .320)
    strikeouts = sum(_number(row.get("strikeouts")) for row in active)
    walks = sum(_number(row.get("walks")) for row in active)
    reliability = pa / (pa + 80.0)
    kbb = (strikeouts - walks) / pa if pa else .12
    quality = reliability * ((.320 - xwoba) + .25 * (kbb - .12))
    load1 = load3 = 0.0
    appearance_days = set()
    for row in active:
        age = (recent_date - date.fromisoformat(row["date"])).days
        pitches = _number(row.get("pitches"))
        if age <= 3:
            load3 += pitches
            appearance_days.add(age)
        if age == 1:
            load1 += pitches
    back_to_back = float(1 in appearance_days and 2 in appearance_days)
    availability = exp(-load1 / 35.0 - load3 / 120.0 - .35 * back_to_back)
    return quality, availability, load3


def _bullpen_summary(state, team_id, game_date):
    roster = state["team_relievers"].get(str(team_id), {})
    today = date.fromisoformat(game_date)
    pitcher_ids = [
        pitcher_id for pitcher_id, last_date in roster.items()
        if 0 < (today - date.fromisoformat(last_date)).days <= 30
    ]
    values = [_reliever_summary(state["relievers"][pitcher_id], game_date) for pitcher_id in pitcher_ids]
    values.sort(key=lambda row: row[0], reverse=True)
    core = values[:7]
    if not core:
        return {"available": 0.0, "lost": 0.0, "fresh": .5, "load": 0.0}
    available = sum(quality * availability for quality, availability, _ in core) / len(core)
    lost = sum(abs(quality) * (1 - availability) for quality, availability, _ in core) / len(core)
    fresh = sum(availability >= .65 for _, availability, _ in core) / len(core)
    load = sum(value[2] for value in core) / len(core)
    return {"available": available, "lost": lost, "fresh": fresh, "load": load}


def features(state, game, context):
    context = context or {}
    home_context, away_context = context.get("home", {}), context.get("away", {})
    home_starter = _starter_summary(state["starters"][str(home_context.get("starter_id"))], game["date"])
    away_starter = _starter_summary(state["starters"][str(away_context.get("starter_id"))], game["date"])
    home_pen = _bullpen_summary(state, game["home_id"], game["date"])
    away_pen = _bullpen_summary(state, game["away_id"], game["date"])
    moneyline = [
        home_starter["outs"] - away_starter["outs"],
        away_starter["run_rate"] - home_starter["run_rate"],
        away_starter["efficiency"] - home_starter["efficiency"],
        away_starter["fatigue"] - home_starter["fatigue"],
        home_starter["velocity_trend"] - away_starter["velocity_trend"],
        away_starter["xwoba_trend"] - home_starter["xwoba_trend"],
        home_pen["available"] - away_pen["available"],
        away_pen["lost"] - home_pen["lost"],
        home_pen["fresh"] - away_pen["fresh"],
        away_pen["load"] - home_pen["load"],
    ]
    totals = [
        home_starter["outs"] + away_starter["outs"],
        home_starter["run_rate"] + away_starter["run_rate"],
        home_starter["efficiency"] + away_starter["efficiency"],
        home_starter["fatigue"] + away_starter["fatigue"],
        min(0.0, home_starter["velocity_trend"]) + min(0.0, away_starter["velocity_trend"]),
        home_starter["xwoba"] + away_starter["xwoba"],
        home_pen["available"] + away_pen["available"],
        home_pen["lost"] + away_pen["lost"],
        home_pen["fresh"] + away_pen["fresh"],
        home_pen["load"] + away_pen["load"],
    ]
    return moneyline, totals


def apply_game(state, game, context, statcast):
    context, statcast = context or {}, statcast or {}
    for side, team_key in (("home", "home_id"), ("away", "away_id")):
        current = context.get(side, {})
        observed_starter = statcast.get(f"{side}_starter") or {}
        official_id = current.get("starter_id")
        if official_id and str(observed_starter.get("pitcher_id")) == str(official_id):
            state["starters"][str(official_id)].append({
                "date": game["date"],
                "outs": _number(current.get("starter_game_outs")),
                "earned_runs": _number(current.get("starter_game_earned_runs")),
                "pitches": _number(current.get("starter_game_pitches"), observed_starter.get("pitches", 0)),
                "plate_appearances": _number(observed_starter.get("plate_appearances")),
                "xwoba": _number(observed_starter.get("xwoba"), .320),
                "avg_velocity": _number(observed_starter.get("avg_velocity"), 92.5),
            })
        team_id = str(game[team_key])
        starter_id = str(observed_starter.get("pitcher_id")) if observed_starter.get("pitcher_id") else None
        for pitcher in statcast.get(f"{side}_pitcher_lines", []) or []:
            pitcher_id = pitcher.get("pitcher_id")
            if not pitcher_id or str(pitcher_id) == starter_id:
                continue
            key = str(pitcher_id)
            state["relievers"][key].append({
                "date": game["date"], "pitches": _number(pitcher.get("pitches")),
                "plate_appearances": _number(pitcher.get("plate_appearances")),
                "xwoba": _number(pitcher.get("xwoba"), .320),
                "strikeouts": _number(pitcher.get("strikeouts")),
                "walks": _number(pitcher.get("walks")),
            })
            state["team_relievers"][team_id][key] = game["date"]
