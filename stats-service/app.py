"""Small HTTP adapter around MLB-StatsAPI for the Node application."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse
import json
import math
import os
import re
import requests
import subprocess
import sys
import threading
import time
import statsapi

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ml.predict import context_completeness, load_bundle, predict as model_predict
from ml.slips import load_slips, normalize_team as normalize_slip_team, parse_pdf, placed_at_iso, save_slip

PORT = int(os.getenv("MLB_STATS_PORT", "3002"))
_detail_cache = {}
_projection_board_cache = {}
_projection_enrichment_pending = set()
_projection_enrichment_lock = threading.Lock()
_summary_cache = {}
_teams_cache = None
_players_cache = None
_team_detail_cache = {}
_model_history_cache = {}
_projection_last = {}
_projection_last_context = {}
_projection_last_completeness = {}
_projection_last_game_state = {}
_projection_recent_alerts = {}
_bullpen_cache = {}
_recent_form_cache = {}
_pitcher_profile_cache = {}
_prediction_results_cache = None
_detail_locks = {}
_detail_locks_guard = threading.Lock()
_projection_monitor = {"running": False, "pregame_seconds": 60, "live_seconds": 10, "last_discovery_at": None, "last_refresh_at": None, "tracked_games": 0, "last_error": None}
PROJECTION_LOG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ml", "data", "projection_snapshots.jsonl")
MODEL_REPORT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ml", "artifacts", "report.json")
MAINTENANCE_STATE = os.path.join(os.path.dirname(MODEL_REPORT), "maintenance_state.json")


def maintenance_status():
    try:
        with open(MAINTENANCE_STATE, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {"status": "not_run"}


def game_summary(game_id):
    game_id = int(game_id)
    if game_id not in _summary_cache:
        feed = statsapi.get("game", {"gamePk": game_id})
        data = feed.get("gameData", {})
        venue = data.get("venue", {})
        location = venue.get("location", {})
        coords = location.get("defaultCoordinates", {})
        teams = data.get("teams", {})
        _summary_cache[game_id] = {
            "game_id": game_id, "status": data.get("status", {}).get("detailedState", "Unknown"),
            "datetime": data.get("datetime", {}).get("dateTime"),
            "venue": {"id": venue.get("id"), "name": venue.get("name"), "latitude": coords.get("latitude"),
                      "longitude": coords.get("longitude"), "timezone": venue.get("timeZone", {}).get("id"),
                      "roof_type": venue.get("fieldInfo", {}).get("roofType")},
            "away": normalize_team(teams.get("away", {})), "home": normalize_team(teams.get("home", {})),
        }
    return _summary_cache[game_id]


def detail_lock(game_id):
    with _detail_locks_guard:
        return _detail_locks.setdefault(int(game_id), threading.Lock())


def game_detail(game_id, force=False):
    game_id = int(game_id)
    with detail_lock(game_id):
        if force:
            _detail_cache.pop(game_id, None)
        return _game_detail(game_id)


def _game_detail(game_id):
    game_id = int(game_id)
    cached = _detail_cache.get(game_id)
    if cached:
        cached_at, cached_payload = cached
        state = cached_payload.get("status_code")
        ttl = 8 if state == "Live" else 3600 if state == "Final" else 45
        if (datetime.now(timezone.utc) - cached_at).total_seconds() < ttl:
            return cached_payload
        _detail_cache.pop(game_id, None)
    if game_id not in _detail_cache:
        feed = statsapi.get("game", {"gamePk": game_id})
        data = feed.get("gameData", {})
        venue = data.get("venue", {})
        location = venue.get("location", {})
        coords = location.get("defaultCoordinates", {})
        teams = data.get("teams", {})
        probable = data.get("probablePitchers", {})
        status_data = data.get("status", {})
        live = feed.get("liveData", {})
        linescore = live.get("linescore", {})
        all_plays = live.get("plays", {}).get("allPlays", [])
        current_play = live.get("plays", {}).get("currentPlay") or (all_plays[-1] if all_plays else {})
        box_teams = live.get("boxscore", {}).get("teams", {})
        game_time = data.get("datetime", {}).get("dateTime")
        team_ids = [teams.get("away", {}).get("id"), teams.get("home", {}).get("id")]
        with ThreadPoolExecutor(max_workers=4) as pool:
            away_pitcher = pool.submit(pitcher_profile, probable.get("away"))
            home_pitcher = pool.submit(pitcher_profile, probable.get("home"))
            away_recent = pool.submit(recent_form, team_ids[0], game_time, game_id)
            home_recent = pool.submit(recent_form, team_ids[1], game_time, game_id)
            pitcher_profiles = {"away": away_pitcher.result(), "home": home_pitcher.result()}
            recent_results = [away_recent.result(), home_recent.result()]
        context = live_context(feed, pitcher_profiles, team_ids, game_time, game_id)
        status_code = status_data.get("abstractGameState", "Preview")
        if status_code == "Final":
            projection = locked_pregame_projection(game_id, game_time)
        else:
            try:
                projection = moneyline_projection(team_ids[1], team_ids[0], game_time, context)
                if status_code == "Live":
                    projection = apply_live_game_state(projection, linescore, current_play.get("count", {}))
            except Exception as exc:
                projection = {"available": False, "message": f"Projection refresh failed: {exc}"}
            projection = record_projection(game_id, projection, context, status_code, game_time)
        payload = {
            "game_id": game_id,
            "status": status_data.get("detailedState", "Unknown"),
            "status_code": status_code,
            "context_updated_at": projection.get("snapshot_at") or context.get("updated_at"),
            "projection_refresh_seconds": 10 if status_code == "Live" else 0 if status_code == "Final" else 60,
            "datetime": data.get("datetime", {}).get("dateTime"),
            "venue": {
                "id": venue.get("id"),
                "name": venue.get("name"),
                "latitude": coords.get("latitude"),
                "longitude": coords.get("longitude"),
                "timezone": venue.get("timeZone", {}).get("id"),
                "roof_type": venue.get("fieldInfo", {}).get("roofType"),
            },
            "away": normalize_team(teams.get("away", {})),
            "home": normalize_team(teams.get("home", {})),
            "linescore": {
                "inning": linescore.get("currentInning"),
                "inning_ordinal": linescore.get("currentInningOrdinal"),
                "inning_state": linescore.get("inningState"),
                "teams": linescore.get("teams", {}),
                "offense": linescore.get("offense", {}),
                "defense": linescore.get("defense", {}),
                "innings": linescore.get("innings", []),
            },
            "count": current_play.get("count", {"balls": 0, "strikes": 0, "outs": 0}),
            "plays": normalize_plays(all_plays[-12:]),
            "pitches": normalize_pitches(current_play.get("playEvents", [])),
            "team_stats": {
                "away": box_teams.get("away", {}).get("teamStats", {}),
                "home": box_teams.get("home", {}).get("teamStats", {}),
            },
            "live_stats": {
                "away": normalize_live_team(box_teams.get("away", {}), all_plays),
                "home": normalize_live_team(box_teams.get("home", {}), all_plays),
            },
            "probable_pitchers": pitcher_profiles,
            "model_context": context,
            "recent_form": {"away": recent_results[0], "home": recent_results[1]},
            "projection": projection,
        }
        _detail_cache[game_id] = (datetime.now(timezone.utc), payload)
    return payload


def normalize_team(team):
    record = team.get("record", {})
    return {
        "id": team.get("id"),
        "name": team.get("name"),
        "abbr": team.get("abbreviation"),
        "wins": record.get("wins"),
        "losses": record.get("losses"),
        "pct": record.get("winningPercentage"),
    }


def normalize_plays(plays):
    output = []
    for play in reversed(plays):
        result, about, count = play.get("result", {}), play.get("about", {}), play.get("count", {})
        output.append({
            "id": about.get("atBatIndex"), "inning": about.get("inning"), "half": about.get("halfInning"),
            "event": result.get("event"), "event_type": result.get("eventType"), "description": result.get("description"),
            "away_score": result.get("awayScore"), "home_score": result.get("homeScore"), "is_out": result.get("isOut", False),
            "balls": count.get("balls", 0), "strikes": count.get("strikes", 0), "outs": count.get("outs", 0),
        })
    return output


def normalize_pitches(events):
    pitches = []
    for event in events:
        if not event.get("isPitch"):
            continue
        details, pitch = event.get("details", {}), event.get("pitchData", {})
        coords, breaks = pitch.get("coordinates", {}), pitch.get("breaks", {})
        pitches.append({
            "id": event.get("pitchNumber"), "type": details.get("type", {}).get("description", "Pitch"),
            "velocity": pitch.get("startSpeed"), "spin": breaks.get("spinRate"), "zone": pitch.get("zone"),
            "px": coords.get("pX"), "pz": coords.get("pZ"), "result": details.get("description"),
            "balls": event.get("count", {}).get("balls", 0), "strikes": event.get("count", {}).get("strikes", 0),
        })
    return pitches


def normalize_live_team(box_team, all_plays):
    plate_appearances = {}
    for play in all_plays:
        matchup, result, about = play.get("matchup", {}), play.get("result", {}), play.get("about", {})
        batter = matchup.get("batter", {})
        batter_id = batter.get("id")
        if not batter_id or not result.get("event"):
            continue
        plate_appearances.setdefault(batter_id, []).append({
            "inning": about.get("inning"),
            "half": about.get("halfInning"),
            "event": result.get("event"),
            "event_type": result.get("eventType"),
            "description": result.get("description"),
            "is_out": result.get("isOut", False),
        })

    players = list((box_team.get("players") or {}).values())
    batters = []
    for player in players:
        game_stats = player.get("stats", {}).get("batting", {})
        status = player.get("gameStatus", {})
        batting_order = player.get("battingOrder")
        appearances = plate_appearances.get(player.get("person", {}).get("id"), [])
        if not batting_order and not appearances and not status.get("isCurrentBatter"):
            continue
        if status.get("isOnBench") and not appearances:
            continue
        person, position = player.get("person", {}), player.get("position", {})
        batters.append({
            "id": person.get("id"), "name": person.get("fullName"),
            "position": position.get("abbreviation"),
            "batting_order": int(batting_order or 9999),
            "current": bool(status.get("isCurrentBatter")),
            "substitute": bool(status.get("isSubstitute")),
            "summary": game_stats.get("summary") or f"{game_stats.get('hits', 0)}-{game_stats.get('atBats', 0)}",
            "at_bats": game_stats.get("atBats", 0), "hits": game_stats.get("hits", 0),
            "runs": game_stats.get("runs", 0), "rbi": game_stats.get("rbi", 0),
            "walks": game_stats.get("baseOnBalls", 0), "strikeouts": game_stats.get("strikeOuts", 0),
            "home_runs": game_stats.get("homeRuns", 0), "plate_appearances": appearances,
        })
    batters.sort(key=lambda item: (item["batting_order"], item["substitute"], item["name"] or ""))

    pitchers = []
    player_map = {player.get("person", {}).get("id"): player for player in players}
    pitcher_ids = box_team.get("pitchers") or []
    for pitcher_id in pitcher_ids:
        player = player_map.get(pitcher_id, {})
        person, status = player.get("person", {}), player.get("gameStatus", {})
        game_stats = player.get("stats", {}).get("pitching", {})
        pitchers.append({
            "id": person.get("id") or pitcher_id, "name": person.get("fullName") or "Unknown pitcher",
            "current": bool(status.get("isCurrentPitcher")),
            "pitches": game_stats.get("numberOfPitches", 0), "strikes": game_stats.get("strikes", 0),
            "innings": game_stats.get("inningsPitched", "0.0"), "hits": game_stats.get("hits", 0),
            "runs": game_stats.get("runs", 0), "earned_runs": game_stats.get("earnedRuns", 0),
            "walks": game_stats.get("baseOnBalls", 0), "strikeouts": game_stats.get("strikeOuts", 0),
            "batters_faced": game_stats.get("battersFaced", 0),
        })

    batting = box_team.get("teamStats", {}).get("batting", {})
    pitching = box_team.get("teamStats", {}).get("pitching", {})
    return {
        "totals": {
            "runs": batting.get("runs", 0), "hits": batting.get("hits", 0),
            "home_runs": batting.get("homeRuns", 0), "walks": batting.get("baseOnBalls", 0),
            "strikeouts": batting.get("strikeOuts", 0), "left_on_base": batting.get("leftOnBase", 0),
            "pitches": pitching.get("numberOfPitches", sum(item["pitches"] or 0 for item in pitchers)),
        },
        "batters": batters, "pitchers": pitchers,
    }


def teams_data():
    global _teams_cache
    if _teams_cache is None:
        raw = statsapi.get("teams", {"sportIds": 1, "season": 2026, "hydrate": "standings,venue(location)"})
        _teams_cache = [normalize_team_record(team) for team in raw.get("teams", [])]
    return _teams_cache


def players_data():
    global _players_cache
    if _players_cache is None:
        teams = {team["id"]: team for team in teams_data()}
        people = statsapi.get("sports_players", {"sportId": 1, "season": 2026}).get("people", [])
        _players_cache = []
        for person in people:
            team_id = person.get("currentTeam", {}).get("id")
            team = teams.get(team_id)
            if not person.get("active") or not team:
                continue
            position = person.get("primaryPosition", {})
            _players_cache.append({
                "id": person.get("id"), "name": person.get("fullName"),
                "first_name": person.get("firstName"), "last_name": person.get("lastName"),
                "number": person.get("primaryNumber"), "age": person.get("currentAge"),
                "position": position.get("name"), "position_abbr": position.get("abbreviation"),
                "team_id": team_id, "team_name": team.get("name"), "team_abbr": team.get("abbr"),
                "bats": person.get("batSide", {}).get("code"), "throws": person.get("pitchHand", {}).get("code"),
            })
        _players_cache.sort(key=lambda row: ((row.get("last_name") or ""), (row.get("first_name") or "")))
    return _players_cache


def normalize_team_record(team):
    record = team.get("record", {})
    splits = {item.get("type"): item for item in record.get("records", {}).get("splitRecords", [])}
    coordinates = team.get("venue", {}).get("location", {}).get("defaultCoordinates", {})
    return {
        "id": team.get("id"), "name": team.get("name"), "abbr": team.get("abbreviation"),
        "league": team.get("league", {}).get("name"), "division": team.get("division", {}).get("name"),
        "venue": team.get("venue", {}).get("name"), "wins": record.get("wins", 0), "losses": record.get("losses", 0),
        "pct": record.get("winningPercentage"), "rank": record.get("sportRank"), "division_rank": record.get("divisionRank"),
        "games_back": record.get("divisionGamesBack"), "streak": record.get("streak", {}).get("streakCode"),
        "runs_scored": record.get("runsScored", 0), "runs_allowed": record.get("runsAllowed", 0),
        "run_differential": record.get("runDifferential", 0),
        "home": splits.get("home", {}), "away": splits.get("away", {}), "last_ten": splits.get("lastTen", {}),
        "venue_latitude": coordinates.get("latitude"), "venue_longitude": coordinates.get("longitude"),
    }


def team_detail(team_id):
    team_id = int(team_id)
    cached = _team_detail_cache.get(team_id)
    if cached and datetime.now(timezone.utc) - cached[0] < timedelta(minutes=5):
        return cached[1]
    team = next((item for item in teams_data() if item["id"] == team_id), None)
    raw_stats = statsapi.get("team_stats", {"teamId": team_id, "stats": "season", "group": "hitting,pitching", "season": 2026})
    stat_groups = {}
    for group in raw_stats.get("stats", []):
        split = group.get("splits", [])
        stat_groups[group.get("group", {}).get("displayName")] = split[0].get("stat", {}) if split else {}
    roster = statsapi.get("team_roster", {
        "teamId": team_id,
        "rosterType": "active",
        "season": 2026,
        "hydrate": "person(stats(group=[hitting,pitching],type=[season],season=2026))",
    }).get("roster", [])
    today = datetime.now(timezone.utc).date()
    recent = statsapi.schedule(start_date=(today - timedelta(days=14)).isoformat(), end_date=today.isoformat(), team=team_id)
    recent = [game for game in recent if "Final" in game.get("status", "")][-10:]
    result = {"team": team, "stats": stat_groups, "roster": roster, "recent": recent}
    _team_detail_cache[team_id] = (datetime.now(timezone.utc), result)
    return result


def recent_form(team_id, before_datetime, exclude_game_id):
    if not team_id:
        return []
    try:
        game_date = datetime.fromisoformat((before_datetime or datetime.now(timezone.utc).isoformat()).replace("Z", "+00:00")).date()
    except ValueError:
        game_date = datetime.now(timezone.utc).date()
    end_date = game_date - timedelta(days=1)
    cache_key = f"{team_id}:{end_date.isoformat()}"
    cached = _recent_form_cache.get(cache_key)
    if cached and datetime.now(timezone.utc) - cached[0] < timedelta(minutes=10):
        return cached[1]
    games = statsapi.schedule(start_date=(end_date - timedelta(days=30)).isoformat(), end_date=end_date.isoformat(), team=int(team_id))
    finals = [game for game in games if "Final" in game.get("status", "") and int(game.get("game_id", 0)) != int(exclude_game_id)]
    output = []
    for game in reversed(finals[-5:]):
        home = int(game.get("home_id", 0)) == int(team_id)
        team_score = game.get("home_score", 0) if home else game.get("away_score", 0)
        opponent_score = game.get("away_score", 0) if home else game.get("home_score", 0)
        output.append({
            "game_id": game.get("game_id"), "date": game.get("game_date"),
            "opponent": game.get("away_name") if home else game.get("home_name"), "location": "vs" if home else "@",
            "team_score": team_score, "opponent_score": opponent_score, "result": "W" if team_score > opponent_score else "L",
        })
    _recent_form_cache[cache_key] = (datetime.now(timezone.utc), output)
    return output


def _float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def bullpen_recent_pitches(team_id, game_datetime, exclude_game_id):
    game_date = datetime.fromisoformat(game_datetime.replace("Z", "+00:00")).date()
    key = f"{team_id}:{game_date}:{exclude_game_id}"
    if key in _bullpen_cache:
        cached_at, cached_value = _bullpen_cache[key]
        if datetime.now(timezone.utc) - cached_at < timedelta(minutes=5):
            return cached_value
    games = statsapi.schedule(start_date=(game_date - timedelta(days=3)).isoformat(), end_date=(game_date - timedelta(days=1)).isoformat(), team=int(team_id))
    total = 0.0
    for game in games:
        if "Final" not in game.get("status", "") or int(game.get("game_id", 0)) == int(exclude_game_id):
            continue
        feed = statsapi.get("game", {"gamePk": int(game["game_id"])})
        side = "home" if int(game.get("home_id", 0)) == int(team_id) else "away"
        raw = feed.get("liveData", {}).get("boxscore", {}).get("teams", {}).get(side, {})
        players, pitchers = raw.get("players", {}), raw.get("pitchers", [])
        total += sum(_float(players.get("ID" + str(pid), {}).get("stats", {}).get("pitching", {}).get("numberOfPitches")) for pid in pitchers[1:])
    _bullpen_cache[key] = (datetime.now(timezone.utc), total)
    return total


def live_context(feed, pitcher_profiles, team_ids, game_datetime, game_id):
    data = feed.get("gameData", {})
    raw_teams = feed.get("liveData", {}).get("boxscore", {}).get("teams", {})
    weather = data.get("weather", {})
    wind_match = re.search(r"(\d+)\s*mph", weather.get("wind", ""), re.I)
    weather_context = {"temperature": _float(weather.get("temp"), 65), "wind_speed": _float(wind_match.group(1)) if wind_match else 0, "condition": weather.get("condition"), "source": "MLB game feed"}
    if weather.get("temp") is None:
        coords = data.get("venue", {}).get("location", {}).get("defaultCoordinates", {})
        weather_context = open_meteo_weather(coords.get("latitude"), coords.get("longitude"), game_datetime) or weather_context
    game_status = data.get("status", {}).get("abstractGameState", "Preview")
    context = {"weather": weather_context, "updated_at": datetime.now(timezone.utc).isoformat()}
    for side, team_id in (("away", team_ids[0]), ("home", team_ids[1])):
        raw = raw_teams.get(side, {})
        players, order = raw.get("players", {}), raw.get("battingOrder", [])[:9]
        official_pitchers = raw.get("pitchers", [])
        bullpen_ids = raw.get("bullpen", []) or official_pitchers[1:]
        def roster_player(player_id, batting_spot=None):
            player = players.get("ID" + str(player_id), {})
            person, position = player.get("person", {}), player.get("position", {})
            return {
                "id": int(player_id), "name": person.get("fullName") or f"Player {player_id}",
                "position": position.get("abbreviation") or position.get("name") or "—",
                "position_name": position.get("name"), "position_type": position.get("type"),
                "batting_order": batting_spot,
            }
        ops = [_float(players.get("ID" + str(pid), {}).get("seasonStats", {}).get("batting", {}).get("ops"), .710) for pid in order]
        profile = pitcher_profiles.get(side) or {}
        probable_id = profile.get("id")
        starter_confirmed = bool(probable_id and official_pitchers and int(official_pitchers[0]) == int(probable_id) and (len(order) >= 9 or game_status in ("Live", "Final")))
        bullpen_confirmed = bool(bullpen_ids and (len(order) >= 9 or game_status in ("Live", "Final")))
        context[side] = {
            "starter_id": probable_id, "starter_name": profile.get("name"),
            "starter_era": _float(profile.get("era"), 4.5), "starter_whip": _float(profile.get("whip"), 1.35),
            "starter_status": "confirmed" if starter_confirmed else "predicted" if probable_id else "pending",
            "lineup_ids": order, "lineup_confirmed": len(order) >= 9,
            "lineup_players": [roster_player(pid, index + 1) for index, pid in enumerate(order)],
            "lineup_ops": sum(ops) / len(ops) if ops else .710,
            "bullpen_status": "confirmed" if bullpen_confirmed else "predicted",
            "bullpen_pitcher_ids": bullpen_ids,
            "bullpen_players": [roster_player(pid) for pid in bullpen_ids],
        }
    with ThreadPoolExecutor(max_workers=2) as pool:
        loads = list(pool.map(lambda item: bullpen_recent_pitches(item[1], game_datetime, game_id), (("away", team_ids[0]), ("home", team_ids[1]))))
    context["away"]["bullpen_recent_pitches"], context["home"]["bullpen_recent_pitches"] = loads
    return context


def open_meteo_weather(latitude, longitude, game_datetime):
    if latitude is None or longitude is None or not game_datetime:
        return None
    target = datetime.fromisoformat(game_datetime.replace("Z", "+00:00"))
    day = target.date().isoformat()
    historical = target < datetime.now(timezone.utc) - timedelta(days=5)
    endpoint = "https://archive-api.open-meteo.com/v1/archive" if historical else "https://api.open-meteo.com/v1/forecast"
    response = requests.get(endpoint, params={"latitude": latitude, "longitude": longitude, "start_date": day, "end_date": day, "hourly": "temperature_2m,wind_speed_10m,weather_code", "temperature_unit": "fahrenheit", "wind_speed_unit": "mph", "timezone": "UTC"}, timeout=12)
    response.raise_for_status()
    hourly = response.json().get("hourly", {})
    times = hourly.get("time", [])
    if not times:
        return None
    index = min(range(len(times)), key=lambda i: abs(datetime.fromisoformat(times[i]).replace(tzinfo=timezone.utc) - target.astimezone(timezone.utc)))
    code = hourly.get("weather_code", [None] * len(times))[index]
    return {"temperature": _float(hourly.get("temperature_2m", [65] * len(times))[index], 65), "wind_speed": _float(hourly.get("wind_speed_10m", [0] * len(times))[index]), "condition": f"Weather code {code}" if code is not None else None, "source": "Open-Meteo historical weather" if historical else "Open-Meteo forecast"}


def moneyline_projection(home_id, away_id, game_datetime, context=None):
    if not home_id or not away_id or not game_datetime:
        return {"available": False, "message": "Matchup identifiers are incomplete."}
    game_date = datetime.fromisoformat(game_datetime.replace("Z", "+00:00")).date()
    # Future slates all share the same latest completed-game state. Capping the
    # replay date prevents one redundant history rebuild for every slate day.
    end_date = min(game_date - timedelta(days=1), datetime.now(timezone.utc).date() - timedelta(days=1))
    cache_key = end_date.isoformat()
    if cache_key not in _model_history_cache:
        try:
            with open(MODEL_REPORT, "r", encoding="utf-8") as handle:
                trained_through = datetime.fromisoformat(json.load(handle).get("trained_through_date", "1900-01-01")).date()
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            trained_through = datetime(1900, 1, 1).date()
        games, cursor = [], max(datetime(end_date.year, 3, 1).date(), trained_through + timedelta(days=1))
        while cursor <= end_date:
            chunk_end = min(end_date, cursor + timedelta(days=30))
            games.extend(statsapi.schedule(start_date=cursor.isoformat(), end_date=chunk_end.isoformat(), sportId=1))
            cursor = chunk_end + timedelta(days=1)
        normalized = []
        for game in games:
            if "Final" not in game.get("status", "") or game.get("home_score") is None or game.get("away_score") is None or game.get("home_score") == game.get("away_score"):
                continue
            normalized.append({"game_id": int(game["game_id"]), "date": game["game_date"], "home_id": int(game["home_id"]), "away_id": int(game["away_id"]), "home_score": int(game["home_score"]), "away_score": int(game["away_score"])})
        _model_history_cache.clear()
        _model_history_cache[cache_key] = sorted(normalized, key=lambda row: (row["date"], row["game_id"]))
    return model_predict(home_id, away_id, game_date.isoformat(), _model_history_cache[cache_key], context)


def apply_live_game_state(projection, linescore, count=None):
    """Blend the trained pregame prior with the current official base/out state."""
    if not projection.get("available"):
        return projection
    teams = linescore.get("teams", {})
    home_runs = int(_float(teams.get("home", {}).get("runs")))
    away_runs = int(_float(teams.get("away", {}).get("runs")))
    inning = max(1, int(_float(linescore.get("currentInning"), 1)))
    half = str(linescore.get("inningState") or "Top")
    outs = max(0, min(3, int(_float((count or {}).get("outs")))))
    offense = linescore.get("offense", {})
    bases = (bool(offense.get("first")), bool(offense.get("second")), bool(offense.get("third")))
    base_key = sum((1, 2, 4)[index] for index, occupied in enumerate(bases) if occupied)
    run_expectancy = {
        0: (0.48, 0.25, 0.10), 1: (0.86, 0.51, 0.22), 2: (1.10, 0.67, 0.32), 3: (1.44, 0.91, 0.43),
        4: (1.35, 0.95, 0.35), 5: (1.78, 1.14, 0.48), 6: (1.96, 1.37, 0.57), 7: (2.31, 1.54, 0.76),
    }[base_key][min(outs, 2)]
    completed_halves = max(0, (inning - 1) * 2 + (1 if half.lower().startswith("bottom") else 0))
    remaining_halves = max(.35, 18 - completed_halves - outs / 3)
    game_progress = min(1.0, max(0.0, 1 - remaining_halves / 18))
    run_leverage = .55 + 2.8 * game_progress ** 2
    offense_sign = 1 if half.lower().startswith("bottom") else -1
    pregame_probability = min(.995, max(.005, float(projection["home_win_probability"])))
    pregame_logit = math.log(pregame_probability / (1 - pregame_probability))
    score_adjustment = (home_runs - away_runs) * run_leverage
    base_out_adjustment = offense_sign * run_expectancy * run_leverage * .55
    live_probability = 1 / (1 + math.exp(-(pregame_logit + score_adjustment + base_out_adjustment)))
    live_probability = round(min(.995, max(.005, live_probability)), 4)
    impact = round(live_probability - pregame_probability, 4)
    state = {
        "inning": inning, "half": half, "outs": outs, "home_runs": home_runs, "away_runs": away_runs,
        "bases": {"first": bases[0], "second": bases[1], "third": bases[2]}, "run_expectancy": round(run_expectancy, 2),
    }
    live_reason = {"feature": "live_game_state", "label": "official live score and base/out state", "direction": "home" if impact >= 0 else "away", "value": home_runs - away_runs, "impact": impact}
    projection.update({
        "pregame_home_win_probability": projection["home_win_probability"],
        "pregame_away_win_probability": projection["away_win_probability"],
        "home_win_probability": live_probability,
        "away_win_probability": round(1 - live_probability, 4),
        "projected_side": "home" if live_probability >= .5 else "away",
        "projection_source": "live_game_state",
        "projection_phase": "live",
        "game_state": state,
        "historical_tier": None,
        "confidence_explanation": "Live projection combines the trained pregame forecast with the official score, inning, outs and baserunner state. The live adjustment is tracked separately from pregame model accuracy.",
        "reasons": [live_reason] + [reason for reason in projection.get("reasons", []) if reason.get("feature") != "live_game_state"],
    })
    return projection


def cached_context_projection(game_id):
    cached = _detail_cache.get(int(game_id))
    if not cached:
        return None
    payload = cached[1]
    projection = payload.get("projection", {})
    if not projection.get("available"):
        return None
    return {"projection": projection, "updated_at": payload.get("context_updated_at")}


def enqueue_projection_enrichment(games):
    queued = []
    with _projection_enrichment_lock:
        for game in games:
            game_id = int(game["game_id"])
            if game_id not in _projection_enrichment_pending and cached_context_projection(game_id) is None:
                _projection_enrichment_pending.add(game_id)
                queued.append(game_id)
    if not queued:
        return 0

    def warm():
        def load(game_id):
            try:
                game_detail(game_id)
            except Exception as exc:
                print(f"[projection-warmup] game {game_id} failed: {exc}", flush=True)
            finally:
                with _projection_enrichment_lock:
                    _projection_enrichment_pending.discard(game_id)
        with ThreadPoolExecutor(max_workers=min(4, len(queued))) as pool:
            list(pool.map(load, queued))
        _projection_board_cache.clear()

    threading.Thread(target=warm, name="projection-board-warmup", daemon=True).start()
    return len(queued)


def projection_board(start_date, days=7):
    """Return a fast, market-free projection board for slip construction."""
    try:
        first_day = datetime.fromisoformat(start_date).date()
    except (TypeError, ValueError):
        first_day = datetime.now(timezone.utc).date()
    days = max(1, min(int(days or 7), 14))
    cache_key = f"{first_day.isoformat()}:{days}"
    cached = _projection_board_cache.get(cache_key)
    cached_ttl = min(55, int(cached[1].get("refresh_seconds", 60))) if cached else 55
    if cached and datetime.now(timezone.utc) - cached[0] < timedelta(seconds=cached_ttl):
        return cached[1]
    final_day = first_day + timedelta(days=days - 1)
    raw_games = statsapi.schedule(start_date=first_day.isoformat(), end_date=final_day.isoformat(), sportId=1)
    now = datetime.now(timezone.utc)
    context_candidates = []
    for game in raw_games:
        try:
            starts_at = datetime.fromisoformat(game.get("game_datetime", "").replace("Z", "+00:00"))
        except (TypeError, ValueError):
            continue
        # Keep the Builder on the same context-aware snapshot as the matchup
        # screen for normal daily/two-day slates and every game within 48h.
        # Very large future ranges retain the fast early baseline until their
        # games enter that window, avoiding hundreds of concurrent MLB feeds.
        if "final" not in str(game.get("status", "")).lower() and now - timedelta(minutes=15) <= starts_at and (len(raw_games) <= 36 or starts_at <= now + timedelta(hours=48)):
            context_candidates.append(game)

    context_projections = {str(game["game_id"]): snapshot for game in context_candidates if (snapshot := cached_context_projection(game["game_id"]))}
    enrichment_pending = enqueue_projection_enrichment([game for game in context_candidates if str(game["game_id"]) not in context_projections])
    games = []
    for game in raw_games:
        if "final" in str(game.get("status", "")).lower() or not game.get("game_datetime"):
            continue
        try:
            starts_at = datetime.fromisoformat(game["game_datetime"].replace("Z", "+00:00"))
        except (TypeError, ValueError):
            continue
        if starts_at < now - timedelta(minutes=15):
            continue
        # Confirmed starters and lineups normally arrive close to first pitch.
        # Load the official game feed for that window so Builder probabilities
        # use the same context-aware projection shown on the matchup page.
        context_snapshot = context_projections.get(str(game["game_id"]))
        projection = (context_snapshot or {}).get("projection") or moneyline_projection(game.get("home_id"), game.get("away_id"), game["game_datetime"])
        if not projection.get("available"):
            continue
        home_probability = projection["home_win_probability"]
        away_probability = projection["away_win_probability"]
        selected_home = home_probability >= away_probability
        games.append({
            "game_id": int(game["game_id"]), "starts_at": game["game_datetime"],
            "status": game.get("status", "Scheduled"), "venue": game.get("venue_name") or "Venue TBD",
            "away": {"id": int(game["away_id"]), "name": game.get("away_name"), "abbr": (game.get("away_name") or "AWY")[:3].upper()},
            "home": {"id": int(game["home_id"]), "name": game.get("home_name"), "abbr": (game.get("home_name") or "HME")[:3].upper()},
            "away_win_probability": away_probability, "home_win_probability": home_probability,
            "recommended_side": "home" if selected_home else "away",
            "recommended_team_id": int(game["home_id"] if selected_home else game["away_id"]),
            "recommended_probability": max(home_probability, away_probability),
            "model_confidence": projection.get("confidence_score"),
            "historical_tier": projection.get("historical_tier"),
            "input_completeness": projection.get("input_completeness", 0),
            "projection_updated_at": (context_snapshot or {}).get("updated_at") or now.isoformat(),
            "projection_basis": "matchup_synced" if context_snapshot else "early_baseline",
        })
    games.sort(key=lambda item: item["starts_at"])
    recommendation = sorted(games, key=lambda item: item["recommended_probability"], reverse=True)[:5] if len(games) >= 5 else []
    try:
        with open(MODEL_REPORT, "r", encoding="utf-8") as handle:
            model_report = json.load(handle)
            slip_calibration = model_report.get("slip_calibration")
            multiday_slip_calibrations = model_report.get("multiday_slip_calibrations", {})
            multiday_validation_grid = model_report.get("multiday_validation_grid", {})
    except (OSError, json.JSONDecodeError):
        slip_calibration = None
        multiday_slip_calibrations = {}
        multiday_validation_grid = {}
    payload = {
        "generated_at": now.isoformat(), "start_date": first_day.isoformat(), "days": days,
        "games": games, "recommended_game_ids": [item["game_id"] for item in recommendation],
        "recommendation_available": len(recommendation) == 5,
        "slip_calibration": slip_calibration,
        "multiday_slip_calibrations": multiday_slip_calibrations,
        "multiday_validation_grid": multiday_validation_grid,
        "market_inputs": False, "refresh_seconds": 3 if enrichment_pending else 60,
        "enrichment_pending": enrichment_pending,
    }
    _projection_board_cache[cache_key] = (datetime.now(timezone.utc), payload)
    return payload


def circumstance_changes(previous, current):
    if not previous:
        return []
    alerts = []
    for side in ("away", "home"):
        old, new = previous.get(side, {}), current.get(side, {})
        if old.get("starter_id") and new.get("starter_id") and old["starter_id"] != new["starter_id"]:
            alerts.append({"level":"critical", "type":"starter_change", "message":f"{side.title()} starter changed from {old.get('starter_name')} to {new.get('starter_name')}."})
        if old.get("starter_status") != "confirmed" and new.get("starter_status") == "confirmed":
            alerts.append({"level":"info", "type":"starter_confirmed", "message":f"{side.title()} starter {new.get('starter_name')} is now confirmed by the official game roster."})
        if not old.get("lineup_confirmed") and new.get("lineup_confirmed"):
            alerts.append({"level":"info", "type":"lineup_confirmed", "message":f"{side.title()} lineup is now confirmed."})
        elif old.get("lineup_ids") and new.get("lineup_ids") and old["lineup_ids"] != new["lineup_ids"]:
            alerts.append({"level":"warning", "type":"lineup_change", "message":f"{side.title()} confirmed lineup changed."})
        delta = _float(new.get("bullpen_recent_pitches")) - _float(old.get("bullpen_recent_pitches"))
        if abs(delta) >= 20:
            alerts.append({"level":"warning", "type":"bullpen_change", "message":f"{side.title()} three-day bullpen workload changed by {delta:+.0f} pitches."})
        if old.get("bullpen_status") != "confirmed" and new.get("bullpen_status") == "confirmed":
            alerts.append({"level":"info", "type":"bullpen_confirmed", "message":f"{side.title()} bullpen is now confirmed from the submitted official pitcher pool."})
    old_weather, new_weather = previous.get("weather", {}), current.get("weather", {})
    temp_delta = _float(new_weather.get("temperature"), 65) - _float(old_weather.get("temperature"), 65)
    wind_delta = _float(new_weather.get("wind_speed")) - _float(old_weather.get("wind_speed"))
    if abs(temp_delta) >= 8 or abs(wind_delta) >= 5 or (old_weather.get("condition") and new_weather.get("condition") and old_weather.get("condition") != new_weather.get("condition")):
        alerts.append({"level":"warning", "type":"weather_change", "message":f"Game weather changed: {new_weather.get('condition') or 'unknown'}, {_float(new_weather.get('temperature'),65):.0f}°F, {_float(new_weather.get('wind_speed')):.0f} mph wind."})
    return alerts


def load_projection_snapshots(game_id=None):
    snapshots = {}
    try:
        with open(PROJECTION_LOG, "r", encoding="utf-8") as handle:
            for line in handle:
                try:
                    row = json.loads(line)
                    row_game_id = int(row["game_id"])
                    if game_id is not None and row_game_id != int(game_id):
                        continue
                    row["_recorded_at"] = datetime.fromisoformat(row["recorded_at"].replace("Z", "+00:00"))
                    snapshots.setdefault(row_game_id, []).append(row)
                except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                    continue
    except OSError:
        return {}
    return snapshots


def last_pregame_snapshot(game_id, game_datetime):
    if not game_datetime:
        return None
    try:
        starts_at = datetime.fromisoformat(game_datetime.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    rows = load_projection_snapshots(game_id).get(int(game_id), [])
    eligible = [row for row in rows if row["_recorded_at"] <= starts_at and row.get("phase") != "live"]
    return max(eligible, key=lambda row: row["_recorded_at"]) if eligible else None


def locked_pregame_projection(game_id, game_datetime):
    snapshot = last_pregame_snapshot(game_id, game_datetime)
    if not snapshot:
        return {"available": False, "message": "No projection was archived before scheduled first pitch.", "projection_source": "pregame_missing"}
    probability = float(snapshot["home_win_probability"])
    projection = dict(snapshot.get("projection") or {})
    bundle = load_bundle()
    completeness = context_completeness(snapshot.get("context"))
    if "confidence_score" not in projection:
        base_confidence = float(bundle["confidence_model"].predict([abs(probability - .5)])[0])
        confidence = .5 + (base_confidence - .5) * (.7 + .3 * completeness)
        projection.update({
            "confidence_score": round(confidence * 100),
            "confidence_label": "High" if confidence >= .70 else "Moderate" if confidence >= .60 else "Low",
            "input_completeness": round(completeness, 2),
            "confidence_explanation": "Expected straight-up hit rate for similarly decisive walk-forward predictions, reduced when live inputs are incomplete.",
        })
    selected_probability = max(probability, 1 - probability)
    tiers = [tier for tier in bundle["report"].get("selective_accuracy", []) if selected_probability >= tier["minimum_probability"]]
    projection.update({
        "available": True,
        "home_win_probability": round(probability, 4),
        "away_win_probability": round(float(snapshot.get("away_win_probability", 1 - probability)), 4),
        "projected_side": "home" if probability >= .5 else "away",
        "historical_tier": projection.get("historical_tier") or (tiers[-1] if tiers else None),
        "reasons": snapshot.get("reasons", projection.get("reasons", [])),
        "circumstance_alerts": snapshot.get("circumstance_alerts", []),
        "movement": {"previous_home_probability": None, "change": 0.0, "changed": False},
        "model": bundle["report"],
        "market_inputs": False,
        "snapshot_at": snapshot["recorded_at"],
        "projection_source": "pregame_locked",
        "projection_phase": "pregame",
    })
    return projection


def record_projection(game_id, projection, context=None, status_code="Preview", scheduled_start=None):
    if not projection.get("available"):
        return projection
    if status_code not in ("Preview", "Live"):
        return projection
    current = projection["home_win_probability"]
    previous = _projection_last.get(str(game_id))
    change = round(current - previous, 4) if previous is not None else 0.0
    movement = {"previous_home_probability": previous, "change": change, "changed": previous is not None and abs(change) >= 0.005, "direction": "home" if change >= 0 else "away", "label": f"{abs(change) * 100:.1f} percentage-point move" if previous is not None else "Initial projection"}
    projection["movement"] = movement
    new_alerts = circumstance_changes(_projection_last_context.get(str(game_id)), context or {})
    coverage = float(projection.get("input_completeness") or 0)
    previous_coverage = _projection_last_completeness.get(str(game_id))
    coverage_changed = previous_coverage is not None and abs(coverage - previous_coverage) >= .01
    if coverage_changed:
        new_alerts.append({"level": "info", "type": "input_coverage_change", "message": f"Live input coverage changed from {previous_coverage:.0%} to {coverage:.0%}."})
    if new_alerts:
        _projection_recent_alerts[str(game_id)] = (datetime.now(timezone.utc), new_alerts)
    recent = _projection_recent_alerts.get(str(game_id))
    projection["circumstance_alerts"] = new_alerts or (recent[1] if recent and datetime.now(timezone.utc) - recent[0] <= timedelta(minutes=15) else [])
    game_state = projection.get("game_state")
    game_state_signature = json.dumps(game_state, sort_keys=True) if game_state else None
    game_state_changed = game_state_signature is not None and game_state_signature != _projection_last_game_state.get(str(game_id))
    if previous is None or movement["changed"] or coverage_changed or game_state_changed or new_alerts:
        os.makedirs(os.path.dirname(PROJECTION_LOG), exist_ok=True)
        audit_keys = ("confidence_score", "confidence_label", "input_completeness", "confidence_explanation", "historical_tier", "market_inputs", "projection_source", "projection_phase", "game_state", "pregame_home_win_probability", "pregame_away_win_probability")
        snapshot = {"game_id": int(game_id), "recorded_at": datetime.now(timezone.utc).isoformat(), "scheduled_start": scheduled_start, "phase": "live" if status_code == "Live" else "pregame", "home_win_probability": current, "away_win_probability": projection["away_win_probability"], "reasons": projection.get("reasons", []), "context": context, "circumstance_alerts": new_alerts, "projection": {key: projection.get(key) for key in audit_keys}}
        with open(PROJECTION_LOG, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(snapshot) + "\n")
    _projection_last[str(game_id)] = current
    if context:_projection_last_context[str(game_id)] = context
    _projection_last_completeness[str(game_id)] = coverage
    if game_state_signature is not None:
        _projection_last_game_state[str(game_id)] = game_state_signature
    return projection


def completed_prediction_results(limit=50):
    """Score the last pre-first-pitch snapshot against official final results."""
    global _prediction_results_cache
    now = datetime.now(timezone.utc)
    if _prediction_results_cache and now - _prediction_results_cache[0] < timedelta(minutes=5):
        return _prediction_results_cache[1]
    snapshots = load_projection_snapshots()
    if not snapshots:
        payload = {"games": [], "evaluated": 0, "correct": 0, "accuracy": None, "updated_at": now.isoformat()}
        _prediction_results_cache = (now, payload)
        return payload

    earliest = min(row["_recorded_at"].date() for rows in snapshots.values() for row in rows)
    games = statsapi.schedule(start_date=earliest.isoformat(), end_date=now.date().isoformat(), sportId=1)
    results = []
    for game in games:
        game_id = int(game.get("game_id") or 0)
        if game_id not in snapshots or "final" not in str(game.get("status", "")).lower():
            continue
        if game.get("home_score") is None or game.get("away_score") is None or int(game["home_score"]) == int(game["away_score"]):
            continue
        try:
            starts_at = datetime.fromisoformat(game["game_datetime"].replace("Z", "+00:00"))
        except (KeyError, TypeError, ValueError):
            continue
        eligible = [row for row in snapshots[game_id] if row["_recorded_at"] <= starts_at and row.get("phase") != "live"]
        if not eligible:
            continue
        snapshot = max(eligible, key=lambda row: row["_recorded_at"])
        home_probability = float(snapshot["home_win_probability"])
        projected_side = "home" if home_probability >= .5 else "away"
        actual_side = "home" if int(game["home_score"]) > int(game["away_score"]) else "away"
        correct = projected_side == actual_side
        home = {"id": int(game["home_id"]), "name": game.get("home_name")}
        away = {"id": int(game["away_id"]), "name": game.get("away_name")}
        results.append({
            "game_id": game_id, "starts_at": game.get("game_datetime"), "snapshot_at": snapshot["recorded_at"],
            "home": home, "away": away, "home_score": int(game["home_score"]), "away_score": int(game["away_score"]),
            "home_win_probability": home_probability, "away_win_probability": float(snapshot["away_win_probability"]),
            "projected_side": projected_side, "projected_team": (home if projected_side == "home" else away),
            "winner_side": actual_side, "winner": (home if actual_side == "home" else away), "correct": correct,
        })
    results.sort(key=lambda row: row["starts_at"] or "", reverse=True)
    results = results[:max(1, min(int(limit or 50), 100))]
    correct = sum(1 for row in results if row["correct"])
    payload = {"games": results, "evaluated": len(results), "correct": correct, "accuracy": correct / len(results) if results else None, "updated_at": now.isoformat(), "snapshot_rule": "Last archived projection at or before scheduled first pitch"}
    _prediction_results_cache = (now, payload)
    return payload


def enrich_slip(slip):
    if not slip.get("selections"):
        return slip
    dates = [datetime.fromisoformat(item["scheduled_local"]).date() for item in slip["selections"]]
    games = statsapi.schedule(start_date=(min(dates) - timedelta(days=1)).isoformat(), end_date=(max(dates) + timedelta(days=1)).isoformat(), sportId=1)
    for selection in slip["selections"]:
        wanted = {normalize_slip_team(selection["team_1"]), normalize_slip_team(selection["team_2"])}
        game = next((item for item in games if {normalize_slip_team(item.get("away_name", "")), normalize_slip_team(item.get("home_name", ""))} == wanted), None)
        if not game:
            continue
        selection.update({"game_id": int(game["game_id"]), "status": game.get("status", "Unknown"), "away_team": game.get("away_name"), "home_team": game.get("home_name"), "away_score": game.get("away_score"), "home_score": game.get("home_score")})
        if "Final" in game.get("status", ""):
            selected_home = normalize_slip_team(selection["selected_team"]) == normalize_slip_team(game.get("home_name", ""))
            selected_score = game.get("home_score") if selected_home else game.get("away_score")
            other_score = game.get("away_score") if selected_home else game.get("home_score")
            selection["outcome"] = "won" if selected_score > other_score else "lost"
        else:
            previous = selection.get("selected_probability")
            projection = game_detail(game["game_id"]).get("projection", {})
            if projection.get("available"):
                selected_home = normalize_slip_team(selection["selected_team"]) == normalize_slip_team(game.get("home_name", ""))
                current = projection["home_win_probability"] if selected_home else projection["away_win_probability"]
                selection["selected_probability"] = current
                selection["model_confidence"] = projection.get("confidence_score")
                selection["confidence_label"] = projection.get("confidence_label")
                alerts = []
                if current < 0.5: alerts.append({"level": "warning", "message": f"Model now favors the opponent ({current:.1%} selected-team probability)."})
                if previous is not None and previous - current >= 0.05: alerts.append({"level": "critical", "message": f"Projection fell {(previous-current):.1%} since the prior check."})
                alerts.extend(projection.get("circumstance_alerts", []))
                selection["alerts"] = alerts
    slip["last_checked_at"] = datetime.now(timezone.utc).isoformat()
    selection_year = datetime.fromisoformat(slip["selections"][0]["scheduled_local"]).year
    slip["placed_at_iso"] = placed_at_iso(slip.get("placed_at"), slip.get("imported_at"), selection_year)
    now_local = datetime.now()
    slip["active"] = any(
        "final" not in str(item.get("status", "")).lower()
        and "completed" not in str(item.get("status", "")).lower()
        and item.get("outcome", "pending") == "pending"
        and (
            item.get("game_id") is not None
            or datetime.fromisoformat(item["scheduled_local"]) >= now_local - timedelta(hours=8)
        )
        for item in slip["selections"]
    )
    return slip


def schedule(date):
    with ThreadPoolExecutor(max_workers=2) as pool:
        games_future = pool.submit(statsapi.schedule, date=date)
        teams_future = pool.submit(teams_data)
        games, teams = games_future.result(), teams_future.result()
    team_by_id = {int(team["id"]): team for team in teams}
    for game in games:
        away, home = team_by_id.get(int(game.get("away_id") or 0), {}), team_by_id.get(int(game.get("home_id") or 0), {})
        game["details"] = {
            "status": game.get("status"), "away": away, "home": home,
            "venue": {"id": game.get("venue_id"), "name": game.get("venue_name") or home.get("venue"), "latitude": home.get("venue_latitude"), "longitude": home.get("venue_longitude")},
        }
    return games


def player_search(query):
    if not query.strip():
        return []
    return statsapi.lookup_player(query)[:10]


def player_detail(player_id):
    return statsapi.player_stat_data(int(player_id), group="[hitting,pitching,fielding]", type="season")


def pitcher_profile(person):
    if not person or not person.get("id"):
        return None
    player_id = int(person["id"])
    cached = _pitcher_profile_cache.get(player_id)
    if cached and datetime.now(timezone.utc) - cached[0] < timedelta(minutes=10):
        return cached[1]
    profile = statsapi.player_stat_data(player_id, group="pitching", type="season")
    pitching = next((item.get("stats", {}) for item in profile.get("stats", []) if item.get("group") == "pitching"), {})
    result = {
        "id": person.get("id"), "name": person.get("fullName"), "team": profile.get("current_team"),
        "position": profile.get("position"), "era": pitching.get("era"), "whip": pitching.get("whip"),
        "innings": pitching.get("inningsPitched"), "strikeouts": pitching.get("strikeOuts"),
        "walks": pitching.get("baseOnBalls"), "wins": pitching.get("wins"), "losses": pitching.get("losses"),
    }
    _pitcher_profile_cache[player_id] = (datetime.now(timezone.utc), result)
    return result


class Handler(BaseHTTPRequestHandler):
    def send_json(self, payload, status=200):
        body = json.dumps(payload, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "http://localhost:5173")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        try:
            if parsed.path == "/health":
                self.send_json({"status": "ok", "provider": "MLB-StatsAPI", "version": statsapi.__version__, "maintenance": maintenance_status(), "projection_monitor": _projection_monitor})
            elif parsed.path == "/model":
                with open(MODEL_REPORT, "r", encoding="utf-8") as handle:
                    report = json.load(handle)
                report["maintenance"] = maintenance_status()
                report["completed_predictions"] = completed_prediction_results()
                self.send_json(report)
            elif parsed.path == "/projection-board":
                start_date = query.get("start_date", [datetime.now(timezone.utc).date().isoformat()])[0]
                self.send_json(projection_board(start_date, query.get("days", [7])[0]))
            elif parsed.path == "/games":
                date = query.get("date", [datetime.now(timezone.utc).date().isoformat()])[0]
                self.send_json(schedule(date))
            elif parsed.path.startswith("/games/") and parsed.path.endswith("/summary"):
                self.send_json(game_summary(parsed.path.split("/")[-2]))
            elif parsed.path.startswith("/games/"):
                self.send_json(game_detail(parsed.path.rsplit("/", 1)[-1]))
            elif parsed.path == "/teams":
                self.send_json(teams_data())
            elif parsed.path.startswith("/teams/"):
                self.send_json(team_detail(parsed.path.rsplit("/", 1)[-1]))
            elif parsed.path == "/players":
                self.send_json(players_data())
            elif parsed.path == "/players/search":
                self.send_json(player_search(query.get("q", [""])[0]))
            elif parsed.path.startswith("/players/"):
                self.send_json(player_detail(parsed.path.rsplit("/", 1)[-1]))
            elif parsed.path == "/slips":
                slips = [
                    item if item.get("active") is False and all(selection.get("outcome") != "pending" for selection in item.get("selections", [])) else enrich_slip(item)
                    for item in load_slips()
                ]
                for slip in slips: save_slip(slip)
                slips.sort(key=lambda item: item.get("placed_at_iso") or item.get("imported_at") or "", reverse=True)
                self.send_json(slips)
            else:
                self.send_json({"error": "Not found"}, 404)
        except Exception as exc:
            self.send_json({"error": str(exc), "provider": "MLB-StatsAPI"}, 502)

    def do_POST(self):
        parsed = urlparse(self.path)
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            if parsed.path == "/slips/import":
                slip = enrich_slip(parse_pdf(payload["data"], payload.get("filename", "slip.pdf")))
                self.send_json(save_slip(slip), 201)
            else:
                self.send_json({"error": "Not found"}, 404)
        except Exception as exc:
            self.send_json({"error": str(exc), "provider": "Slip parser"}, 422)

    def log_message(self, fmt, *args):
        print(f"[mlb-stats] {self.address_string()} {fmt % args}")


def projection_refresh_loop():
    """Refresh imminent and live game projections independently of page traffic."""
    if os.getenv("NINTH_PROJECTION_MONITOR_ENABLED", "1").lower() in ("0", "false", "no"):
        return
    pregame_seconds = max(30, int(os.getenv("NINTH_PREGAME_REFRESH_SECONDS", "60")))
    live_seconds = max(5, int(os.getenv("NINTH_LIVE_REFRESH_SECONDS", "10")))
    discovery_seconds = max(15, int(os.getenv("NINTH_GAME_DISCOVERY_SECONDS", "30")))
    monitor_hours = max(2, int(os.getenv("NINTH_PREGAME_MONITOR_HOURS", "24")))
    _projection_monitor.update({"running": True, "pregame_seconds": pregame_seconds, "live_seconds": live_seconds})
    tracked, next_due = {}, {}
    next_discovery = 0.0
    while True:
        monotonic_now = time.monotonic()
        now = datetime.now(timezone.utc)
        if monotonic_now >= next_discovery:
            try:
                raw_games = statsapi.schedule(start_date=(now.date() - timedelta(days=1)).isoformat(), end_date=(now.date() + timedelta(days=1)).isoformat(), sportId=1)
                discovered = {}
                for game in raw_games:
                    try:
                        game_id = int(game.get("game_id") or 0)
                        starts_at = datetime.fromisoformat(str(game.get("game_datetime") or "").replace("Z", "+00:00"))
                    except (TypeError, ValueError):
                        continue
                    status = str(game.get("status") or "")
                    status_lower = status.lower()
                    if not game_id or "final" in status_lower or "completed" in status_lower:
                        continue
                    is_live = "live" in status_lower or "progress" in status_lower
                    in_window = now - timedelta(hours=6) <= starts_at <= now + timedelta(hours=monitor_hours)
                    if not is_live and not in_window:
                        continue
                    previous_live = tracked.get(game_id, {}).get("is_live", False)
                    discovered[game_id] = {"is_live": is_live, "starts_at": starts_at.isoformat(), "status": status}
                    if game_id not in next_due or (is_live and not previous_live):
                        next_due[game_id] = 0.0
                tracked = discovered
                next_due = {game_id: due for game_id, due in next_due.items() if game_id in tracked}
                _projection_monitor.update({"last_discovery_at": now.isoformat(), "tracked_games": len(tracked), "last_error": None})
            except Exception as exc:
                _projection_monitor["last_error"] = f"Discovery failed: {exc}"
            next_discovery = monotonic_now + discovery_seconds
        due_ids = [game_id for game_id in tracked if monotonic_now >= next_due.get(game_id, 0)]
        if due_ids:
            def refresh(game_id):
                try:
                    detail = game_detail(game_id, force=True)
                    return game_id, detail.get("status_code", "Preview"), None
                except Exception as exc:
                    return game_id, None, str(exc)
            with ThreadPoolExecutor(max_workers=min(4, len(due_ids))) as pool:
                results = list(pool.map(refresh, due_ids))
            refreshed_at = datetime.now(timezone.utc)
            for game_id, status_code, error in results:
                if error:
                    next_due[game_id] = time.monotonic() + 15
                    _projection_monitor["last_error"] = f"Game {game_id}: {error}"
                    continue
                is_live = status_code == "Live"
                if game_id in tracked:
                    tracked[game_id]["is_live"] = is_live
                    tracked[game_id]["status"] = status_code
                next_due[game_id] = time.monotonic() + (live_seconds if is_live else pregame_seconds)
                _projection_monitor.update({"last_refresh_at": refreshed_at.isoformat(), "last_game_id": game_id, "last_error": None})
        time.sleep(1)


def maintenance_loop():
    """Run the guarded data/model maintenance check without blocking requests."""
    if os.getenv("NINTH_MAINTENANCE_ENABLED", "1").lower() in ("0", "false", "no"):
        return
    interval = max(900, int(os.getenv("NINTH_MAINTENANCE_CHECK_SECONDS", "3600")))
    while True:
        try:
            result = subprocess.run(
                [sys.executable, "-m", "ml.maintenance", "--once"],
                cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                capture_output=True, text=True, timeout=60 * 60,
            )
            output = (result.stdout or result.stderr).strip()
            if output:
                print(f"[model-maintenance] {output}", flush=True)
        except Exception as exc:
            print(f"[model-maintenance] check failed: {exc}", flush=True)
        time.sleep(interval)


if __name__ == "__main__":
    threading.Thread(target=projection_refresh_loop, name="projection-refresh", daemon=True).start()
    threading.Thread(target=maintenance_loop, name="model-maintenance", daemon=True).start()
    print(f"MLB Stats provider listening on {PORT}")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
