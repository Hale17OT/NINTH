"""Point-in-time feature construction for NINTH player-prop models."""
from __future__ import annotations

import json
import math
import os
from collections import defaultdict, deque
from datetime import date
from pathlib import Path

import numpy as np
from scipy.stats import nbinom, poisson


ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = Path(os.getenv("NINTH_DATA_DIR", ROOT / "ml" / "data"))
BOX_PATH = DATA_ROOT / "player_boxscores.jsonl"
STATCAST_PATH = DATA_ROOT / "statcast_rich_games.jsonl"

BATTER_PROPS = {
    "hits": (0.5, 1.5, 2.5),
    "total_bases": (0.5, 1.5, 2.5, 3.5),
    "home_runs": (0.5, 1.5),
    "runs": (0.5, 1.5),
    "rbi": (0.5, 1.5, 2.5),
    "walks": (0.5, 1.5),
    "strikeouts": (0.5, 1.5, 2.5),
    "doubles": (0.5, 1.5),
    "singles": (0.5, 1.5),
    "triples": (0.5,),
    "hits_runs_rbi": tuple(x + 0.5 for x in range(0, 8)),
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
    "win": (0.5,),
}
PROP_LABELS = {
    "hits": "Hits", "total_bases": "Total bases", "home_runs": "Home runs",
    "runs": "Runs", "rbi": "RBIs", "walks": "Walks",
    "strikeouts": "Strikeouts", "doubles": "Doubles",
    "singles": "Singles", "triples": "Triples",
    "hits_runs_rbi": "Hits + runs + RBIs",
    "stolen_bases": "Stolen bases", "outs": "Pitching outs",
    "hits_allowed": "Hits allowed", "earned_runs": "Earned runs allowed",
    "home_runs_allowed": "Home runs allowed", "pitches": "Pitches thrown",
    "win": "Pitcher to win",
}
BAT_MAP = {
    "hits": "hits", "total_bases": "totalBases", "home_runs": "homeRuns",
    "runs": "runs", "rbi": "rbi", "walks": "baseOnBalls",
    "strikeouts": "strikeOuts", "doubles": "doubles", "stolen_bases": "stolenBases",
    "triples": "triples",
}
PITCH_MAP = {
    "strikeouts": "strikeOuts", "outs": "outs", "walks": "baseOnBalls",
    "hits_allowed": "hits", "earned_runs": "earnedRuns",
    "home_runs_allowed": "homeRuns", "pitches": "numberOfPitches",
    "win": "wins",
}
STATCAST_KEYS = (
    "xwoba", "hard_hit_rate", "barrel_rate", "whiff_rate",
    "avg_exit_velocity", "avg_velocity",
)
OPPONENT_PROP_MAP = {
    "batter": {
        "hits": "hits_allowed", "total_bases": "hits_allowed",
        "home_runs": "home_runs_allowed", "runs": "earned_runs",
        "rbi": "earned_runs", "walks": "walks",
        "strikeouts": "strikeouts", "doubles": "hits_allowed",
        "singles": "hits_allowed", "triples": "hits_allowed",
        "hits_runs_rbi": "earned_runs",
        "stolen_bases": "walks",
    },
    "pitcher": {
        "strikeouts": "strikeouts", "outs": "plate_appearances",
        "walks": "walks", "hits_allowed": "hits",
        "earned_runs": "runs", "home_runs_allowed": "home_runs",
        "pitches": "plate_appearances", "win": "runs",
    },
}


def _league_default(kind, prop):
    return {
        "hits": .95, "total_bases": 1.45, "home_runs": .13, "runs": .52, "rbi": .5,
        "walks": .35 if kind == "batter" else 2.2,
        "strikeouts": .9 if kind == "batter" else 5.2,
        "doubles": .18, "singles": .62, "triples": .02,
        "hits_runs_rbi": 1.97, "stolen_bases": .08, "outs": 15.5,
        "hits_allowed": 4.8, "earned_runs": 2.5,
        "home_runs_allowed": .8, "pitches": 86.0, "win": .28,
    }[prop]


def _distribution_mean(rows, season_rows, prior, kind, prop):
    league_default = _league_default(kind, prop)
    opportunity_default = 4.1 if kind == "batter" else 23.0
    count = len(season_rows)
    current_mean = _mean(season_rows, prop, 50, league_default)
    recent_mean = _mean(rows, prop, 10, current_mean)
    prior_mean = _finite(prior.get(prop), league_default)
    recent_opportunity = _mean(rows, "plate_appearances", 10, opportunity_default)
    prior_opportunity = _finite(prior.get("_opportunity"), opportunity_default)
    recent_rate = _sum_rate(rows, prop, "plate_appearances", 20, league_default / opportunity_default)
    prior_rate = _finite(prior.get(f"{prop}_per_opportunity"), prior_mean / max(1.0, prior_opportunity))
    shrunk_rate = (count * recent_rate + 18 * prior_rate) / (count + 18)
    projected_opportunity = (count * recent_opportunity + 12 * prior_opportunity) / (count + 12)
    rate_mean = shrunk_rate * projected_opportunity
    count_mean = (count * recent_mean + 12 * prior_mean) / (count + 12)
    return .65 * rate_mean + .35 * count_mean


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


def load_games(path=None):
    source = Path(path) if path is not None else BOX_PATH
    return sorted(_jsonl(source), key=lambda row: (row["date"], int(row["game_id"])))


def load_games_before(target_date, season, path=None):
    """Load completed games from one season strictly before an inference date."""
    source = Path(path) if path is not None else BOX_PATH
    target_date = str(target_date)[:10]
    season = int(season)
    return sorted(
        (
            row for row in _jsonl(source)
            if int(row.get("season") or 0) == season
            and str(row.get("date") or "")[:10] < target_date
        ),
        key=lambda row: (row["date"], int(row["game_id"])),
    )


def load_statcast(game_ids=None, path=None):
    """Return compact same-game outcomes used only after a sample is emitted."""
    output = {}
    source = Path(path) if path is not None else STATCAST_PATH
    if not source.exists():
        return output
    wanted = None if game_ids is None else {int(game_id) for game_id in game_ids}
    for game in _jsonl(source):
        game_id = int(game["game_id"])
        if wanted is not None and game_id not in wanted:
            continue
        sides = {}
        for side in ("away", "home"):
            batters = {
                int(row["batter_id"]): {key: row.get(key) for key in STATCAST_KEYS}
                for row in game.get(f"{side}_batters", [])
            }
            for hand, suffix in (("left", "l"), ("right", "r")):
                for row in game.get(f"{side}_batters_vs_{hand}", []):
                    player = batters.setdefault(int(row["batter_id"]), {})
                    for key in STATCAST_KEYS:
                        player[f"{key}_vs_{suffix}"] = row.get(key)
            pitchers = {
                int(row["pitcher_id"]): {
                    **{key: row.get(key) for key in STATCAST_KEYS},
                    "pitcher_hand": row.get("pitcher_hand"),
                }
                for row in game.get(f"{side}_pitcher_lines", [])
            }
            sides[side] = {"batters": batters, "pitchers": pitchers}
        output[game_id] = sides
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


def _sum_rate(rows, numerator, denominator, size, default=0.0):
    values = list(rows)[-size:]
    numerator_total = sum(_finite(row.get(numerator)) for row in values)
    denominator_total = sum(_finite(row.get(denominator)) for row in values)
    return float(numerator_total / denominator_total) if denominator_total > 0 else float(default)


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
    values.extend((
        "opportunity_5", "opportunity_10", "opportunity_20",
        "opportunity_season", "opportunity_prior",
        "prop_per_opportunity_5", "prop_per_opportunity_10",
        "prop_per_opportunity_20", "prop_per_opportunity_season",
        "prop_per_opportunity_prior",
        "opponent_prop_5", "opponent_prop_10", "opponent_prop_20",
    ))
    for key in STATCAST_KEYS:
        values.extend((f"{key}_10", f"{key}_season"))
        values.extend((f"opponent_starter_{key}_10", f"opponent_starter_{key}_season"))
    if kind == "batter":
        for key in STATCAST_KEYS:
            values.extend((f"platoon_{key}_10", f"platoon_{key}_season"))
    values.extend((
        "opponent_lineup_hit_rate", "opponent_lineup_strikeout_rate",
        "opponent_lineup_walk_rate", "opponent_lineup_home_run_rate",
        "opponent_lineup_history_reliability",
        "team_runs_5", "team_runs_10", "team_hits_10", "team_home_runs_10",
        "opponent_runs_5", "opponent_runs_10", "opponent_hits_10",
    ))
    return values


def build_features(state, kind, player_id, team_id, opponent_id, game_date, season, prop, line,
                   home=False, lineup_slot=0, opponent_starter_id=None,
                   opponent_starter_hand=None, opponent_lineup_ids=None):
    bucket = state["batters" if kind == "batter" else "pitchers"][int(player_id)]
    rows = bucket["games"]
    season_rows = [row for row in rows if int(row["season"]) == int(season)]
    prior = bucket.get("prior") or {}
    props = BATTER_PROPS if kind == "batter" else PITCHER_PROPS
    team_opp = state["teams"][int(opponent_id)]["pitching" if kind == "batter" else "batting"]
    opposing_starter = state["pitchers"].get(int(opponent_starter_id or 0), {"games": []})
    starter_rows = opposing_starter.get("games", [])
    league_default = _league_default(kind, prop)
    opportunity_default = 4.1 if kind == "batter" else 23.0
    prior_mean = _finite(prior.get(prop), league_default)
    prior_opportunity = _finite(prior.get("_opportunity"), opportunity_default)
    prior_rate = _finite(prior.get(f"{prop}_per_opportunity"), prior_mean / max(1.0, prior_opportunity))
    shrunk_mean = _distribution_mean(rows, season_rows, prior, kind, prop)
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
        # Every history column has a stable semantic regardless of which prop
        # is being predicted. This keeps shared matrices free of target leakage.
        default = _league_default(kind, target)
        values.extend((_mean(rows, target, 5, default), _mean(rows, target, 10, default), _mean(rows, target, 20, default)))
        values.append(_mean(season_rows, target, 50, _finite(prior.get(target), default)))
        values.append(_finite(prior.get(target), default))
    values.extend((
        _mean(rows, "plate_appearances", 5, opportunity_default),
        _mean(rows, "plate_appearances", 10, opportunity_default),
        _mean(rows, "plate_appearances", 20, opportunity_default),
        _mean(season_rows, "plate_appearances", 50, prior_opportunity),
        prior_opportunity,
        _sum_rate(rows, prop, "plate_appearances", 5, prior_rate),
        _sum_rate(rows, prop, "plate_appearances", 10, prior_rate),
        _sum_rate(rows, prop, "plate_appearances", 20, prior_rate),
        _sum_rate(season_rows, prop, "plate_appearances", 50, prior_rate),
        prior_rate,
    ))
    opponent_prop = OPPONENT_PROP_MAP[kind].get(prop, prop)
    values.extend((
        _mean(team_opp, opponent_prop, 5, league_default),
        _mean(team_opp, opponent_prop, 10, league_default),
        _mean(team_opp, opponent_prop, 20, league_default),
    ))
    for key in STATCAST_KEYS:
        valid_10 = [_finite(row.get(key), np.nan) for row in list(rows)[-10:]]
        valid_all = [_finite(row.get(key), np.nan) for row in season_rows]
        valid_10 = [value for value in valid_10 if np.isfinite(value)]
        valid_all = [value for value in valid_all if np.isfinite(value)]
        values.extend((float(np.mean(valid_10)) if valid_10 else 0.0, float(np.mean(valid_all)) if valid_all else 0.0))
        starter_10 = [_finite(row.get(key), np.nan) for row in list(starter_rows)[-10:]]
        starter_all = [_finite(row.get(key), np.nan) for row in starter_rows]
        starter_10 = [value for value in starter_10 if np.isfinite(value)]
        starter_all = [value for value in starter_all if np.isfinite(value)]
        values.extend((
            float(np.mean(starter_10)) if starter_10 else 0.0,
            float(np.mean(starter_all)) if starter_all else 0.0,
        ))
    if kind == "batter":
        suffix = "l" if str(opponent_starter_hand or "").upper().startswith("L") else "r"
        for key in STATCAST_KEYS:
            split_key = f"{key}_vs_{suffix}"
            recent_split = [_finite(row.get(split_key), np.nan) for row in list(rows)[-10:]]
            season_split = [_finite(row.get(split_key), np.nan) for row in season_rows]
            recent_split = [value for value in recent_split if np.isfinite(value)]
            season_split = [value for value in season_split if np.isfinite(value)]
            values.extend((
                float(np.mean(recent_split)) if recent_split else 0.0,
                float(np.mean(season_split)) if season_split else 0.0,
            ))
    if kind == "pitcher" and opponent_lineup_ids:
        summaries = []
        for opponent_player_id in list(opponent_lineup_ids)[:9]:
            opponent_bucket = state["batters"].get(int(opponent_player_id), {"games": [], "prior": {}})
            opponent_rows = opponent_bucket.get("games", [])
            opponent_prior = opponent_bucket.get("prior") or {}
            pa = sum(_finite(row.get("plate_appearances")) for row in list(opponent_rows)[-20:])
            def lineup_rate(target, default):
                prior_value = _finite(
                    opponent_prior.get(f"{target}_per_opportunity"), default,
                )
                return _sum_rate(
                    opponent_rows, target, "plate_appearances", 20, prior_value,
                )
            summaries.append((
                lineup_rate("hits", .23), lineup_rate("strikeouts", .22),
                lineup_rate("walks", .08), lineup_rate("home_runs", .032),
                pa / (pa + 100),
            ))
        while len(summaries) < 9:
            summaries.append((.23, .22, .08, .032, 0.0))
        weights = np.asarray([1.12, 1.10, 1.08, 1.06, 1.02, .98, .93, .88, .83])
        weights /= weights.sum()
        values.extend(
            float(sum(weight * row[index] for weight, row in zip(weights, summaries)))
            for index in range(5)
        )
    else:
        values.extend((0.0, 0.0, 0.0, 0.0, 0.0))
    own_batting = state["teams"][int(team_id)]["batting"]
    opponent_batting = state["teams"][int(opponent_id)]["batting"]
    values.extend((
        _mean(own_batting, "runs", 5, 4.4),
        _mean(own_batting, "runs", 10, 4.4),
        _mean(own_batting, "hits", 10, 8.2),
        _mean(own_batting, "home_runs", 10, 1.1),
        _mean(opponent_batting, "runs", 5, 4.4),
        _mean(opponent_batting, "runs", 10, 4.4),
        _mean(opponent_batting, "hits", 10, 8.2),
    ))
    return np.asarray(values, dtype=np.float32)


def retarget_threshold(features, state, kind, player_id, season, prop, line):
    """Replace only the six threshold-dependent values for an unchanged prop."""
    output = np.array(features, copy=True)
    rows = state["batters" if kind == "batter" else "pitchers"][int(player_id)]["games"]
    season_rows = [row for row in rows if int(row["season"]) == int(season)]
    values = [_finite(row.get(prop)) for row in list(rows)[-30:]]
    prior = state["batters" if kind == "batter" else "pitchers"][int(player_id)].get("prior") or {}
    mean = _distribution_mean(rows, season_rows, prior, kind, prop)
    variance = float(np.var(values)) if len(values) >= 5 else max(mean, .1)
    distribution = distribution_probability(mean, variance, line)
    output[0] = float(line); output[15] = distribution
    output[16] = _rate(rows, prop, line, 5, distribution)
    output[17] = _rate(rows, prop, line, 10, distribution)
    output[18] = _rate(rows, prop, line, 20, distribution)
    output[19] = _rate(season_rows, prop, line, 50, distribution)
    return output


def retarget_line(features, state, kind, player_id, season, prop, line, opponent_id=None):
    """Reuse shared player features while replacing every prop/line-specific value."""
    output = retarget_threshold(features, state, kind, player_id, season, prop, line)
    rows = state["batters" if kind == "batter" else "pitchers"][int(player_id)]["games"]
    season_rows = [row for row in rows if int(row["season"]) == int(season)]
    prior = state["batters" if kind == "batter" else "pitchers"][int(player_id)].get("prior") or {}
    props = BATTER_PROPS if kind == "batter" else PITCHER_PROPS
    league_default = _league_default(kind, prop)
    opportunity_default = 4.1 if kind == "batter" else 23.0
    prior_opportunity = _finite(prior.get("_opportunity"), opportunity_default)
    prior_rate = _finite(
        prior.get(f"{prop}_per_opportunity"),
        _finite(prior.get(prop), league_default) / max(1.0, prior_opportunity),
    )
    opportunity_offset = 20 + 5 * len(props)
    rate_offset = opportunity_offset + 5
    output[rate_offset:rate_offset + 5] = (
        _sum_rate(rows, prop, "plate_appearances", 5, prior_rate),
        _sum_rate(rows, prop, "plate_appearances", 10, prior_rate),
        _sum_rate(rows, prop, "plate_appearances", 20, prior_rate),
        _sum_rate(season_rows, prop, "plate_appearances", 50, prior_rate),
        prior_rate,
    )
    if opponent_id is not None:
        team_opp = state["teams"][int(opponent_id)]["pitching" if kind == "batter" else "batting"]
        opponent_prop = OPPONENT_PROP_MAP[kind].get(prop, prop)
        opponent_offset = rate_offset + 5
        output[opponent_offset:opponent_offset + 3] = (
            _mean(team_opp, opponent_prop, 5, league_default),
            _mean(team_opp, opponent_prop, 10, league_default),
            _mean(team_opp, opponent_prop, 20, league_default),
        )
    return output


def _outcomes(kind, stats):
    mapping = BAT_MAP if kind == "batter" else PITCH_MAP
    outcomes = {prop: _finite(stats.get(source)) for prop, source in mapping.items()}
    if kind == "batter":
        outcomes["singles"] = max(
            0.0,
            outcomes["hits"] - outcomes["doubles"]
            - outcomes["triples"] - outcomes["home_runs"],
        )
        outcomes["hits_runs_rbi"] = outcomes["hits"] + outcomes["runs"] + outcomes["rbi"]
    return outcomes


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
            bucket["prior"]["_opportunity"] = _mean(prior_rows, "plate_appearances", 50, 4.1 if group == "batters" else 23.0)
            for key in keys:
                bucket["prior"][f"{key}_per_opportunity"] = _sum_rate(
                    prior_rows, key, "plate_appearances", 50, 0,
                )
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
        starter_hands = {
            side: ((sc_game.get(side) or {}).get("pitchers", {}).get(starters.get(side), {}) or {}).get("pitcher_hand")
            for side in ("away", "home")
        }
        confirmed_lineups = {}
        for side in ("away", "home"):
            ordered = []
            for player in game[side]["players"]:
                batting = player.get("batting") or {}
                batting_order = str(player.get("batting_order") or "")
                if (
                    batting.get("plateAppearances", 0) > 0
                    and len(batting_order) >= 3 and batting_order[:1].isdigit()
                    and batting_order[1:] == "00"
                ):
                    ordered.append((int(batting_order[:1]), int(player["player_id"])))
            confirmed_lineups[side] = [
                player_id for _, player_id in sorted(ordered)
            ][:9]
        pending_updates = []
        pending_team_updates = []
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
                            "game_id": game_id,
                            "team_id": team_id, "opponent_id": opponent_id, "date": game["date"],
                            "season": season, "home": side == "home", "lineup_slot": slot,
                            "outcomes": outcomes, "state": state, "opponent_starter_id": starters.get(opponent),
                            "opponent_starter_hand": starter_hands.get(opponent),
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
                            "game_id": game_id,
                            "team_id": team_id, "opponent_id": opponent_id, "date": game["date"],
                            "season": season, "home": side == "home", "lineup_slot": 0,
                            "outcomes": outcomes, "state": state,
                            "opponent_starter_id": starters.get(opponent),
                            "opponent_lineup_ids": confirmed_lineups.get(opponent, []),
                        }
                    sc = (sc_game.get(side) or {}).get("pitchers", {}).get(player_id, {})
                    pending_updates.append(("pitcher", player_id, team_id, player["name"], {**outcomes, **sc, "date": game["date"], "season": season, "plate_appearances": pitching.get("battersFaced", 0)}))
            batting_rows = [
                player.get("batting") or {} for player in game[side]["players"]
                if (player.get("batting") or {}).get("plateAppearances", 0) > 0
            ]
            batting_aggregate = {
                prop: sum(_outcomes("batter", row)[prop] for row in batting_rows)
                for prop in BATTER_PROPS
            }
            batting_aggregate["plate_appearances"] = sum(
                _finite(row.get("plateAppearances")) for row in batting_rows
            )
            pitching_rows = [
                player.get("pitching") or {} for player in game[side]["players"]
                if player.get("pitching")
            ]
            pitching_aggregate = {
                prop: sum(_outcomes("pitcher", row)[prop] for row in pitching_rows)
                for prop in PITCHER_PROPS
            }
            pitching_aggregate["plate_appearances"] = sum(
                _finite(row.get("battersFaced")) for row in pitching_rows
            )
            pending_team_updates.append((team_id, batting_aggregate, pitching_aggregate))
            if lineup:
                state["teams"][team_id]["lineups"].append(lineup)
        for kind, player_id, team_id, name, row in pending_updates:
            bucket = state["batters" if kind == "batter" else "pitchers"][player_id]
            bucket["games"].append(row); bucket["name"] = name; bucket["team_id"] = team_id
        for team_id, batting, pitching in pending_team_updates:
            state["teams"][team_id]["batting"].append(batting)
            if pitching:
                state["teams"][team_id]["pitching"].append(pitching)
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
