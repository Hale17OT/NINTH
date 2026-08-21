"""Small HTTP adapter around MLB-StatsAPI for the Node application."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse
from difflib import SequenceMatcher
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

# Joblib's physical-core probe shells out to Windows during the first sklearn
# prediction and can hang when that system query is unavailable. These models
# are small and requests are already parallelized at the game level, so keep
# each individual inference deterministic and single-threaded.
_MODEL_INFERENCE_THREADS = os.getenv("NINTH_MODEL_INFERENCE_THREADS", "1")
os.environ.setdefault("LOKY_MAX_CPU_COUNT", _MODEL_INFERENCE_THREADS)
os.environ.setdefault("OMP_NUM_THREADS", _MODEL_INFERENCE_THREADS)

import statsapi

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ml.artifact_store import ensure_current as ensure_runtime_release
from ml.predict import context_completeness, load_bundle, predict as model_predict
from ml.totals_predict import load_bundle as load_totals_bundle, predict as totals_model_predict
from ml.player_props_predict import (
    AUTOMATIC_RECOMMENDATION_FLOOR,
    load_bundle as load_player_props_bundle,
    predict_candidates,
    projected_lineup,
)
from ml.slips import load_slips, normalize_team as normalize_slip_team, parse_pdf, placed_at_iso, save_slip
from ml.melbet_history import (
    analyse_history as analyse_melbet_history,
    normalize_slip as normalize_melbet_history_slip,
    save_slip as save_melbet_history_slip,
    save_slips as save_melbet_history_slips,
    snapshot as melbet_history_snapshot,
)

HOST = os.getenv("MLB_STATS_HOST", "127.0.0.1")
# Container platforms inject PORT. Prefer it over the local development
# override so a stale MLB_STATS_PORT cannot make the service unreachable.
PORT = int(os.getenv("PORT") or os.getenv("MLB_STATS_PORT") or "3002")
SLIP_TIMEZONE_OFFSET_HOURS = float(os.getenv("NINTH_SLIP_TIMEZONE_OFFSET_HOURS", "3"))
_detail_cache = {}
_projection_board_cache = {}
_board_schedule_cache = {}
_board_schedule_lock = threading.Lock()


class NotFoundError(Exception):
    """Raised when an MLB entity identifier does not resolve."""
_baseline_projection_cache = {}
_baseline_projection_lock = threading.Lock()
_baseline_projection_pending = set()
_projection_enrichment_pending = set()
_projection_enrichment_lock = threading.Lock()
_summary_cache = {}
_teams_cache = None
_players_cache = None
_player_peer_cache = None
_team_detail_cache = {}
_model_history_cache = {}
_projection_last = {}
_projection_last_context = {}
_projection_last_completeness = {}
_projection_last_game_state = {}
_projection_recent_alerts = {}
_totals_projection_last = {}
_bullpen_cache = {}
_bullpen_history_cache = {"fingerprint": None, "rows": []}
_bullpen_history_lock = threading.Lock()
_recent_form_cache = {}
_pitcher_profile_cache = {}
_prediction_results_cache = None
_prediction_results_lock = threading.Lock()
_weather_cache = {}
_weather_backoff_until = 0.0
_weather_locks = {}
_weather_locks_guard = threading.Lock()
_league_rankings_cache = {}
_league_rankings_lock = threading.Lock()
_inning_distribution_cache = {}
_inning_distribution_lock = threading.Lock()
_melbet_totals_cache = {"updated_at": None, "last_attempt_at": None, "markets": [], "error": None, "consecutive_failures": 0, "retry_after": None}
_melbet_totals_lock = threading.Lock()
_melbet_totals_snapshot_lock = threading.Lock()
_melbet_totals_snapshot_last = {}
_melbet_totals_snapshot_loaded = False
_melbet_player_props_cache = {"updated_at": None, "last_attempt_at": None, "markets": [], "error": None, "consecutive_failures": 0, "retry_after": None}
_melbet_player_props_lock = threading.Lock()
_player_props_bundle = None
_player_props_bundle_mtime = None
_player_props_bundle_lock = threading.Lock()
_player_props_board_cache = {}
_player_props_refreshing = set()
_player_props_cache_lock = threading.Lock()
_player_prop_snapshot_lock = threading.Lock()
_player_prop_build_snapshot_lock = threading.Lock()
_player_prop_snapshot_last = {}
_player_prop_priced_snapshot_last = {}
_player_prop_priced_snapshot_at = {}
_player_prop_results_cache = None
_player_prop_results_lock = threading.Lock()
_player_prop_guarantee_cache = None
_player_prop_guarantee_lock = threading.Lock()
_player_prop_boxscore_cache = {}
_slip_refresh_lock = threading.Lock()
_slip_refresh_running = False
_slip_refresh_state = {"running": False, "last_started_at": None, "last_finished_at": None, "last_error": None}
_detail_locks = {}
_detail_locks_guard = threading.Lock()
_projection_monitor = {"running": False, "pregame_seconds": 300, "live_seconds": 10, "last_discovery_at": None, "last_refresh_at": None, "tracked_games": 0, "last_error": None}
_player_prop_monitor = {
    "running": False,
    "refresh_seconds": 300,
    "last_attempt_at": None,
    "last_success_at": None,
    "archived_games": 0,
    "last_error": None,
}
_maintenance_catchup_lock = threading.Lock()
_maintenance_catchup = {
    "running": False, "target_date": None, "last_started_at": None,
    "last_finished_at": None, "last_error": None, "last_result": None,
}
APP_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARTIFACT_DIR = os.getenv("NINTH_ARTIFACT_DIR", os.path.join(APP_ROOT, "ml", "artifacts"))
DATA_DIR = os.getenv("NINTH_DATA_DIR", os.path.join(APP_ROOT, "ml", "data"))
PROJECTION_LOG = os.path.join(DATA_DIR, "projection_snapshots.jsonl")
MODEL_REPORT = os.path.join(ARTIFACT_DIR, "report.json")
TOTALS_REPORT = os.path.join(os.path.dirname(MODEL_REPORT), "totals_report.json")
MARKET_SLIP_CALIBRATION = os.path.join(os.path.dirname(MODEL_REPORT), "market_slip_calibration.json")
MAINTENANCE_STATE = os.path.join(os.path.dirname(MODEL_REPORT), "maintenance_state.json")
MELBET_PRIMARY_BASE = "https://mel-bet.et"
MELBET_PROXY_BASE = "https://melbet-322491.top"
MELBET_BASES = (MELBET_PRIMARY_BASE, MELBET_PROXY_BASE)
MELBET_CHAMP_PATH = "/service-api/LineFeed/GetChampZip"
MELBET_GAME_PATH = "/service-api/LineFeed/GetGameZip"
MELBET_MLB_CHAMP_ID = 166775


def _melbet_refresh_seconds(cache=None, games=None, now=None):
    """Use a quiet cadence normally and tighten it only around first pitch."""
    now = now or datetime.now(timezone.utc)
    standard = max(60, int(os.getenv("NINTH_MELBET_REFRESH_SECONDS", "300")))
    near_start = max(30, int(os.getenv("NINTH_MELBET_NEAR_START_SECONDS", "60")))
    window = max(5, int(os.getenv("NINTH_MELBET_NEAR_START_MINUTES", "30")))
    rows = games if games is not None else (cache or {}).get("markets", [])
    for row in rows or []:
        value = row.get("starts_at") or row.get("datetime") or row.get("game_datetime")
        try:
            starts_at = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
            if starts_at.tzinfo is None:
                starts_at = starts_at.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            continue
        seconds = (starts_at - now).total_seconds()
        if -15 * 60 <= seconds <= window * 60:
            return near_start
    return standard


def _melbet_cache_fresh(cache, force=False, games=None, now=None):
    if force:
        return False
    now = now or datetime.now(timezone.utc)
    retry_after = cache.get("retry_after")
    if retry_after and now < retry_after:
        return True
    cached_at = cache.get("updated_at")
    refresh_seconds = _melbet_refresh_seconds(cache, games, now)
    cache["refresh_seconds"] = refresh_seconds
    return bool(cached_at and (now - cached_at).total_seconds() < refresh_seconds)


def _record_melbet_success(cache, now, markets, **values):
    refresh_seconds = _melbet_refresh_seconds(cache, markets, now)
    cache.update({
        "updated_at": now, "markets": markets, "error": None,
        "consecutive_failures": 0, "retry_after": None,
        "refresh_seconds": refresh_seconds, **values,
    })


def _record_melbet_failure(cache, now, error):
    failures = int(cache.get("consecutive_failures") or 0) + 1
    base = _melbet_refresh_seconds(cache, now=now)
    maximum = max(base, int(os.getenv("NINTH_MELBET_MAX_BACKOFF_SECONDS", "1800")))
    delay = min(maximum, base * (2 ** min(failures - 1, 4)))
    cache.update({
        "error": str(error), "consecutive_failures": failures,
        "retry_after": now + timedelta(seconds=delay), "refresh_seconds": delay,
    })
    if not cache.get("markets") and not cache.get("updated_at"):
        cache["updated_at"] = now
PLAYER_PROPS_REPORT = os.path.join(os.path.dirname(MODEL_REPORT), "player_props_report.json")
LIVE_PLAYER_PROPS_AUDIT = os.path.join(os.path.dirname(MODEL_REPORT), "live_player_prop_audit.json")
LIVE_PLAYER_PROP_BUILD_AUDIT = os.path.join(os.path.dirname(MODEL_REPORT), "live_player_prop_build_audit.json")
PLAYER_PROP_FORWARD_POLICY = os.path.join(os.path.dirname(MODEL_REPORT), "player_prop_forward_policy.json")
PLAYER_PROP_RERANKER_SHADOW_AUDIT = os.path.join(
    os.path.dirname(MODEL_REPORT), "player_prop_reranker_shadow_candidate.json",
)
DEPLOYMENT_SELECTION_AUDIT = os.path.join(os.path.dirname(MODEL_REPORT), "deployment_selection_audit.json")
PLAYER_PROP_PROJECTION_LOG = os.path.join(
    DATA_DIR, "player_prop_projection_snapshots.jsonl",
)
PLAYER_PROP_PRICED_BOARD_LOG = os.path.join(
    DATA_DIR, "player_prop_priced_board_snapshots.jsonl",
)
PLAYER_PROP_PRICED_BOARD_AUDIT = os.path.join(
    os.path.dirname(MODEL_REPORT), "player_prop_priced_board_audit.json",
)
PLAYER_PROP_BUILD_LOG = os.path.join(
    DATA_DIR, "player_prop_build_snapshots.jsonl",
)
PLAYER_BOXSCORES = os.path.join(
    DATA_DIR, "player_boxscores.jsonl",
)
MELBET_TOTALS_SNAPSHOT_LOG = os.path.join(
    DATA_DIR, "melbet_totals_snapshots.jsonl",
)

# MelBet exposes player selections in a linked Player's Stats sub-game. These
# group identifiers are stable baseball market identifiers. Decimal odds are
# retained only as display and selection-eligibility metadata; they are never
# passed into a prediction model or used to alter a model probability.
MELBET_PLAYER_PROP_MARKETS = {
    # Names and selection templates come from MelBet's English bet-template
    # files. ``at_least`` selections use an integer display value, while the
    # model's equivalent threshold is N - 0.5 (for example, 6 or more is over
    # 5.5). Prices are deliberately not represented here or downstream.
    2891: {"prop": "strikeouts", "kind": "pitcher", "name": "Pitchers. Total Strikeouts", "format": "over_under", "types": {3868: "over", 3869: "under"}},
    3425: {"prop": "home_runs", "kind": "batter", "name": "Player To Score Home Run", "format": "yes", "model_line": .5, "display_line": 1, "types": {4743: "over"}},
    8527: {"prop": "hits", "kind": "batter", "name": "Batters. Total Hits", "format": "over_under", "types": {8091: "over", 8092: "under"}},
    10465: {"prop": "total_bases", "kind": "batter", "name": "Batters. Total Bases Taken", "format": "over_under", "types": {13827: "over", 13828: "under"}},
    10466: {"prop": "home_runs", "kind": "batter", "name": "Batters. Total Home Runs", "format": "over_under", "types": {13829: "over", 13830: "under"}},
    10469: {"prop": "singles", "kind": "batter", "name": "Batters. Total Singles", "format": "over_under", "types": {13838: "over", 13839: "under"}},
    10710: {"prop": "outs", "kind": "pitcher", "name": "Pitchers. Total Outs", "format": "over_under", "types": {14500: "over", 14501: "under"}},
    10711: {"prop": "win", "kind": "pitcher", "name": "Pitchers. To Win", "format": "yes_no", "model_line": .5, "display_line": 1, "types": {14502: "over", 14503: "under"}},
    10712: {"prop": "walks", "kind": "pitcher", "name": "Pitchers. Total Walks Allowed", "format": "over_under", "types": {14504: "over", 14505: "under"}},
    10713: {"prop": "hits_allowed", "kind": "pitcher", "name": "Pitchers. Total Hits Allowed", "format": "over_under", "types": {14506: "over", 14507: "under"}},
    10714: {"prop": "rbi", "kind": "batter", "name": "Batters. Total RBIs", "format": "over_under", "types": {14508: "over", 14509: "under"}},
    10955: {"prop": "stolen_bases", "kind": "batter", "name": "Batters. Total Stolen Bases", "format": "over_under", "types": {15212: "over", 15213: "under"}},
    10956: {"prop": "doubles", "kind": "batter", "name": "Batters. Total Doubles", "format": "over_under", "types": {15214: "over", 15215: "under"}},
    10957: {"prop": "triples", "kind": "batter", "name": "Batters. Total Triples", "format": "over_under", "types": {15216: "over", 15217: "under"}},
    11325: {"prop": "strikeouts", "kind": "batter", "name": "Batters. Total Strikeouts Allowed", "format": "over_under", "types": {16064: "over", 16065: "under"}},
    11326: {"prop": "hits_runs_rbi", "kind": "batter", "name": "Batters. Total Hits, Runs, and RBIs", "format": "over_under", "types": {16062: "over", 16063: "under"}},
    11327: {"prop": "walks", "kind": "batter", "name": "Batters. Total Walks", "format": "over_under", "types": {16066: "over", 16067: "under"}},
    11328: {"prop": "runs", "kind": "batter", "name": "Batters. Total Runs", "format": "over_under", "types": {16068: "over", 16069: "under"}},
    11351: {"prop": "hits", "kind": "batter", "name": "Batters. Extra Total Hits", "format": "at_least", "types": {16125: "over"}},
    11352: {"prop": "total_bases", "kind": "batter", "name": "Batters. Extra Total Bases Taken", "format": "at_least", "types": {16126: "over"}},
    11353: {"prop": "home_runs", "kind": "batter", "name": "Batters. Extra Total Home Runs", "format": "at_least", "types": {16127: "over"}},
    11354: {"prop": "runs", "kind": "batter", "name": "Batters. Extra Total Runs", "format": "at_least", "types": {16128: "over"}},
    11355: {"prop": "hits_runs_rbi", "kind": "batter", "name": "Batters. Extra Total Hits, Runs, and RBIs", "format": "at_least", "types": {16129: "over"}},
    11356: {"prop": "rbi", "kind": "batter", "name": "Batters. Extra Total RBIs", "format": "at_least", "types": {16130: "over"}},
    11357: {"prop": "strikeouts", "kind": "batter", "name": "Batters. Extra Total Strikeouts Allowed", "format": "at_least", "types": {16131: "over"}},
    11358: {"prop": "strikeouts", "kind": "pitcher", "name": "Pitchers. Extra Total Strikeouts", "format": "at_least", "types": {16132: "over"}},
}
MELBET_PLAYER_PROP_GROUPS = {
    group_id: market["prop"] for group_id, market in MELBET_PLAYER_PROP_MARKETS.items()
}


def player_props_bundle():
    global _player_props_bundle, _player_props_bundle_mtime
    model_path = os.path.join(ARTIFACT_DIR, "player_props.joblib")
    model_mtime = os.stat(model_path).st_mtime_ns
    if _player_props_bundle is None or _player_props_bundle_mtime != model_mtime:
        with _player_props_bundle_lock:
            if _player_props_bundle is None or _player_props_bundle_mtime != model_mtime:
                _player_props_bundle = load_player_props_bundle()
                _player_props_bundle_mtime = model_mtime
    return _player_props_bundle


def player_prop_automatic_policy():
    """Build the automatic-card gate from immutable exact-line evidence.

    Raw model probabilities remain available for manual picks. Automatic cards
    require enough completed, pregame MelBet observations for the exact prop
    family, then shrink confidence by the observed post-selection calibration
    ratio. This prevents a sparse market from winning merely because its raw
    probability is the largest value on a slate.
    """
    minimum_samples = max(25, int(os.getenv("NINTH_PROP_AUTOMATIC_MIN_SAMPLES", "100")))
    minimum_accuracy = float(os.getenv("NINTH_PROP_AUTOMATIC_MIN_ACCURACY", ".55"))
    maximum_brier = float(os.getenv("NINTH_PROP_AUTOMATIC_MAX_BRIER", ".24"))
    maximum_calibration_gap = float(os.getenv("NINTH_PROP_AUTOMATIC_MAX_CALIBRATION_GAP", ".05"))
    try:
        with open(PLAYER_PROPS_REPORT, encoding="utf-8") as handle:
            deployed = json.load(handle).get("models", {})
    except (OSError, json.JSONDecodeError):
        deployed = {}
    try:
        with open(LIVE_PLAYER_PROPS_AUDIT, encoding="utf-8") as handle:
            audit = json.load(handle)
    except (OSError, json.JSONDecodeError):
        audit = {}
    try:
        with open(LIVE_PLAYER_PROP_BUILD_AUDIT, encoding="utf-8") as handle:
            build_audit = json.load(handle)
    except (OSError, json.JSONDecodeError):
        build_audit = {}
    try:
        with open(PLAYER_PROP_PRICED_BOARD_AUDIT, encoding="utf-8") as handle:
            priced_audit = json.load(handle)
    except (OSError, json.JSONDecodeError):
        priced_audit = {}
    try:
        with open(PLAYER_PROP_FORWARD_POLICY, encoding="utf-8") as handle:
            forward_policy = json.load(handle)
    except (OSError, json.JSONDecodeError):
        forward_policy = {}

    selected = (audit.get("automatic_one_per_game_excluding_home_runs", {}) or {}).get("0.65", {}) or {}
    audit_rows = audit.get("rows") or []

    def calibration_ratio(metrics):
        accuracy = float(metrics.get("accuracy") or 0)
        confidence = float(metrics.get("mean_confidence") or 0)
        if accuracy <= .5 or confidence <= .5:
            return .5
        return max(.5, min(1.0, (accuracy - .5) / (confidence - .5)))

    def wilson_lower_bound(wins, samples, z=1.645):
        if samples <= 0:
            return None
        rate = wins / samples
        denominator = 1 + z * z / samples
        centre = rate + z * z / (2 * samples)
        margin = z * math.sqrt((rate * (1 - rate) / samples) + z * z / (4 * samples * samples))
        return max(0.0, (centre - margin) / denominator)

    def summarize_segment(values):
        samples = len(values)
        if not samples:
            return None
        wins = sum(int(row.get("actual") or 0) for row in values)
        mean_confidence = sum(float(row.get("probability") or 0) for row in values) / samples
        accuracy = wins / samples
        brier = sum(
            (float(row.get("probability") or 0) - int(row.get("actual") or 0)) ** 2
            for row in values
        ) / samples
        metrics = {
            "samples": samples,
            "wins": wins,
            "accuracy": round(accuracy, 6),
            "mean_confidence": round(mean_confidence, 6),
            "brier": round(brier, 6),
            "lower_bound": round(wilson_lower_bound(wins, samples), 6),
        }
        metrics["confidence_multiplier"] = round(calibration_ratio(metrics), 6)
        return metrics

    exact_groups = {}
    for row in audit_rows:
        try:
            segment = f"{str(row['side']).lower()}:{float(row['line']):g}"
            key = f"{row['kind']}:{row['prop']}"
        except (KeyError, TypeError, ValueError):
            continue
        exact_groups.setdefault(key, {}).setdefault(segment, []).append(row)

    # Build Best is a post-selection system, so also audit the exact line/side
    # that wins the within-game ranking. This catches selection bias such as a
    # generally sound market whose most confident recommendations are poor.
    top_by_game = {}
    for row in audit_rows:
        if row.get("prop") == "home_runs":
            continue
        game_id = row.get("game_id")
        current = top_by_game.get(game_id)
        if current is None or float(row.get("probability") or 0) > float(current.get("probability") or 0):
            top_by_game[game_id] = row
    selected_groups = {}
    for row in top_by_game.values():
        try:
            segment = f"{str(row['side']).lower()}:{float(row['line']):g}"
            key = f"{row['kind']}:{row['prop']}"
        except (KeyError, TypeError, ValueError):
            continue
        selected_groups.setdefault(key, {}).setdefault(segment, []).append(row)

    selection_multiplier = calibration_ratio(selected)
    rules = {}
    evidence_by_prop = audit.get("by_prop", {}) or {}
    priced_by_line = priced_audit.get("by_market_side_line", {}) or {}
    for key in deployed:
        evidence = evidence_by_prop.get(key) or {}
        samples = int(evidence.get("selections") or 0)
        accuracy = float(evidence.get("accuracy") or 0)
        mean_confidence = float(evidence.get("mean_confidence") or 0)
        brier = float(evidence.get("brier") if evidence.get("brier") is not None else 1)
        wins = round(accuracy * samples)
        lower_bound = wilson_lower_bound(wins, samples) if samples else None
        quality_checks = {
            "minimum_accuracy": accuracy >= minimum_accuracy,
            "maximum_brier": brier <= maximum_brier,
            "maximum_calibration_gap": mean_confidence - accuracy <= maximum_calibration_gap + 1e-9,
            "positive_lower_bound": lower_bound is not None and lower_bound > .5,
        }
        eligible = samples >= minimum_samples and all(quality_checks.values())
        market_multiplier = calibration_ratio(evidence) if samples else .5
        if samples < minimum_samples:
            reason = f"Needs {minimum_samples} completed exact-line observations; currently {samples}."
        elif not eligible:
            failed = ", ".join(
                check.replace("_", " ") for check, passed in quality_checks.items() if not passed
            )
            reason = f"Manual only: completed exact-line evidence failed {failed}."
        else:
            reason = "Eligible from completed, accurate and calibrated exact-line evidence."
        segments = {
            segment: summarize_segment(values)
            for segment, values in (exact_groups.get(key) or {}).items()
        }
        selection_segments = {
            segment: summarize_segment(values)
            for segment, values in (selected_groups.get(key) or {}).items()
        }
        priced_segments = {}
        prefix = f"{key}:"
        for segment_key, segment_value in priced_by_line.items():
            if segment_key.startswith(prefix):
                priced_segments[segment_key[len(prefix):]] = segment_value
        rules[key] = {
            "automatic_eligible": eligible,
            "samples": samples,
            "brier": evidence.get("brier"),
            "accuracy": evidence.get("accuracy"),
            "mean_confidence": evidence.get("mean_confidence"),
            "confidence_multiplier": round(min(selection_multiplier, market_multiplier), 6),
            "segments": segments,
            "selection_segments": selection_segments,
            "priced_segments": priced_segments,
            "quality_checks": quality_checks,
            "lower_bound": round(lower_bound, 6) if lower_bound is not None else None,
            # Short-priced no-HR legs are excluded by the selected odds floor;
            # higher-priced HR overs remain available once their own line and
            # priced evidence passes the same automatic-card gates.
            "blocked_sides": [],
            "reason": reason,
        }
    return {
        "minimum_probability": AUTOMATIC_RECOMMENDATION_FLOOR,
        "maximum_per_game": 1,
        "minimum_market_samples": minimum_samples,
        "minimum_market_accuracy": minimum_accuracy,
        "maximum_market_brier": maximum_brier,
        "maximum_market_calibration_gap": maximum_calibration_gap,
        "minimum_exact_segment_samples": 30,
        "minimum_selection_segment_samples": 10,
        "minimum_priced_segment_samples": 30,
        "maximum_exact_segment_brier": .24,
        "maximum_exact_segment_calibration_gap": .05,
        "minimum_exact_segment_lower_bound": .50,
        "lower_confidence_lines_manual_only": True,
        "sportsbook_disagreement_tolerance": .15,
        "sweep_sportsbook_disagreement_tolerance": .10,
        "sweep_requires_paired_prices": True,
        "tier_a_lower_bound": .65,
        "tier_a_market_accuracy": .75,
        "tier_a_market_brier": .20,
        "tier_b_market_accuracy": .65,
        "market_side_repeat_penalty": .025,
        "cross_card_reuse_penalty": .25,
        "sweep_tier_b_maximum": 2,
        "sweep_probation_maximum": 1,
        "balanced_tier_b_maximum": 3,
        "balanced_probation_maximum": 2,
        "sweep_market_side_maximum": 2,
        "balanced_market_side_maximum": 3,
        "sweep_maximum_legs": 5,
        "minimum_build_selection_samples": 20,
        "sparse_selection_sportsbook_weight": .75,
        "sparse_selection_edge_multiplier": .5,
        "portfolio_context_reuse_penalty": .08,
        "reranker_version": forward_policy.get("reranker_version") or "within_game_v1",
        "reranker_promoted": bool(forward_policy.get("reranker_promoted", False)),
        "reranker_shadow_candidate": forward_policy.get("shadow_candidate"),
        "line_clearance_ranking_weight": float(forward_policy.get("line_clearance_ranking_weight") or .035),
        "sportsbook_disagreement_ranking_weight": float(forward_policy.get("sportsbook_disagreement_ranking_weight") or .35),
        "unpaired_price_fragility_penalty": float(forward_policy.get("unpaired_price_fragility_penalty") or .015),
        "forward_test_policy_id": forward_policy.get("policy_id"),
        "forward_test_policy_date": forward_policy.get("policy_date"),
        "forward_test_training_through": forward_policy.get("training_through"),
        "ranking_probability": "Frozen within-game reranker using calibrated probability, model line clearance, matchup readiness, fragility, sportsbook agreement and exact selection-process evidence",
        "selection_confidence_multiplier": round(selection_multiplier, 6),
        "basis": "Last immutable pregame MelBet recommendation per completed game",
        "build_selection_audit": {
            key: value for key, value in build_audit.items()
            if key != "rows"
        },
        "market_rules": rules,
    }


def deployment_selection_policy():
    """Return the prospective gate for automatic moneyline/totals cards."""
    try:
        with open(DEPLOYMENT_SELECTION_AUDIT, encoding="utf-8") as handle:
            audit = json.load(handle)
    except (OSError, json.JSONDecodeError):
        audit = {}
    moneyline = audit.get("moneyline") or {}
    totals = audit.get("totals") or {}
    return {
        "generated_at": audit.get("generated_at"),
        "snapshot_rule": audit.get("snapshot_rule") or "No completed deployment audit is available",
        "moneyline": {
            **moneyline,
            "minimum_probability": None,
            "automatic_eligible": True,
            "reason": "Every available moneyline can enter Build Best; probability ranks picks and is not a hard cutoff.",
        },
        "totals": {
            **totals,
            "rules": totals.get("rules") or {},
            "automatic_eligible_rules": int(totals.get("automatic_eligible_rules") or 0),
            "calibration": totals.get("calibration") or {},
            "reason": (
                "Production Over/Under probabilities use a chronologically validated calibration correction."
                if (totals.get("calibration") or {}).get("promoted") is True else
                "Totals remain available manually until the production calibration improves held-out Brier score."
            ),
        },
    }


def _props_game(game, bundle):
    game_id = int(game.get("game_id") or game.get("gamePk"))
    feed = statsapi.get("game", {"gamePk": game_id})
    data = feed.get("gameData", {}); teams = data.get("teams", {})
    raw_teams = feed.get("liveData", {}).get("boxscore", {}).get("teams", {})
    probable = data.get("probablePitchers", {})
    game_players = data.get("players", {})
    game_date = (data.get("datetime", {}).get("officialDate") or str(game.get("game_date", ""))[:10])
    season = int(data.get("game", {}).get("season") or game_date[:4])

    def market_names(player_id, primary_name):
        person = game_players.get("ID" + str(player_id), {})
        values = [
            primary_name, person.get("fullName"), person.get("fullFMLName"),
            " ".join(filter(None, [person.get("firstName"), person.get("lastName")])),
            " ".join(filter(None, [person.get("useName"), person.get("lastName")])),
        ]
        return list(dict.fromkeys(value for value in values if value))
    starters = {}
    for side in ("away", "home"):
        person = probable.get(side) or {}
        raw = raw_teams.get(side, {})
        if not person.get("id") and raw.get("pitchers"):
            pid = int(raw["pitchers"][0]); player = raw.get("players", {}).get("ID" + str(pid), {})
            person = player.get("person") or {"id": pid, "fullName": f"Player {pid}"}
        starters[side] = person
    lineups = {}
    lineup_statuses = {}
    for side in ("away", "home"):
        team_id = int(teams.get(side, {}).get("id") or game.get(f"{side}_id"))
        raw = raw_teams.get(side, {}); order = (raw.get("battingOrder") or [])[:9]
        if order:
            players = raw.get("players", {})
            lineups[side] = [{
                "player_id": int(pid), "lineup_slot": index + 1,
                "name": (players.get("ID" + str(pid), {}).get("person") or {}).get("fullName"),
            } for index, pid in enumerate(order)]
            lineup_statuses[side] = "confirmed"
        else:
            lineups[side] = projected_lineup(bundle, team_id, game_date, season)
            lineup_statuses[side] = "projected"
    candidates = []
    for side, opponent in (("away", "home"), ("home", "away")):
        team_id = int(teams.get(side, {}).get("id") or game.get(f"{side}_id"))
        opponent_id = int(teams.get(opponent, {}).get("id") or game.get(f"{opponent}_id"))
        starter = starters.get(side) or {}
        if starter.get("id"):
            candidate = {
                "kind": "pitcher", "player_id": int(starter["id"]),
                "name": starter.get("fullName"), "team_id": team_id, "opponent_id": opponent_id,
                "market_names": market_names(starter["id"], starter.get("fullName")),
                "home": side == "home", "lineup_slot": 0, "side": side,
                "role": "Starting pitcher", "lineup_status": "confirmed" if raw_teams.get(side, {}).get("pitchers") else "probable",
                "opponent_starter_id": (starters.get(opponent) or {}).get("id"),
                "opponent_lineup_ids": [
                    int(player["player_id"]) for player in lineups.get(opponent, [])
                ],
                "opponent_lineup_status": lineup_statuses.get(opponent, "projected"),
            }
            candidates.append(candidate)
        lineup = lineups.get(side, []); lineup_status = lineup_statuses.get(side, "projected")
        for batter in lineup:
            candidate = {
                "kind": "batter", "player_id": int(batter["player_id"]), "name": batter.get("name"),
                "market_names": market_names(batter["player_id"], batter.get("name")),
                "team_id": team_id, "opponent_id": opponent_id, "home": side == "home",
                "lineup_slot": batter.get("lineup_slot"), "opponent_starter_id": (starters.get(opponent) or {}).get("id"),
                "opponent_starter_hand": (
                    game_players.get("ID" + str((starters.get(opponent) or {}).get("id")), {})
                    .get("pitchHand", {}).get("code")
                ),
                "side": side, "role": f"Projected batting order #{batter.get('lineup_slot')}", "lineup_status": lineup_status,
            }
            candidates.append(candidate)
    return {
        "game_id": game_id, "datetime": data.get("datetime", {}).get("dateTime") or game.get("game_datetime"),
        "official_date": game_date,
        "status": data.get("status", {}).get("detailedState") or game.get("status"),
        "away": normalize_team(teams.get("away", {})), "home": normalize_team(teams.get("home", {})),
        "_candidates": candidates, "_game_date": game_date, "_season": season,
    }


def player_props_board(start_date, days=1, force=False, defer_refresh=False, force_market=False):
    days = max(1, min(7, int(days))); key = f"{start_date}:{days}"
    with _player_props_cache_lock:
        cached = _player_props_board_cache.get(key)
        if cached and (not force or defer_refresh):
            cache_ttl = max(10, min(300, int(cached[1].get("refresh_seconds", 300))))
            should_refresh = defer_refresh or time.monotonic() - cached[0] >= cache_ttl
            if should_refresh and key not in _player_props_refreshing:
                _player_props_refreshing.add(key)
                def refresh():
                    try: player_props_board(start_date, days, force=True)
                    finally:
                        with _player_props_cache_lock: _player_props_refreshing.discard(key)
                threading.Thread(target=refresh, name=f"player-props-{key}", daemon=True).start()
            if should_refresh or key in _player_props_refreshing:
                return {**cached[1], "refresh_in_progress": True, "refresh_seconds": 60}
            return cached[1]
    first = datetime.fromisoformat(start_date).date(); last = first + timedelta(days=days - 1)
    schedule_rows = statsapi.schedule(start_date=first.isoformat(), end_date=last.isoformat(), sportId=1)
    eligible = [
        row for row in schedule_rows
        if not re.search(r"Final|Cancelled|Postponed|In Progress|Live|Warmup", str(row.get("status", "")), re.I)
    ]
    bundle = player_props_bundle()
    with ThreadPoolExecutor(max_workers=min(7, max(2, len(eligible) + 1))) as pool:
        # Rebuilding projections must not force a new sportsbook request. The
        # MelBet cache owns its five-minute/near-start cadence and backoff.
        market_future = pool.submit(melbet_player_prop_markets, force_market)
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
    partial_market_games = 0
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
        if market and market.get("partial"):
            partial_market_games += 1
    refresh_seconds = _melbet_refresh_seconds(market_snapshot, games)
    if market_snapshot.get("error"):
        refresh_seconds = max(refresh_seconds, int(market_snapshot.get("refresh_seconds") or refresh_seconds))
    payload = {
        "start_date": first.isoformat(), "days": days, "updated_at": datetime.now(timezone.utc).isoformat(),
        "refresh_seconds": refresh_seconds, "method": "Market-free calibrated player-game distributions restricted by current MelBet selections; decimal odds are display/filter metadata only",
        "automatic_recommendation_policy": player_prop_automatic_policy(),
        "games": games,
        "player_prop_line_feed": {
            "source": "MelBet displayed player props and decimal odds", "prices_used": False,
            "odds_available": True, "odds_format": "decimal", "odds_model_inputs": False,
            "observed_at": market_snapshot.get("updated_at").isoformat() if market_snapshot.get("updated_at") else None,
            "listed_games": len(market_snapshot.get("markets", [])), "partial_games": partial_market_games,
            "error": market_snapshot.get("error"), "refresh_seconds": refresh_seconds,
            "consecutive_failures": int(market_snapshot.get("consecutive_failures") or 0),
        },
    }
    record_player_prop_snapshots(games)
    with _player_props_cache_lock:
        _player_props_board_cache[key] = (time.monotonic(), payload)
    return payload


def record_player_prop_snapshots(games):
    """Archive recommendations and a separate full, priced pregame board."""
    global _player_prop_results_cache
    recorded_at = datetime.now(timezone.utc).isoformat()
    rows = []
    priced_rows = []
    for game in games:
        if game.get("player_line_market", {}).get("stale"):
            continue
        selections = []
        priced_candidates = []
        for player in game.get("players", []):
            for prop in player.get("props", []):
                for threshold_row in prop.get("thresholds", []):
                    melbet = threshold_row.get("melbet_selections") or {}
                    best_prices = {}
                    for price_side in ("over", "under"):
                        available_prices = [
                            float(value["decimal_odds"])
                            for value in melbet.get(price_side, [])
                            if value.get("decimal_odds") is not None and float(value["decimal_odds"]) > 1
                        ]
                        if available_prices:
                            best_prices[price_side] = max(available_prices)
                    paired_total = sum(1 / best_prices[value] for value in ("over", "under")) \
                        if all(value in best_prices for value in ("over", "under")) else None
                    for price_side in ("over", "under"):
                        probability = threshold_row.get(f"{price_side}_probability")
                        if probability is None:
                            continue
                        for price in melbet.get(price_side, []):
                            decimal_odds = price.get("decimal_odds")
                            if decimal_odds is None or float(decimal_odds) <= 1:
                                continue
                            sportsbook_probability = (
                                (1 / best_prices[price_side]) / paired_total
                                if paired_total and price_side in best_prices else None
                            )
                            priced_candidates.append({
                                "player_id": int(player["player_id"]),
                                "player_name": player.get("name"),
                                "kind": player.get("kind"),
                                "team_id": int(player.get("team_id") or 0),
                                "opponent_id": int(player.get("opponent_id") or 0),
                                "prop": prop.get("prop"), "label": prop.get("label"),
                                "line": float(threshold_row["line"]), "side": price_side,
                                "model_probability": float(probability),
                                "decimal_odds": float(decimal_odds),
                                "opposite_decimal_odds": best_prices.get("under" if price_side == "over" else "over"),
                                "sportsbook_probability": sportsbook_probability,
                                "group_id": price.get("group_id"), "type_id": price.get("type_id"),
                                "format": price.get("format"), "display_line": price.get("display_line"),
                                "market_name": price.get("market_name"),
                                "selection_name": price.get("selection_name"),
                                "lineup_status": player.get("lineup_status"),
                                "lineup_slot": player.get("lineup_slot"),
                                "role": player.get("role"),
                                "opponent_starter_id": player.get("opponent_starter_id"),
                                "opponent_lineup_status": player.get("opponent_lineup_status"),
                                "history_games": int(player.get("history_games") or 0),
                                "recent_10_average": prop.get("recent_10_average"),
                                "recommended": (
                                    float(prop.get("recommended_line")) == float(threshold_row["line"])
                                    and prop.get("recommended_side") == price_side
                                ) if prop.get("recommended_line") is not None else False,
                            })
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
                    "lineup_status": player.get("lineup_status"),
                })
        if not selections and not priced_candidates:
            continue
        game_id = int(game["game_id"])
        if selections:
            selections.sort(key=lambda row: (row["player_id"], row["prop"], row["line"], row["side"]))
            signature = json.dumps(selections, sort_keys=True, separators=(",", ":"))
            if _player_prop_snapshot_last.get(game_id) != signature:
                _player_prop_snapshot_last[game_id] = signature
                rows.append({
                    "game_id": game_id, "recorded_at": recorded_at,
                    "scheduled_start": game.get("datetime"),
                    "game_date": game.get("official_date") or str(game.get("datetime") or "")[:10],
                    "official_date": game.get("official_date"),
                    "away": game.get("away"), "home": game.get("home"),
                    "selections": selections,
                    "snapshot_rule": "Exact displayed recommendation before first pitch",
                })
        if priced_candidates:
            priced_candidates.sort(key=lambda row: (
                row["player_id"], row["prop"], row["line"], row["side"],
                int(row.get("group_id") or 0), int(row.get("type_id") or 0),
            ))
            priced_signature = json.dumps(priced_candidates, sort_keys=True, separators=(",", ":"))
            last_priced_at = float(_player_prop_priced_snapshot_at.get(game_id) or 0)
            archive_interval = max(60, int(os.getenv("NINTH_PLAYER_PROP_PRICED_ARCHIVE_SECONDS", "900")))
            scheduled = None
            try:
                scheduled = datetime.fromisoformat(str(game.get("datetime") or "").replace("Z", "+00:00"))
                if scheduled.tzinfo is None:
                    scheduled = scheduled.replace(tzinfo=timezone.utc)
            except ValueError:
                pass
            minutes_to_start = (scheduled - datetime.now(timezone.utc)).total_seconds() / 60 if scheduled else None
            near_first_pitch = minutes_to_start is not None and 0 <= minutes_to_start <= 20
            interval_elapsed = time.monotonic() - last_priced_at >= archive_interval
            if (_player_prop_priced_snapshot_last.get(game_id) != priced_signature
                    and (not last_priced_at or interval_elapsed or near_first_pitch)):
                _player_prop_priced_snapshot_last[game_id] = priced_signature
                _player_prop_priced_snapshot_at[game_id] = time.monotonic()
                priced_rows.append({
                    "game_id": game_id, "recorded_at": recorded_at,
                    "scheduled_start": game.get("datetime"),
                    "game_date": game.get("official_date") or str(game.get("datetime") or "")[:10],
                    "official_date": game.get("official_date"),
                    "away": game.get("away"), "home": game.get("home"),
                    "candidates": priced_candidates,
                    "snapshot_rule": "Every displayed MelBet player-prop price before first pitch",
                })
    if not rows and not priced_rows:
        return
    with _player_prop_snapshot_lock:
        if rows:
            os.makedirs(os.path.dirname(PLAYER_PROP_PROJECTION_LOG), exist_ok=True)
            with open(PLAYER_PROP_PROJECTION_LOG, "a", encoding="utf-8") as handle:
                for row in rows:
                    handle.write(json.dumps(row, separators=(",", ":")) + "\n")
        if priced_rows:
            os.makedirs(os.path.dirname(PLAYER_PROP_PRICED_BOARD_LOG), exist_ok=True)
            with open(PLAYER_PROP_PRICED_BOARD_LOG, "a", encoding="utf-8") as handle:
                for row in priced_rows:
                    handle.write(json.dumps(row, separators=(",", ":")) + "\n")
    _player_prop_results_cache = None


def record_player_prop_build(payload):
    """Archive the exact recommendations selected by a Build Best action."""
    entries = payload.get("entries") if isinstance(payload, dict) else None
    if not isinstance(entries, list) or not 1 <= len(entries) <= 20:
        raise ValueError("Build snapshot entries must contain between 1 and 20 selections")

    clean_entries = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("Every build snapshot entry must be an object")
        side = str(entry.get("side") or "").lower()
        kind = str(entry.get("kind") or "").lower()
        if side not in ("over", "under") or kind not in ("batter", "pitcher"):
            raise ValueError("Build snapshot entries require a valid player kind and side")
        selection_source = str(entry.get("selection_source") or (
            "guarantee" if str(payload.get("prop_preset") or "").lower() == "guarantee" else "model"
        )).lower()
        if selection_source not in ("model", "guarantee"):
            raise ValueError("Build snapshot entries require a valid selection source")
        guarantee_samples = max(0, int(entry.get("guarantee_samples") or 0))
        guarantee_correct = max(0, int(entry.get("guarantee_correct") or 0))
        if guarantee_correct > guarantee_samples:
            raise ValueError("Guarantee correct selections cannot exceed its sample count")
        clean_entries.append({
            "game_id": int(entry["game_id"]),
            "official_date": str(entry.get("official_date") or "")[:10] or None,
            "scheduled_start": str(entry.get("scheduled_start") or "")[:40] or None,
            "player_id": int(entry["player_id"]),
            "player_name": str(entry.get("player_name") or "")[:120],
            "kind": kind,
            "team_id": int(entry.get("team_id") or 0),
            "prop": str(entry["prop"])[:80],
            "label": str(entry.get("label") or "")[:120],
            "line": float(entry["line"]),
            "side": side,
            "model_probability": float(entry["model_probability"]),
            "recommendation_probability": float(entry["recommendation_probability"]),
            "decimal_odds": float(entry["decimal_odds"]) if entry.get("decimal_odds") is not None else None,
            "market_name": str(entry.get("market_name") or "")[:160],
            "selection_name": str(entry.get("selection_name") or "")[:160],
            "audit_samples": max(0, int(entry.get("audit_samples") or 0)),
            "exact_audit_samples": max(0, int(entry.get("exact_audit_samples") or 0)),
            "selection_audit_samples": max(0, int(entry.get("selection_audit_samples") or 0)),
            "lineup_status": str(entry.get("lineup_status") or "")[:30] or None,
            "sportsbook_probability": (
                float(entry["sportsbook_probability"])
                if entry.get("sportsbook_probability") is not None else None
            ),
            "robust_probability": float(entry.get("robust_probability") or entry["recommendation_probability"]),
            "process_probability": float(entry.get("process_probability") or entry.get("robust_probability") or entry["recommendation_probability"]),
            "candidate_rank": max(1, int(entry.get("candidate_rank") or 1)),
            "within_game_rank": max(1, int(entry.get("within_game_rank") or entry.get("candidate_rank") or 1)),
            "rerank_score": float(entry["rerank_score"]) if entry.get("rerank_score") is not None else None,
            "shadow_rerank_score": float(entry["shadow_rerank_score"]) if entry.get("shadow_rerank_score") is not None else None,
            "reranker_promoted": bool(entry.get("reranker_promoted")),
            "expected_value": float(entry["expected_value"]) if entry.get("expected_value") is not None else None,
            "raw_line_clearance": float(entry["raw_line_clearance"]) if entry.get("raw_line_clearance") is not None else None,
            "normalized_line_clearance": float(entry["normalized_line_clearance"]) if entry.get("normalized_line_clearance") is not None else None,
            "fragility_penalty": max(0.0, float(entry.get("fragility_penalty") or 0)),
            "fragility_reasons": [str(value)[:80] for value in (entry.get("fragility_reasons") or [])[:12]],
            "sportsbook_disagreement": float(entry["sportsbook_disagreement"]) if entry.get("sportsbook_disagreement") is not None else None,
            "reranker_version": str(entry.get("reranker_version") or "")[:40] or None,
            "selection_action": str(entry.get("selection_action") or payload.get("selection_action") or "build_best")[:30],
            "replaced_selection": entry.get("replaced_selection") if isinstance(entry.get("replaced_selection"), dict) else None,
            "post_selection_samples": max(0, int(entry.get("post_selection_samples") or 0)),
            "selection_source": selection_source,
            "guarantee_samples": guarantee_samples,
            "guarantee_correct": guarantee_correct,
            "guarantee_accuracy": float(entry["guarantee_accuracy"]) if entry.get("guarantee_accuracy") is not None else None,
            "guarantee_wilson_lower": float(entry["guarantee_wilson_lower"]) if entry.get("guarantee_wilson_lower") is not None else None,
            "guarantee_evidence": str(entry.get("guarantee_evidence") or "")[:30] or None,
            "guarantee_score": float(entry["guarantee_score"]) if entry.get("guarantee_score") is not None else None,
            "guarantee_robust_floor": float(entry["guarantee_robust_floor"]) if entry.get("guarantee_robust_floor") is not None else None,
        })
    if any(
        not 0 <= row["model_probability"] <= 1
        or not 0 <= row["recommendation_probability"] <= 1
        or not 0 <= row["robust_probability"] <= 1
        or not 0 <= row["process_probability"] <= 1
        or (row["sportsbook_probability"] is not None and not 0 <= row["sportsbook_probability"] <= 1)
        or (row["guarantee_accuracy"] is not None and not 0 <= row["guarantee_accuracy"] <= 1)
        or (row["guarantee_wilson_lower"] is not None and not 0 <= row["guarantee_wilson_lower"] <= 1)
        or (row["guarantee_score"] is not None and not 0 <= row["guarantee_score"] <= 1)
        or (row["guarantee_robust_floor"] is not None and not 0 <= row["guarantee_robust_floor"] <= 1)
        for row in clean_entries
    ):
        raise ValueError("Build snapshot probabilities must be between zero and one")

    record = {
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "start_date": str(payload.get("start_date") or "")[:10],
        "days": max(1, min(7, int(payload.get("days") or 1))),
        "target_legs": max(1, min(20, int(payload.get("target_legs") or len(clean_entries)))),
        "build_style": str(payload.get("build_style") or "balanced")[:20],
        "build_side": str(payload.get("build_side") or "both")[:10],
        "minimum_odds": str(payload.get("minimum_odds") or "all")[:20],
        "recommendation_cutoff": str(payload.get("recommendation_cutoff") or "0.65")[:20],
        "portfolio_mode": str(payload.get("portfolio_mode") or "best")[:20],
        "prop_preset": str(payload.get("prop_preset") or "included")[:20],
        "guarantee_robust_floor": (
            float(payload["guarantee_robust_floor"])
            if payload.get("guarantee_robust_floor") is not None
            else .6 if str(payload.get("prop_preset") or "").lower() == "guarantee" else None
        ),
        "rotation_depth": max(0, int(payload.get("rotation_depth") or 0)),
        "selection_action": str(payload.get("selection_action") or "build_best")[:30],
        "shadow_test": bool(payload.get("shadow_test")),
        "forward_test_policy_id": str((payload.get("policy") or {}).get("forward_test_policy_id") or "")[:120] or None,
        "decisions": [value for value in (payload.get("decisions") or [])[:20] if isinstance(value, dict)],
        "selected_prop_types": [str(value)[:80] for value in (payload.get("selected_prop_types") or [])[:40]],
        "selected_prop_sides": {
            str(key)[:80]: str(value).lower()[:10]
            for key, value in (payload.get("selected_prop_sides") or {}).items()
            if str(value).lower() in ("both", "over", "under")
        } if isinstance(payload.get("selected_prop_sides"), dict) else {},
        "policy": payload.get("policy") if isinstance(payload.get("policy"), dict) else {},
        "entries": clean_entries,
        "snapshot_rule": "Exact Build Best selections before first pitch",
    }
    if record["guarantee_robust_floor"] is not None and not 0 <= record["guarantee_robust_floor"] <= 1:
        raise ValueError("Guarantee robust floor must be between zero and one")
    with _player_prop_build_snapshot_lock:
        os.makedirs(os.path.dirname(PLAYER_PROP_BUILD_LOG), exist_ok=True)
        with open(PLAYER_PROP_BUILD_LOG, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, separators=(",", ":")) + "\n")
    return {"ok": True, "recorded_at": record["recorded_at"], "entries": len(clean_entries)}


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
    interval = max(60, int(os.getenv("NINTH_PLAYER_PROP_REFRESH_SECONDS", "300")))
    _player_prop_monitor.update({"running": True, "refresh_seconds": interval})
    while True:
        started = time.monotonic()
        try:
            today, payload = refresh_player_prop_archive()
            interval = max(60, int(payload.get("refresh_seconds") or interval))
            _player_prop_monitor["refresh_seconds"] = interval
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


def runtime_release_status():
    try:
        with open(os.path.join(ARTIFACT_DIR, ".release.json"), encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {"release_id": None, "source": "local-artifacts"}


def missed_nightly_settlement_date(now=None):
    """Return the missed settlement date after tonight's maintenance window."""
    now = (now or datetime.now().astimezone()).astimezone()
    hour = max(0, min(23, int(os.getenv("NINTH_MAINTENANCE_HOUR", "11"))))
    minute = max(0, min(59, int(os.getenv("NINTH_MAINTENANCE_MINUTE", "15"))))
    scheduled = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if now < scheduled:
        return None
    return (now.date() - timedelta(days=1)).isoformat()


def lightweight_maintenance_catchup_due(now=None):
    if os.getenv("NINTH_MAINTENANCE_CATCHUP_ENABLED", "1").lower() in ("0", "false", "no"):
        return None
    target = missed_nightly_settlement_date(now)
    if not target:
        return None
    try:
        with open(PLAYER_PROP_RERANKER_SHADOW_AUDIT, encoding="utf-8") as handle:
            settled_through = str(json.load(handle).get("through") or "")[:10]
    except (OSError, json.JSONDecodeError):
        settled_through = ""
    state_through = str(maintenance_status().get("last_sync_date") or "")[:10]
    return target if min(settled_through, state_through) < target else None


def queue_lightweight_maintenance_catchup(now=None):
    """Resume one genuinely missed nightly maintenance cycle in the background."""
    target = lightweight_maintenance_catchup_due(now)
    if not target:
        return False
    with _maintenance_catchup_lock:
        completed_target = (
            _maintenance_catchup.get("target_date") == target
            and (_maintenance_catchup.get("last_result") or {}).get("status")
            not in (None, "settlement_incomplete", "training_failed")
        )
        if _maintenance_catchup["running"] or completed_target:
            return False
        _maintenance_catchup.update({
            "running": True, "target_date": target,
            "last_started_at": datetime.now(timezone.utc).isoformat(),
            "last_finished_at": None, "last_error": None, "last_result": None,
        })

    def catch_up():
        global _prediction_results_cache, _player_prop_results_cache, _player_prop_guarantee_cache
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        try:
            result = subprocess.run(
                [
                    sys.executable, "-m", "ml.maintenance", "--once",
                    "--through", target,
                ],
                cwd=root, capture_output=True, text=True,
                timeout=2 * 60 * 60, check=True,
            )
            payload = json.loads((result.stdout or "{}").strip().splitlines()[-1])
            if payload.get("status") == "settlement_incomplete":
                raise RuntimeError(
                    f"Settlement is incomplete through {target}; deferred games remain."
                )
            _prediction_results_cache = None
            _player_prop_results_cache = None
            _player_prop_guarantee_cache = None
            _projection_board_cache.clear()
            _maintenance_catchup["last_result"] = payload
            print(f"[model-maintenance] catch-up completed through {target}", flush=True)
        except Exception as exc:
            _maintenance_catchup["last_error"] = str(exc)
            print(f"[model-maintenance] lightweight catch-up failed: {exc}", flush=True)
        finally:
            _maintenance_catchup.update({
                "running": False,
                "last_finished_at": datetime.now(timezone.utc).isoformat(),
            })

    threading.Thread(target=catch_up, name="model-maintenance-catchup", daemon=True).start()
    return True


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


def cached_game_detail(game_id, allow_stale=False):
    cached = _detail_cache.get(int(game_id))
    if not cached:
        return None
    cached_at, payload = cached
    state = payload.get("status_code")
    ttl = 8 if state == "Live" else 3600 if state == "Final" else 45
    if allow_stale or (datetime.now(timezone.utc) - cached_at).total_seconds() < ttl:
        return payload
    return None


def pending_game_detail(game_id):
    """Return a usable shell while one background enrichment owns the lock."""
    summary = game_summary(game_id)
    status = str(summary.get("status") or "Unknown")
    status_lower = status.lower()
    status_code = (
        "Final" if "final" in status_lower or "completed" in status_lower else
        "Live" if "live" in status_lower or "progress" in status_lower else
        "Preview"
    )
    return {
        **summary,
        "status_code": status_code,
        "partial": True,
        "context_updated_at": None,
        "projection_refresh_seconds": 10 if status_code == "Live" else max(60, int(os.getenv("NINTH_PREGAME_REFRESH_SECONDS", "300"))),
        "projection": {"available": False, "message": "The matchup projection is calculating in the background."},
        "totals_projection": {"available": False, "selection_available": False, "message": "The totals projection is calculating in the background."},
        "model_context": {
            "weather": {"temperature": None, "wind_speed": None, "condition": "Weather is refreshing", "source": "Pending", "available": False},
        },
        "team_stats": {}, "probable_pitchers": {}, "pitching_matchup": {}, "recent_form": {},
        "linescore": {}, "plays": [], "pitches": [], "live_stats": None,
    }


def game_detail(game_id, force=False):
    game_id = int(game_id)
    if not force:
        cached = cached_game_detail(game_id)
        if cached:
            return cached
    lock = detail_lock(game_id)
    acquired = lock.acquire(blocking=False)
    if not force:
        stale = cached_game_detail(game_id, allow_stale=True)
        if acquired:
            def refresh_uncached_detail():
                try:
                    _game_detail(game_id, bypass_cache=True)
                except Exception as exc:
                    print(f"[matchup-enrichment] game {game_id} failed: {exc}", flush=True)
                finally:
                    lock.release()
            threading.Thread(
                target=refresh_uncached_detail,
                name=f"matchup-enrichment-{game_id}",
                daemon=True,
            ).start()
        return stale or pending_game_detail(game_id)
    if not acquired:
        cached = cached_game_detail(game_id, allow_stale=True)
        if cached:
            return cached
        raise RuntimeError("Game projection refresh is already in progress")
    try:
        return _game_detail(game_id, bypass_cache=force)
    finally:
        lock.release()


def _game_detail(game_id, bypass_cache=False):
    game_id = int(game_id)
    cached = _detail_cache.get(game_id)
    if cached and not bypass_cache:
        cached_at, cached_payload = cached
        state = cached_payload.get("status_code")
        ttl = 8 if state == "Live" else 3600 if state == "Final" else 45
        if (datetime.now(timezone.utc) - cached_at).total_seconds() < ttl:
            return cached_payload
    if bypass_cache or game_id not in _detail_cache or not cached_game_detail(game_id):
        feed = statsapi.get("game", {"gamePk": game_id})
        data = feed.get("gameData", {})
        if not data.get("teams", {}).get("away") or not data.get("teams", {}).get("home"):
            raise NotFoundError("Game not found")
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
        status_code = status_data.get("abstractGameState", "Preview")
        with ThreadPoolExecutor(max_workers=7) as pool:
            away_pitcher = pool.submit(
                pitcher_profile, probable.get("away"), game_time, game_id,
            )
            home_pitcher = pool.submit(
                pitcher_profile, probable.get("home"), game_time, game_id,
            )
            away_recent = pool.submit(recent_form, team_ids[0], game_time, game_id)
            home_recent = pool.submit(recent_form, team_ids[1], game_time, game_id)
            bullpen_future = pool.submit(
                bullpen_performance, team_ids, game_time, game_id,
            )
            totals_market_future = (
                None if status_code == "Final" else pool.submit(
                    match_melbet_totals,
                    teams.get("home", {}).get("name"), teams.get("away", {}).get("name"), game_time,
                )
            )
            league_context_future = pool.submit(
                matchup_league_context, team_ids, game_time, game_id,
            )
            pitcher_profiles = {"away": away_pitcher.result(), "home": home_pitcher.result()}
            recent_results = [away_recent.result(), home_recent.result()]
            bullpen_results = bullpen_future.result()
            totals_market = totals_market_future.result() if totals_market_future else None
            league_context = league_context_future.result()
        pitching_matchup = {}
        for side, team_id in (("away", team_ids[0]), ("home", team_ids[1])):
            starter = pitcher_profiles.get(side) or {}
            pitching_matchup[side] = {
                **(bullpen_results.get(int(team_id)) or {}),
                "starter_id": starter.get("id"),
                "starter_name": starter.get("name"),
                "starter_runs_per_start": starter.get("runs_per_start"),
                "starter_earned_runs_per_start": starter.get("earned_runs_per_start"),
                "starter_starts": starter.get("starts_before_matchup", 0),
            }
        context = live_context(feed, pitcher_profiles, team_ids, game_time, game_id)
        if status_code == "Final":
            locked_snapshot = last_pregame_snapshot(game_id, game_time)
            projection = locked_pregame_projection(game_id, game_time, locked_snapshot)
            totals_projection = locked_pregame_totals_projection(game_id, game_time, locked_snapshot)
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
            "projection_refresh_seconds": 10 if status_code == "Live" else 0 if status_code == "Final" else max(60, int(os.getenv("NINTH_PREGAME_REFRESH_SECONDS", "300"))),
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
            "pitching_matchup": pitching_matchup,
            "league_context": league_context,
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
    if team is None:
        raise NotFoundError("Team not found")
    today = datetime.now(timezone.utc).date()
    season = today.year
    with ThreadPoolExecutor(max_workers=5) as pool:
        stats_future = pool.submit(statsapi.get, "team_stats", {
            "teamId": team_id, "stats": "season", "group": "hitting,pitching", "season": season,
        })
        roster_future = pool.submit(statsapi.get, "team_roster", {
            "teamId": team_id,
            "rosterType": "active",
            "season": season,
            "hydrate": f"person(stats(group=[hitting,pitching],type=[season],season={season}))",
        })
        schedule_future = pool.submit(team_season_schedule, team_id, season)
        rankings_future = pool.submit(matchup_league_rankings, season, today.isoformat())
        innings_future = pool.submit(team_inning_distribution, team_id, season, today.isoformat())

        raw_stats = stats_future.result()
        roster = roster_future.result().get("roster", [])
        try:
            schedule = schedule_future.result()
        except Exception:
            schedule = []
        try:
            rankings = rankings_future.result().get(team_id, {})
        except Exception:
            rankings = {}
        try:
            inning_distribution = innings_future.result()
        except Exception:
            inning_distribution = {"available": False, "sample_games": 0}
    stat_groups = {}
    for group in raw_stats.get("stats", []):
        split = group.get("splits", [])
        stat_groups[group.get("group", {}).get("displayName")] = split[0].get("stat", {}) if split else {}
    recent = [game for game in schedule if game.get("is_final")][-10:]
    result = {
        "team": team,
        "season": season,
        "through": today.isoformat(),
        "stats": stat_groups,
        "roster": roster,
        "recent": recent,
        "schedule": schedule,
        "league_rankings": rankings.get("rankings") or [],
        "league_team_count": max((row.get("teams", 0) for row in rankings.get("rankings") or []), default=0),
        "inning_distribution": inning_distribution,
    }
    _team_detail_cache[team_id] = (datetime.now(timezone.utc), result)
    return result


def normalize_team_schedule(payload, team_id):
    """Reduce a season schedule to complete, linkable team-game rows."""
    output = []
    for date_row in (payload or {}).get("dates", []) or []:
        for game in date_row.get("games", []) or []:
            # Keep the team history linkable inside the MLB entity graph.  The
            # schedule feed can also contain spring and international
            # exhibitions whose opponents are not MLB team-detail entities.
            if game.get("gameType") not in {"R", "F", "D", "L", "W"}:
                continue
            teams = game.get("teams") or {}
            away = teams.get("away") or {}
            home = teams.get("home") or {}
            away_team = away.get("team") or {}
            home_team = home.get("team") or {}
            is_home = int(home_team.get("id") or 0) == int(team_id)
            club, opponent = (home, away) if is_home else (away, home)
            club_team, opponent_team = club.get("team") or {}, opponent.get("team") or {}
            status = game.get("status") or {}
            detailed_status = status.get("detailedState") or status.get("abstractGameState") or "Scheduled"
            is_disrupted = bool(re.search(r"postponed|cancelled|suspended", detailed_status, re.IGNORECASE))
            is_final = not is_disrupted and (
                status.get("abstractGameState") == "Final" or detailed_status in ("Final", "Game Over")
            )
            team_score = club.get("score") if is_final else None
            opponent_score = opponent.get("score") if is_final else None
            result = None
            if is_final and team_score is not None and opponent_score is not None:
                result = "W" if int(team_score) > int(opponent_score) else "L" if int(team_score) < int(opponent_score) else "T"
            output.append({
                "game_id": int(game.get("gamePk") or 0),
                "date": str(date_row.get("date") or str(game.get("gameDate") or "")[:10]),
                "datetime": game.get("gameDate"),
                "game_type": game.get("gameType"),
                "status": detailed_status,
                "status_code": status.get("statusCode"),
                "is_final": is_final,
                "is_home": is_home,
                "team_id": int(club_team.get("id") or team_id),
                "team_name": club_team.get("name"),
                "opponent_id": int(opponent_team.get("id") or 0),
                "opponent": opponent_team.get("name") or "Unknown opponent",
                "team_score": team_score,
                "opponent_score": opponent_score,
                "result": result,
                "venue_id": int((game.get("venue") or {}).get("id") or 0) or None,
                "venue": (game.get("venue") or {}).get("name"),
                "series": game.get("seriesDescription"),
                "game_number": int(game.get("gameNumber") or 1),
                "doubleheader": game.get("doubleHeader"),
                "team_starter_id": int((club.get("probablePitcher") or {}).get("id") or 0) or None,
                "team_starter": (club.get("probablePitcher") or {}).get("fullName"),
                "opponent_starter_id": int((opponent.get("probablePitcher") or {}).get("id") or 0) or None,
                "opponent_starter": (opponent.get("probablePitcher") or {}).get("fullName"),
            })
    return sorted(output, key=lambda row: (row.get("datetime") or row.get("date") or "", row["game_id"]))


def team_season_schedule(team_id, season):
    response = requests.get(
        "https://statsapi.mlb.com/api/v1/schedule",
        params={
            "sportId": 1,
            "teamId": int(team_id),
            "season": int(season),
            "hydrate": "probablePitcher",
        },
        timeout=20,
    )
    response.raise_for_status()
    return normalize_team_schedule(response.json(), team_id)


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


def _innings_pitched(value):
    """Convert baseball innings notation (for example, 123.2) to decimal innings."""
    text = str(value or "0")
    whole, _, fraction = text.partition(".")
    outs = int(fraction[:1]) if fraction[:1].isdigit() else 0
    return max(0.0, _float(whole) + min(2, outs) / 3.0)


def _metric_display(value, style):
    if value is None or not math.isfinite(float(value)):
        return "—"
    value = float(value)
    if style == "rate":
        return f"{value:.1f}%"
    if style == "ops":
        return f"{value:.3f}".lstrip("0")
    return f"{value:.2f}"


def _rank_team_metric(profiles, key, higher_is_better):
    available = [
        (team_id, float(profile[key]))
        for team_id, profile in profiles.items()
        if profile.get(key) is not None and math.isfinite(float(profile[key]))
    ]
    available.sort(key=lambda item: item[1], reverse=higher_is_better)
    ranks = {}
    previous = None
    previous_rank = 0
    for index, (team_id, value) in enumerate(available, 1):
        if previous is None or not math.isclose(value, previous, rel_tol=1e-9, abs_tol=1e-9):
            previous_rank = index
            previous = value
        ranks[team_id] = previous_rank
    return ranks, len(available)


def build_team_league_rankings(hitting_splits, pitching_splits):
    """Create comparable MLB ranks from the official all-team season splits."""
    profiles = {}
    for split in hitting_splits or []:
        team_id = int((split.get("team") or {}).get("id") or 0)
        if not team_id:
            continue
        stat = split.get("stat") or {}
        games = max(1.0, _float(stat.get("gamesPlayed"), 1))
        plate_appearances = max(1.0, _float(stat.get("plateAppearances"), 1))
        average = _float(stat.get("avg"))
        slugging = _float(stat.get("slg"))
        profiles.setdefault(team_id, {}).update({
            "team_id": team_id,
            "team_name": (split.get("team") or {}).get("name"),
            "runs_per_game": _float(stat.get("runs")) / games,
            "batting_average": average,
            "on_base_percentage": _float(stat.get("obp")),
            "slugging_percentage": slugging,
            "ops": _float(stat.get("ops")),
            "isolated_power": slugging - average,
            "home_runs_per_game": _float(stat.get("homeRuns")) / games,
            "hitter_k_rate": 100 * _float(stat.get("strikeOuts")) / plate_appearances,
            "walk_rate": 100 * _float(stat.get("baseOnBalls")) / plate_appearances,
        })
    for split in pitching_splits or []:
        team_id = int((split.get("team") or {}).get("id") or 0)
        if not team_id:
            continue
        stat = split.get("stat") or {}
        games = max(1.0, _float(stat.get("gamesPlayed"), 1))
        innings = max(1 / 3, _innings_pitched(stat.get("inningsPitched")))
        batters_faced = max(1.0, _float(stat.get("battersFaced"), 1))
        profiles.setdefault(team_id, {}).update({
            "team_id": team_id,
            "team_name": (split.get("team") or {}).get("name"),
            "staff_era": _float(stat.get("era")),
            "staff_whip": _float(stat.get("whip")),
            "pitcher_k9": _float(stat.get("strikeoutsPer9Inn")) or 9 * _float(stat.get("strikeOuts")) / innings,
            "pitcher_k_rate": 100 * _float(stat.get("strikeOuts")) / batters_faced,
            "pitcher_walk_rate": 100 * _float(stat.get("baseOnBalls")) / batters_faced,
            "home_runs_allowed_per_9": 9 * _float(stat.get("homeRuns")) / innings,
            "runs_allowed_per_game": _float(stat.get("runs")) / games,
        })

    definitions = [
        ("runs_per_game", "Runs per game", "OFFENSE", True, "number"),
        ("batting_average", "Batting average", "OFFENSE", True, "ops"),
        ("on_base_percentage", "On-base percentage", "OFFENSE", True, "ops"),
        ("slugging_percentage", "Slugging percentage", "OFFENSE", True, "ops"),
        ("ops", "OPS", "OFFENSE", True, "ops"),
        ("isolated_power", "Isolated power", "OFFENSE", True, "ops"),
        ("home_runs_per_game", "Home runs per game", "OFFENSE", True, "number"),
        ("hitter_k_rate", "Hitter K rate", "OFFENSE", False, "rate"),
        ("walk_rate", "Walk rate", "OFFENSE", True, "rate"),
        ("staff_era", "Staff ERA", "RUN PREVENTION", False, "number"),
        ("staff_whip", "Staff WHIP", "RUN PREVENTION", False, "number"),
        ("pitcher_k9", "Pitcher K / 9", "RUN PREVENTION", True, "number"),
        ("pitcher_k_rate", "Pitcher K rate", "RUN PREVENTION", True, "rate"),
        ("pitcher_walk_rate", "Pitcher walk rate", "RUN PREVENTION", False, "rate"),
        ("home_runs_allowed_per_9", "Home runs allowed / 9", "RUN PREVENTION", False, "number"),
        ("runs_allowed_per_game", "Runs allowed / game", "RUN PREVENTION", False, "number"),
    ]
    rank_maps = {
        key: _rank_team_metric(profiles, key, higher)
        for key, _, _, higher, _ in definitions
    }
    output = {}
    for team_id, profile in profiles.items():
        rows = []
        for key, label, group, higher, style in definitions:
            value = profile.get(key)
            rank, total = rank_maps[key]
            if value is None or team_id not in rank:
                continue
            percentile = 100 if total <= 1 else 100 * (total - rank[team_id]) / (total - 1)
            rows.append({
                "key": key,
                "label": label,
                "group": group,
                "value": round(float(value), 4),
                "display": _metric_display(value, style),
                "rank": rank[team_id],
                "teams": total,
                "percentile": round(percentile, 1),
                "higher_is_better": higher,
            })
        output[team_id] = {
            "team_id": team_id,
            "team_name": profile.get("team_name"),
            "rankings": rows,
        }
    return output


def summarize_inning_distribution(schedule_payload, team_id, excluded_game_id=None):
    """Aggregate each inning's run contribution per completed team game."""
    scored = [0.0] * 10
    allowed = [0.0] * 10
    scored_games = [0] * 10
    allowed_games = [0] * 10
    games = 0
    for date_row in (schedule_payload or {}).get("dates", []) or []:
        for game in date_row.get("games", []) or []:
            if excluded_game_id and int(game.get("gamePk") or 0) == int(excluded_game_id):
                continue
            if (game.get("status") or {}).get("abstractGameState") != "Final":
                continue
            teams = game.get("teams") or {}
            away_id = int((((teams.get("away") or {}).get("team") or {}).get("id")) or 0)
            home_id = int((((teams.get("home") or {}).get("team") or {}).get("id")) or 0)
            if int(team_id) == away_id:
                side, opponent = "away", "home"
            elif int(team_id) == home_id:
                side, opponent = "home", "away"
            else:
                continue
            innings = (game.get("linescore") or {}).get("innings") or []
            if not innings:
                continue
            game_scored = [0.0] * 10
            game_allowed = [0.0] * 10
            games += 1
            for inning in innings:
                inning_number = max(1, int(inning.get("num") or 1))
                index = min(9, inning_number - 1)
                game_scored[index] += _float((inning.get(side) or {}).get("runs"))
                game_allowed[index] += _float((inning.get(opponent) or {}).get("runs"))
            for index in range(10):
                scored[index] += game_scored[index]
                allowed[index] += game_allowed[index]
                if game_scored[index] > 0:
                    scored_games[index] += 1
                if game_allowed[index] > 0:
                    allowed_games[index] += 1

    labels = [str(inning) for inning in range(1, 10)] + ["10+"]
    if not games:
        return {
            "available": False,
            "sample_games": 0,
            "labels": labels,
            "scored_per_game": [],
            "allowed_per_game": [],
            "phases": [],
        }
    scored_per_game = [round(value / games, 3) for value in scored]
    allowed_per_game = [round(value / games, 3) for value in allowed]
    total_scored = sum(scored)
    total_allowed = sum(allowed)
    phase_definitions = [
        ("EARLY", [0, 1, 2]),
        ("MIDDLE", [3, 4, 5]),
        ("LATE", [6, 7, 8]),
        ("EXTRAS", [9]),
    ]
    phases = []
    for label, indexes in phase_definitions:
        phase_scored = sum(scored[index] for index in indexes)
        phase_allowed = sum(allowed[index] for index in indexes)
        phases.append({
            "label": label,
            "innings": "10+" if label == "EXTRAS" else f"{indexes[0] + 1}–{indexes[-1] + 1}",
            "scored_per_game": round(phase_scored / games, 2),
            "allowed_per_game": round(phase_allowed / games, 2),
            "scored_share": round(100 * phase_scored / total_scored, 1) if total_scored else 0,
            "allowed_share": round(100 * phase_allowed / total_allowed, 1) if total_allowed else 0,
        })
    return {
        "available": True,
        "sample_games": games,
        "labels": labels,
        "scored_per_game": scored_per_game,
        "allowed_per_game": allowed_per_game,
        "scoring_game_rate": [round(100 * value / games, 1) for value in scored_games],
        "allowing_game_rate": [round(100 * value / games, 1) for value in allowed_games],
        "runs_scored_per_game": round(total_scored / games, 2),
        "runs_allowed_per_game": round(total_allowed / games, 2),
        "phases": phases,
    }


def matchup_league_rankings(season, through_date):
    cache_key = (int(season), str(through_date))
    with _league_rankings_lock:
        cached = _league_rankings_cache.get(cache_key)
    if cached:
        return cached
    params = {
        "stats": "byDateRange",
        "sportIds": 1,
        "startDate": f"{int(season)}-03-01",
        "endDate": str(through_date),
    }

    def fetch(group):
        response = requests.get(
            "https://statsapi.mlb.com/api/v1/teams/stats",
            params={**params, "group": group}, timeout=15,
        )
        response.raise_for_status()
        stats = response.json().get("stats") or []
        return (stats[0].get("splits") or []) if stats else []

    with ThreadPoolExecutor(max_workers=2) as pool:
        hitting_future = pool.submit(fetch, "hitting")
        pitching_future = pool.submit(fetch, "pitching")
        result = build_team_league_rankings(hitting_future.result(), pitching_future.result())
    with _league_rankings_lock:
        _league_rankings_cache[cache_key] = result
    return result


def team_inning_distribution(team_id, season, through_date, excluded_game_id=None):
    cache_key = (int(team_id), int(season), str(through_date))
    with _inning_distribution_lock:
        cached = _inning_distribution_cache.get(cache_key)
    if cached:
        return cached
    response = requests.get(
        "https://statsapi.mlb.com/api/v1/schedule",
        params={
            "sportId": 1,
            "teamId": int(team_id),
            "startDate": f"{int(season)}-03-01",
            "endDate": str(through_date),
            "gameType": "R",
            "hydrate": "linescore",
        },
        timeout=20,
    )
    response.raise_for_status()
    result = summarize_inning_distribution(response.json(), team_id, excluded_game_id)
    with _inning_distribution_lock:
        _inning_distribution_cache[cache_key] = result
    return result


def matchup_league_context(team_ids, game_time, game_id):
    try:
        matchup_date = datetime.fromisoformat(str(game_time).replace("Z", "+00:00")).date()
    except (TypeError, ValueError):
        matchup_date = datetime.now(timezone.utc).date()
    through_date = matchup_date - timedelta(days=1)
    season = matchup_date.year
    try:
        with ThreadPoolExecutor(max_workers=3) as pool:
            rankings_future = pool.submit(matchup_league_rankings, season, through_date.isoformat())
            away_future = pool.submit(team_inning_distribution, team_ids[0], season, through_date.isoformat(), game_id)
            home_future = pool.submit(team_inning_distribution, team_ids[1], season, through_date.isoformat(), game_id)
            rankings = rankings_future.result()
            distributions = {"away": away_future.result(), "home": home_future.result()}
        teams = {}
        matchup_keys = {
            "runs_per_game", "ops", "hitter_k_rate", "walk_rate",
            "staff_era", "staff_whip", "pitcher_k9", "runs_allowed_per_game",
        }
        for side, team_id in (("away", team_ids[0]), ("home", team_ids[1])):
            ranked = rankings.get(int(team_id), {})
            teams[side] = {
                "team_id": int(team_id),
                "team_name": ranked.get("team_name"),
                "rankings": [row for row in ranked.get("rankings") or [] if row.get("key") in matchup_keys],
                "inning_distribution": distributions[side],
            }
        return {
            "available": any(team.get("rankings") for team in teams.values()),
            "season": season,
            "through": through_date.isoformat(),
            "team_count": max((row.get("teams", 0) for team in teams.values() for row in team.get("rankings", [])), default=0),
            "teams": teams,
            "source": "MLB Stats API team by-date-range statistics and hydrated final linescores",
        }
    except Exception as exc:
        return {
            "available": False,
            "season": season,
            "through": through_date.isoformat(),
            "team_count": 0,
            "teams": {},
            "message": f"League context is temporarily unavailable: {exc}",
        }


def _bullpen_game_line(game, side):
    """Reduce one completed box score to the bullpen fields used by matchups."""
    pitchers = []
    for player in (game.get(side, {}).get("players") or []):
        pitching = player.get("pitching") or {}
        if not pitching or int(pitching.get("gamesStarted") or 0) > 0:
            continue
        pitchers.append(pitching)
    runs_are_exact = all("runs" in pitching for pitching in pitchers)
    earned_runs = sum(_float(pitching.get("earnedRuns")) for pitching in pitchers)
    return {
        "game_id": int(game.get("game_id") or 0),
        "date": str(game.get("date") or "")[:10],
        "season": int(game.get("season") or 0),
        "team_id": int(game.get(side, {}).get("team_id") or 0),
        "outs": sum(int(pitching.get("outs") or 0) for pitching in pitchers),
        "earned_runs": earned_runs,
        "runs": (
            sum(_float(pitching.get("runs")) for pitching in pitchers)
            if runs_are_exact else earned_runs
        ),
        "runs_are_exact": runs_are_exact,
        "relief_appearances": len(pitchers),
    }


def _bullpen_history_rows():
    """Load a compact current file index and invalidate it after nightly sync."""
    try:
        stat = os.stat(PLAYER_BOXSCORES)
        fingerprint = (PLAYER_BOXSCORES, stat.st_mtime_ns, stat.st_size)
    except OSError:
        return []
    if _bullpen_history_cache["fingerprint"] == fingerprint:
        return _bullpen_history_cache["rows"]
    with _bullpen_history_lock:
        if _bullpen_history_cache["fingerprint"] == fingerprint:
            return _bullpen_history_cache["rows"]
        rows = []
        with open(PLAYER_BOXSCORES, encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                game = json.loads(line)
                rows.extend((_bullpen_game_line(game, "away"), _bullpen_game_line(game, "home")))
        _bullpen_history_cache.update({"fingerprint": fingerprint, "rows": rows})
        return rows


def bullpen_performance(team_ids, game_datetime, exclude_game_id):
    """Return point-in-time season bullpen ERA and runs allowed per team game."""
    target_date = str(game_datetime or "")[:10]
    season = int(target_date[:4]) if target_date[:4].isdigit() else datetime.now(timezone.utc).year
    wanted = {int(team_id) for team_id in team_ids if team_id}
    grouped = {team_id: [] for team_id in wanted}
    for row in _bullpen_history_rows():
        team_id = int(row.get("team_id") or 0)
        if (
            team_id in wanted
            and int(row.get("season") or 0) == season
            and row.get("date", "") < target_date
            and int(row.get("game_id") or 0) != int(exclude_game_id or 0)
        ):
            grouped[team_id].append(row)
    output = {}
    for team_id, rows in grouped.items():
        outs = sum(row["outs"] for row in rows)
        earned_runs = sum(row["earned_runs"] for row in rows)
        exact_runs = bool(rows) and all(row["runs_are_exact"] for row in rows)
        runs = sum(row["runs"] for row in rows)
        games = len(rows)
        output[team_id] = {
            "bullpen_era": round(earned_runs * 27 / outs, 2) if outs else None,
            "bullpen_runs_per_game": round(runs / games, 2) if games else None,
            "bullpen_runs_basis": "runs" if exact_runs else "earned_runs",
            "bullpen_games": games,
            "bullpen_innings": round(outs / 3, 1),
            "bullpen_relief_appearances": sum(row["relief_appearances"] for row in rows),
            "through": max((row["date"] for row in rows), default=None),
        }
    return output


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
            batting = player.get("seasonStats", {}).get("batting", {})
            plate_appearances = _float(batting.get("plateAppearances"))
            ops = _float(batting.get("ops"), .710)
            shrunk_ops = (
                plate_appearances * ops + 120 * .710
            ) / (plate_appearances + 120)
            return {
                "id": int(player_id), "name": person.get("fullName") or f"Player {player_id}",
                "position": position.get("abbreviation") or position.get("name") or "—",
                "position_name": position.get("name"), "position_type": position.get("type"),
                "batting_order": batting_spot, "ops": ops,
                "shrunk_ops": shrunk_ops, "pa": plate_appearances,
            }
        lineup_players = [roster_player(pid, index + 1) for index, pid in enumerate(order)]
        ops = [player["ops"] for player in lineup_players]
        shrunk_ops = [player["shrunk_ops"] for player in lineup_players]
        profile = pitcher_profiles.get(side) or {}
        probable_id = profile.get("id")
        starter_confirmed = bool(probable_id and official_pitchers and int(official_pitchers[0]) == int(probable_id) and (len(order) >= 9 or game_status in ("Live", "Final")))
        bullpen_confirmed = bool(bullpen_ids and (len(order) >= 9 or game_status in ("Live", "Final")))
        context[side] = {
            "starter_id": probable_id, "starter_name": profile.get("name"),
            "starter_era": _float(profile.get("era"), 4.5), "starter_whip": _float(profile.get("whip"), 1.35),
            "starter_fip": _float(profile.get("fip"), 4.5),
            "starter_innings": _float(profile.get("innings_decimal")),
            "starter_strikeouts": _float(profile.get("strikeouts")),
            "starter_walks": _float(profile.get("walks")),
            "starter_home_runs": _float(profile.get("home_runs")),
            "starter_status": "confirmed" if starter_confirmed else "predicted" if probable_id else "pending",
            "lineup_ids": order, "lineup_confirmed": len(order) >= 9,
            "lineup_players": lineup_players,
            "lineup_ops": sum(ops) / len(ops) if ops else .710,
            "lineup_ops_shrunk": sum(shrunk_ops) / len(shrunk_ops) if shrunk_ops else .710,
            "lineup_average_pa": (
                sum(player["pa"] for player in lineup_players) / len(lineup_players)
                if lineup_players else 0
            ),
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
            # Weather enriches a matchup, but it must never hold the core game
            # feed hostage.  A short connect/read budget lets the existing
            # neutral or cached fallback take over when Open-Meteo is down.
            response = requests.get(endpoint, params={"latitude": latitude, "longitude": longitude, "start_date": day, "end_date": day, "hourly": "temperature_2m,wind_speed_10m,weather_code", "temperature_unit": "fahrenheit", "wind_speed_unit": "mph", "timezone": "UTC"}, timeout=(1.5, 3.0))
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


def _player_market_name_parts(value):
    value = unicodedata.normalize("NFKD", str(value or ""))
    value = "".join(char for char in value if not unicodedata.combining(char))
    return [part for part in re.findall(r"[a-z0-9]+", value.lower()) if part not in {"jr", "sr", "ii", "iii", "iv"}]


def _match_melbet_player(players, name):
    """Match exact names first, then only unique identity-safe variants."""
    exact = players.get(_normalize_player_market_name(name))
    if exact:
        return exact
    wanted_parts = _player_market_name_parts(name)
    if len(wanted_parts) < 2:
        return None

    def identity(parts):
        first = parts[0]
        # Treat ``J. T. Realmuto`` and ``JT Realmuto`` as the same initials.
        # Other middle names are deliberately excluded from identity.
        if len(parts) > 2 and all(len(part) == 1 for part in parts[:-1]):
            first = "".join(parts[:-1])
        return first, parts[-1]

    wanted_first, wanted_last = identity(wanted_parts)
    candidates = []
    for offered in players.values():
        offered_parts = _player_market_name_parts(offered.get("name"))
        if len(offered_parts) < 2:
            continue
        offered_first, offered_last = identity(offered_parts)
        if offered_last != wanted_last or offered_first[0] != wanted_first[0]:
            continue
        if offered_first == wanted_first:
            score = 1.0
        elif (len(offered_first) == 1 or len(wanted_first) == 1) and (
            offered_first.startswith(wanted_first) or wanted_first.startswith(offered_first)
        ):
            score = .9
        else:
            first_score = SequenceMatcher(None, wanted_first, offered_first).ratio()
            if min(len(wanted_first), len(offered_first)) < 3 or first_score < .72:
                continue
            score = .8 + first_score / 10
        candidates.append((score, offered))
    candidates.sort(key=lambda item: item[0], reverse=True)
    if not candidates or (len(candidates) > 1 and candidates[0][0] - candidates[1][0] < .02):
        return None
    return candidates[0][1]


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


def _melbet_game_params(game_id, count=250):
    return {
        "id": int(game_id), "lng": "en", "cfview": 0,
        "isSubGames": "true", "GroupEvents": "true", "countevents": int(count),
        "partner": 1, "country": 87,
    }


def _melbet_game_payload(game_id, usable=None, count=250):
    return _melbet_value(MELBET_GAME_PATH, _melbet_game_params(game_id, count), usable=usable)


def _melbet_complete_player_payload(game_id):
    """Fetch every player selection, following MelBet's advertised total."""
    count = 2000
    payload = _melbet_game_payload(game_id, count=count)
    advertised = int(payload.get("EC") or 0)
    if advertised > count:
        payload = _melbet_game_payload(game_id, count=advertised + 100)
    if not _parse_melbet_player_prop_groups(payload):
        raise ValueError("response contained no supported MLB player markets")
    return payload


def _melbet_champ_payload():
    return _melbet_value(
        MELBET_CHAMP_PATH,
        {"sport": 5, "champ": MELBET_MLB_CHAMP_ID, "lng": "en", "partner": 1},
        usable=lambda value: bool(value.get("G")),
        timeout=(3.0, 7.0),
    )


def _parse_melbet_player_prop_groups(payload):
    """Return displayed player selections and non-model decimal-odds metadata."""
    players = {}
    for group in payload.get("GE", []):
        group_id = int(group.get("G", 0))
        market = MELBET_PLAYER_PROP_MARKETS.get(group_id)
        if not market:
            continue
        by_selection = {}
        for row in _melbet_event_rows(group.get("E", [])):
            person = row.get("PL") or {}
            if not person.get("N") or (row.get("P") is None and "model_line" not in market):
                continue
            type_id = int(row.get("T", 0))
            side = market["types"].get(type_id)
            if not side:
                continue
            name = str(person["N"])
            display_line = float(row["P"]) if row.get("P") is not None else float(market["display_line"])
            model_line = float(market.get("model_line", display_line - .5 if market["format"] == "at_least" else display_line))
            key = (_normalize_player_market_name(name), model_line)
            entry = by_selection.setdefault(key, {"name": name, "selections": {}})
            entry["selections"][side] = {
                "group_id": group_id, "type_id": type_id, "side": side,
                "format": market["format"], "market_name": market["name"],
                "player_name": name,
                "display_line": display_line,
                "decimal_odds": float(row["C"]) if row.get("C") is not None and float(row["C"]) > 1 else None,
                "selection_name": (
                    f"{name} ({display_line:g}) Or More" if market["format"] == "at_least"
                    else f"{name} - {'Yes' if side == 'over' else 'No'}" if market["format"] == "yes_no"
                    else name if market["format"] == "yes"
                    else f"{name} {side.title()} ({display_line:g})"
                ),
            }
        for (name_key, line), entry in by_selection.items():
            selections = entry["selections"]
            player = players.setdefault(name_key, {"name": entry["name"], "props": {}, "offers": []})
            player["props"].setdefault(market["prop"], []).append(line)
            for selection in selections.values():
                player["offers"].append({"prop": market["prop"], "line": line, **selection})
    for player in players.values():
        player["props"] = {prop: sorted(set(lines)) for prop, lines in player["props"].items()}
        player["offers"].sort(key=lambda row: (row["prop"], row["line"], row["side"], row["group_id"]))
    return players


def _unmapped_melbet_player_prop_groups(payload):
    """Expose unsupported live group shapes without guessing their meaning."""
    values = []
    for group in payload.get("GE", []):
        group_id = int(group.get("G", 0))
        if not group_id or group_id in MELBET_PLAYER_PROP_MARKETS:
            continue
        rows = _melbet_event_rows(group.get("E", []))
        player_rows = [row for row in rows if (row.get("PL") or {}).get("N")]
        if not player_rows:
            continue
        values.append({
            "group_id": group_id,
            "player_selections": len(player_rows),
            "thresholds": sorted({float(row["P"]) for row in player_rows if row.get("P") is not None}),
            "selection_types": sorted({int(row["T"]) for row in player_rows if row.get("T") is not None}),
        })
    return values


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
    # Player-stat sub-games currently contain roughly 1,000 selections.
    # MelBet otherwise truncates the response at the requested count, which
    # silently drops the groups rendered below the first page.
    props_payload = _melbet_complete_player_payload(subgame["CI"]) if subgame else {}
    players = _parse_melbet_player_prop_groups(props_payload)
    source_host = props_payload.get("_ninth_melbet_host") or main.get("_ninth_melbet_host") or game.get("feed_host")
    return {
        **game, "player_subgame_id": int(subgame["CI"]) if subgame else None,
        "players": players, "feed_host": source_host,
        "unmapped_player_groups": _unmapped_melbet_player_prop_groups(props_payload),
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
    if _melbet_cache_fresh(_melbet_player_props_cache, force=force, now=now):
        return _melbet_player_props_cache
    with _melbet_player_props_lock:
        if _melbet_cache_fresh(_melbet_player_props_cache, force=force, now=now):
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
            unknown = {}
            for item in markets:
                for group in item.get("unmapped_player_groups") or []:
                    summary = unknown.setdefault(group["group_id"], {
                        "group_id": group["group_id"], "games_offered": 0,
                        "player_selections": 0, "thresholds": set(), "selection_types": set(),
                    })
                    summary["games_offered"] += 1
                    summary["player_selections"] += group["player_selections"]
                    summary["thresholds"].update(group["thresholds"])
                    summary["selection_types"].update(group["selection_types"])
            unmapped_groups = [{
                **value,
                "thresholds": sorted(value["thresholds"]),
                "selection_types": sorted(value["selection_types"]),
            } for _, value in sorted(unknown.items())]
            _player_prop_monitor["unmapped_market_groups"] = unmapped_groups
            _record_melbet_success(
                _melbet_player_props_cache, now, markets, sources=sources,
                unmapped_market_groups=unmapped_groups,
            )
        except (requests.RequestException, ValueError, TypeError, KeyError) as exc:
            _record_melbet_failure(_melbet_player_props_cache, now, exc)
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
    listed_prop_types = sorted({
        str(offer.get("prop"))
        for player in market.get("players", {}).values()
        for offer in player.get("offers", [])
        if offer.get("prop")
    })
    home_runs_only = listed_prop_types == ["home_runs"]
    return {
        "available": True, "players": market["players"],
        "source": "MelBet displayed player props" + (" via proxy" if market.get("feed_host") == MELBET_PROXY_BASE else ""),
        "feed_host": market.get("feed_host"), "prices_used": False,
        "odds_format": "decimal", "odds_model_inputs": False,
        "observed_at": market.get("last_confirmed_at") or (snapshot.get("updated_at").isoformat() if snapshot.get("updated_at") else None),
        "stale": bool(market.get("stale")),
        "partial": home_runs_only,
        "market_status": "home_runs_only" if home_runs_only else "full_or_mixed",
        "listed_prop_types": listed_prop_types,
        "bookmaker_game_id": market["bookmaker_game_id"],
        "player_subgame_id": market.get("player_subgame_id"),
    }


def restrict_player_props_to_available_lines(players, market):
    if not market or not market.get("players"):
        return []
    restricted = []
    for player in players or []:
        offered = next((
            match for name in (player.get("market_names") or [player.get("name")])
            if (match := _match_melbet_player(market["players"], name))
        ), None)
        if not offered:
            continue
        props = []
        for projection in player.get("props", []):
            offered_lines = {float(line) for line in offered.get("props", {}).get(projection.get("prop"), [])}
            offer_rows = [row for row in offered.get("offers", []) if row.get("prop") == projection.get("prop")]
            offers_by_line = {}
            for offer in offer_rows:
                offers_by_line.setdefault(float(offer["line"]), {}).setdefault(offer["side"], []).append(offer)
            thresholds = []
            for row in projection.get("thresholds", []):
                line = float(row.get("line", -999))
                if line not in offered_lines:
                    continue
                selections = offers_by_line.get(line) or {
                    "over": [], "under": [],
                }
                available_sides = [side for side in ("over", "under") if side in selections]
                # Backward compatibility for cached snapshots written before
                # selection metadata was introduced.
                if not offer_rows:
                    available_sides = ["over", "under"]
                thresholds.append({
                    **row, "available_sides": available_sides,
                    "melbet_selections": selections,
                })
            if not thresholds:
                continue
            choices = [
                (float(row.get(f"{side}_probability", 0)), row, side)
                for row in thresholds for side in row["available_sides"]
            ]
            if not choices:
                continue
            _, best, side = max(choices, key=lambda value: value[0])
            market_names = sorted({
                selection["market_name"] for row in thresholds
                for values in row["melbet_selections"].values() for selection in values
            })
            props.append({
                **projection, "thresholds": thresholds, "recommended_line": float(best["line"]),
                "recommended_side": side, "recommended_probability": float(best[f"{side}_probability"]),
                "melbet_market_names": market_names,
                "line_market": {"source": market["source"], "prices_used": False, "odds_format": "decimal", "odds_model_inputs": False, "observed_at": market.get("observed_at")},
            })
        if props:
            value = {key: item for key, item in player.items() if key != "market_names"}; value["props"] = props
            value["best_projection"] = max(props, key=lambda row: row["recommended_probability"])
            restricted.append(value)
    return restricted


def _fetch_melbet_game_totals(game):
    def displayed_market(payload):
        group = next((row for row in payload.get("GE", []) if int(row.get("G", 0)) == 17), None)
        events = _melbet_event_rows((group or {}).get("E", []))
        over = {
            float(row["P"]): (float(row["C"]) if row.get("C") is not None and float(row["C"]) > 1 else None)
            for row in events
            if int(row.get("T", 0)) == 9 and row.get("P") is not None
            and 2 <= float(row["P"]) <= 25
        }
        under = {
            float(row["P"]): (float(row["C"]) if row.get("C") is not None and float(row["C"]) > 1 else None)
            for row in events
            if int(row.get("T", 0)) == 10 and row.get("P") is not None
            and 2 <= float(row["P"]) <= 25
        }
        lines = sorted(set(over) & set(under))
        moneyline_group = next((row for row in payload.get("GE", []) if int(row.get("G", 0)) == 1), None)
        moneyline_rows = _melbet_event_rows((moneyline_group or {}).get("E", []))
        moneyline = {
            "home" if int(row.get("T", 0)) == 1 else "away": float(row["C"])
            for row in moneyline_rows
            if int(row.get("T", 0)) in (1, 3) and row.get("C") is not None and float(row["C"]) > 1
        }
        return {
            "lines": lines,
            "total_odds": {line: {"over": over[line], "under": under[line]} for line in lines},
            "moneyline_odds": moneyline,
        }

    payload = _melbet_game_payload(
        game["bookmaker_game_id"],
        usable=lambda value: bool(displayed_market(value)["lines"] or displayed_market(value)["moneyline_odds"]),
    )
    displayed = displayed_market(payload)
    # Only thresholds displayed on both sides survive. Odds remain isolated
    # from inference and are used later only as UI labels and eligibility rails.
    return {**game, **displayed, "feed_host": payload.get("_ninth_melbet_host") or game.get("feed_host")}


def _safe_fetch_melbet_game_totals(game):
    try:
        return _fetch_melbet_game_totals(game)
    except (requests.RequestException, ValueError, TypeError, KeyError) as exc:
        print(f"[melbet-totals] game {game.get('bookmaker_game_id')} unavailable: {exc}", flush=True)
        return None


def _melbet_totals_snapshot_payload(market):
    lines = sorted({
        float(line) for line in market.get("lines", [])
        if 2 <= float(line) <= 25
    })
    total_odds = {}
    source_total_odds = market.get("total_odds") or {}
    for line in lines:
        prices = source_total_odds.get(line) or source_total_odds.get(str(line)) or source_total_odds.get(f"{line:g}") or {}
        normalized = {
            side: float(prices[side]) for side in ("over", "under")
            if prices.get(side) is not None and float(prices[side]) > 1
        }
        if normalized:
            total_odds[f"{line:g}"] = normalized
    moneyline_odds = {
        side: float((market.get("moneyline_odds") or {})[side])
        for side in ("home", "away")
        if (market.get("moneyline_odds") or {}).get(side) is not None
        and float((market.get("moneyline_odds") or {})[side]) > 1
    }
    return {"lines": lines, "total_odds": total_odds, "moneyline_odds": moneyline_odds}


def record_melbet_totals_snapshots(markets, observed_at):
    """Archive point-in-time line grids and display-only prices for replay."""
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
                                _melbet_totals_snapshot_payload(saved), sort_keys=True, separators=(",", ":"),
                            )
                        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                            continue
            _melbet_totals_snapshot_loaded = True
        rows = []
        for market in markets or []:
            snapshot = _melbet_totals_snapshot_payload(market)
            lines = snapshot["lines"]
            names = f"{market.get('away_name', '')} {market.get('home_name', '')}"
            if not lines or "(runs)" in names.lower():
                continue
            event_id = int(market["bookmaker_game_id"])
            signature = json.dumps(snapshot, sort_keys=True, separators=(",", ":"))
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
                "total_odds": snapshot["total_odds"],
                "moneyline_odds": snapshot["moneyline_odds"],
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


def melbet_totals_markets(force=False, defer_refresh=False):
    """Return current full-game lines and display-only decimal odds."""
    now = datetime.now(timezone.utc)
    if _melbet_cache_fresh(_melbet_totals_cache, force=force, now=now):
        return _melbet_totals_cache
    if defer_refresh:
        with _melbet_totals_lock:
            if _melbet_totals_cache.get("refreshing"):
                return _melbet_totals_cache
            _melbet_totals_cache["refreshing"] = True

        def refresh():
            try:
                melbet_totals_markets(force=True)
            finally:
                with _melbet_totals_lock:
                    _melbet_totals_cache["refreshing"] = False
                _projection_board_cache.clear()

        threading.Thread(target=refresh, name="melbet-totals-refresh", daemon=True).start()
        return _melbet_totals_cache
    with _melbet_totals_lock:
        if _melbet_cache_fresh(_melbet_totals_cache, force=force, now=now):
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
            _record_melbet_success(_melbet_totals_cache, now, markets, sources=sources)
            record_melbet_totals_snapshots(markets, now)
        except (requests.RequestException, ValueError, TypeError, KeyError) as exc:
            _record_melbet_failure(_melbet_totals_cache, now, exc)
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
        "odds_format": "decimal", "odds_model_inputs": False,
        "moneyline_odds": market.get("moneyline_odds", {}),
        "total_odds": market.get("total_odds", {}),
        "observed_at": snapshot.get("updated_at").isoformat() if snapshot.get("updated_at") else None,
        "bookmaker_game_id": market["bookmaker_game_id"], "game_label": market.get("game_label"),
    }


def totals_distribution_probability(expected_total, line, side, prediction_interval_80):
    """Conservative side probability implied by the model's residual interval."""
    try:
        expected = float(expected_total)
        threshold = float(line)
        lower, upper = (float(value) for value in prediction_interval_80)
    except (TypeError, ValueError):
        return None
    lower_width = expected - lower
    upper_width = upper - expected
    residual_width = max(lower_width, upper_width)
    if not math.isfinite(residual_width) or residual_width <= 0:
        return None
    # For a central 80% interval, either tail is 1.28155 standard deviations.
    # Using the wider tail is deliberately conservative when residuals are skewed.
    sigma = residual_width / 1.2815515655446004
    z_score = (threshold - expected) / max(sigma, 1e-6)
    under = .5 * (1 + math.erf(z_score / math.sqrt(2)))
    probability = under if side == "under" else 1 - under
    return max(0.0, min(1.0, probability))


def totals_empirical_residual_probability(expected_total, line, side, calibration):
    """Return a smoothed probability from previously settled forecast errors.

    Residuals are frozen by nightly maintenance and therefore predate the game
    being selected.  A small symmetric prior prevents a short residual history
    from producing extreme probabilities.
    """
    try:
        threshold = float(line) - float(expected_total)
    except (TypeError, ValueError):
        return None
    residuals = []
    for value in (calibration or {}).get("empirical_residuals", []):
        try:
            residual = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(residual):
            residuals.append(residual)
    minimum = int((calibration or {}).get("minimum_empirical_residuals") or 60)
    if len(residuals) < minimum:
        return None
    prior = 8.0
    over = (sum(value > threshold for value in residuals) + prior / 2) / (len(residuals) + prior)
    probability = over if side == "over" else 1 - over
    return max(0.0, min(1.0, probability))


def totals_no_vig_imbalance(row):
    odds = row.get("melbet_odds") or {}
    try:
        over_price, under_price = float(odds["over"]), float(odds["under"])
        if over_price <= 1 or under_price <= 1:
            return None
        over_implied, under_implied = 1 / over_price, 1 / under_price
        return abs(over_implied / (over_implied + under_implied) - .5)
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        return None


def totals_market_central_line(thresholds):
    """Return the displayed total whose paired prices are closest to even."""
    candidates = []
    for row in thresholds or []:
        imbalance = totals_no_vig_imbalance(row)
        if imbalance is not None:
            candidates.append((imbalance, float(row["line"])))
    return min(candidates)[1] if candidates else None


def deterministic_totals_audit_selection(projection, thresholds=None):
    """Return one stable, market-representative selection for model auditing.

    Audit selection is intentionally independent of the deployment promotion
    gate. The Builder may only consume ``recommended_*`` when
    ``automatic_builder_eligible`` is true, while this selection exists for
    every usable pregame totals forecast, including legacy snapshots.
    """
    projection = projection or {}
    try:
        audit_line = float(projection.get("audit_line"))
        audit_side = str(projection.get("audit_side") or "").lower()
        audit_probability = float(projection.get("audit_probability"))
        if audit_side in ("over", "under"):
            return {
                "line": audit_line, "side": audit_side,
                "probability": audit_probability,
                "push_probability": float(projection.get("audit_push_probability") or 0),
                "rule": projection.get("audit_selection_rule") or "archived_deterministic_audit_selection",
            }
    except (TypeError, ValueError):
        pass

    usable = []
    for threshold in thresholds if thresholds is not None else projection.get("thresholds", []):
        try:
            line = float(threshold["line"])
            over = float(threshold["over_probability"])
            under = float(threshold["under_probability"])
        except (KeyError, TypeError, ValueError):
            continue
        usable.append((line, threshold, over, under))

    if not usable:
        try:
            line = float(projection.get("recommended_line"))
            side = str(projection.get("recommended_side") or "").lower()
            probability = float(projection.get("recommended_probability"))
        except (TypeError, ValueError):
            return None
        if side not in ("over", "under"):
            return None
        return {
            "line": line, "side": side, "probability": probability,
            "push_probability": 0.0,
            "rule": "original_model_recommendation_without_threshold_grid",
        }

    central_line = totals_market_central_line([row for _, row, _, _ in usable])
    if central_line is None:
        try:
            recommended_line = float(projection.get("recommended_line"))
        except (TypeError, ValueError):
            recommended_line = None
        offered_lines = {line for line, _, _, _ in usable}
        if recommended_line in offered_lines:
            central_line = recommended_line
        else:
            try:
                central_line = float(projection.get("expected_total_runs"))
            except (TypeError, ValueError):
                ordered = sorted(offered_lines)
                central_line = ordered[(len(ordered) - 1) // 2]

    # Audit the actual balanced market line.  Moving an integer centre to a
    # lower half-line mechanically favoured Overs and treated pushes as losses.
    try:
        expected_anchor = float(projection.get("expected_total_runs"))
    except (TypeError, ValueError):
        expected_anchor = central_line
    line, selected_row, over, under = min(
        usable,
        key=lambda item: (abs(item[0] - central_line), abs(item[0] - expected_anchor)),
    )
    side = "over" if over >= under else "under"
    probability = over if side == "over" else under
    return {
        "line": line, "side": side, "probability": round(probability, 4),
        "push_probability": round(float(selected_row.get("push_probability") or 0), 4),
        "rule": "exact_balanced_market_line_max_probability_side_push_aware",
    }


def apply_totals_audit_selection(projection, thresholds=None):
    selection = deterministic_totals_audit_selection(projection, thresholds)
    if selection:
        projection.update({
            "audit_line": selection["line"],
            "audit_side": selection["side"],
            "audit_probability": selection["probability"],
            "audit_push_probability": selection.get("push_probability", 0),
            "audit_selection_rule": selection["rule"],
            "audit_policy_version": "central-line-consensus-v2",
        })
    return projection


def restrict_totals_to_available_lines(projection, market):
    result = dict(projection or {})
    result["line_market"] = market or {
        "available": False, "lines": [], "source": "MelBet displayed full-game totals",
        "prices_used": False, "observed_at": None,
    }
    result["selection_available"] = bool(market and market.get("lines"))
    result["automatic_selection_available"] = False
    result["automatic_builder_eligible"] = False
    if not result.get("available") or not result["selection_available"]:
        apply_totals_audit_selection(result)
        return result
    offered = {float(line) for line in market["lines"]}
    thresholds = [row for row in result.get("thresholds", []) if float(row.get("line", -999)) in offered]
    if not thresholds:
        result["selection_available"] = False
        return result
    normalized_thresholds = []
    for threshold in thresholds:
        row = dict(threshold)
        row["melbet_odds"] = (market.get("total_odds", {}).get(float(row.get("line", -999))) or {})
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
    apply_totals_audit_selection(result, thresholds)
    configured_lines = (result.get("model") or {}).get("decision_lines") or [7.5, 8.5, 9.5, 10.5]
    decision_lines = {float(line) for line in configured_lines}
    deployment_policy = deployment_selection_policy().get("totals", {})
    calibration = deployment_policy.get("calibration") or {}
    calibration_promoted = calibration.get("promoted") is True
    logit_slope = float(calibration.get("logit_slope") or 1) if calibration_promoted else 1.0
    global_intercepts = calibration.get("global_intercepts") or {}
    line_side_intercepts = calibration.get("line_side_intercepts") or {}
    hierarchical_calibration = bool(global_intercepts and line_side_intercepts)
    legacy_offset = float(calibration.get("intercept", calibration.get("logit_offset")) or 0) if calibration_promoted else 0.0
    expected_total = result.get("expected_total_runs")
    try:
        expected_total = float(expected_total)
    except (TypeError, ValueError):
        expected_total = None
    prediction_interval_80 = result.get("prediction_interval_80")
    consistency_margin = float(calibration.get("consistency_margin_runs") or 1.0)
    override_probability = float(calibration.get("consistency_override_probability") or .62)
    exact_selection_rules = deployment_policy.get("rules") or {}
    automatic_thresholds = []
    for row in thresholds:
        if float(row["line"]) not in decision_lines:
            continue
        raw_over = max(1e-6, min(1 - 1e-6, float(row["over_probability"])))
        raw_under = max(1e-6, min(1 - 1e-6, float(row["under_probability"])))
        if hierarchical_calibration:
            scores = {}
            for side, raw in (("over", raw_over), ("under", raw_under)):
                key = f"{float(row['line']):g}:{side}"
                intercept = float(line_side_intercepts.get(key, global_intercepts.get(side, 0)) or 0)
                scores[side] = 1 / (1 + math.exp(-(intercept + logit_slope * math.log(raw / (1 - raw)))))
            score_total = scores["over"] + scores["under"]
            calibrated_over = scores["over"] / score_total
            calibrated_under = scores["under"] / score_total
        else:
            calibrated_over = 1 / (1 + math.exp(-(legacy_offset + logit_slope * math.log(raw_over / (1 - raw_over)))))
            calibrated_under = 1 - calibrated_over
        difference = None if expected_total is None else expected_total - float(row["line"])
        if difference is not None and difference >= consistency_margin and raw_over >= .5 and calibrated_over < .5:
            row["pre_consistency_over_probability"] = round(calibrated_over, 4)
            calibrated_over = .5 + (raw_over - .5) * .5
            calibrated_under = 1 - calibrated_over
            row["consistency_adjustment"] = "rejected_contradictory_under_used_conservative_raw_over"
        elif difference is not None and difference <= -consistency_margin and raw_under >= .5 and calibrated_under < .5:
            row["pre_consistency_under_probability"] = round(calibrated_under, 4)
            calibrated_under = .5 + (raw_under - .5) * .5
            calibrated_over = 1 - calibrated_under
            row["consistency_adjustment"] = "rejected_contradictory_over_used_conservative_raw_under"
        row["uncalibrated_over_probability"] = round(raw_over, 4)
        row["uncalibrated_under_probability"] = round(raw_under, 4)
        row["over_probability"] = round(calibrated_over, 4)
        row["under_probability"] = round(calibrated_under, 4)
        for side in ("over", "under"):
            distribution_probability = totals_distribution_probability(
                expected_total, row["line"], side, prediction_interval_80,
            )
            row[f"distribution_{side}_probability"] = (
                None if distribution_probability is None else round(distribution_probability, 4)
            )
        row["probability_calibration"] = (
            "hierarchical_line_side_platt" if hierarchical_calibration
            else "production_logit_offset" if calibration_promoted else "none"
        )
        if calibration_promoted:
            automatic_thresholds.append(row)
    result["calibrated_decision_lines"] = sorted(
        float(row["line"]) for row in automatic_thresholds
    )
    result["automatic_selection_lines"] = []
    result["automatic_selection_policy"] = {
        "status": "calibrated" if automatic_thresholds else "calibration_not_promoted",
        "decision_lines": sorted(decision_lines), "deployment": deployment_policy,
        "manual_lines_remain_available": True,
    }
    central_market_line = totals_market_central_line(thresholds)
    result["central_market_line"] = central_market_line
    if central_market_line is not None:
        result["automatic_selection_policy"].update({
            "central_market_line": central_market_line,
            "line_anchor": "exact balanced MelBet total; no alternate-line fallback",
        })
    if not automatic_thresholds:
        result.update({
            "thresholds": thresholds,
            "recommended_line": None,
            "recommended_side": None,
            "recommended_probability": None,
            "automatic_builder_eligible": False,
            "confidence_score": None,
            "confidence_label": "Manual only",
            "line_selection_rule": "Production totals calibration has not passed chronological validation; all listed lines remain manually selectable",
        })
        return result
    candidates = []
    rejected_candidates = []
    for row in automatic_thresholds:
        line = float(row["line"])
        if central_market_line is None or abs(line - central_market_line) > 1e-9:
            rejected_candidates.append({
                "line": line, "side": None, "probability": None,
                "market_line_distance": None if central_market_line is None else abs(line - central_market_line),
                "reason": "Rejected: automatic totals use only MelBet's balanced central line; alternate ladder lines remain manual.",
            })
            continue
        for side in ("over", "under"):
            calibrated_probability = float(row.get(f"{side}_probability", 0))
            distribution_probability = row.get(f"distribution_{side}_probability")
            empirical_probability = totals_empirical_residual_probability(
                expected_total, line, side, calibration,
            )
            consensus_values = [calibrated_probability]
            if distribution_probability is not None:
                consensus_values.append(float(distribution_probability))
            if empirical_probability is not None:
                consensus_values.append(float(empirical_probability))
            probability = min(consensus_values)
            difference = None if expected_total is None else expected_total - line
            contradiction = difference is not None and (
                (side == "under" and difference >= consistency_margin)
                or (side == "over" and difference <= -consistency_margin)
            )
            evidence_key = f"{line:g}:{side}"
            evidence = exact_selection_rules.get(evidence_key) or {}
            evidence_passed = evidence.get("automatic_eligible") is True
            distribution_agrees = distribution_probability is not None and float(distribution_probability) >= .5
            empirical_agrees = empirical_probability is not None and float(empirical_probability) >= .5
            override = probability >= override_probability and evidence_passed
            candidate = {
                "probability": probability, "side": side, "line": line,
                "market_line_distance": None if central_market_line is None else abs(line - central_market_line),
                "calibrated_probability": calibrated_probability,
                "distribution_probability": distribution_probability,
                "empirical_residual_probability": empirical_probability,
                "exact_line_side_evidence": evidence,
                "distribution_consistent": not contradiction,
                "consistency_override": bool(contradiction and override),
            }
            if not evidence_passed:
                candidate["reason"] = (
                    f"Rejected: {side.title()} {line:g} has not passed the exact line/side sample, Brier and Wilson gates."
                )
                rejected_candidates.append(candidate)
            elif not distribution_agrees or not empirical_agrees:
                missing = []
                if not distribution_agrees:
                    missing.append("forecast distribution")
                if not empirical_agrees:
                    missing.append("nightly empirical residuals")
                candidate["reason"] = (
                    f"Rejected: {side.title()} {line:g} lacks agreement from " + " and ".join(missing) + "."
                )
                rejected_candidates.append(candidate)
            elif contradiction and not override:
                candidate["reason"] = (
                    f"Rejected: {side.title()} {line:g} contradicts expected total {expected_total:g} "
                    f"by {abs(difference):.1f} runs without validated {override_probability:.0%} override evidence."
                )
                rejected_candidates.append(candidate)
            elif probability < .5:
                candidate["reason"] = (
                    f"Rejected: conservative calibrated/distribution {side.title()} {line:g} "
                    "probability is below 50%."
                )
                rejected_candidates.append(candidate)
            else:
                candidates.append(candidate)
    result["automatic_selection_rejections"] = rejected_candidates
    result["automatic_candidates"] = sorted(candidates, key=lambda item: (
        item["market_line_distance"] if item["market_line_distance"] is not None else 0,
        -item["probability"],
    ))
    if not candidates:
        result.update({
            "thresholds": thresholds,
            "recommended_line": None,
            "recommended_side": None,
            "recommended_probability": None,
            "automatic_selection_available": False,
            "automatic_builder_eligible": False,
            "confidence_score": None,
            "confidence_label": "Manual only",
            "line_selection_rule": "No central-line side passed exact evidence plus forecast-distribution and empirical-residual consensus; listed lines remain manually selectable",
        })
        result["automatic_selection_policy"]["status"] = "distribution_consistency_rejected"
        return result
    selected = max(candidates, key=lambda item: item["probability"])
    probability, side, line = selected["probability"], selected["side"], selected["line"]
    if central_market_line is not None:
        result["automatic_selection_lines"] = [line]
    completeness = float(result.get("input_completeness", 0))
    adjusted = .5 + (probability - .5) * (.75 + .25 * completeness)
    result.update({
        "thresholds": thresholds, "recommended_line": line,
        "recommended_side": side, "recommended_probability": round(probability, 4),
        "automatic_selection_available": True,
        "automatic_builder_eligible": True,
        "confidence_score": round(adjusted * 100),
        "confidence_label": "High" if adjusted >= .72 else "Moderate" if adjusted >= .60 else "Low",
        "line_selection_rule": "Exact balanced MelBet line with passed line/side evidence and conservative agreement across calibration, forecast distribution and nightly empirical residuals; decimal odds only identify the central line",
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
                    "doubleheader": game.get("doubleHeader", "N"),
                    "game_number": int(game.get("gameNumber") or 1),
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


def moneyline_builder_probability(probability, doubleheader="N", game_number=1):
    """Shrink doubleheader recommendations toward a coin flip for ranking only.

    Same-day rematches have extra lineup, bullpen and availability uncertainty.
    The model probability remains visible/auditable; this conservative value is
    used only by automatic builders so a doubleheader cannot look more certain
    than the evidence supports.
    """
    probability = max(0.0, min(1.0, float(probability)))
    is_doubleheader = str(doubleheader or "N").upper() != "N" or int(game_number or 1) > 1
    multiplier = .75 if is_doubleheader else 1.0
    return round(.5 + (probability - .5) * multiplier, 6), multiplier


def projection_board(start_date, days=7):
    """Return a fast, market-free projection board for slip construction."""
    try:
        first_day = datetime.fromisoformat(start_date).date()
    except (TypeError, ValueError):
        first_day = datetime.now(timezone.utc).date()
    days = max(1, min(int(days or 7), 14))
    cache_key = f"{first_day.isoformat()}:{days}"
    cached = _projection_board_cache.get(cache_key)
    cached_ttl = max(5, min(300, int(cached[1].get("refresh_seconds", 300)))) if cached else 300
    if cached and datetime.now(timezone.utc) - cached[0] < timedelta(seconds=cached_ttl):
        return cached[1]
    final_day = first_day + timedelta(days=days - 1)
    raw_games = board_schedule(first_day.isoformat(), final_day.isoformat())
    # Market discovery must never hold the MLB slate hostage. On a cold start,
    # return projections immediately and merge MelBet lines on the next poll.
    totals_market_snapshot = melbet_totals_markets(defer_refresh=True)
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

    recommendation_policy = deployment_selection_policy()
    moneyline_policy = recommendation_policy["moneyline"]
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
        selected_probability = max(home_probability, away_probability)
        builder_probability, uncertainty_multiplier = moneyline_builder_probability(
            selected_probability, game.get("doubleheader"), game.get("game_number"),
        )
        games.append({
            "game_id": int(game["game_id"]), "starts_at": game["game_datetime"],
            "doubleheader": game.get("doubleheader", "N"),
            "game_number": int(game.get("game_number") or 1),
            "status": game.get("status", "Scheduled"), "venue": game.get("venue_name") or "Venue TBD",
            "away": {"id": int(game["away_id"]), "name": game.get("away_name"), "abbr": (game.get("away_name") or "AWY")[:3].upper()},
            "home": {"id": int(game["home_id"]), "name": game.get("home_name"), "abbr": (game.get("home_name") or "HME")[:3].upper()},
            "away_win_probability": away_probability, "home_win_probability": home_probability,
            "recommended_side": "home" if selected_home else "away",
            "recommended_team_id": int(game["home_id"] if selected_home else game["away_id"]),
            "recommended_probability": selected_probability,
            "moneyline_builder_probability": builder_probability,
            "moneyline_uncertainty_multiplier": uncertainty_multiplier,
            "automatic_moneyline_eligible": True,
            "model_confidence": projection.get("confidence_score"),
            "historical_tier": projection.get("historical_tier"),
            "input_completeness": projection.get("input_completeness", 0),
            "projection_updated_at": (context_snapshot or {}).get("updated_at") or now.isoformat(),
            "projection_basis": "matchup_synced" if context_snapshot else "early_baseline",
            "moneyline_odds": (totals_market or {}).get("moneyline_odds", {}),
            "totals_projection": totals_projection,
        })
    games.sort(key=lambda item: item["starts_at"])
    # Start slower official personnel/weather work only after the usable board
    # has been built, avoiding resource contention on the initial response.
    enrichment_pending = enqueue_projection_enrichment(context_candidates)
    recommendation = sorted(
        games, key=lambda item: item["moneyline_builder_probability"], reverse=True,
    )[:5] if len(games) >= 5 else []
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
            deployed_totals_model = (totals_report or {}).get("model")
            calibrated_totals_model = market_slip_calibration.get("totals_model")
            market_slip_calibration["deployed_totals_model"] = deployed_totals_model
            market_slip_calibration["compatible_with_deployed_totals"] = bool(
                deployed_totals_model
                and calibrated_totals_model
                and calibrated_totals_model == deployed_totals_model
            )
            if not market_slip_calibration["compatible_with_deployed_totals"]:
                market_slip_calibration["compatibility_note"] = (
                    "Totals and mixed card adjustment is disabled because this "
                    "calibrator was not generated from the deployed totals artifact."
                )
    except (OSError, json.JSONDecodeError):
        market_slip_calibration = None
    payload = {
        "generated_at": now.isoformat(), "start_date": first_day.isoformat(), "days": days,
        "games": games, "recommended_game_ids": [item["game_id"] for item in recommendation],
        "automatic_recommendation_policy": recommendation_policy,
        "recommendation_available": len(recommendation) == 5,
        "slip_calibration": slip_calibration,
        "multiday_slip_calibrations": multiday_slip_calibrations,
        "multiday_validation_grid": multiday_validation_grid,
        "totals_model": totals_report,
        "market_slip_calibration": market_slip_calibration,
        "market_inputs": False, "refresh_seconds": 10 if enrichment_pending or baseline_pending else 300,
        "enrichment_pending": enrichment_pending + baseline_pending,
        "projection_pending": baseline_pending,
        "scheduled_games": len(upcoming_games),
        "totals_line_feed": {
            "source": "MelBet displayed full-game totals and decimal odds", "prices_used": False,
            "odds_available": True, "odds_format": "decimal", "odds_model_inputs": False,
            "observed_at": totals_market_snapshot.get("updated_at").isoformat() if totals_market_snapshot.get("updated_at") else None,
            "listed_games": len(totals_market_snapshot.get("markets", [])),
            "error": totals_market_snapshot.get("error"),
            "refresh_seconds": int(totals_market_snapshot.get("refresh_seconds") or _melbet_refresh_seconds(totals_market_snapshot, upcoming_games)),
            "consecutive_failures": int(totals_market_snapshot.get("consecutive_failures") or 0),
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


def reverse_jsonl(path, block_size=128 * 1024):
    """Yield an append-only JSONL file newest-first without loading it all."""
    try:
        with open(path, "rb") as handle:
            handle.seek(0, os.SEEK_END)
            position = handle.tell()
            leading_fragment = b""
            while position > 0:
                read_size = min(block_size, position)
                position -= read_size
                handle.seek(position)
                parts = (handle.read(read_size) + leading_fragment).split(b"\n")
                leading_fragment = parts[0]
                for raw in reversed(parts[1:]):
                    if not raw.strip():
                        continue
                    try:
                        yield json.loads(raw)
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        continue
            if leading_fragment.strip():
                try:
                    yield json.loads(leading_fragment)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    pass
    except OSError:
        return


def last_pregame_snapshot(game_id, game_datetime):
    if not game_datetime:
        return None
    try:
        starts_at = datetime.fromisoformat(game_datetime.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    wanted_game_id = int(game_id)
    for row in reverse_jsonl(PROJECTION_LOG):
        try:
            if int(row["game_id"]) != wanted_game_id or row.get("phase") == "live":
                continue
            recorded_at = datetime.fromisoformat(row["recorded_at"].replace("Z", "+00:00"))
        except (KeyError, TypeError, ValueError):
            continue
        if recorded_at <= starts_at:
            row["_recorded_at"] = recorded_at
            return row
    return None


def locked_pregame_projection(game_id, game_datetime, snapshot=None):
    snapshot = snapshot or last_pregame_snapshot(game_id, game_datetime)
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


def locked_pregame_totals_projection(game_id, game_datetime, snapshot=None):
    snapshot = snapshot or last_pregame_snapshot(game_id, game_datetime)
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
        apply_totals_audit_selection(totals_projection)
        if totals_projection.get("automatic_builder_eligible") is None:
            totals_projection["automatic_builder_eligible"] = (
                totals_projection.get("automatic_selection_available") is True
            )
        total_keys = ("expected_total_runs", "prediction_interval_80", "recommended_line", "recommended_side", "recommended_probability", "audit_line", "audit_side", "audit_probability", "audit_push_probability", "audit_selection_rule", "audit_policy_version", "automatic_builder_eligible", "automatic_selection_available", "confidence_score", "confidence_label", "input_completeness", "confidence_explanation", "thresholds", "reasons", "market_inputs", "selection_available", "line_market", "line_selection_rule", "central_market_line", "automatic_selection_policy", "automatic_selection_rejections")
        totals_summary = {key: totals_projection.get(key) for key in total_keys}
        previous_total = _totals_projection_last.get(str(game_id))
        totals_changed = previous_total is None or any(
            previous_total.get(key) != totals_summary.get(key)
            for key in ("recommended_line", "recommended_side", "audit_line", "audit_side", "audit_push_probability", "automatic_builder_eligible")
        ) or any(
            abs(float(previous_total.get(key) or 0) - float(totals_summary.get(key) or 0)) >= .005
            for key in ("recommended_probability", "audit_probability")
        )
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
        results = [
            {**row, "correct": row["total_correct"]}
            for row in results if row.get("totals_eligible")
        ]
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
            push_legs = sum(1 for row in selections if market == "totals" and row.get("total_push"))
            decided_legs = legs - push_legs
            daily_parlays.append({
                "legs": legs, "correct_legs": correct_legs, "push_legs": push_legs,
                "leg_accuracy": correct_legs / decided_legs if decided_legs else None,
                "all_correct": decided_legs > 0 and correct_legs == decided_legs,
                "game_ids": [row["game_id"] for row in selections],
            })
    page_size = max(1, min(int(page_size or 10), 50))
    total = len(results)
    total_pages = max(1, math.ceil(total / page_size))
    page = max(1, min(int(page or 1), total_pages))
    start = (page - 1) * page_size
    games = results[start:start + page_size]
    scored = [row for row in results if not (market == "totals" and row.get("total_push"))]
    correct = sum(1 for row in scored if row["correct"])
    brier = None
    if market == "totals" and scored:
        brier = sum((float(row["total_probability"]) - int(row["total_correct"])) ** 2 for row in scored) / len(scored)
    return {
        "games": games, "evaluated": len(scored), "correct": correct,
        "pushes": sum(1 for row in results if row.get("total_push")) if market == "totals" else 0,
        "accuracy": correct / len(scored) if scored else None, "date": target_date,
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
        "strikeouts": "strikeOuts", "doubles": "doubles", "triples": "triples",
        "stolen_bases": "stolenBases",
    },
    "pitcher": {
        "strikeouts": "strikeOuts", "outs": "outs", "walks": "baseOnBalls",
        "hits_allowed": "hits", "earned_runs": "earnedRuns",
        "home_runs_allowed": "homeRuns", "pitches": "pitchesThrown", "win": "wins",
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
    try:
        if kind == "batter" and selection.get("prop") == "singles":
            return float(stats.get("hits") or 0) - float(stats.get("doubles") or 0) \
                - float(stats.get("triples") or 0) - float(stats.get("homeRuns") or 0)
        if kind == "batter" and selection.get("prop") == "hits_runs_rbi":
            return float(stats.get("hits") or 0) + float(stats.get("runs") or 0) \
                + float(stats.get("rbi") or 0)
        if not field:
            return None
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
    if _player_prop_results_cache and now - _player_prop_results_cache[0] < timedelta(minutes=15):
        results, updated_at = _player_prop_results_cache[1], _player_prop_results_cache[0].isoformat()
    else:
        snapshots = load_player_prop_snapshots()
        results = []
        if snapshots:
            earliest = min(row["_recorded_at"].date() for rows in snapshots.values() for row in rows)
            games = statsapi.schedule(start_date=earliest.isoformat(), end_date=now.date().isoformat(), sportId=1)
            eligible_games = []
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
                eligible_games.append((game, game_id, starts_at, snapshot))

            def fetch_boxscore(item):
                game_id = item[1]
                try:
                    return game_id, _player_prop_boxscore(game_id)
                except (requests.RequestException, ValueError, KeyError):
                    return game_id, None

            with ThreadPoolExecutor(max_workers=min(8, len(eligible_games) or 1)) as pool:
                boxscores = dict(pool.map(fetch_boxscore, eligible_games))

            for game, game_id, starts_at, snapshot in eligible_games:
                boxscore = boxscores.get(game_id)
                if not boxscore:
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
                audit_selection = deterministic_totals_audit_selection(total_projection)
                total_line = audit_selection.get("line") if audit_selection else None
                total_side = audit_selection.get("side") if audit_selection else None
                total_probability = audit_selection.get("probability") if audit_selection else None
                total_runs = int(game["home_score"]) + int(game["away_score"])
                totals_eligible = total_line is not None and total_side in ("over", "under") and total_probability is not None
                total_push = bool(totals_eligible and total_runs == float(total_line))
                total_correct = (
                    bool((total_runs > float(total_line)) == (total_side == "over"))
                    if totals_eligible and not total_push else None
                )
                automatic_builder_eligible = total_projection.get("automatic_builder_eligible")
                if automatic_builder_eligible is None:
                    automatic_builder_eligible = total_projection.get("automatic_selection_available") is True
                results.append({
                    "game_id": game_id, "game_date": game.get("game_date") or starts_at.date().isoformat(),
                    "starts_at": game.get("game_datetime"), "snapshot_at": snapshot["recorded_at"],
                    "home": home, "away": away, "home_score": int(game["home_score"]), "away_score": int(game["away_score"]),
                    "home_win_probability": home_probability, "away_win_probability": float(snapshot["away_win_probability"]),
                    "projected_side": projected_side, "projected_team": (home if projected_side == "home" else away),
                    "winner_side": actual_side, "winner": (home if actual_side == "home" else away), "correct": correct,
                    "totals_eligible": totals_eligible, "total_runs": total_runs, "total_line": total_line,
                    "total_side": total_side, "total_probability": total_probability, "total_correct": total_correct,
                    "total_push": total_push,
                    "total_automatic_builder_eligible": bool(automatic_builder_eligible),
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


def _player_peer_profiles():
    global _player_peer_cache
    if _player_peer_cache is not None:
        return _player_peer_cache
    groups = {}
    def number(value):
        try:
            return float(value or 0)
        except (TypeError, ValueError):
            return 0.0
    for group in ("hitting", "pitching"):
        payload = statsapi.get("stats", {"stats": "season", "group": group, "season": 2026, "playerPool": "ALL", "limit": 2000})
        splits = next((item.get("splits", []) for item in payload.get("stats", []) if item.get("group", {}).get("displayName") == group), [])
        rows = []
        for split in splits:
            stat, person = split.get("stat", {}), split.get("player", {})
            player_key = person.get("id")
            if not player_key:
                continue
            if group == "hitting":
                pa = number(stat.get("plateAppearances"))
                metrics = {
                    "AVG": number(stat.get("avg")), "OBP": number(stat.get("obp")),
                    "SLG": number(stat.get("slg")), "OPS": number(stat.get("ops")),
                    "BB rate": number(stat.get("baseOnBalls")) / pa if pa else None,
                    "K rate": number(stat.get("strikeOuts")) / pa if pa else None,
                    "Isolated power": number(stat.get("slg")) - number(stat.get("avg")),
                }
                qualified = pa >= 25
            else:
                batters = number(stat.get("battersFaced"))
                metrics = {
                    "ERA": number(stat.get("era")), "WHIP": number(stat.get("whip")),
                    "K rate": number(stat.get("strikeOuts")) / batters if batters else None,
                    "BB rate": number(stat.get("baseOnBalls")) / batters if batters else None,
                    "HR rate": number(stat.get("homeRuns")) / batters if batters else None,
                }
                qualified = batters >= 20
            rows.append({"id": int(player_key), "metrics": metrics, "qualified": qualified})
        peers = [row for row in rows if row["qualified"]]
        lower_better = {"K rate"} if group == "hitting" else {"ERA", "WHIP", "BB rate", "HR rate"}
        for row in rows:
            profile = []
            for label, value in row["metrics"].items():
                sample = [peer["metrics"].get(label) for peer in peers]
                sample = [number for number in sample if number is not None and math.isfinite(number)]
                percentile = None
                if value is not None and sample:
                    favorable = sum(number >= value for number in sample) if label in lower_better else sum(number <= value for number in sample)
                    percentile = round(favorable / len(sample) * 100)
                profile.append({"key": label.lower().replace(" ", "_"), "label": label, "value": round(value, 3) if value is not None else None, "percentile": percentile,
                    "definition": {"AVG":"Hits divided by at-bats.","OBP":"Rate of reaching base excluding errors and fielder choices.","SLG":"Total bases divided by at-bats.","OPS":"On-base percentage plus slugging percentage.","BB rate":"Walks divided by plate appearances or batters faced.","K rate":"Strikeouts divided by plate appearances or batters faced.","Isolated power":"Slugging percentage minus batting average.","ERA":"Earned runs allowed per nine innings.","WHIP":"Walks plus hits allowed per inning.","HR rate":"Home runs allowed divided by batters faced."}.get(label, "Official season rate.")})
            groups[row["id"]] = {"group": group, "sample": len(peers), "metrics": profile}
    _player_peer_cache = groups
    return groups


def normalize_player_game_logs(payload):
    """Preserve game identity and every official per-game stat for player pages."""
    people = (payload or {}).get("people") or []
    output = []
    if not people:
        return output
    for section in people[0].get("stats", []) or []:
        group = (section.get("group") or {}).get("displayName")
        if group not in ("hitting", "pitching", "fielding"):
            continue
        for split in section.get("splits", []) or []:
            game = split.get("game") or {}
            game_id = int(game.get("gamePk") or 0)
            if not game_id:
                continue
            stat = split.get("stat") or {}
            team = split.get("team") or {}
            opponent = split.get("opponent") or {}
            decision = None
            if group == "pitching":
                decision = "W" if int(stat.get("wins") or 0) else "L" if int(stat.get("losses") or 0) else "S" if int(stat.get("saves") or 0) else "ND"
            output.append({
                "game_id": game_id,
                "date": split.get("date"),
                "season": split.get("season"),
                "group": group,
                "game_type": split.get("gameType"),
                "game_number": int(game.get("gameNumber") or 1),
                "day_night": game.get("dayNight"),
                "is_home": bool(split.get("isHome")),
                "team_win": bool(split.get("isWin")),
                "decision": decision,
                "team_id": int(team.get("id") or 0) or None,
                "team": team.get("name"),
                "opponent_id": int(opponent.get("id") or 0) or None,
                "opponent": opponent.get("name") or "Unknown opponent",
                "positions": [position.get("abbreviation") for position in split.get("positionsPlayed", []) or [] if position.get("abbreviation")],
                "summary": stat.get("summary"),
                "stats": stat,
            })
    return sorted(output, key=lambda row: (row.get("date") or "", row["game_id"], row["group"]))


def player_game_logs(player_id, season):
    raw = statsapi.get("person", {
        "personId": int(player_id),
        "hydrate": (
            "stats(group=[hitting,pitching,fielding],type=gameLog,"
            f"season={int(season)},sportId=1),currentTeam"
        ),
    })
    return normalize_player_game_logs(raw)


def player_detail(player_id):
    player_id = int(player_id)
    current_season = datetime.now(timezone.utc).year
    season = statsapi.player_stat_data(
        player_id, group="[hitting,pitching,fielding]", type="season", season=current_season,
    )
    try:
        season["game_log"] = player_game_logs(player_id, current_season)
    except Exception:
        season["game_log"] = []
    try:
        season["peer_profile"] = _player_peer_profiles().get(player_id)
    except Exception:
        season["peer_profile"] = None
    return season


def _pitcher_game_line(split):
    stat = split.get("stat", {})
    decision = "W" if int(stat.get("wins") or 0) else "L" if int(stat.get("losses") or 0) else "ND"
    opponent = split.get("opponent", {})
    return {
        "game_id": (split.get("game") or {}).get("gamePk"),
        "date": split.get("date"),
        "opponent_id": opponent.get("id"),
        "opponent": opponent.get("name") or "Unknown opponent",
        "venue": "home" if split.get("isHome") else "away",
        "decision": decision,
        "team_result": "W" if split.get("isWin") else "L",
        "innings": stat.get("inningsPitched"),
        "hits": stat.get("hits"),
        "runs": stat.get("runs"),
        "earned_runs": stat.get("earnedRuns"),
        "walks": stat.get("baseOnBalls"),
        "strikeouts": stat.get("strikeOuts"),
        "home_runs": stat.get("homeRuns"),
        "pitches": stat.get("numberOfPitches"),
    }


def _guarantee_wilson_lower(wins, samples, z=1.282):
    """Return an 80% Wilson lower bound for a compact, sample-aware rank."""
    if samples <= 0:
        return 0.0
    rate = wins / samples
    denominator = 1 + z * z / samples
    centre = rate + z * z / (2 * samples)
    margin = z * math.sqrt(rate * (1 - rate) / samples + z * z / (4 * samples * samples))
    return max(0.0, (centre - margin) / denominator)


def player_prop_guarantees(minimum_samples=1, search=None, prop_types=None):
    """Aggregate immutable prop predictions by player and exact pick identity.

    The user-facing name is Guarantee List, but the ranking is deliberately a
    historical consistency measure rather than a future-certainty claim.
    """
    global _player_prop_guarantee_cache
    try:
        fingerprint = os.path.getmtime(LIVE_PLAYER_PROPS_AUDIT)
    except OSError:
        fingerprint = None
    with _player_prop_guarantee_lock:
        if not _player_prop_guarantee_cache or _player_prop_guarantee_cache[0] != fingerprint:
            try:
                with open(LIVE_PLAYER_PROPS_AUDIT, encoding="utf-8") as handle:
                    audit = json.load(handle)
            except (OSError, json.JSONDecodeError):
                audit = {}
            groups = {}
            for row in audit.get("rows") or []:
                try:
                    key = (
                        int(row["player_id"]), str(row["kind"]), str(row["prop"]),
                        str(row["side"]).lower(), float(row["line"]),
                    )
                    actual = int(row["actual"])
                    probability = float(row.get("probability") or .5)
                except (KeyError, TypeError, ValueError):
                    continue
                group = groups.setdefault(key, {
                    "player_id": key[0], "player_name": row.get("player") or row.get("player_name") or f"Player {key[0]}",
                    "kind": key[1], "prop": key[2], "side": key[3], "line": key[4], "rows": [],
                })
                group["rows"].append({
                    "date": row.get("official_date") or row.get("date"),
                    "actual": actual, "probability": probability, "value": row.get("value"),
                })
            records = []
            for group in groups.values():
                rows = sorted(group.pop("rows"), key=lambda item: item.get("date") or "")
                samples = len(rows)
                wins = sum(row["actual"] for row in rows)
                recent = rows[-10:]
                streak = 0
                for row in reversed(rows):
                    if row["actual"] != 1:
                        break
                    streak += 1
                accuracy = wins / samples
                brier = sum((row["probability"] - row["actual"]) ** 2 for row in rows) / samples
                lower = _guarantee_wilson_lower(wins, samples)
                evidence = "established" if samples >= 10 else "developing" if samples >= 5 else "early"
                records.append({
                    **group, "label": group["prop"].replace("_", " ").title(),
                    "samples": samples, "correct": wins, "accuracy": round(accuracy, 6),
                    "brier_score": round(brier, 6), "wilson_lower": round(lower, 6),
                    "consistency_score": round(lower * min(1.0, samples / 10), 6),
                    "current_streak": streak, "recent_10_correct": sum(row["actual"] for row in recent),
                    "recent_10_samples": len(recent), "first_date": rows[0].get("date"),
                    "last_date": rows[-1].get("date"), "evidence": evidence,
                })
            records.sort(key=lambda row: (row["consistency_score"], row["samples"], row["accuracy"]), reverse=True)
            _player_prop_guarantee_cache = (fingerprint, records)
        records = list(_player_prop_guarantee_cache[1])
    minimum_samples = max(1, min(int(minimum_samples or 1), 100))
    records = [row for row in records if row["samples"] >= minimum_samples]
    if prop_types:
        wanted = {str(value).lower() for value in prop_types}
        records = [row for row in records if f"{row['kind']}:{row['prop']}".lower() in wanted]
    if search:
        needle = str(search).strip().lower()
        records = [row for row in records if needle in row["player_name"].lower()]
    total_predictions = sum(row["samples"] for row in records)
    return {
        "records": records, "players": len({row["player_id"] for row in records}),
        "exact_picks": len(records), "predictions": total_predictions,
        "minimum_samples": minimum_samples,
        "updated_at": datetime.fromtimestamp(fingerprint, timezone.utc).isoformat() if fingerprint else None,
        "method": "Same player, role, prop, side and exact line across immutable pregame predictions",
        "ranking": "80% Wilson lower bound multiplied by evidence maturity through ten settled samples",
        "warning": "Historical consistency is not a guarantee of the next outcome.",
    }


def _pitcher_venue_split(split):
    stat = split.get("stat", {})
    return {
        "record": f"{int(stat.get('wins') or 0)}-{int(stat.get('losses') or 0)}",
        "wins": int(stat.get("wins") or 0),
        "losses": int(stat.get("losses") or 0),
        "era": stat.get("era"),
        "whip": stat.get("whip"),
        "innings": stat.get("inningsPitched"),
        "starts": int(stat.get("gamesStarted") or 0),
    }


def pitcher_profile(person, game_datetime=None, current_game_id=None):
    if not person or not person.get("id"):
        return None
    player_id = int(person["id"])
    try:
        season = int(str(game_datetime)[:4]) if game_datetime else datetime.now(timezone.utc).year
    except (TypeError, ValueError):
        season = datetime.now(timezone.utc).year
    cache_key = (player_id, season, int(current_game_id or 0))
    cached = _pitcher_profile_cache.get(cache_key)
    if cached and datetime.now(timezone.utc) - cached[0] < timedelta(minutes=10):
        return cached[1]
    params = {
        "personId": player_id,
        "hydrate": (
            "stats(group=[pitching],type=[season,gameLog,homeAndAway],"
            f"season={season},sportId=1),currentTeam"
        ),
    }
    raw = statsapi.get("person", params)
    profile = (raw.get("people") or [{}])[0]
    sections = {
        item.get("type", {}).get("displayName"): item.get("splits", [])
        for item in profile.get("stats", [])
        if item.get("group", {}).get("displayName") == "pitching"
    }
    season_splits = sections.get("season") or []
    pitching = season_splits[0].get("stat", {}) if season_splits else {}
    cutoff_date = str(game_datetime or "")[:10]
    prior_starts = [
        split for split in sections.get("gameLog", [])
        if int(split.get("stat", {}).get("gamesStarted") or 0) > 0
        and int((split.get("game") or {}).get("gamePk") or 0) != int(current_game_id or 0)
        and (not cutoff_date or str(split.get("date") or "")[:10] < cutoff_date)
    ]
    prior_starts.sort(key=lambda split: split.get("date") or "", reverse=True)
    venue_splits = {
        "home" if split.get("isHome") else "away": _pitcher_venue_split(split)
        for split in sections.get("homeAndAway", [])
    }
    innings = _innings_pitched(pitching.get("inningsPitched"))
    strikeouts = _float(pitching.get("strikeOuts"))
    walks = _float(pitching.get("baseOnBalls"))
    home_runs = _float(pitching.get("homeRuns"))
    starts = len(prior_starts)
    runs_allowed = sum(_float(split.get("stat", {}).get("runs")) for split in prior_starts)
    earned_runs_allowed = sum(_float(split.get("stat", {}).get("earnedRuns")) for split in prior_starts)
    fip = (
        (13 * home_runs + 3 * walks - 2 * strikeouts) / innings + 3.1
        if innings > 0 else 4.5
    )
    result = {
        "id": person.get("id"), "name": person.get("fullName"),
        "team": (profile.get("currentTeam") or {}).get("name"),
        "team_id": (profile.get("currentTeam") or {}).get("id"),
        "position": (profile.get("primaryPosition") or {}).get("abbreviation"),
        "era": pitching.get("era"), "whip": pitching.get("whip"),
        "innings": pitching.get("inningsPitched"), "innings_decimal": innings,
        "strikeouts": pitching.get("strikeOuts"),
        "walks": pitching.get("baseOnBalls"), "wins": pitching.get("wins"), "losses": pitching.get("losses"),
        "home_runs": pitching.get("homeRuns"), "fip": round(fip, 3),
        "starts_before_matchup": starts,
        "runs_per_start": round(runs_allowed / starts, 2) if starts else None,
        "earned_runs_per_start": round(earned_runs_allowed / starts, 2) if starts else None,
        "home_away": venue_splits,
        "recent_starts": [_pitcher_game_line(split) for split in prior_starts[:5]],
    }
    _pitcher_profile_cache[cache_key] = (datetime.now(timezone.utc), result)
    return result


class Handler(BaseHTTPRequestHandler):
    def parsed_request(self):
        """Accept both direct local paths and the public /api/stats mount."""
        parsed = urlparse(self.path)
        prefix = "/api/stats"
        if parsed.path == prefix:
            return parsed._replace(path="/")
        if parsed.path.startswith(prefix + "/"):
            return parsed._replace(path=parsed.path[len(prefix):])
        return parsed

    def send_json(self, payload, status=200):
        body = json.dumps(payload, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "http://localhost:5173")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = self.parsed_request()
        query = parse_qs(parsed.query)
        try:
            release_sync = None
            if parsed.path in {
                "/health", "/model", "/model/results", "/projection-board",
                "/player-props", "/player-props/guarantees",
            }:
                release_sync = ensure_runtime_release()
            if parsed.path == "/health":
                self.send_json({
                    "status": "ok", "provider": "MLB-StatsAPI", "version": statsapi.__version__,
                    "maintenance": maintenance_status(), "projection_monitor": _projection_monitor,
                    "player_prop_monitor": _player_prop_monitor,
                    "maintenance_catchup": _maintenance_catchup,
                    "model_release": runtime_release_status(),
                    "model_sync": release_sync,
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
                    try:
                        with open(LIVE_PLAYER_PROPS_AUDIT, "r", encoding="utf-8") as handle:
                            report["player_props_model"]["live_shadow_audit"] = json.load(handle)
                    except (OSError, json.JSONDecodeError):
                        report["player_props_model"]["live_shadow_audit"] = None
                    try:
                        with open(PLAYER_PROP_RERANKER_SHADOW_AUDIT, "r", encoding="utf-8") as handle:
                            report["player_props_model"]["reranker_shadow_candidate"] = json.load(handle)
                    except (OSError, json.JSONDecodeError):
                        report["player_props_model"]["reranker_shadow_candidate"] = None
                except (OSError, json.JSONDecodeError):
                    report["player_props_model"] = None
                report["maintenance"] = maintenance_status()
                report["model_release"] = runtime_release_status()
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
            elif parsed.path == "/player-props/guarantees":
                prop_types = [
                    value for item in query.get("prop_types", [])
                    for value in str(item).split(",") if str(value).strip()
                ] or None
                self.send_json(player_prop_guarantees(
                    query.get("minimum_samples", [1])[0],
                    query.get("search", [None])[0], prop_types,
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
            elif parsed.path == "/alter-ego":
                self.send_json(melbet_history_snapshot())
            else:
                self.send_json({"error": "Not found"}, 404)
        except NotFoundError as exc:
            self.send_json({"error": str(exc), "provider": "MLB-StatsAPI"}, 404)
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else 502
            if status == 404:
                self.send_json({"error": "MLB resource not found", "provider": "MLB-StatsAPI"}, 404)
            else:
                self.send_json({"error": "The MLB data provider request failed", "provider": "MLB-StatsAPI"}, 502)
        except Exception as exc:
            print(f"[mlb-stats] request failed: {exc}", flush=True)
            self.send_json({"error": "The MLB data provider request failed", "provider": "MLB-StatsAPI"}, 502)

    def do_POST(self):
        parsed = self.parsed_request()
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            if parsed.path == "/slips/import":
                slip = save_slip(parse_pdf(payload["data"], payload.get("filename", "slip.pdf")))
                queue_slip_refresh()
                self.send_json(slip, 201)
            elif parsed.path == "/slips/parse":
                self.send_json(parse_pdf(payload["data"], payload.get("filename", "slip.pdf")), 200)
            elif parsed.path == "/alter-ego/normalize":
                self.send_json(normalize_melbet_history_slip(payload.get("slip") or payload), 200)
            elif parsed.path == "/alter-ego/normalize-batch":
                slips = payload.get("slips") or []
                if not isinstance(slips, list) or not slips or len(slips) > 500:
                    raise ValueError("MelBet batch import must contain between 1 and 500 slips.")
                self.send_json({"slips": [normalize_melbet_history_slip(slip) for slip in slips]}, 200)
            elif parsed.path == "/alter-ego/analyse":
                slips = payload.get("slips") or []
                if not isinstance(slips, list) or len(slips) > 5000:
                    raise ValueError("Alter Ego analysis accepts no more than 5,000 slips.")
                self.send_json(analyse_melbet_history({"version": 1, "slips": slips}), 200)
            elif parsed.path == "/alter-ego/import":
                save_melbet_history_slip(payload.get("slip") or payload)
                self.send_json(melbet_history_snapshot(), 201)
            elif parsed.path == "/alter-ego/import-batch":
                result = save_melbet_history_slips(payload.get("slips") or [])
                self.send_json({"import": result, "analysis": melbet_history_snapshot()}, 201)
            elif parsed.path == "/player-props/build-snapshots":
                self.send_json(record_player_prop_build(payload), 201)
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
    pregame_seconds = max(60, int(os.getenv("NINTH_PREGAME_REFRESH_SECONDS", "300")))
    live_seconds = max(5, int(os.getenv("NINTH_LIVE_REFRESH_SECONDS", "10")))
    discovery_seconds = max(30, int(os.getenv("NINTH_GAME_DISCOVERY_SECONDS", "60")))
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
                        # Live state is urgent. Ordinary pregame work is spread
                        # across its five-minute window so a cold start cannot
                        # launch the entire slate at once.
                        stagger = 0 if is_live else (game_id * 97) % pregame_seconds
                        next_due[game_id] = monotonic_now + stagger
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
    """Run guarded data/model maintenance once nightly, never at startup."""
    if os.getenv("NINTH_MAINTENANCE_ENABLED", "1").lower() in ("0", "false", "no"):
        return
    while True:
        now = datetime.now().astimezone()
        hour = max(0, min(23, int(os.getenv("NINTH_MAINTENANCE_HOUR", "11"))))
        minute = max(0, min(59, int(os.getenv("NINTH_MAINTENANCE_MINUTE", "15"))))
        next_run = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if next_run <= now:
            next_run += timedelta(days=1)
        time.sleep(max(1, (next_run - now).total_seconds()))
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


if __name__ == "__main__":
    queue_lightweight_maintenance_catchup()
    threading.Thread(target=projection_refresh_loop, name="projection-refresh", daemon=True).start()
    threading.Thread(target=maintenance_loop, name="model-maintenance", daemon=True).start()
    threading.Thread(target=player_prop_archive_loop, name="player-props-archive", daemon=True).start()
    print(f"MLB Stats provider listening on {HOST}:{PORT}")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
