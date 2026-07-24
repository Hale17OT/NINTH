"""Leakage-safe, market-free features for forecasting MLB game totals."""
from collections import defaultdict, deque
from copy import deepcopy
from datetime import date
from math import cos, pi, sin, sqrt

import numpy as np

from ml.features import apply_result, fresh_state, reset_season_records, serializable_state


TOTAL_FEATURE_NAMES = [
    "league_recent_runs", "home_offense_20", "away_offense_20",
    "home_runs_allowed_20", "away_runs_allowed_20", "home_recent_total_10",
    "away_recent_total_10", "home_total_volatility_20", "away_total_volatility_20",
    "venue_recent_total", "starter_era_sum", "starter_whip_sum", "starter_fip_sum",
    "lineup_ops_sum", "bullpen_3day_pitches_sum", "minimum_team_rest",
    "temperature_f", "wind_speed_mph", "month_sin", "month_cos", "context_available",
    "home_starter_era", "away_starter_era",
    "home_starter_whip", "away_starter_whip", "home_starter_fip", "away_starter_fip",
    "home_starter_k_minus_bb_per_inning", "away_starter_k_minus_bb_per_inning",
    "home_starter_prior_innings", "away_starter_prior_innings",
    "home_lineup_ops", "away_lineup_ops", "home_lineup_ops_spread", "away_lineup_ops_spread",
    "home_lineup_bottom_ops", "away_lineup_bottom_ops",
    "home_bullpen_3day_pitches", "away_bullpen_3day_pitches", "home_rest", "away_rest",
    "prior_matchup_expected_total", "prior_offense_sum", "prior_defense_sum",
    "shrunk_matchup_expected_total", "prior_strength_reliability",
]


def fresh_totals_state():
    return {
        "base": fresh_state(),
        "league_totals": deque(maxlen=400),
        "venue_totals": defaultdict(lambda: deque(maxlen=100)),
    }


def _deque(value, size):
    return value if isinstance(value, deque) else deque(value or [], maxlen=size)


def hydrate_totals_state(value):
    state = deepcopy(value)
    state["league_totals"] = _deque(state.get("league_totals"), 400)
    venues = defaultdict(lambda: deque(maxlen=100))
    for key, rows in state.get("venue_totals", {}).items():
        venues[str(key)] = _deque(rows, 100)
    state["venue_totals"] = venues
    # Hydrate the base state through its existing compatibility layer.
    base = state["base"]
    for team_id in list(base.get("teams", {})):
        from ml.features import _team
        _team(base, team_id)
    return state


def serializable_totals_state(state):
    return {
        "base": serializable_state(state["base"]),
        "league_totals": list(state["league_totals"]),
        "venue_totals": {str(key): list(value) for key, value in state["venue_totals"].items()},
    }


def _avg(values, default):
    rows = list(values)
    return float(sum(rows) / len(rows)) if rows else float(default)


def _std(values, default=3.5):
    rows = list(values)
    return float(np.std(rows)) if len(rows) >= 4 else float(default)


def _team(base, team_id):
    from ml.features import _team as team_value
    return team_value(base, team_id)


def _rest(last_date, game_date):
    if not last_date:
        return 3.0
    return float(max(0, min(10, (date.fromisoformat(game_date) - date.fromisoformat(last_date)).days - 1)))


def _number(value, default):
    try:
        value = float(value)
        return value if np.isfinite(value) else float(default)
    except (TypeError, ValueError):
        return float(default)


def totals_features(state, home_id, away_id, game_date, context=None):
    """Build features using only games and context known before ``game_date``."""
    context = context or {}
    home_context, away_context = context.get("home", {}), context.get("away", {})
    weather = context.get("weather", {})
    home, away = _team(state["base"], home_id), _team(state["base"], away_id)
    from ml.features import _bullpen
    league = _avg(state["league_totals"], 9.0)
    home_totals = [a + b for a, b in zip(home["runs_for"], home["runs_allowed"])]
    away_totals = [a + b for a, b in zip(away["runs_for"], away["runs_allowed"])]
    month = date.fromisoformat(game_date).month
    lineup_home = _number(home_context.get("lineup_ops_shrunk", home_context.get("lineup_ops")), .710)
    lineup_away = _number(away_context.get("lineup_ops_shrunk", away_context.get("lineup_ops")), .710)
    def lineup_shape(side):
        values = [_number(row.get("shrunk_ops", row.get("ops")), .710) for row in side.get("lineup_players", [])]
        if not values:
            return .08, .68
        return float(np.std(values)), float(np.mean(sorted(values)[:min(3, len(values))]))
    home_spread, home_bottom = lineup_shape(home_context)
    away_spread, away_bottom = lineup_shape(away_context)
    home_innings = _number(home_context.get("starter_innings"), 0)
    away_innings = _number(away_context.get("starter_innings"), 0)
    home_kbb = (_number(home_context.get("starter_strikeouts"), 0) - _number(home_context.get("starter_walks"), 0)) / max(10, home_innings)
    away_kbb = (_number(away_context.get("starter_strikeouts"), 0) - _number(away_context.get("starter_walks"), 0)) / max(10, away_innings)
    home_bullpen = _number(home_context.get("bullpen_recent_pitches"), _bullpen(home, game_date))
    away_bullpen = _number(away_context.get("bullpen_recent_pitches"), _bullpen(away, game_date))
    def prior_rates(team):
        previous=team.get("previous_season") or {};games=float(previous.get("games",0));weight=games/(games+30)
        offense=(float(previous.get("runs_for_total",0))+30*league/2)/(games+30)
        defense=(float(previous.get("runs_allowed_total",0))+30*league/2)/(games+30)
        current_games=float(team.get("games",0));shrunk_offense=(float(team.get("runs_for_total",0))+30*offense)/(current_games+30);shrunk_defense=(float(team.get("runs_allowed_total",0))+30*defense)/(current_games+30)
        return offense,defense,shrunk_offense,shrunk_defense,weight
    hp,ap=prior_rates(home),prior_rates(away)
    legacy = [
        league,
        _avg(list(home["runs_for"])[-20:], league / 2),
        _avg(list(away["runs_for"])[-20:], league / 2),
        _avg(list(home["runs_allowed"])[-20:], league / 2),
        _avg(list(away["runs_allowed"])[-20:], league / 2),
        _avg(home_totals[-10:], league), _avg(away_totals[-10:], league),
        _std(home_totals[-20:]), _std(away_totals[-20:]),
        _avg(state["venue_totals"][str(home_id)], league),
        _number(home_context.get("starter_era"), 4.5) + _number(away_context.get("starter_era"), 4.5),
        _number(home_context.get("starter_whip"), 1.35) + _number(away_context.get("starter_whip"), 1.35),
        _number(home_context.get("starter_fip"), 4.5) + _number(away_context.get("starter_fip"), 4.5),
        lineup_home + lineup_away, home_bullpen + away_bullpen,
        min(_rest(home.get("last_date"), game_date), _rest(away.get("last_date"), game_date)),
        _number(weather.get("temperature"), 65), _number(weather.get("wind_speed"), 0),
        sin(2 * pi * month / 12), cos(2 * pi * month / 12), float(bool(context)),
    ]
    detail = [
        _number(home_context.get("starter_era"), 4.5), _number(away_context.get("starter_era"), 4.5),
        _number(home_context.get("starter_whip"), 1.35), _number(away_context.get("starter_whip"), 1.35),
        _number(home_context.get("starter_fip"), 4.5), _number(away_context.get("starter_fip"), 4.5),
        home_kbb, away_kbb, min(home_innings, 250), min(away_innings, 250),
        lineup_home, lineup_away, home_spread, away_spread, home_bottom, away_bottom,
        home_bullpen, away_bullpen, _rest(home.get("last_date"), game_date), _rest(away.get("last_date"), game_date),
        .5*(hp[0]+ap[1]+ap[0]+hp[1]),hp[0]+ap[0],hp[1]+ap[1],
        .5*(hp[2]+ap[3]+ap[2]+hp[3]),min(hp[4],ap[4]),
    ]
    return legacy + detail


def apply_totals_result(state, game, context=None):
    total = int(game["home_score"]) + int(game["away_score"])
    state["league_totals"].append(total)
    state["venue_totals"][str(game["home_id"])].append(total)
    apply_result(state["base"], game, context)


def reset_totals_season(state):
    reset_season_records(state["base"])
