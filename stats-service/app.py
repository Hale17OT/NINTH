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
import unicodedata
import statsapi

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ml.predict import context_completeness, load_bundle, predict as model_predict
from ml.totals_predict import load_bundle as load_totals_bundle, predict as totals_model_predict
from ml.player_props_predict import load_bundle as load_player_props_bundle, predict_candidates, projected_lineup
from ml.slips import load_slips, normalize_team as normalize_slip_team, parse_pdf, placed_at_iso, save_slip

PORT = int(os.getenv("MLB_STATS_PORT", "3002"))
SLIP_TIMEZONE_OFFSET_HOURS = float(os.getenv("NINTH_SLIP_TIMEZONE_OFFSET_HOURS", "3"))
_detail_cache = {}
_projection_board_cache = {}
_board_schedule_cache = {}
_board_schedule_lock = threading.Lock()
_baseline_projection_cache = {}
_baseline_projection_lock = threading.Lock()
_baseline_projection_pending = set()
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
_totals_projection_last = {}
_bullpen_cache = {}
_recent_form_cache = {}
_pitcher_profile_cache = {}
_prediction_results_cache = None
_prediction_results_lock = threading.Lock()
_weather_cache = {}
_weather_backoff_until = 0.0
_weather_locks = {}
_weather_locks_guard = threading.Lock()
_melbet_totals_cache = {"updated_at": None, "last_attempt_at": None, "markets": [], "error": None}
_melbet_totals_lock = threading.Lock()
_melbet_totals_snapshot_lock = threading.Lock()
_melbet_totals_snapshot_last = {}
_melbet_totals_snapshot_loaded = False
_melbet_player_props_cache = {"updated_at": None, "last_attempt_at": None, "markets": [], "error": None}
_melbet_player_props_lock = threading.Lock()
_player_props_bundle = None
_player_props_bundle_lock = threading.Lock()
_player_props_board_cache = {}
_player_props_refreshing = set()
_player_props_cache_lock = threading.Lock()
_player_prop_snapshot_lock = threading.Lock()
_player_prop_snapshot_last = {}
_player_prop_results_cache = None
_player_prop_results_lock = threading.Lock()
_player_prop_boxscore_cache = {}
_slip_refresh_lock = threading.Lock()
_slip_refresh_running = False
_slip_refresh_state = {"running": False, "last_started_at": None, "last_finished_at": None, "last_error": None}
_detail_locks = {}
_detail_locks_guard = threading.Lock()
_projection_monitor = {"running": False, "pregame_seconds": 60, "live_seconds": 10, "last_discovery_at": None, "last_refresh_at": None, "tracked_games": 0, "last_error": None}
_player_prop_monitor = {
    "running": False,
    "refresh_seconds": 60,
    "last_attempt_at": None,
    "last_success_at": None,
    "archived_games": 0,
    "last_error": None,
}
PROJECTION_LOG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ml", "data", "projection_snapshots.jsonl")
MODEL_REPORT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ml", "artifacts", "report.json")
TOTALS_REPORT = os.path.join(os.path.dirname(MODEL_REPORT), "totals_report.json")
MARKET_SLIP_CALIBRATION = os.path.join(os.path.dirname(MODEL_REPORT), "market_slip_calibration.json")
MAINTENANCE_STATE = os.path.join(os.path.dirname(MODEL_REPORT), "maintenance_state.json")
MELBET_PRIMARY_BASE = "https://mel-bet.et"
MELBET_PROXY_BASE = "https://melbet-322491.top"
MELBET_BASES = (MELBET_PRIMARY_BASE, MELBET_PROXY_BASE)
MELBET_CHAMP_PATH = "/service-api/LineFeed/GetChampZip"
MELBET_GAME_PATH = "/service-api/LineFeed/GetGameZip"
MELBET_MLB_CHAMP_ID = 166775
PLAYER_PROPS_REPORT = os.path.join(os.path.dirname(MODEL_REPORT), "player_props_report.json")
PLAYER_PROP_PROJECTION_LOG = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "ml", "data", "player_prop_projection_snapshots.jsonl",
)
MELBET_TOTALS_SNAPSHOT_LOG = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "ml", "data", "melbet_totals_snapshots.jsonl",
)

# MelBet exposes player selections in a linked Player's Stats sub-game. These
# group identifiers are stable baseball market identifiers; price fields are
# intentionally never copied into NINTH.
MELBET_PLAYER_PROP_GROUPS = {
    10710: "outs", 2891: "strikeouts", 10713: "hits_allowed", 10712: "walks",
    10466: "home_runs", 11328: "runs", 8527: "hits",
    10465: "total_bases", 10956: "doubles", 10714: "rbi",
}


def player_props_bundle():
    global _player_props_bundle
    if _player_props_bundle is None:
        with _player_props_bundle_lock:
            if _player_props_bundle is None:
                _player_props_bundle = load_player_props_bundle()
    return _player_props_bundle


def _props_game(game, bundle):
    game_id = int(game.get("game_id") or game.get("gamePk"))
    feed = statsapi.get("game", {"gamePk": game_id})
    data = feed.get("gameData", {}); teams = data.get("teams", {})
    raw_teams = feed.get("liveData", {}).get("boxscore", {}).get("teams", {})
    probable = data.get("probablePitchers", {})
    game_date = (data.get("datetime", {}).get("officialDate") or str(game.get("game_date", ""))[:10])
    season = int(data.get("game", {}).get("season") or game_date[:4])
    starters = {}
    for side in ("away", "home"):
        person = probable.get(side) or {}
        raw = raw_teams.get(side, {})
        if not person.get("id") and raw.get("pitchers"):
            pid = int(raw["pitchers"][0]); player = raw.get("players", {}).get("ID" + str(pid), {})
            person = player.get("person") or {"id": pid, "fullName": f"Player {pid}"}
        starters[side] = person
    candidates = []
    for side, opponent in (("away", "home"), ("home", "away")):
        team_id = int(teams.get(side, {}).get("id") or game.get(f"{side}_id"))
        opponent_id = int(teams.get(opponent, {}).get("id") or game.get(f"{opponent}_id"))
        starter = starters.get(side) or {}
        if starter.get("id"):
            candidate = {
                "kind": "pitcher", "player_id": int(starter["id"]),
                "name": starter.get("fullName"), "team_id": team_id, "opponent_id": opponent_id,
                "home": side == "home", "lineup_slot": 0, "side": side,
                "role": "Starting pitcher", "lineup_status": "confirmed" if raw_teams.get(side, {}).get("pitchers") else "probable",
            }
            candidates.append(candidate)
        raw = raw_teams.get(side, {}); order = (raw.get("battingOrder") or [])[:9]
        if order:
            players = raw.get("players", {})
            lineup = [{"player_id": int(pid), "lineup_slot": index + 1,
                       "name": (players.get("ID" + str(pid), {}).get("person") or {}).get("fullName")}
                      for index, pid in enumerate(order)]
            lineup_status = "confirmed"
        else:
            lineup = projected_lineup(bundle, team_id); lineup_status = "projected"
        for batter in lineup:
            candidate = {
                "kind": "batter", "player_id": int(batter["player_id"]), "name": batter.get("name"),
                "team_id": team_id, "opponent_id": opponent_id, "home": side == "home",
                "lineup_slot": batter.get("lineup_slot"), "opponent_starter_id": (starters.get(opponent) or {}).get("id"),
                "side": side, "role": f"Projected batting order #{batter.get('lineup_slot')}", "lineup_status": lineup_status,
            }
            candidates.append(candidate)
    return {
        "game_id": game_id, "datetime": data.get("datetime", {}).get("dateTime") or game.get("game_datetime"),
        "status": data.get("status", {}).get("detailedState") or game.get("status"),
        "away": normalize_team(teams.get("away", {})), "home": normalize_team(teams.get("home", {})),
        "_candidates": candidates, "_game_date": game_date, "_season": season,
    }


def player_props_board(start_date, days=1, force=False, defer_refresh=False):
    days = max(1, min(7, int(days))); key = f"{start_date}:{days}"
    with _player_props_cache_lock:
        cached = _player_props_board_cache.get(key)
        if cached and (not force or defer_refresh):
            should_refresh = defer_refresh or time.monotonic() - cached[0] >= 60
            if should_refresh and key not in _player_props_refreshing:
                _player_props_refreshing.add(key)
                def refresh():
                    try: player_props_board(start_date, days, force=True)
                    finally:
                        with _player_props_cache_lock: _player_props_refreshing.discard(key)
                threading.Thread(target=refresh, name=f"player-props-{key}", daemon=True).start()
            if should_refresh or key in _player_props_refreshing:
                return {**cached[1], "refresh_in_progress": True, "refresh_seconds": 10}
            return cached[1]
    first = datetime.fromisoformat(start_date).date(); last = first + timedelta(days=days - 1)
    schedule_rows = statsapi.schedule(start_date=first.isoformat(), end_date=last.isoformat(), sportId=1)
    eligible = [
        row for row in schedule_rows
        if not re.search(r"Final|Cancelled|Postponed|In Progress|Live|Warmup", str(row.get("status", "")), re.I)
    ]
    bundle = player_props_bundle()
    with ThreadPoolExecutor(max_workers=min(7, max(2, len(eligible) + 1))) as pool:
        market_future = pool.submit(melbet_player_prop_markets, force)
        games = list(pool.map(lambda row: _props_game(row, bundle), eligible))
    candidate_groups = {}
    for game in games:
        key_group = (game.pop("_game_date"), game.pop("_season"))
        for candidate in game.pop("_candidates"):
            candidate["_game_id"] = game["game_id"]
            candidate_groups.setdefault(key_group, []).append(candidate)
        game["players"] = []
    games_by_id = {game["game_id"]: game for game in games}
    for (game_date, season), candidates in candidate_groups.items():
        for player in predict_candidates(bundle, candidates, game_date, season):
            game_id = player.pop("_game_id")
            games_by_id[game_id]["players"].append(player)
    market_snapshot = market_future.result()
    for game in games:
        market = match_melbet_player_props(
            game.get("home", {}).get("name"), game.get("away", {}).get("name"),
            game.get("datetime"), market_snapshot,
        )
        game["players"] = restrict_player_props_to_available_lines(game.get("players"), market)
        game["player_line_market"] = market or {
            "available": False, "source": "MelBet displayed player props",
            "prices_used": False, "observed_at": market_snapshot.get("updated_at").isoformat() if market_snapshot.get("updated_at") else None,
        }
    payload = {
        "start_date": first.isoformat(), "days": days, "updated_at": datetime.now(timezone.utc).isoformat(),
        "refresh_seconds": 60, "method": "Market-free calibrated player-game distributions restricted to currently displayed selections",
        "games": games,
        "player_prop_line_feed": {
            "source": "MelBet displayed player props", "prices_used": False,
            "observed_at": market_snapshot.get("updated_at").isoformat() if market_snapshot.get("updated_at") else None,
            "listed_games": len(market_snapshot.get("markets", [])), "error": market_snapshot.get("error"),
        },
    }
    record_player_prop_snapshots(games)
    with _player_props_cache_lock:
        _player_props_board_cache[key] = (time.monotonic(), payload)
    return payload


def record_player_prop_snapshots(games):
    """Archive only the exact model recommendations visible before first pitch."""
    global _player_prop_results_cache
    recorded_at = datetime.now(timezone.utc).isoformat()
    rows = []
    for game in games:
        if game.get("player_line_market", {}).get("stale"):
            continue
        selections = []
        for player in game.get("players", []):
            for prop in player.get("props", []):
                line = prop.get("recommended_line")
                side = prop.get("recommended_side")
                threshold = next(
                    (row for row in prop.get("thresholds", []) if float(row.get("line")) == float(line)),
                    None,
                ) if line is not None else None
                probability = threshold.get(f"{side}_probability") if threshold and side in ("over", "under") else None
                if probability is None:
                    continue
                selections.append({
                    "player_id": int(player["player_id"]), "player_name": player.get("name"),
                    "kind": player.get("kind"), "team_id": int(player.get("team_id") or 0),
                    "prop": prop.get("prop"), "label": prop.get("label"),
                    "line": float(line), "side": side, "probability": float(probability),
                })
        if not selections:
            continue
        selections.sort(key=lambda row: (row["player_id"], row["prop"], row["line"], row["side"]))
        game_id = int(game["game_id"])
        signature = json.dumps(selections, sort_keys=True, separators=(",", ":"))
        if _player_prop_snapshot_last.get(game_id) == signature:
            continue
        _player_prop_snapshot_last[game_id] = signature
        rows.append({
            "game_id": game_id, "recorded_at": recorded_at,
            "scheduled_start": game.get("datetime"),
            "game_date": str(game.get("datetime") or "")[:10],
            "away": game.get("away"), "home": game.get("home"),
            "selections": selections,
            "snapshot_rule": "Exact displayed recommendation before first pitch",
        })
    if not rows:
        return
    with _player_prop_snapshot_lock:
        os.makedirs(os.path.dirname(PLAYER_PROP_PROJECTION_LOG), exist_ok=True)
        with open(PLAYER_PROP_PROJECTION_LOG, "a", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, separators=(",", ":")) + "\n")
    _player_prop_results_cache = None


def refresh_player_prop_archive():
    """Capture today's exact displayed prop recommendations without a UI request."""
    today = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=-4))).date().isoformat()
    _player_prop_monitor["last_attempt_at"] = datetime.now(timezone.utc).isoformat()
    payload = player_props_board(today, 1, force=True)
    archived_games = sum(
        1 for game in payload.get("games", [])
        if game.get("players") and not game.get("player_line_market", {}).get("stale")
    )
    _player_prop_monitor.update({
        "last_success_at": datetime.now(timezone.utc).isoformat(),
        "archived_games": archived_games,
        "last_error": None,
    })
    return today, payload


def player_prop_archive_loop():
    """Keep the deployment ledger populated even when the builder is never opened."""
    interval = max(60, int(os.getenv("NINTH_PLAYER_PROP_REFRESH_SECONDS", "60")))
    _player_prop_monitor.update({"running": True, "refresh_seconds": interval})
    while True:
        started = time.monotonic()
        try:
            today, payload = refresh_player_prop_archive()
            listed = payload.get("player_prop_line_feed", {}).get("listed_games", 0)
            print(f"[player-props] archived {today} with {listed} listed games", flush=True)
        except Exception as exc:
            _player_prop_monitor["last_error"] = str(exc)
            print(f"[player-props] archive refresh failed: {exc}", flush=True)
        time.sleep(max(1, interval - (time.monotonic() - started)))


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
        with ThreadPoolExecutor(max_workers=5) as pool:
            away_pitcher = pool.submit(pitcher_profile, probable.get("away"))
            home_pitcher = pool.submit(pitcher_profile, probable.get("home"))
            away_recent = pool.submit(recent_form, team_ids[0], game_time, game_id)
            home_recent = pool.submit(recent_form, team_ids[1], game_time, game_id)
            totals_market_future = pool.submit(
                match_melbet_totals,
                teams.get("home", {}).get("name"), teams.get("away", {}).get("name"), game_time,
            )
            pitcher_profiles = {"away": away_pitcher.result(), "home": home_pitcher.result()}
            recent_results = [away_recent.result(), home_recent.result()]
            totals_market = totals_market_future.result()
        context = live_context(feed, pitcher_profiles, team_ids, game_time, game_id)
        status_code = status_data.get("abstractGameState", "Preview")
        if status_code == "Final":
            projection = locked_pregame_projection(game_id, game_time)
            totals_projection = locked_pregame_totals_projection(game_id, game_time)
        else:
            try:
                projection = moneyline_projection(team_ids[1], team_ids[0], game_time, context)
                totals_projection = total_runs_projection(team_ids[1], team_ids[0], game_time, context)
                totals_projection = restrict_totals_to_available_lines(totals_projection, totals_market)
                if status_code == "Live":
                    projection = apply_live_game_state(projection, linescore, current_play.get("count", {}))
                    totals_projection = apply_live_total_state(totals_projection, linescore, current_play.get("count", {}))
            except Exception as exc:
                projection = {"available": False, "message": f"Projection refresh failed: {exc}"}
                totals_projection = {"available": False, "message": f"Totals refresh failed: {exc}"}
            projection = record_projection(game_id, projection, context, status_code, game_time, totals_projection)
        payload = {
            "game_id": game_id,
            "status": status_data.get("detailedState", "Unknown"),
            "status_code": status_code,
            "context_updated_at": projection.get("snapshot_at") or context.get("updated_at"),
            "projection_refresh_seconds": 10 if status_code == "Live" else 0 if status_code == "Final" else 60,
            "totals_projection": totals_projection,
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
    mlb_weather_available = weather.get("temp") is not None
    weather_context = {"temperature": _float(weather.get("temp"), 65), "wind_speed": _float(wind_match.group(1)) if wind_match else 0, "condition": weather.get("condition") or ("Weather temporarily unavailable" if not mlb_weather_available else None), "source": "MLB game feed" if mlb_weather_available else "Neutral weather fallback", "available": mlb_weather_available}
    if weather.get("temp") is None:
        coords = data.get("venue", {}).get("location", {}).get("defaultCoordinates", {})
        forecast = open_meteo_weather(coords.get("latitude"), coords.get("longitude"), game_datetime)
        if forecast:
            weather_context = forecast
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
    """Return cached weather when possible and never fail a baseball request."""
    global _weather_backoff_until
    if latitude is None or longitude is None or not game_datetime:
        return None
    target = datetime.fromisoformat(game_datetime.replace("Z", "+00:00"))
    day = target.date().isoformat()
    historical = target < datetime.now(timezone.utc) - timedelta(days=5)
    key = f"{round(float(latitude), 3)}:{round(float(longitude), 3)}:{day}:{target.hour}:{'history' if historical else 'forecast'}"
    with _weather_locks_guard:
        request_lock = _weather_locks.setdefault(key, threading.Lock())
    with request_lock:
        now_monotonic = time.monotonic()
        cached = _weather_cache.get(key)
        cache_seconds = 24 * 60 * 60 if historical else 30 * 60
        if cached and now_monotonic - cached[0] < cache_seconds:
            return dict(cached[1])
        if now_monotonic < _weather_backoff_until:
            if cached:
                stale = dict(cached[1]); stale["source"] = f"{stale.get('source', 'Open-Meteo')} · cached during provider cooldown"; return stale
            return None
        endpoint = "https://archive-api.open-meteo.com/v1/archive" if historical else "https://api.open-meteo.com/v1/forecast"
        try:
            response = requests.get(endpoint, params={"latitude": latitude, "longitude": longitude, "start_date": day, "end_date": day, "hourly": "temperature_2m,wind_speed_10m,weather_code", "temperature_unit": "fahrenheit", "wind_speed_unit": "mph", "timezone": "UTC"}, timeout=12)
            if response.status_code == 429:
                try:
                    retry_seconds = max(60, min(900, int(response.headers.get("Retry-After", "300"))))
                except (TypeError, ValueError):
                    retry_seconds = 300
                _weather_backoff_until = now_monotonic + retry_seconds
                if cached:
                    stale = dict(cached[1]); stale["source"] = f"{stale.get('source', 'Open-Meteo')} · cached during rate limit"; return stale
                return None
            response.raise_for_status()
            hourly = response.json().get("hourly", {})
            times = hourly.get("time", [])
            if not times:
                return dict(cached[1]) if cached else None
            index = min(range(len(times)), key=lambda i: abs(datetime.fromisoformat(times[i]).replace(tzinfo=timezone.utc) - target.astimezone(timezone.utc)))
            code = hourly.get("weather_code", [None] * len(times))[index]
            result = {"temperature": _float(hourly.get("temperature_2m", [65] * len(times))[index], 65), "wind_speed": _float(hourly.get("wind_speed_10m", [0] * len(times))[index]), "condition": f"Weather code {code}" if code is not None else None, "source": "Open-Meteo historical weather" if historical else "Open-Meteo forecast", "available": True}
            _weather_cache[key] = (time.monotonic(), result)
            return dict(result)
        except (requests.RequestException, ValueError, TypeError, IndexError, KeyError) as exc:
            _weather_backoff_until = max(_weather_backoff_until, now_monotonic + 60)
            if cached:
                stale = dict(cached[1]); stale["source"] = f"{stale.get('source', 'Open-Meteo')} · cached after provider error"; return stale
            print(f"[weather] Open-Meteo unavailable; continuing without forecast: {exc}", flush=True)
            return None


def _melbet_event_rows(value):
    rows = []
    if isinstance(value, dict):
        if "T" in value:
            rows.append(value)
        else:
            for child in value.values():
                rows.extend(_melbet_event_rows(child))
    elif isinstance(value, list):
        for child in value:
            rows.extend(_melbet_event_rows(child))
    return rows


def _normalize_player_market_name(value):
    value = unicodedata.normalize("NFKD", str(value or ""))
    value = "".join(char for char in value if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]", "", value.lower())


def _melbet_referer(base):
    return f"{base}/en/line/baseball/{MELBET_MLB_CHAMP_ID}-usa-mlb"


def _melbet_value(path, params, usable=None, timeout=(3.0, 8.0)):
    """Try the official MelBet host first, then its configured proxy.

    A syntactically valid but empty response is treated as unavailable when a
    market-specific ``usable`` predicate is supplied.
    """
    errors = []
    for base in MELBET_BASES:
        try:
            response = requests.get(
                f"{base}{path}",
                params=params,
                headers={"Referer": _melbet_referer(base), "Accept": "application/json"},
                timeout=timeout,
            )
            response.raise_for_status()
            value = response.json().get("Value", {})
            if usable is not None and not usable(value):
                raise ValueError("response contained no usable MLB markets")
            if isinstance(value, dict):
                value = dict(value)
                value["_ninth_melbet_host"] = base
            return value
        except (requests.RequestException, ValueError, TypeError, KeyError) as exc:
            errors.append(f"{base}: {exc}")
    raise requests.RequestException(" | ".join(errors) or "MelBet feeds unavailable")


def _melbet_game_params(game_id):
    return {
        "id": int(game_id), "lng": "en", "cfview": 0,
        "isSubGames": "true", "GroupEvents": "true", "countevents": 250,
        "partner": 1, "country": 87,
    }


def _melbet_game_payload(game_id, usable=None):
    return _melbet_value(MELBET_GAME_PATH, _melbet_game_params(game_id), usable=usable)


def _melbet_champ_payload():
    return _melbet_value(
        MELBET_CHAMP_PATH,
        {"sport": 5, "champ": MELBET_MLB_CHAMP_ID, "lng": "en", "partner": 1},
        usable=lambda value: bool(value.get("G")),
        timeout=(3.0, 7.0),
    )


def _parse_melbet_player_prop_groups(payload):
    """Return displayed player thresholds by normalized name; discard prices."""
    players = {}
    for group in payload.get("GE", []):
        prop = MELBET_PLAYER_PROP_GROUPS.get(int(group.get("G", 0)))
        if not prop:
            continue
        by_selection = {}
        for row in _melbet_event_rows(group.get("E", [])):
            person = row.get("PL") or {}
            if not person.get("N") or row.get("P") is None:
                continue
            name = str(person["N"]); line = float(row["P"])
            key = (_normalize_player_market_name(name), line)
            entry = by_selection.setdefault(key, {"name": name, "types": set()})
            entry["types"].add(int(row.get("T", 0)))
        for (name_key, line), entry in by_selection.items():
            # A selectable higher/lower threshold must be present on both sides.
            if len(entry["types"]) < 2:
                continue
            player = players.setdefault(name_key, {"name": entry["name"], "props": {}})
            player["props"].setdefault(prop, []).append(line)
    for player in players.values():
        player["props"] = {prop: sorted(set(lines)) for prop, lines in player["props"].items()}
    return players


def _fetch_melbet_game_player_props(game):
    def player_subgame(payload):
        linked = [*payload.get("SG", []), *payload.get("BIG", [])]
        return next((row for row in linked if "player" in str(row.get("TG", "")).lower() and row.get("CI")), None)

    main = _melbet_game_payload(game["bookmaker_game_id"], usable=lambda payload: player_subgame(payload) is not None)
    # Regular games expose linked markets through SG, while some grouped and
    # doubleheader events expose them through BIG. MelBet uses both shapes for
    # the same "Players' stats" sub-game, so inspect both collections.
    linked_games = [*main.get("SG", []), *main.get("BIG", [])]
    subgame = next((row for row in linked_games if "player" in str(row.get("TG", "")).lower() and row.get("CI")), None)
    props_payload = _melbet_game_payload(
        subgame["CI"],
        usable=lambda payload: bool(_parse_melbet_player_prop_groups(payload)),
    ) if subgame else {}
    players = _parse_melbet_player_prop_groups(props_payload)
    source_host = props_payload.get("_ninth_melbet_host") or main.get("_ninth_melbet_host") or game.get("feed_host")
    return {
        **game, "player_subgame_id": int(subgame["CI"]) if subgame else None,
        "players": players, "feed_host": source_host,
    }


def _safe_fetch_melbet_game_player_props(game):
    try:
        return _fetch_melbet_game_player_props(game)
    except (requests.RequestException, ValueError, TypeError, KeyError) as exc:
        print(f"[melbet-player-props] game {game.get('bookmaker_game_id')} unavailable: {exc}", flush=True)
        return None


def melbet_player_prop_markets(force=False):
    """Return currently displayed MLB player thresholds, never sportsbook prices."""
    now = datetime.now(timezone.utc)
    cached_at = _melbet_player_props_cache.get("updated_at")
    if not force and cached_at and now - cached_at < timedelta(seconds=60):
        return _melbet_player_props_cache
    last_attempt = _melbet_player_props_cache.get("last_attempt_at")
    if not force and _melbet_player_props_cache.get("error") and last_attempt and now - last_attempt < timedelta(minutes=1):
        return _melbet_player_props_cache
    with _melbet_player_props_lock:
        cached_at = _melbet_player_props_cache.get("updated_at")
        if not force and cached_at and now - cached_at < timedelta(seconds=60):
            return _melbet_player_props_cache
        _melbet_player_props_cache["last_attempt_at"] = now
        try:
            payload = _melbet_champ_payload()
            feed_host = payload.get("_ninth_melbet_host")
            games = [{
                "bookmaker_game_id": int(row["CI"]),
                "home_name": row["O1"], "away_name": row["O2"],
                "starts_at": datetime.fromtimestamp(int(row["S"]), timezone.utc).isoformat(),
                "game_label": row.get("TG") or None,
                "feed_host": feed_host,
            } for row in payload.get("G", []) if row.get("CI") and row.get("O1") and row.get("O2") and row.get("S")]
            previous_updated_at = _melbet_player_props_cache.get("updated_at")
            previous_by_id = {
                int(item["bookmaker_game_id"]): item
                for item in _melbet_player_props_cache.get("markets", [])
                if item.get("bookmaker_game_id")
            }
            # The line feed becomes unreliable under a larger burst because
            # each MLB game requires a second request for its player sub-game.
            with ThreadPoolExecutor(max_workers=min(3, len(games) or 1)) as pool:
                first_pass = list(pool.map(_safe_fetch_melbet_game_player_props, games))
            markets_by_id = {
                item["bookmaker_game_id"]: {
                    **item, "stale": False, "last_confirmed_at": now.isoformat(),
                }
                for item in first_pass
                if item and item.get("players")
            }
            # Keep a recently confirmed exact market through one transient
            # per-game timeout instead of making the whole builder wait for a
            # second blocking pass. The browser helper always validates the
            # exact live line again before clicking it.
            preserve_previous = (
                previous_updated_at is not None
                and now - previous_updated_at <= timedelta(minutes=5)
            )
            if preserve_previous:
                for game in games:
                    game_id = game["bookmaker_game_id"]
                    previous = previous_by_id.get(game_id)
                    if game_id not in markets_by_id and previous and previous.get("players"):
                        markets_by_id[game_id] = {**previous, "stale": True}
            markets = list(markets_by_id.values())
            sources = sorted({item.get("feed_host") for item in markets if item.get("feed_host")})
            _melbet_player_props_cache.update({"updated_at": now, "markets": markets, "sources": sources, "error": None})
        except (requests.RequestException, ValueError, TypeError, KeyError) as exc:
            _melbet_player_props_cache["error"] = str(exc)
            if not _melbet_player_props_cache.get("markets"):
                _melbet_player_props_cache["updated_at"] = now
            print(f"[melbet-player-props] current listings unavailable: {exc}", flush=True)
    return _melbet_player_props_cache


def match_melbet_player_props(home_name, away_name, starts_at, snapshot=None):
    snapshot = snapshot or melbet_player_prop_markets()
    target_teams = {normalize_slip_team(home_name), normalize_slip_team(away_name)}
    try:
        target_time = datetime.fromisoformat(str(starts_at).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    candidates = []
    for market in snapshot.get("markets", []):
        if {normalize_slip_team(market["home_name"]), normalize_slip_team(market["away_name"])} != target_teams:
            continue
        market_time = datetime.fromisoformat(market["starts_at"])
        candidates.append((abs((market_time - target_time).total_seconds()), market))
    if not candidates:
        return None
    distance, market = min(candidates, key=lambda item: item[0])
    if distance > 3 * 60 * 60:
        return None
    return {
        "available": True, "players": market["players"],
        "source": "MelBet displayed player props" + (" via proxy" if market.get("feed_host") == MELBET_PROXY_BASE else ""),
        "feed_host": market.get("feed_host"), "prices_used": False,
        "observed_at": market.get("last_confirmed_at") or (snapshot.get("updated_at").isoformat() if snapshot.get("updated_at") else None),
        "stale": bool(market.get("stale")),
        "bookmaker_game_id": market["bookmaker_game_id"],
        "player_subgame_id": market.get("player_subgame_id"),
    }


def restrict_player_props_to_available_lines(players, market):
    if not market or not market.get("players"):
        return []
    restricted = []
    for player in players or []:
        offered = market["players"].get(_normalize_player_market_name(player.get("name")))
        if not offered:
            continue
        props = []
        for projection in player.get("props", []):
            offered_lines = {float(line) for line in offered.get("props", {}).get(projection.get("prop"), [])}
            thresholds = [row for row in projection.get("thresholds", []) if float(row.get("line", -999)) in offered_lines]
            if not thresholds:
                continue
            best = max(thresholds, key=lambda row: max(float(row.get("over_probability", 0)), float(row.get("under_probability", 0))))
            side = "over" if float(best.get("over_probability", 0)) >= float(best.get("under_probability", 0)) else "under"
            props.append({
                **projection, "thresholds": thresholds, "recommended_line": float(best["line"]),
                "recommended_side": side, "recommended_probability": float(best[f"{side}_probability"]),
                "line_market": {"source": market["source"], "prices_used": False, "observed_at": market.get("observed_at")},
            })
        if props:
            value = dict(player); value["props"] = props
            value["best_projection"] = max(props, key=lambda row: row["recommended_probability"])
            restricted.append(value)
    return restricted


def _fetch_melbet_game_totals(game):
    def displayed_lines(payload):
        group = next((row for row in payload.get("GE", []) if int(row.get("G", 0)) == 17), None)
        events = _melbet_event_rows((group or {}).get("E", []))
        over = {
            float(row["P"]) for row in events
            if int(row.get("T", 0)) == 9 and row.get("P") is not None
            and 2 <= float(row["P"]) <= 25
        }
        under = {
            float(row["P"]) for row in events
            if int(row.get("T", 0)) == 10 and row.get("P") is not None
            and 2 <= float(row["P"]) <= 25
        }
        return sorted(over & under)

    payload = _melbet_game_payload(game["bookmaker_game_id"], usable=lambda value: bool(displayed_lines(value)))
    lines = displayed_lines(payload)
    # Only thresholds displayed on both sides survive. Price fields are
    # deliberately discarded before this data reaches model selection.
    return {**game, "lines": lines, "feed_host": payload.get("_ninth_melbet_host") or game.get("feed_host")}


def _safe_fetch_melbet_game_totals(game):
    try:
        return _fetch_melbet_game_totals(game)
    except (requests.RequestException, ValueError, TypeError, KeyError) as exc:
        print(f"[melbet-totals] game {game.get('bookmaker_game_id')} unavailable: {exc}", flush=True)
        return None


def record_melbet_totals_snapshots(markets, observed_at):
    """Archive exact point-in-time line grids without retaining prices."""
    global _melbet_totals_snapshot_loaded
    observed = observed_at.isoformat() if isinstance(observed_at, datetime) else str(observed_at)
    with _melbet_totals_snapshot_lock:
        if not _melbet_totals_snapshot_loaded:
            if os.path.exists(MELBET_TOTALS_SNAPSHOT_LOG):
                with open(MELBET_TOTALS_SNAPSHOT_LOG, encoding="utf-8") as handle:
                    for line in handle:
                        try:
                            saved = json.loads(line)
                            _melbet_totals_snapshot_last[int(saved["bookmaker_game_id"])] = json.dumps(
                                sorted(float(value) for value in saved.get("lines", [])),
                                separators=(",", ":"),
                            )
                        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                            continue
            _melbet_totals_snapshot_loaded = True
        rows = []
        for market in markets or []:
            lines = sorted({
                float(line) for line in market.get("lines", [])
                if 2 <= float(line) <= 25
            })
            names = f"{market.get('away_name', '')} {market.get('home_name', '')}"
            if not lines or "(runs)" in names.lower():
                continue
            event_id = int(market["bookmaker_game_id"])
            signature = json.dumps(lines, separators=(",", ":"))
            if _melbet_totals_snapshot_last.get(event_id) == signature:
                continue
            _melbet_totals_snapshot_last[event_id] = signature
            rows.append({
                "bookmaker_game_id": event_id,
                "observed_at": observed,
                "starts_at": market.get("starts_at"),
                "home_name": market.get("home_name"),
                "away_name": market.get("away_name"),
                "lines": lines,
                "feed_host": market.get("feed_host"),
                "prices_used": False,
            })
        if not rows:
            return 0
        os.makedirs(os.path.dirname(MELBET_TOTALS_SNAPSHOT_LOG), exist_ok=True)
        with open(MELBET_TOTALS_SNAPSHOT_LOG, "a", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, separators=(",", ":")) + "\n")
    return len(rows)


def melbet_totals_markets(force=False):
    """Return currently displayed full-game MLB totals, never their prices."""
    now = datetime.now(timezone.utc)
    cached_at = _melbet_totals_cache.get("updated_at")
    if not force and cached_at and now - cached_at < timedelta(minutes=2):
        return _melbet_totals_cache
    last_attempt = _melbet_totals_cache.get("last_attempt_at")
    if not force and _melbet_totals_cache.get("error") and last_attempt and now - last_attempt < timedelta(minutes=1):
        return _melbet_totals_cache
    with _melbet_totals_lock:
        cached_at = _melbet_totals_cache.get("updated_at")
        if not force and cached_at and now - cached_at < timedelta(minutes=2):
            return _melbet_totals_cache
        _melbet_totals_cache["last_attempt_at"] = now
        try:
            payload = _melbet_champ_payload()
            feed_host = payload.get("_ninth_melbet_host")
            games = []
            for row in payload.get("G", []):
                if not row.get("CI") or not row.get("O1") or not row.get("O2") or not row.get("S"):
                    continue
                if "(runs)" in f"{row.get('O1')} {row.get('O2')}".lower():
                    continue
                games.append({
                    "bookmaker_game_id": int(row["CI"]),
                    "home_name": row["O1"], "away_name": row["O2"],
                    "starts_at": datetime.fromtimestamp(int(row["S"]), timezone.utc).isoformat(),
                    "game_label": row.get("TG") or None, "feed_host": feed_host,
                })
            with ThreadPoolExecutor(max_workers=min(6, len(games) or 1)) as pool:
                fetched = list(pool.map(_safe_fetch_melbet_game_totals, games))
            # Preserve championship-discovered events even if neither host has
            # a totals market. Moneyline handoff still needs the event ID.
            markets = [item if item else {**game, "lines": []} for game, item in zip(games, fetched)]
            sources = sorted({item.get("feed_host") for item in markets if item.get("feed_host")})
            _melbet_totals_cache.update({"updated_at": now, "markets": markets, "sources": sources, "error": None})
            record_melbet_totals_snapshots(markets, now)
        except (requests.RequestException, ValueError, TypeError, KeyError) as exc:
            _melbet_totals_cache["error"] = str(exc)
            if not _melbet_totals_cache.get("markets"):
                _melbet_totals_cache["updated_at"] = now
            print(f"[melbet-totals] current lines unavailable: {exc}", flush=True)
    return _melbet_totals_cache


def match_melbet_totals(home_name, away_name, starts_at, snapshot=None):
    snapshot = snapshot or melbet_totals_markets()
    target_teams = {normalize_slip_team(home_name), normalize_slip_team(away_name)}
    try:
        target_time = datetime.fromisoformat(str(starts_at).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    candidates = []
    for market in snapshot.get("markets", []):
        teams = {normalize_slip_team(market["home_name"]), normalize_slip_team(market["away_name"])}
        if teams != target_teams:
            continue
        market_time = datetime.fromisoformat(market["starts_at"])
        candidates.append((abs((market_time - target_time).total_seconds()), market))
    if not candidates:
        return None
    distance, market = min(candidates, key=lambda item: item[0])
    if distance > 3 * 60 * 60:
        return None
    return {
        "available": bool(market["lines"]), "lines": market["lines"],
        "source": "MelBet displayed full-game totals" + (" via proxy" if market.get("feed_host") == MELBET_PROXY_BASE else ""),
        "feed_host": market.get("feed_host"), "prices_used": False,
        "observed_at": snapshot.get("updated_at").isoformat() if snapshot.get("updated_at") else None,
        "bookmaker_game_id": market["bookmaker_game_id"], "game_label": market.get("game_label"),
    }


def restrict_totals_to_available_lines(projection, market):
    result = dict(projection or {})
    result["line_market"] = market or {
        "available": False, "lines": [], "source": "MelBet displayed full-game totals",
        "prices_used": False, "observed_at": None,
    }
    result["selection_available"] = bool(market and market.get("lines"))
    if not result.get("available") or not result["selection_available"]:
        return result
    offered = {float(line) for line in market["lines"]}
    thresholds = [row for row in result.get("thresholds", []) if float(row.get("line", -999)) in offered]
    if not thresholds:
        result["selection_available"] = False
        return result
    normalized_thresholds = []
    for threshold in thresholds:
        row = dict(threshold)
        push = max(0.0, min(1.0, float(row.get("push_probability", 0) or 0)))
        resolved = 1 - push
        is_integer_line = abs(float(row.get("line", 0)) - round(float(row.get("line", 0)))) < 1e-9
        if is_integer_line and push > 0 and resolved > 1e-9:
            row.update({
                "raw_over_probability": float(row.get("over_probability", 0)),
                "raw_under_probability": float(row.get("under_probability", 0)),
                "over_probability": round(float(row.get("over_probability", 0)) / resolved, 4),
                "under_probability": round(float(row.get("under_probability", 0)) / resolved, 4),
                "probability_basis": "conditional_on_no_push",
            })
        normalized_thresholds.append(row)
    thresholds = normalized_thresholds
    candidates = []
    for row in thresholds:
        for side in ("over", "under"):
            candidates.append((float(row.get(f"{side}_probability", 0)), side, float(row["line"])))
    probability, side, line = max(candidates, key=lambda item: item[0])
    completeness = float(result.get("input_completeness", 0))
    adjusted = .5 + (probability - .5) * (.75 + .25 * completeness)
    result.update({
        "thresholds": thresholds, "recommended_line": line,
        "recommended_side": side, "recommended_probability": round(probability, 4),
        "confidence_score": round(adjusted * 100),
        "confidence_label": "High" if adjusted >= .72 else "Moderate" if adjusted >= .60 else "Low",
        "line_selection_rule": "Highest calibrated side probability among currently displayed full-game totals; integer-line chances are conditional on no push; prices excluded",
    })
    return result


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


def total_runs_projection(home_id, away_id, game_datetime, context=None):
    if not home_id or not away_id or not game_datetime:
        return {"available": False, "message": "Matchup identifiers are incomplete."}
    game_date = datetime.fromisoformat(game_datetime.replace("Z", "+00:00")).date()
    end_date = min(game_date - timedelta(days=1), datetime.now(timezone.utc).date() - timedelta(days=1))
    cache_key = end_date.isoformat()
    if cache_key not in _model_history_cache:
        # Populate the shared completed-game history once via the moneyline path.
        moneyline_projection(home_id, away_id, game_datetime, context)
    return totals_model_predict(home_id, away_id, game_date.isoformat(), _model_history_cache.get(cache_key, []), context)


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


def apply_live_total_state(projection, linescore, count=None):
    """Condition the pregame run distribution on official live game state."""
    if not projection.get("available"):
        return projection
    teams = linescore.get("teams", {})
    current_runs = int(_float(teams.get("home", {}).get("runs"))) + int(_float(teams.get("away", {}).get("runs")))
    inning = max(1, int(_float(linescore.get("currentInning"), 1)))
    half = str(linescore.get("inningState") or "Top")
    outs = max(0, min(3, int(_float((count or {}).get("outs")))))
    completed_halves = max(0.0, (inning - 1) * 2 + (1 if half.lower().startswith("bottom") else 0) + outs / 3)
    remaining_halves = max(0.0, 18 - completed_halves)
    progress = min(1.0, completed_halves / 18)
    pregame_expected = float(projection.get("expected_total_runs") or 9)
    prior_remaining = pregame_expected * remaining_halves / 18
    observed_rate = current_runs / max(1.0, completed_halves)
    pace_remaining = observed_rate * remaining_halves
    live_weight = min(.55, progress * .65)
    expected_remaining = max(0.0, (1 - live_weight) * prior_remaining + live_weight * pace_remaining)
    live_expected = current_runs + expected_remaining
    variance = max(.2, expected_remaining + .10 * expected_remaining ** 2)
    sigma = math.sqrt(variance)
    thresholds = []
    for row in projection.get("thresholds", []):
        line = float(row["line"])
        needed = math.floor(line) + 1 - current_runs
        is_integer = abs(line - round(line)) < 1e-9
        if remaining_halves <= 0:
            over_probability = .999 if current_runs > line else .001
            under_probability = .999 if current_runs < line else .001
            push_probability = .998 if is_integer and current_runs == int(line) else 0.0
        else:
            z = (needed - .5 - expected_remaining) / sigma
            over_probability = min(.999, max(.001, .5 * math.erfc(z / math.sqrt(2))))
            if is_integer:
                under_cutoff = line - current_runs - .5
                under_probability = min(.999, max(.001, .5 * (1 + math.erf((under_cutoff - expected_remaining) / (sigma * math.sqrt(2))))))
                push_probability = max(0.0, 1 - over_probability - under_probability)
            else:
                under_probability = 1 - over_probability
                push_probability = 0.0
        thresholds.append({"line": line, "over_probability": round(over_probability, 4), "under_probability": round(under_probability, 4), "push_probability": round(push_probability, 4)})
    decision_lines = set(projection.get("model", {}).get("decision_lines", (7.5, 8.5, 9.5, 10.5)))
    choices = []
    for row in thresholds:
        if row["line"] not in decision_lines:
            continue
        is_over = row["over_probability"] >= .5
        choices.append({"line": row["line"], "side": "over" if is_over else "under", "probability": row["over_probability"] if is_over else row["under_probability"]})
    recommended = max(choices, key=lambda item: item["probability"]) if choices else None
    if recommended:
        projection.update({
            "pregame_expected_total_runs": pregame_expected,
            "expected_total_runs": round(live_expected, 1),
            "prediction_interval_80": [round(max(current_runs, live_expected - 1.282 * sigma), 1), round(live_expected + 1.282 * sigma, 1)],
            "thresholds": thresholds,
            "recommended_line": recommended["line"], "recommended_side": recommended["side"],
            "recommended_probability": round(recommended["probability"], 4),
            "confidence_score": round(recommended["probability"] * 100),
            "confidence_label": "High" if recommended["probability"] >= .72 else "Moderate" if recommended["probability"] >= .60 else "Low",
            "projection_source": "live_run_state", "projection_phase": "live",
            "live_state": {"inning": inning, "half": half, "outs": outs, "runs_scored": current_runs, "remaining_halves": round(remaining_halves, 2)},
            "confidence_explanation": "Live total conditions the pregame distribution on official runs, inning and outs. This live layer is forward-audited separately from the displayed pregame Brier score.",
            "reasons": [{"feature": "live_total_state", "label": "official runs and remaining game", "direction": recommended["side"], "value": current_runs, "impact": 0}] + [reason for reason in projection.get("reasons", []) if reason.get("feature") != "live_total_state"],
        })
    return projection


def cached_context_projection(game_id):
    cached = _detail_cache.get(int(game_id))
    if not cached:
        return None
    cached_at, payload = cached
    projection = payload.get("projection", {})
    if not projection.get("available"):
        return None
    return {
        "projection": projection,
        "totals_projection": payload.get("totals_projection", {}),
        "updated_at": payload.get("context_updated_at"),
        "cached_at": cached_at.isoformat(),
        "age_seconds": max(0.0, (datetime.now(timezone.utc) - cached_at).total_seconds()),
        "status_code": payload.get("status_code", "Preview"),
    }


def enqueue_projection_enrichment(games):
    queued = []
    with _projection_enrichment_lock:
        for game in games:
            game_id = int(game["game_id"])
            snapshot = cached_context_projection(game_id)
            freshness_seconds = 8 if snapshot and snapshot.get("status_code") == "Live" else 45
            stale = snapshot is None or snapshot.get("age_seconds", freshness_seconds) >= freshness_seconds
            if game_id not in _projection_enrichment_pending and stale:
                _projection_enrichment_pending.add(game_id)
                queued.append(game_id)
    if not queued:
        return 0

    def warm():
        def load(game_id):
            try:
                game_detail(game_id, force=True)
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


def board_schedule(start_date, end_date):
    """Fetch only the official schedule fields needed by the Builder.

    MLB-StatsAPI's high-level ``schedule`` helper hydrates media, broadcasts,
    decisions and linescores. That payload is useful on the Games page but made
    a seven-day Builder slate intermittently exceed both API timeouts. The
    advanced ``get`` call is still MLB-StatsAPI, with a bounded request and a
    short stale-if-error cache so navigation never waits indefinitely.
    """
    key = f"{start_date}:{end_date}"
    now = datetime.now(timezone.utc)
    with _board_schedule_lock:
        cached = _board_schedule_cache.get(key)
        if cached and now - cached[0] < timedelta(seconds=55):
            return cached[1]
    try:
        raw = statsapi.get(
            "schedule",
            {"startDate": start_date, "endDate": end_date, "sportId": 1},
            request_kwargs={"timeout": (3.0, 6.0)},
        )
        games = []
        for day in raw.get("dates", []):
            for game in day.get("games", []):
                teams = game.get("teams", {})
                away = teams.get("away", {}).get("team", {})
                home = teams.get("home", {}).get("team", {})
                games.append({
                    "game_id": game.get("gamePk"),
                    "game_datetime": game.get("gameDate"),
                    "game_date": day.get("date"),
                    "status": game.get("status", {}).get("detailedState", "Scheduled"),
                    "away_name": away.get("name", "Away"),
                    "home_name": home.get("name", "Home"),
                    "away_id": away.get("id"),
                    "home_id": home.get("id"),
                    "away_score": teams.get("away", {}).get("score"),
                    "home_score": teams.get("home", {}).get("score"),
                    "venue_id": game.get("venue", {}).get("id"),
                    "venue_name": game.get("venue", {}).get("name"),
                })
        with _board_schedule_lock:
            _board_schedule_cache[key] = (now, games)
        return games
    except (requests.RequestException, ValueError, TypeError, KeyError):
        if cached:
            return cached[1]
        raise


def cached_baseline_projections(game):
    """Cache context-free model work separately from the short-lived board.

    Personnel enrichment intentionally clears the board every few seconds. The
    underlying team/date baseline does not change when that happens, so replaying
    the model state for every game on every poll was wasted work—especially for
    7–14 day ranges.
    """
    key = (
        int(game["game_id"]),
        int(game["home_id"]),
        int(game["away_id"]),
        str(game["game_datetime"]),
    )
    with _baseline_projection_lock:
        cached = _baseline_projection_cache.get(key)
    if cached:
        return cached
    value = (
        moneyline_projection(game.get("home_id"), game.get("away_id"), game["game_datetime"]),
        total_runs_projection(game.get("home_id"), game.get("away_id"), game["game_datetime"]),
    )
    with _baseline_projection_lock:
        _baseline_projection_cache[key] = value
    return value


def peek_baseline_projections(game):
    key = (
        int(game["game_id"]),
        int(game["home_id"]),
        int(game["away_id"]),
        str(game["game_datetime"]),
    )
    with _baseline_projection_lock:
        return _baseline_projection_cache.get(key)


def enqueue_baseline_projections(games):
    queued = []
    with _baseline_projection_lock:
        for game in games:
            game_id = int(game["game_id"])
            key = (
                game_id,
                int(game["home_id"]),
                int(game["away_id"]),
                str(game["game_datetime"]),
            )
            if game_id not in _baseline_projection_pending and key not in _baseline_projection_cache:
                _baseline_projection_pending.add(game_id)
                queued.append(game)
    if not queued:
        return 0

    def warm():
        def load(game):
            try:
                cached_baseline_projections(game)
            except Exception as exc:
                print(f"[baseline-warmup] game {game.get('game_id')} failed: {exc}", flush=True)
            finally:
                with _baseline_projection_lock:
                    _baseline_projection_pending.discard(int(game["game_id"]))
        with ThreadPoolExecutor(max_workers=min(4, len(queued))) as pool:
            list(pool.map(load, queued))
        _projection_board_cache.clear()

    threading.Thread(target=warm, name="baseline-projection-warmup", daemon=True).start()
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
    raw_games = board_schedule(first_day.isoformat(), final_day.isoformat())
    totals_market_snapshot = melbet_totals_markets()
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
    # Keep serving the last valid context-aware probability while stale games
    # refresh in the background. The next short board poll picks up the fresh
    # snapshot without flashing back to an early baseline.
    upcoming_games = []
    for game in raw_games:
        if "final" in str(game.get("status", "")).lower() or not game.get("game_datetime"):
            continue
        try:
            starts_at = datetime.fromisoformat(game["game_datetime"].replace("Z", "+00:00"))
        except (TypeError, ValueError):
            continue
        if starts_at < now - timedelta(minutes=15):
            continue
        upcoming_games.append(game)

    baselines = {}
    missing_baselines = [
        game for game in upcoming_games
        if not (context_projections.get(str(game["game_id"]), {}).get("projection")
                and context_projections.get(str(game["game_id"]), {}).get("totals_projection"))
    ]
    if missing_baselines:
        # Produce a useful first screen inside the browser's response budget,
        # then progressively merge the rest of a large range in the background.
        foreground = missing_baselines[:5]
        remainder = missing_baselines[5:]
        first = foreground.pop(0)
        baselines[str(first["game_id"])] = cached_baseline_projections(first)
        if foreground:
            with ThreadPoolExecutor(max_workers=len(foreground)) as pool:
                values = pool.map(cached_baseline_projections, foreground)
                baselines.update({str(game["game_id"]): value for game, value in zip(foreground, values)})
        baseline_pending = enqueue_baseline_projections(remainder)
    else:
        baseline_pending = 0

    for game in upcoming_games:
        cached = peek_baseline_projections(game)
        if cached:
            baselines[str(game["game_id"])] = cached

    games = []
    for game in upcoming_games:
        # Confirmed starters and lineups normally arrive close to first pitch.
        # Load the official game feed for that window so Builder probabilities
        # use the same context-aware projection shown on the matchup page.
        context_snapshot = context_projections.get(str(game["game_id"]))
        baseline_projection, baseline_totals = baselines.get(str(game["game_id"]), (None, None))
        projection = (context_snapshot or {}).get("projection") or baseline_projection
        totals_projection = (context_snapshot or {}).get("totals_projection") or baseline_totals
        if projection is None or totals_projection is None:
            continue
        totals_market = match_melbet_totals(
            game.get("home_name"), game.get("away_name"), game.get("game_datetime"), totals_market_snapshot,
        )
        totals_projection = restrict_totals_to_available_lines(totals_projection, totals_market)
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
            "totals_projection": totals_projection,
        })
    games.sort(key=lambda item: item["starts_at"])
    # Start slower official personnel/weather work only after the usable board
    # has been built, avoiding resource contention on the initial response.
    enrichment_pending = enqueue_projection_enrichment(context_candidates)
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
    try:
        with open(TOTALS_REPORT, "r", encoding="utf-8") as handle:
            totals_report = json.load(handle)
    except (OSError, json.JSONDecodeError):
        totals_report = None
    try:
        with open(MARKET_SLIP_CALIBRATION, "r", encoding="utf-8") as handle:
            market_slip_calibration = json.load(handle)
    except (OSError, json.JSONDecodeError):
        market_slip_calibration = None
    payload = {
        "generated_at": now.isoformat(), "start_date": first_day.isoformat(), "days": days,
        "games": games, "recommended_game_ids": [item["game_id"] for item in recommendation],
        "recommendation_available": len(recommendation) == 5,
        "slip_calibration": slip_calibration,
        "multiday_slip_calibrations": multiday_slip_calibrations,
        "multiday_validation_grid": multiday_validation_grid,
        "totals_model": totals_report,
        "market_slip_calibration": market_slip_calibration,
        "market_inputs": False, "refresh_seconds": 3 if enrichment_pending or baseline_pending else 15,
        "enrichment_pending": enrichment_pending + baseline_pending,
        "projection_pending": baseline_pending,
        "scheduled_games": len(upcoming_games),
        "totals_line_feed": {
            "source": "MelBet displayed full-game totals", "prices_used": False,
            "observed_at": totals_market_snapshot.get("updated_at").isoformat() if totals_market_snapshot.get("updated_at") else None,
            "listed_games": len(totals_market_snapshot.get("markets", [])),
            "error": totals_market_snapshot.get("error"),
        },
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


def locked_pregame_totals_projection(game_id, game_datetime):
    snapshot = last_pregame_snapshot(game_id, game_datetime)
    stored = (snapshot or {}).get("totals_projection")
    if not stored:
        return {"available": False, "message": "No totals forecast was archived before scheduled first pitch."}
    projection = dict(stored)
    projection.update({
        "available": True, "snapshot_at": snapshot["recorded_at"],
        "projection_source": "pregame_locked", "projection_phase": "pregame",
        "model": load_totals_bundle()["report"],
    })
    return projection


def record_projection(game_id, projection, context=None, status_code="Preview", scheduled_start=None, totals_projection=None):
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
    totals_summary = None
    totals_changed = False
    if totals_projection and totals_projection.get("available"):
        total_keys = ("expected_total_runs", "prediction_interval_80", "recommended_line", "recommended_side", "recommended_probability", "confidence_score", "confidence_label", "input_completeness", "confidence_explanation", "thresholds", "reasons", "market_inputs", "selection_available", "line_market", "line_selection_rule")
        totals_summary = {key: totals_projection.get(key) for key in total_keys}
        previous_total = _totals_projection_last.get(str(game_id))
        totals_changed = previous_total is None or previous_total.get("recommended_line") != totals_summary.get("recommended_line") or previous_total.get("recommended_side") != totals_summary.get("recommended_side") or abs(float(previous_total.get("recommended_probability", 0)) - float(totals_summary.get("recommended_probability", 0))) >= .005
    if previous is None or movement["changed"] or coverage_changed or game_state_changed or new_alerts or totals_changed:
        os.makedirs(os.path.dirname(PROJECTION_LOG), exist_ok=True)
        audit_keys = ("confidence_score", "confidence_label", "input_completeness", "confidence_explanation", "historical_tier", "market_inputs", "projection_source", "projection_phase", "game_state", "pregame_home_win_probability", "pregame_away_win_probability")
        snapshot = {"game_id": int(game_id), "recorded_at": datetime.now(timezone.utc).isoformat(), "scheduled_start": scheduled_start, "phase": "live" if status_code == "Live" else "pregame", "home_win_probability": current, "away_win_probability": projection["away_win_probability"], "reasons": projection.get("reasons", []), "context": context, "circumstance_alerts": new_alerts, "projection": {key: projection.get(key) for key in audit_keys}, "totals_projection": totals_summary}
        with open(PROJECTION_LOG, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(snapshot) + "\n")
    _projection_last[str(game_id)] = current
    if context:_projection_last_context[str(game_id)] = context
    _projection_last_completeness[str(game_id)] = coverage
    if totals_summary:
        _totals_projection_last[str(game_id)] = totals_summary
    if game_state_signature is not None:
        _projection_last_game_state[str(game_id)] = game_state_signature
    return projection


def prediction_results_page(results, target_date=None, page=1, page_size=10, updated_at=None, market="moneyline"):
    """Filter and paginate scored forecasts without changing their audit totals."""
    if market == "totals":
        results = [{**row, "correct": row["total_correct"]} for row in results if row.get("totals_eligible")]
    if target_date:
        results = [row for row in results if row.get("game_date") == target_date]
    ranked = sorted(
        results,
        key=lambda row: float(row.get("total_probability", .5)) if market == "totals" else max(float(row.get("home_win_probability", .5)), float(row.get("away_win_probability", .5))),
        reverse=True,
    )
    daily_parlays = []
    if target_date:
        for legs in range(2, min(8, len(ranked)) + 1):
            selections = ranked[:legs]
            correct_legs = sum(1 for row in selections if row["correct"])
            daily_parlays.append({
                "legs": legs, "correct_legs": correct_legs,
                "leg_accuracy": correct_legs / legs, "all_correct": correct_legs == legs,
                "game_ids": [row["game_id"] for row in selections],
            })
    page_size = max(1, min(int(page_size or 10), 50))
    total = len(results)
    total_pages = max(1, math.ceil(total / page_size))
    page = max(1, min(int(page or 1), total_pages))
    start = (page - 1) * page_size
    games = results[start:start + page_size]
    correct = sum(1 for row in results if row["correct"])
    brier = None
    if market == "totals" and results:
        brier = sum((float(row["total_probability"]) - int(row["total_correct"])) ** 2 for row in results) / len(results)
    return {
        "games": games, "evaluated": total, "correct": correct,
        "accuracy": correct / total if total else None, "date": target_date,
        "market": market, "brier_score": brier,
        "daily_parlays": daily_parlays,
        "page": page, "page_size": page_size, "total_pages": total_pages,
        "updated_at": updated_at or datetime.now(timezone.utc).isoformat(),
        "snapshot_rule": "Last archived projection at or before scheduled first pitch",
    }


PLAYER_PROP_OUTCOME_FIELDS = {
    "batter": {
        "hits": "hits", "total_bases": "totalBases", "home_runs": "homeRuns",
        "runs": "runs", "rbi": "rbi", "walks": "baseOnBalls",
        "strikeouts": "strikeOuts", "doubles": "doubles", "stolen_bases": "stolenBases",
    },
    "pitcher": {
        "strikeouts": "strikeOuts", "outs": "outs", "walks": "baseOnBalls",
        "hits_allowed": "hits", "earned_runs": "earnedRuns",
        "home_runs_allowed": "homeRuns", "pitches": "pitchesThrown",
    },
}


def load_player_prop_snapshots():
    snapshots = {}
    if not os.path.exists(PLAYER_PROP_PROJECTION_LOG):
        return snapshots
    with _player_prop_snapshot_lock:
        with open(PLAYER_PROP_PROJECTION_LOG, encoding="utf-8") as handle:
            for line in handle:
                try:
                    row = json.loads(line)
                    row["_recorded_at"] = datetime.fromisoformat(row["recorded_at"].replace("Z", "+00:00"))
                    snapshots.setdefault(int(row["game_id"]), []).append(row)
                except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                    continue
    for rows in snapshots.values():
        rows.sort(key=lambda row: row["_recorded_at"])
    return snapshots


def _player_prop_boxscore(game_id):
    game_id = int(game_id)
    if game_id not in _player_prop_boxscore_cache:
        feed = statsapi.get("game", {"gamePk": game_id})
        _player_prop_boxscore_cache[game_id] = feed.get("liveData", {}).get("boxscore", {}).get("teams", {})
    return _player_prop_boxscore_cache[game_id]


def _player_prop_actual(boxscore, selection):
    player = None
    player_key = f"ID{int(selection['player_id'])}"
    for side in ("away", "home"):
        candidate = (boxscore.get(side, {}).get("players", {}) or {}).get(player_key)
        if candidate:
            player = candidate
            break
    if not player:
        return None
    kind = selection.get("kind")
    stats = (player.get("stats") or {}).get("batting" if kind == "batter" else "pitching") or {}
    participation = stats.get("plateAppearances") if kind == "batter" else stats.get("battersFaced")
    if int(participation or 0) <= 0:
        return None
    field = PLAYER_PROP_OUTCOME_FIELDS.get(kind, {}).get(selection.get("prop"))
    if not field:
        return None
    try:
        return float(stats.get(field) or 0)
    except (TypeError, ValueError):
        return None


def player_prop_results_page(
    results, target_date=None, page=1, page_size=10, updated_at=None,
    prop_types=None,
):
    if prop_types is not None:
        wanted = {str(value).lower() for value in prop_types}
        results = [
            row for row in results
            if f"{row.get('kind')}:{row.get('prop')}".lower() in wanted
        ]
    if target_date:
        results = [row for row in results if row.get("game_date") == target_date]
    ranked = sorted(
        results,
        key=lambda row: (row.get("starts_at") or "", float(row.get("probability") or .5)),
        reverse=True,
    )
    evaluated = len(ranked)
    correct = sum(1 for row in ranked if row["correct"])
    brier = (
        sum((float(row["probability"]) - int(row["correct"])) ** 2 for row in ranked) / evaluated
        if evaluated else None
    )
    breakdown = []
    for kind, prop in sorted({
        (row.get("kind") or "player", row["prop"]) for row in ranked
    }):
        rows = [
            row for row in ranked
            if (row.get("kind") or "player") == kind and row["prop"] == prop
        ]
        prop_correct = sum(1 for row in rows if row["correct"])
        breakdown.append({
            "kind": kind, "prop": prop, "prop_type": f"{kind}:{prop}",
            "label": rows[0].get("label") or prop.replace("_", " ").title(),
            "evaluated": len(rows), "correct": prop_correct,
            "accuracy": prop_correct / len(rows),
            "brier_score": sum((float(row["probability"]) - int(row["correct"])) ** 2 for row in rows) / len(rows),
        })
    page_size = max(1, min(int(page_size or 10), 100))
    total_pages = max(1, math.ceil(evaluated / page_size))
    page = max(1, min(int(page or 1), total_pages))
    start = (page - 1) * page_size
    return {
        "games": ranked[start:start + page_size],
        "evaluated": evaluated, "correct": correct,
        "accuracy": correct / evaluated if evaluated else None,
        "brier_score": brier, "prop_breakdown": breakdown,
        "prop_types": sorted(prop_types) if prop_types is not None else None,
        "date": target_date, "market": "player_props",
        "page": page, "page_size": page_size, "total_pages": total_pages,
        "updated_at": updated_at or datetime.now(timezone.utc).isoformat(),
        "snapshot_rule": "Last archived displayed player-prop recommendation at or before scheduled first pitch",
    }


def _completed_player_prop_results(
    target_date=None, page=1, page_size=10, prop_types=None,
):
    global _player_prop_results_cache
    now = datetime.now(timezone.utc)
    if _player_prop_results_cache and now - _player_prop_results_cache[0] < timedelta(minutes=5):
        results, updated_at = _player_prop_results_cache[1], _player_prop_results_cache[0].isoformat()
    else:
        snapshots = load_player_prop_snapshots()
        results = []
        if snapshots:
            earliest = min(row["_recorded_at"].date() for rows in snapshots.values() for row in rows)
            games = statsapi.schedule(start_date=earliest.isoformat(), end_date=now.date().isoformat(), sportId=1)
            for game in games:
                game_id = int(game.get("game_id") or 0)
                if game_id not in snapshots or "final" not in str(game.get("status", "")).lower():
                    continue
                try:
                    starts_at = datetime.fromisoformat(game["game_datetime"].replace("Z", "+00:00"))
                except (KeyError, TypeError, ValueError):
                    continue
                eligible = [row for row in snapshots[game_id] if row["_recorded_at"] <= starts_at]
                if not eligible:
                    continue
                snapshot = max(eligible, key=lambda row: row["_recorded_at"])
                try:
                    boxscore = _player_prop_boxscore(game_id)
                except (requests.RequestException, ValueError, KeyError):
                    continue
                home = {"id": int(game["home_id"]), "name": game.get("home_name")}
                away = {"id": int(game["away_id"]), "name": game.get("away_name")}
                for selection in snapshot.get("selections", []):
                    actual = _player_prop_actual(boxscore, selection)
                    line = float(selection["line"])
                    if actual is None or actual == line:
                        continue
                    side = selection["side"]
                    correct = (actual > line) == (side == "over")
                    results.append({
                        **selection, "game_id": game_id,
                        "game_date": game.get("game_date") or starts_at.date().isoformat(),
                        "starts_at": game.get("game_datetime"), "snapshot_at": snapshot["recorded_at"],
                        "home": home, "away": away,
                        "home_score": int(game.get("home_score") or 0),
                        "away_score": int(game.get("away_score") or 0),
                        "actual": actual, "correct": correct,
                    })
        results.sort(key=lambda row: (row["starts_at"] or "", row["probability"]), reverse=True)
        _player_prop_results_cache = (now, results)
        updated_at = now.isoformat()
    return player_prop_results_page(
        results, target_date, page, page_size, updated_at, prop_types,
    )


def _completed_prediction_results(target_date=None, page=1, page_size=10, market="moneyline"):
    """Score archived pre-first-pitch forecasts, then filter and paginate them."""
    global _prediction_results_cache
    now = datetime.now(timezone.utc)
    if _prediction_results_cache and now - _prediction_results_cache[0] < timedelta(minutes=5):
        results, updated_at = _prediction_results_cache[1], _prediction_results_cache[0].isoformat()
    else:
        snapshots = load_projection_snapshots()
        results = []
        if snapshots:
            earliest = min(row["_recorded_at"].date() for rows in snapshots.values() for row in rows)
            games = statsapi.schedule(start_date=earliest.isoformat(), end_date=now.date().isoformat(), sportId=1)
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
                total_projection = snapshot.get("totals_projection") or {}
                total_line = total_projection.get("recommended_line")
                total_side = total_projection.get("recommended_side")
                total_probability = total_projection.get("recommended_probability")
                total_runs = int(game["home_score"]) + int(game["away_score"])
                totals_eligible = total_line is not None and total_side in ("over", "under") and total_probability is not None
                total_correct = bool((total_runs > float(total_line)) == (total_side == "over")) if totals_eligible else None
                results.append({
                    "game_id": game_id, "game_date": game.get("game_date") or starts_at.date().isoformat(),
                    "starts_at": game.get("game_datetime"), "snapshot_at": snapshot["recorded_at"],
                    "home": home, "away": away, "home_score": int(game["home_score"]), "away_score": int(game["away_score"]),
                    "home_win_probability": home_probability, "away_win_probability": float(snapshot["away_win_probability"]),
                    "projected_side": projected_side, "projected_team": (home if projected_side == "home" else away),
                    "winner_side": actual_side, "winner": (home if actual_side == "home" else away), "correct": correct,
                    "totals_eligible": totals_eligible, "total_runs": total_runs, "total_line": total_line,
                    "total_side": total_side, "total_probability": total_probability, "total_correct": total_correct,
                })
        results.sort(key=lambda row: row["starts_at"] or "", reverse=True)
        _prediction_results_cache = (now, results)
        updated_at = now.isoformat()
    return prediction_results_page(results, target_date, page, page_size, updated_at, market)


def completed_prediction_results(
    target_date=None, page=1, page_size=10, market="moneyline", prop_types=None,
):
    if market == "player_props":
        with _player_prop_results_lock:
            return _completed_player_prop_results(
                target_date, page, page_size, prop_types,
            )
    with _prediction_results_lock:
        return _completed_prediction_results(target_date, page, page_size, market)


def void_game_status(status):
    normalized = str(status or "").strip().lower()
    return "postponed" in normalized or "cancelled" in normalized or "canceled" in normalized


def match_slip_game(selection, games):
    """Match a slip leg by teams and scheduled time, including doubleheaders."""
    wanted = {normalize_slip_team(selection["team_1"]), normalize_slip_team(selection["team_2"])}
    scheduled = datetime.fromisoformat(selection["scheduled_local"])
    candidates = []
    for game in games:
        teams = {normalize_slip_team(game.get("away_name", "")), normalize_slip_team(game.get("home_name", ""))}
        if teams != wanted or not game.get("game_datetime"):
            continue
        # Once MLB identifies the originally ticketed game as postponed or
        # cancelled, do not silently move the leg to a replacement game in the
        # same series. The non-played game is terminal for slip tracking.
        if selection.get("game_id") and int(game.get("game_id") or 0) == int(selection["game_id"]) and void_game_status(game.get("status")):
            return game
        try:
            starts_utc = datetime.fromisoformat(game["game_datetime"].replace("Z", "+00:00"))
            starts_on_slip_clock = starts_utc.astimezone(timezone.utc).replace(tzinfo=None) + timedelta(hours=SLIP_TIMEZONE_OFFSET_HOURS)
            candidates.append((abs((starts_on_slip_clock - scheduled).total_seconds()), game))
        except (TypeError, ValueError):
            continue
    if not candidates:
        return None
    distance, game = min(candidates, key=lambda item: item[0])
    # A team pair alone is unsafe during a series. Eight hours accommodates
    # provider time discrepancies without crossing into the next day's game.
    return game if distance <= 8 * 60 * 60 else None


def enrich_slip(slip):
    if not slip.get("selections"):
        return slip
    dates = [datetime.fromisoformat(item["scheduled_local"]).date() for item in slip["selections"]]
    games = statsapi.schedule(start_date=(min(dates) - timedelta(days=1)).isoformat(), end_date=(max(dates) + timedelta(days=1)).isoformat(), sportId=1)
    for selection in slip["selections"]:
        game = match_slip_game(selection, games)
        if not game:
            selection.update({"game_id": None, "status": "unmatched", "away_score": None, "home_score": None, "outcome": "pending", "alerts": []})
            continue
        selection.update({"game_id": int(game["game_id"]), "status": game.get("status", "Unknown"), "away_team": game.get("away_name"), "home_team": game.get("home_name"), "away_score": game.get("away_score"), "home_score": game.get("home_score")})
        if void_game_status(game.get("status")):
            selection.update({"outcome": "void", "alerts": []})
        elif "Final" in game.get("status", ""):
            if selection.get("market") == "totals":
                final_total = int(game.get("home_score") or 0) + int(game.get("away_score") or 0)
                line, side = float(selection["total_line"]), selection["total_side"]
                selection["final_total_runs"] = final_total
                if abs(final_total - line) < 1e-9:
                    selection["outcome"] = "void"
                else:
                    selection["outcome"] = "won" if (side == "over" and final_total > line) or (side == "under" and final_total < line) else "lost"
            else:
                selected_home = normalize_slip_team(selection["selected_team"]) == normalize_slip_team(game.get("home_name", ""))
                selected_score = game.get("home_score") if selected_home else game.get("away_score")
                other_score = game.get("away_score") if selected_home else game.get("home_score")
                selection["outcome"] = "won" if selected_score > other_score else "lost"
        else:
            # Repair a leg that was previously attached to a completed game
            # from another day in the same series.
            selection["outcome"] = "pending"
            previous = selection.get("selected_probability")
            detail = game_detail(game["game_id"])
            projection = detail.get("totals_projection", {}) if selection.get("market") == "totals" else detail.get("projection", {})
            if projection.get("available"):
                if selection.get("market") == "totals":
                    threshold = next((row for row in projection.get("thresholds", []) if float(row.get("line", -1)) == float(selection["total_line"])), None)
                    if threshold is None:
                        continue
                    current = float(threshold[f"{selection['total_side']}_probability"])
                else:
                    selected_home = normalize_slip_team(selection["selected_team"]) == normalize_slip_team(game.get("home_name", ""))
                    current = projection["home_win_probability"] if selected_home else projection["away_win_probability"]
                selection["selected_probability"] = current
                selection["model_confidence"] = projection.get("confidence_score")
                selection["confidence_label"] = projection.get("confidence_label")
                alerts = []
                if current < 0.5:
                    message = f"Model now places this total side below 50% ({current:.1%})." if selection.get("market") == "totals" else f"Model now favors the opponent ({current:.1%} selected-team probability)."
                    alerts.append({"level": "warning", "message": message})
                if previous is not None and previous - current >= 0.05: alerts.append({"level": "critical", "message": f"Projection fell {(previous-current):.1%} since the prior check."})
                alerts.extend(detail.get("projection", {}).get("circumstance_alerts", []))
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


def slip_snapshot():
    """Return persisted slips without waiting on MLB reconciliation."""
    slips = load_slips()
    slips.sort(key=lambda item: item.get("placed_at_iso") or item.get("imported_at") or "", reverse=True)
    return slips


def queue_slip_refresh():
    """Reconcile active slips once in the background, deduplicating page polls."""
    global _slip_refresh_running
    with _slip_refresh_lock:
        if _slip_refresh_running:
            return False
        _slip_refresh_running = True
        _slip_refresh_state.update({"running": True, "last_started_at": datetime.now(timezone.utc).isoformat(), "last_error": None})

    def refresh():
        global _slip_refresh_running
        try:
            for item in slip_snapshot():
                completed = item.get("active") is False and all(selection.get("outcome") != "pending" for selection in item.get("selections", []))
                if completed:
                    continue
                try:
                    save_slip(enrich_slip(item))
                except Exception as exc:
                    _slip_refresh_state["last_error"] = str(exc)
                    print(f"[slips] background refresh failed for {item.get('id')}: {exc}", flush=True)
        finally:
            with _slip_refresh_lock:
                _slip_refresh_running = False
                _slip_refresh_state.update({"running": False, "last_finished_at": datetime.now(timezone.utc).isoformat()})

    threading.Thread(target=refresh, name="slip-refresh", daemon=True).start()
    return True


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
                self.send_json({
                    "status": "ok", "provider": "MLB-StatsAPI", "version": statsapi.__version__,
                    "maintenance": maintenance_status(), "projection_monitor": _projection_monitor,
                    "player_prop_monitor": _player_prop_monitor,
                })
            elif parsed.path == "/model":
                with open(MODEL_REPORT, "r", encoding="utf-8") as handle:
                    report = json.load(handle)
                try:
                    with open(TOTALS_REPORT, "r", encoding="utf-8") as handle:
                        report["totals_model"] = json.load(handle)
                except (OSError, json.JSONDecodeError):
                    report["totals_model"] = None
                try:
                    with open(PLAYER_PROPS_REPORT, "r", encoding="utf-8") as handle:
                        report["player_props_model"] = json.load(handle)
                except (OSError, json.JSONDecodeError):
                    report["player_props_model"] = None
                report["maintenance"] = maintenance_status()
                self.send_json(report)
            elif parsed.path == "/model/results":
                prop_types = None
                if "prop_types" in query:
                    prop_types = [
                        value for item in query.get("prop_types", [])
                        for value in str(item).split(",") if str(value).strip()
                    ]
                self.send_json(completed_prediction_results(
                    query.get("date", [None])[0], query.get("page", [1])[0],
                    query.get("page_size", [10])[0],
                    query.get("market", ["moneyline"])[0], prop_types,
                ))
            elif parsed.path == "/projection-board":
                start_date = query.get("start_date", [datetime.now(timezone.utc).date().isoformat()])[0]
                self.send_json(projection_board(start_date, query.get("days", [7])[0]))
            elif parsed.path == "/player-props":
                start_date = query.get("start_date", [datetime.now(timezone.utc).date().isoformat()])[0]
                refresh = str(query.get("refresh", [""])[0]).lower() in {"1", "true", "yes"}
                self.send_json(player_props_board(start_date, query.get("days", [1])[0], defer_refresh=refresh))
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
                slips = slip_snapshot()
                queue_slip_refresh()
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
                slip = save_slip(parse_pdf(payload["data"], payload.get("filename", "slip.pdf")))
                queue_slip_refresh()
                self.send_json(slip, 201)
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
            refreshed_any = False
            for game_id, status_code, error in results:
                if error:
                    next_due[game_id] = time.monotonic() + 15
                    _projection_monitor["last_error"] = f"Game {game_id}: {error}"
                    continue
                is_live = status_code == "Live"
                refreshed_any = True
                if game_id in tracked:
                    tracked[game_id]["is_live"] = is_live
                    tracked[game_id]["status"] = status_code
                next_due[game_id] = time.monotonic() + (live_seconds if is_live else pregame_seconds)
                _projection_monitor.update({"last_refresh_at": refreshed_at.isoformat(), "last_game_id": game_id, "last_error": None})
            if refreshed_any:
                # Builder requests are inexpensive cached reads, but must see
                # newly reassessed matchup projections on their next poll.
                _projection_board_cache.clear()
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
    threading.Thread(target=player_prop_archive_loop, name="player-props-archive", daemon=True).start()
    print(f"MLB Stats provider listening on {PORT}")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
