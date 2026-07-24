"""Point-in-time feature construction for NINTH player-prop models."""
from __future__ import annotations

import json
import math
from collections import defaultdict, deque
from datetime import date
from pathlib import Path

import numpy as np
from scipy.stats import nbinom, poisson


ROOT = Path(__file__).resolve().parents[1]
BOX_PATH = ROOT / "ml" / "data" / "player_boxscores.jsonl"
STATCAST_PATH = ROOT / "ml" / "data" / "statcast_rich_games.jsonl"

BATTER_PROPS = {
    "hits": (0.5, 1.5, 2.5),
    "total_bases": (0.5, 1.5, 2.5, 3.5),
    "home_runs": (0.5, 1.5),
    "runs": (0.5, 1.5),
    "rbi": (0.5, 1.5, 2.5),
    "walks": (0.5, 1.5),
    "strikeouts": (0.5, 1.5, 2.5),
    "doubles": (0.5, 1.5),
    "stolen_bases": (0.5, 1.5),
}
PITCHER_PROPS = {
    "strikeouts": tuple(x + 0.5 for x in range(2, 10)),
    "outs": tuple(x + 0.5 for x in range(11, 21)),
    "walks": tuple(x + 0.5 for x in range(0, 5)),
    "hits_allowed": tuple(x + 0.5 for x in range(2, 9)),
    "earned_runs": tuple(x + 0.5 for x in range(0, 6)),
    "home_runs_allowed": tuple(x + 0.5 for x in range(0, 4)),
    "pitches": tuple(x + 0.5 for x in range(69, 111, 10)),
}
PROP_LABELS = {
    "hits": "Hits", "total_bases": "Total bases", "home_runs": "Home runs",
    "runs": "Runs", "rbi": "RBIs", "walks": "Walks",
    "strikeouts": "Strikeouts", "doubles": "Doubles",
    "stolen_bases": "Stolen bases", "outs": "Pitching outs",
    "hits_allowed": "Hits allowed", "earned_runs": "Earned runs allowed",
    "home_runs_allowed": "Home runs allowed", "pitches": "Pitches thrown",
}
BAT_MAP = {
    "hits": "hits", "total_bases": "totalBases", "home_runs": "homeRuns",
    "runs": "runs", "rbi": "rbi", "walks": "baseOnBalls",
    "strikeouts": "strikeOuts", "doubles": "doubles", "stolen_bases": "stolenBases",
}
PITCH_MAP = {
    "strikeouts": "strikeOuts", "outs": "outs", "walks": "baseOnBalls",
    "hits_allowed": "hits", "earned_runs": "earnedRuns",
    "home_runs_allowed": "homeRuns", "pitches": "numberOfPitches",
}
STATCAST_KEYS = ("xwoba", "hard_hit_rate", "barrel_rate", "whiff_rate", "avg_exit_velocity")


def _history(maxlen=50):
    return deque(maxlen=maxlen)


def fresh_state():
    return {
        "batters": defaultdict(lambda: {"games": _history(), "prior": {}, "name": "", "team_id": None}),
        "pitchers": defaultdict(lambda: {"games": _history(), "prior": {}, "name": "", "team_id": None}),
        "teams": defaultdict(lambda: {"batting": _history(), "pitching": _history(), "lineups": _history(12)}),
        "season": None,
    }


def _jsonl(path):
    with Path(path).open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def load_games():
    return sorted(_jsonl(BOX_PATH), key=lambda row: (row["date"], int(row["game_id"])))


def load_statcast():
    """Return compact same-game outcomes used only after a sample is emitted."""
    output = {}
    if not STATCAST_PATH.exists():
        return output
    for game in _jsonl(STATCAST_PATH):
        sides = {}
        for side in ("away", "home"):
            batters = {
                int(row["batter_id"]): {key: row.get(key) for key in STATCAST_KEYS}
                for row in game.get(f"{side}_batters", [])
            }
            pitchers = {
                int(row["pitcher_id"]): {key: row.get(key) for key in STATCAST_KEYS}
                for row in game.get(f"{side}_pitcher_lines", [])
            }
            sides[side] = {"batters": batters, "pitchers": pitchers}
        output[int(game["game_id"])] = sides
    return output


def _mean(rows, key, size, default=0.0):
    values = [float(row.get(key, 0) or 0) for row in list(rows)[-size:]]
    return float(np.mean(values)) if values else float(default)


def _rate(rows, key, line, size, default):
    values = [float(row.get(key, 0) or 0) > line for row in list(rows)[-size:]]
    # Empirical-Bayes shrinkage prevents tiny samples from producing 0/1 forecasts.
    return float((sum(values) + 8 * default) / (len(values) + 8))


def _rest(rows, target_date):
    if not rows:
        return 5.0
    return float(max(0, min(14, (date.fromisoformat(target_date) - date.fromisoformat(rows[-1]["date"])).days)))


def _finite(value, default=0.0):
    try:
        value = float(value)
        return value if math.isfinite(value) else float(default)
    except (TypeError, ValueError):
        return float(default)


def distribution_probability(mean, variance, line):
    """Over probability from Poisson or negative binomial when overdispersed."""
    mean = max(0.001, float(mean)); variance = max(mean, float(variance))
    cutoff = math.floor(float(line))
    if variance <= mean * 1.02:
        return float(poisson.sf(cutoff, mean))
    dispersion = max(0.05, mean * mean / max(1e-6, variance - mean))
    success = dispersion / (dispersion + mean)
    return float(nbinom.sf(cutoff, dispersion, success))


def feature_names(kind):
    props = BATTER_PROPS if kind == "batter" else PITCHER_PROPS
    values = [
        "line", "home", "lineup_slot", "season_progress", "career_games", "season_games",
        "days_rest", "opponent_recent_pa", "opponent_recent_primary",
        "opponent_starter_games", "opponent_starter_k_10", "opponent_starter_walks_10",
        "opponent_starter_hits_10", "opponent_starter_hr_10", "opponent_starter_outs_10",
        "distribution_over", "over_rate_5", "over_rate_10", "over_rate_20", "over_rate_season",
    ]
    for prop in props:
        for window in (5, 10, 20):
            values.append(f"{prop}_{window}")
        values.extend((f"{prop}_season", f"{prop}_prior"))
    for key in STATCAST_KEYS:
        values.extend((f"{key}_10", f"{key}_season"))
    return values


def build_features(state, kind, player_id, team_id, opponent_id, game_date, season, prop, line,
                   home=False, lineup_slot=0, opponent_starter_id=None):
    bucket = state["batters" if kind == "batter" else "pitchers"][int(player_id)]
    rows = bucket["games"]
    season_rows = [row for row in rows if int(row["season"]) == int(season)]
    prior = bucket.get("prior") or {}
    props = BATTER_PROPS if kind == "batter" else PITCHER_PROPS
    team_opp = state["teams"][int(opponent_id)]["pitching" if kind == "batter" else "batting"]
    opposing_starter = state["pitchers"].get(int(opponent_starter_id or 0), {"games": []})
    starter_rows = opposing_starter.get("games", [])
    league_default = {
        "hits": .95, "total_bases": 1.45, "home_runs": .13, "runs": .52, "rbi": .5,
        "walks": .35 if kind == "batter" else 2.2, "strikeouts": .9 if kind == "batter" else 5.2,
        "doubles": .18, "stolen_bases": .08, "outs": 15.5, "hits_allowed": 4.8,
        "earned_runs": 2.5, "home_runs_allowed": .8, "pitches": 86.0,
    }[prop]
    current_mean = _mean(season_rows, prop, 50, league_default)
    recent_mean = _mean(rows, prop, 10, current_mean)
    count = len(season_rows)
    shrunk_mean = (count * recent_mean + 12 * _finite(prior.get(prop), league_default)) / (count + 12)
    values_for_var = [_finite(row.get(prop)) for row in list(rows)[-30:]]
    variance = float(np.var(values_for_var)) if len(values_for_var) >= 5 else max(shrunk_mean, league_default)
    distribution_over = distribution_probability(shrunk_mean, variance, line)
    lineup_value = float(lineup_slot or 0)
    primary = "strikeouts" if kind == "batter" else "plate_appearances"
    values = [
        float(line), float(bool(home)), lineup_value, min(1.0, len(season_rows) / 100.0),
        float(len(rows)), float(len(season_rows)), _rest(rows, game_date),
        _mean(team_opp, "plate_appearances", 10, 38.0), _mean(team_opp, primary, 10, 8.5),
        float(len(starter_rows)), _mean(starter_rows, "strikeouts", 10, 5.2),
        _mean(starter_rows, "walks", 10, 2.2), _mean(starter_rows, "hits_allowed", 10, 4.8),
        _mean(starter_rows, "home_runs_allowed", 10, .8), _mean(starter_rows, "outs", 10, 15.5),
        distribution_over,
        _rate(rows, prop, line, 5, distribution_over), _rate(rows, prop, line, 10, distribution_over),
        _rate(rows, prop, line, 20, distribution_over), _rate(season_rows, prop, line, 50, distribution_over),
    ]
    for target in props:
        default = league_default if target == prop else 0.0
        values.extend((_mean(rows, target, 5, default), _mean(rows, target, 10, default), _mean(rows, target, 20, default)))
        values.append(_mean(season_rows, target, 50, _finite(prior.get(target), default)))
        values.append(_finite(prior.get(target), default))
    for key in STATCAST_KEYS:
        valid_10 = [_finite(row.get(key), np.nan) for row in list(rows)[-10:]]
        valid_all = [_finite(row.get(key), np.nan) for row in season_rows]
        valid_10 = [value for value in valid_10 if np.isfinite(value)]
        valid_all = [value for value in valid_all if np.isfinite(value)]
        values.extend((float(np.mean(valid_10)) if valid_10 else 0.0, float(np.mean(valid_all)) if valid_all else 0.0))
    return np.asarray(values, dtype=np.float32)


def retarget_line(features, state, kind, player_id, season, prop, line):
    """Reuse line-independent features when expanding one game to several thresholds."""
    output = np.array(features, copy=True)
    rows = state["batters" if kind == "batter" else "pitchers"][int(player_id)]["games"]
    season_rows = [row for row in rows if int(row["season"]) == int(season)]
    values = [_finite(row.get(prop)) for row in list(rows)[-30:]]
    mean = _mean(rows, prop, 10, 0.1)
    variance = float(np.var(values)) if len(values) >= 5 else max(mean, .1)
    distribution = distribution_probability(mean, variance, line)
    output[0] = float(line); output[15] = distribution
    output[16] = _rate(rows, prop, line, 5, distribution)
    output[17] = _rate(rows, prop, line, 10, distribution)
    output[18] = _rate(rows, prop, line, 20, distribution)
    output[19] = _rate(season_rows, prop, line, 50, distribution)
    return output


def _outcomes(kind, stats):
    mapping = BAT_MAP if kind == "batter" else PITCH_MAP
    return {prop: _finite(stats.get(source)) for prop, source in mapping.items()}


def _roll_season(state, season):
    if state["season"] is None:
        state["season"] = int(season); return
    if int(season) == int(state["season"]):
        return
    for group in ("batters", "pitchers"):
        for bucket in state[group].values():
            prior_rows = [row for row in bucket["games"] if int(row["season"]) == int(state["season"])]
            keys = BATTER_PROPS if group == "batters" else PITCHER_PROPS
            bucket["prior"] = {key: _mean(prior_rows, key, 50, 0) for key in keys}
    state["season"] = int(season)


def replay_samples(games, statcast=None, minimum_history=3, state=None):
    """Yield sample metadata/features then update state with that game's outcome."""
    state = state or fresh_state(); statcast = statcast or {}
    for game in games:
        season, game_id = int(game["season"]), int(game["game_id"])
        _roll_season(state, season)
        sc_game = statcast.get(game_id, {})
        starters = {}
        for side in ("away", "home"):
            for player in game[side]["players"]:
                pitching = player.get("pitching") or {}
                if pitching.get("gamesStarted"):
                    starters[side] = int(player["player_id"]); break
        pending_updates = []
        for side, opponent in (("away", "home"), ("home", "away")):
            team_id, opponent_id = int(game[side]["team_id"]), int(game[opponent]["team_id"])
            lineup = []
            for player in game[side]["players"]:
                player_id = int(player["player_id"])
                batting, pitching = player.get("batting") or {}, player.get("pitching") or {}
                batting_order = str(player.get("batting_order") or "")
                if batting and batting.get("plateAppearances", 0) > 0:
                    slot = int(batting_order[:1]) if batting_order[:1].isdigit() else 0
                    outcomes = _outcomes("batter", batting)
                    bucket = state["batters"][player_id]
                    if len(bucket["games"]) >= minimum_history:
                        yield {
                            "kind": "batter", "player_id": player_id, "name": player["name"],
                            "team_id": team_id, "opponent_id": opponent_id, "date": game["date"],
                            "season": season, "home": side == "home", "lineup_slot": slot,
                            "outcomes": outcomes, "state": state, "opponent_starter_id": starters.get(opponent),
                        }
                    sc = (sc_game.get(side) or {}).get("batters", {}).get(player_id, {})
                    pending_updates.append(("batter", player_id, team_id, player["name"], {**outcomes, **sc, "date": game["date"], "season": season, "plate_appearances": batting.get("plateAppearances", 0)}))
                    if slot:
                        lineup.append(player_id)
                if pitching and pitching.get("gamesStarted"):
                    outcomes = _outcomes("pitcher", pitching)
                    bucket = state["pitchers"][player_id]
                    if len(bucket["games"]) >= minimum_history:
                        yield {
                            "kind": "pitcher", "player_id": player_id, "name": player["name"],
                            "team_id": team_id, "opponent_id": opponent_id, "date": game["date"],
                            "season": season, "home": side == "home", "lineup_slot": 0,
                            "outcomes": outcomes, "state": state, "opponent_starter_id": None,
                        }
                    sc = (sc_game.get(side) or {}).get("pitchers", {}).get(player_id, {})
                    pending_updates.append(("pitcher", player_id, team_id, player["name"], {**outcomes, **sc, "date": game["date"], "season": season, "plate_appearances": pitching.get("battersFaced", 0)}))
            if lineup:
                state["teams"][team_id]["lineups"].append(lineup)
        for kind, player_id, team_id, name, row in pending_updates:
            bucket = state["batters" if kind == "batter" else "pitchers"][player_id]
            bucket["games"].append(row); bucket["name"] = name; bucket["team_id"] = team_id
            state["teams"][team_id]["batting" if kind == "batter" else "pitching"].append(row)
    return state


def serializable_state(state):
    output = {"season": state["season"], "batters": {}, "pitchers": {}, "teams": {}}
    for group in ("batters", "pitchers"):
        for key, value in state[group].items():
            output[group][str(key)] = {**value, "games": list(value["games"])}
    for key, value in state["teams"].items():
        output["teams"][str(key)] = {name: list(rows) for name, rows in value.items()}
    return output


def hydrate_state(value):
    state = fresh_state(); state["season"] = value.get("season")
    for group in ("batters", "pitchers"):
        for key, bucket in value.get(group, {}).items():
            state[group][int(key)] = {**bucket, "games": deque(bucket.get("games", []), maxlen=50)}
    for key, bucket in value.get("teams", {}).items():
        state["teams"][int(key)] = {
            "batting": deque(bucket.get("batting", []), maxlen=50),
            "pitching": deque(bucket.get("pitching", []), maxlen=50),
            "lineups": deque(bucket.get("lineups", []), maxlen=12),
        }
    return state
