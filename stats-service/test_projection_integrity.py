import importlib.util
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch


APP_PATH = Path(__file__).with_name("app.py")
SPEC = importlib.util.spec_from_file_location("ninth_stats_app", APP_PATH)
APP = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(APP)


class ProjectionIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.original_log = APP.PROJECTION_LOG
        self.original_player_prop_log = APP.PLAYER_PROP_PROJECTION_LOG
        APP.PROJECTION_LOG = str(Path(self.temp.name) / "projection_snapshots.jsonl")
        APP.PLAYER_PROP_PROJECTION_LOG = str(Path(self.temp.name) / "player_prop_projection_snapshots.jsonl")
        APP._projection_last.clear()
        APP._projection_last_context.clear()
        APP._projection_last_completeness.clear()
        APP._projection_last_game_state.clear()
        APP._projection_recent_alerts.clear()
        APP._totals_projection_last.clear()
        APP._prediction_results_cache = None
        APP._player_prop_results_cache = None
        APP._player_prop_snapshot_last.clear()
        APP._player_prop_boxscore_cache.clear()
        APP._weather_cache.clear()
        APP._weather_backoff_until = 0.0
        APP._melbet_totals_cache.update({"updated_at": APP.datetime.now(APP.timezone.utc), "last_attempt_at": None, "markets": [], "error": None})
        APP._melbet_player_props_cache.update({"updated_at": APP.datetime.now(APP.timezone.utc), "last_attempt_at": None, "markets": [], "error": None})

    def tearDown(self):
        APP.PROJECTION_LOG = self.original_log
        APP.PLAYER_PROP_PROJECTION_LOG = self.original_player_prop_log
        APP._weather_cache.clear()
        APP._weather_backoff_until = 0.0
        self.temp.cleanup()

    def write_rows(self, rows):
        with open(APP.PROJECTION_LOG, "w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row) + "\n")

    def test_final_projection_uses_last_snapshot_before_first_pitch(self):
        self.write_rows([
            {"game_id": 823443, "recorded_at": "2026-07-14T23:42:56+00:00", "home_win_probability": .5109, "away_win_probability": .4891, "reasons": [], "context": {}},
            {"game_id": 823443, "recorded_at": "2026-07-14T23:50:00+00:00", "phase": "live", "home_win_probability": .47, "away_win_probability": .53, "reasons": [], "context": {}},
            {"game_id": 823443, "recorded_at": "2026-07-15T03:13:00+00:00", "home_win_probability": .4494, "away_win_probability": .5506, "reasons": [], "context": {}},
        ])
        projection = APP.locked_pregame_projection(823443, "2026-07-15T00:00:00Z")
        self.assertEqual(projection["projected_side"], "home")
        self.assertEqual(projection["home_win_probability"], .5109)
        self.assertEqual(projection["snapshot_at"], "2026-07-14T23:42:56+00:00")
        self.assertEqual(projection["projection_source"], "pregame_locked")

    def test_final_status_never_writes_a_projection_snapshot(self):
        projection = {"available": True, "home_win_probability": .55, "away_win_probability": .45}
        APP.record_projection(823443, projection, {}, "Final", "2026-07-15T00:00:00Z")
        self.assertFalse(Path(APP.PROJECTION_LOG).exists())

    def test_live_snapshot_is_explicitly_marked_live(self):
        projection = {"available": True, "home_win_probability": .55, "away_win_probability": .45, "reasons": []}
        APP.record_projection(823443, projection, {}, "Live", "2026-07-15T00:00:00Z")
        with open(APP.PROJECTION_LOG, encoding="utf-8") as handle:
            row = json.loads(handle.readline())
        self.assertEqual(row["phase"], "live")
        self.assertEqual(row["scheduled_start"], "2026-07-15T00:00:00Z")

    def test_totals_forecast_is_archived_and_locked_before_first_pitch(self):
        projection = {"available": True, "home_win_probability": .55, "away_win_probability": .45, "reasons": []}
        totals = {"available": True, "expected_total_runs": 8.9, "prediction_interval_80": [3.4, 14.5], "recommended_line": 10.5, "recommended_side": "under", "recommended_probability": .69, "confidence_score": 66, "confidence_label": "Moderate", "input_completeness": .8, "thresholds": [], "reasons": []}
        scheduled = (APP.datetime.now(APP.timezone.utc) + APP.timedelta(days=1)).replace(microsecond=0).isoformat()
        with patch.object(APP, "load_totals_bundle", return_value={"report": {"model": "test"}}):
            APP.record_projection(823443, projection, {}, "Preview", scheduled, totals)
            locked = APP.locked_pregame_totals_projection(823443, scheduled)
        self.assertTrue(locked["available"])
        self.assertEqual(locked["recommended_side"], "under")
        self.assertEqual(locked["recommended_line"], 10.5)
        self.assertEqual(locked["projection_source"], "pregame_locked")

    def test_live_score_inning_and_base_out_state_move_projection(self):
        projection = {"available": True, "home_win_probability": .50, "away_win_probability": .50, "reasons": [], "historical_tier": {"accuracy": .60}}
        linescore = {"currentInning": 8, "inningState": "Bottom", "teams": {"home": {"runs": 4}, "away": {"runs": 2}}, "offense": {"first": {"id": 1}, "second": None, "third": None}}
        live = APP.apply_live_game_state(projection, linescore, {"outs": 1})
        self.assertGreater(live["home_win_probability"], .50)
        self.assertEqual(live["projection_source"], "live_game_state")
        self.assertEqual(live["projection_phase"], "live")
        self.assertEqual(live["game_state"]["inning"], 8)
        self.assertIsNone(live["historical_tier"])

    def test_live_runs_and_remaining_innings_condition_totals(self):
        projection = {"available": True, "expected_total_runs": 8.8, "recommended_line": 10.5, "recommended_side": "under", "recommended_probability": .69, "thresholds": [{"line": line, "over_probability": .5, "under_probability": .5} for line in (6.5, 7.5, 8.5, 9.5, 10.5, 11.5)], "model": {"decision_lines": [7.5, 8.5, 9.5, 10.5]}, "reasons": []}
        linescore = {"currentInning": 7, "inningState": "Top", "teams": {"home": {"runs": 5}, "away": {"runs": 4}}}
        live = APP.apply_live_total_state(projection, linescore, {"outs": 1})
        self.assertEqual(live["projection_source"], "live_run_state")
        self.assertEqual(live["projection_phase"], "live")
        self.assertEqual(live["live_state"]["runs_scored"], 9)
        self.assertGreater(live["thresholds"][0]["over_probability"], .99)

    def test_input_coverage_change_is_archived_without_probability_move(self):
        first = {"available": True, "home_win_probability": .55, "away_win_probability": .45, "input_completeness": .5, "reasons": []}
        second = {"available": True, "home_win_probability": .55, "away_win_probability": .45, "input_completeness": .7, "reasons": []}
        APP.record_projection(823443, first, {}, "Preview", "2026-07-15T00:00:00Z")
        APP.record_projection(823443, second, {}, "Preview", "2026-07-15T00:00:00Z")
        unchanged = APP.record_projection(823443, dict(second), {}, "Preview", "2026-07-15T00:00:00Z")
        with open(APP.PROJECTION_LOG, encoding="utf-8") as handle:
            rows = [json.loads(line) for line in handle]
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[-1]["circumstance_alerts"][0]["type"], "input_coverage_change")
        self.assertEqual(unchanged["circumstance_alerts"][0]["type"], "input_coverage_change")

    def test_weather_rate_limit_does_not_break_a_projection_request(self):
        class RateLimitedResponse:
            status_code = 429
            headers = {"Retry-After": "120"}

        with patch.object(APP.requests, "get", return_value=RateLimitedResponse()):
            result = APP.open_meteo_weather(40.82919482, -73.9264977, "2026-07-17T23:05:00Z")

        self.assertIsNone(result)
        self.assertGreater(APP._weather_backoff_until, 0.0)

    def test_weather_cooldown_serves_stale_cache(self):
        target_time = (APP.datetime.now(APP.timezone.utc) + APP.timedelta(days=1)).replace(hour=23, minute=5, second=0, microsecond=0)
        target = target_time.isoformat().replace("+00:00", "Z")
        key = f"40.829:-73.926:{target_time.date().isoformat()}:23:forecast"
        cached = {"temperature": 78, "wind_speed": 8, "condition": "Clear", "source": "Open-Meteo forecast", "available": True}
        APP._weather_cache[key] = (APP.time.monotonic() - 1900, cached)
        APP._weather_backoff_until = APP.time.monotonic() + 120

        with patch.object(APP.requests, "get") as weather_request:
            result = APP.open_meteo_weather(40.82919482, -73.9264977, target)

        weather_request.assert_not_called()
        self.assertEqual(result["temperature"], 78)
        self.assertIn("cached during provider cooldown", result["source"])

    def test_slip_refresh_is_backgrounded_and_deduplicated(self):
        started, release = threading.Event(), threading.Event()
        pending = {"id": "test-slip", "active": True, "selections": [{"outcome": "pending"}]}

        def slow_enrichment(item):
            started.set()
            release.wait(2)
            return item

        with patch.object(APP, "slip_snapshot", return_value=[pending]), \
             patch.object(APP, "enrich_slip", side_effect=slow_enrichment), \
             patch.object(APP, "save_slip"):
            self.assertTrue(APP.queue_slip_refresh())
            self.assertTrue(started.wait(1))
            self.assertFalse(APP.queue_slip_refresh())
            release.set()
            deadline = time.monotonic() + 2
            while APP._slip_refresh_state["running"] and time.monotonic() < deadline:
                time.sleep(.01)

        self.assertFalse(APP._slip_refresh_state["running"])

    def test_slip_matching_uses_time_not_first_team_pair(self):
        slip = {
            "id": "series-slip", "placed_at": "18/07/2026 19:49", "imported_at": "2026-07-18T19:50:00",
            "selections": [{
                "event_code": "1", "scheduled_local": "2026-07-19T23:07:00",
                "team_1": "Los Angeles Angels", "team_2": "Detroit Tigers",
                "selected_team": "Los Angeles Angels", "outcome": "won", "game_id": 824009,
            }],
        }
        games = [
            {"game_id": 824009, "game_datetime": "2026-07-19T02:07:00Z", "away_name": "Detroit Tigers", "home_name": "Los Angeles Angels", "status": "Final", "away_score": 2, "home_score": 3},
            {"game_id": 824007, "game_datetime": "2026-07-19T20:07:00Z", "away_name": "Detroit Tigers", "home_name": "Los Angeles Angels", "status": "Scheduled", "away_score": None, "home_score": None},
        ]
        projection = {"available": True, "home_win_probability": .54, "away_win_probability": .46, "confidence_score": 58, "confidence_label": "Low", "circumstance_alerts": []}

        with patch.object(APP.statsapi, "schedule", return_value=games), patch.object(APP, "game_detail", return_value={"projection": projection}):
            enriched = APP.enrich_slip(slip)

        selection = enriched["selections"][0]
        self.assertEqual(selection["game_id"], 824007)
        self.assertEqual(selection["status"], "Scheduled")
        self.assertEqual(selection["outcome"], "pending")
        self.assertTrue(enriched["active"])

    def test_doubleheader_team_labels_normalize_to_the_mlb_team(self):
        self.assertEqual(APP.normalize_slip_team("Game 1 Boston Red Sox"), APP.normalize_slip_team("Boston Red Sox"))

    def test_postponed_ticketed_game_is_void_and_not_moved_to_replacement(self):
        slip = {
            "id": "moved-slip", "placed_at": "17/07/2026 20:18", "imported_at": "2026-07-17T20:19:00",
            "selections": [{
                "event_code": "1", "scheduled_local": "2026-07-18T02:10:00",
                "team_1": "Cleveland Guardians", "team_2": "Pittsburgh Pirates",
                "selected_team": "Cleveland Guardians", "outcome": "pending", "game_id": 824414,
            }],
        }
        games = [
            {"game_id": 824414, "game_datetime": "2026-07-17T23:10:00Z", "away_name": "Pittsburgh Pirates", "home_name": "Cleveland Guardians", "status": "Postponed", "away_score": None, "home_score": None},
            {"game_id": 900001, "game_datetime": "2026-07-18T23:10:00Z", "away_name": "Pittsburgh Pirates", "home_name": "Cleveland Guardians", "status": "Final", "away_score": 2, "home_score": 4},
        ]

        with patch.object(APP.statsapi, "schedule", return_value=games):
            enriched = APP.enrich_slip(slip)

        selection = enriched["selections"][0]
        self.assertEqual(selection["game_id"], 824414)
        self.assertEqual(selection["status"], "Postponed")
        self.assertEqual(selection["outcome"], "void")
        self.assertFalse(enriched["active"])

    def test_final_total_legs_settle_over_under_and_integer_push(self):
        base = {
            "scheduled_local": "2026-07-22T02:07:00", "team_1": "Toronto Blue Jays",
            "team_2": "Tampa Bay Rays", "market": "totals", "game_id": None,
            "status": "unmatched", "outcome": "pending", "alerts": [],
        }
        slip = {
            "id": "totals-slip", "placed_at": "21/07 15:39", "imported_at": "2026-07-21T15:40:00",
            "selections": [
                {**base, "event_code": "1", "selection": "Total Over (6)", "selected_team": "Over 6 total runs", "total_side": "over", "total_line": 6.0},
                {**base, "event_code": "2", "selection": "Total Under (7.5)", "selected_team": "Under 7.5 total runs", "total_side": "under", "total_line": 7.5},
                {**base, "event_code": "3", "selection": "Total Under (7)", "selected_team": "Under 7 total runs", "total_side": "under", "total_line": 7.0},
            ],
        }
        games = [{
            "game_id": 1, "game_datetime": "2026-07-21T23:07:00Z", "away_name": "Tampa Bay Rays",
            "home_name": "Toronto Blue Jays", "status": "Final", "away_score": 3, "home_score": 4,
        }]

        with patch.object(APP.statsapi, "schedule", return_value=games):
            enriched = APP.enrich_slip(slip)

        self.assertEqual([row["outcome"] for row in enriched["selections"]], ["won", "won", "void"])
        self.assertTrue(all(row["final_total_runs"] == 7 for row in enriched["selections"]))
        self.assertFalse(enriched["active"])

    def test_prediction_results_filter_by_mlb_date_and_paginate(self):
        results = [
            {"game_id": 3, "game_date": "2026-07-19", "correct": True, "home_win_probability": .58, "away_win_probability": .42},
            {"game_id": 2, "game_date": "2026-07-19", "correct": False, "home_win_probability": .31, "away_win_probability": .69},
            {"game_id": 1, "game_date": "2026-07-18", "correct": True, "home_win_probability": .62, "away_win_probability": .38},
        ]

        daily = APP.prediction_results_page(results, "2026-07-19", page=1, page_size=10)
        second_page = APP.prediction_results_page(results, page=2, page_size=2)

        self.assertEqual([row["game_id"] for row in daily["games"]], [3, 2])
        self.assertEqual(daily["evaluated"], 2)
        self.assertEqual(daily["correct"], 1)
        self.assertEqual(daily["accuracy"], .5)
        self.assertEqual(daily["daily_parlays"][0]["legs"], 2)
        self.assertEqual(daily["daily_parlays"][0]["correct_legs"], 1)
        self.assertFalse(daily["daily_parlays"][0]["all_correct"])
        self.assertEqual(second_page["total_pages"], 2)
        self.assertEqual([row["game_id"] for row in second_page["games"]], [1])

    def test_prediction_results_score_totals_separately(self):
        results = [
            {"game_id": 1, "game_date": "2026-07-19", "starts_at": "2026-07-19T18:00:00Z", "correct": False, "home_win_probability": .6, "away_win_probability": .4, "totals_eligible": True, "total_probability": .7, "total_correct": True},
            {"game_id": 2, "game_date": "2026-07-19", "starts_at": "2026-07-19T19:00:00Z", "correct": True, "home_win_probability": .55, "away_win_probability": .45, "totals_eligible": True, "total_probability": .6, "total_correct": False},
        ]
        page = APP.prediction_results_page(results, market="totals")
        self.assertEqual(page["correct"], 1)
        self.assertEqual(page["evaluated"], 2)
        self.assertAlmostEqual(page["brier_score"], (.3**2 + .6**2) / 2)

    def test_melbet_full_game_total_parser_discards_prices(self):
        payload = {"Value": {"GE": [{"G": 17, "E": [
            [[{"T": 9, "P": 8.5, "C": 1.7}, {"T": 10, "P": 8.5, "C": 2.1}]],
            [[{"T": 9, "P": 9.5, "C": 2.2}, {"T": 10, "P": 9.5, "C": 1.6}]],
        ]}]}}

        class Response:
            def raise_for_status(self):
                return None
            def json(self):
                return payload

        game = {"bookmaker_game_id": 123, "home_name": "Home", "away_name": "Away", "starts_at": "2026-07-22T17:05:00+00:00"}
        with patch.object(APP.requests, "get", return_value=Response()):
            market = APP._fetch_melbet_game_totals(game)

        self.assertEqual(market["lines"], [8.5, 9.5])
        self.assertNotIn("C", market)

    def test_melbet_champ_feed_falls_back_to_proxy_after_primary_failure(self):
        payload = {"Value": {"G": [{"CI": 123}]}}

        class Response:
            def raise_for_status(self):
                return None
            def json(self):
                return payload

        with patch.object(APP.requests, "get", side_effect=[APP.requests.Timeout("primary timeout"), Response()]) as fetch:
            result = APP._melbet_champ_payload()

        self.assertEqual(result["G"], [{"CI": 123}])
        self.assertEqual(result["_ninth_melbet_host"], APP.MELBET_PROXY_BASE)
        self.assertTrue(fetch.call_args_list[0].args[0].startswith(APP.MELBET_PRIMARY_BASE))
        self.assertTrue(fetch.call_args_list[1].args[0].startswith(APP.MELBET_PROXY_BASE))

    def test_melbet_totals_feed_falls_back_when_primary_market_is_empty(self):
        empty = {"Value": {"GE": []}}
        listed = {"Value": {"GE": [{"G": 17, "E": [[
            {"T": 9, "P": 8.5}, {"T": 10, "P": 8.5},
        ]]}]}}

        class Response:
            def __init__(self, payload):
                self.payload = payload
            def raise_for_status(self):
                return None
            def json(self):
                return self.payload

        game = {"bookmaker_game_id": 123, "home_name": "Home", "away_name": "Away", "starts_at": "2026-07-22T17:05:00+00:00"}
        with patch.object(APP.requests, "get", side_effect=[Response(empty), Response(listed)]) as fetch:
            market = APP._fetch_melbet_game_totals(game)

        self.assertEqual(market["lines"], [8.5])
        self.assertEqual(market["feed_host"], APP.MELBET_PROXY_BASE)
        self.assertTrue(fetch.call_args_list[0].args[0].startswith(APP.MELBET_PRIMARY_BASE))
        self.assertTrue(fetch.call_args_list[1].args[0].startswith(APP.MELBET_PROXY_BASE))

    def test_melbet_event_id_survives_when_totals_are_not_listed(self):
        payload = {
            "G": [{
                "CI": 123, "O1": "Home", "O2": "Away",
                "S": int(APP.datetime(2026, 7, 22, 17, 5, tzinfo=APP.timezone.utc).timestamp()),
            }],
            "_ninth_melbet_host": APP.MELBET_PROXY_BASE,
        }
        with patch.object(APP, "_melbet_champ_payload", return_value=payload), patch.object(APP, "_safe_fetch_melbet_game_totals", return_value=None):
            snapshot = APP.melbet_totals_markets(force=True)

        self.assertEqual(snapshot["markets"][0]["bookmaker_game_id"], 123)
        self.assertEqual(snapshot["markets"][0]["lines"], [])
        market = APP.match_melbet_totals("Home", "Away", "2026-07-22T17:05:00Z", snapshot)
        self.assertFalse(market["available"])
        self.assertEqual(market["bookmaker_game_id"], 123)
        self.assertEqual(market["feed_host"], APP.MELBET_PROXY_BASE)

    def test_melbet_player_prop_parser_requires_both_sides_and_discards_prices(self):
        payload = {"GE": [{"G": 8527, "E": [[
            {"T": 8091, "P": .5, "PL": {"N": "Aaron Judge", "I": 1}, "C": 1.4},
            {"T": 8092, "P": .5, "PL": {"N": "Aaron Judge", "I": 1}, "C": 2.8},
            {"T": 8091, "P": 1.5, "PL": {"N": "Aaron Judge", "I": 1}, "C": 2.2},
        ]]}]}
        players = APP._parse_melbet_player_prop_groups(payload)
        self.assertEqual(players["aaronjudge"]["props"], {"hits": [.5]})
        self.assertNotIn("C", json.dumps(players))

    def test_melbet_player_prop_group_ids_match_visible_market_labels(self):
        def group(group_id):
            return {"G": group_id, "E": [[
                {"T": 8091, "P": .5, "PL": {"N": "Aaron Judge"}},
                {"T": 8092, "P": .5, "PL": {"N": "Aaron Judge"}},
            ]]}

        players = APP._parse_melbet_player_prop_groups({"GE": [
            group(2891), group(10713), group(10956), group(10714), group(10469),
        ]})

        self.assertEqual(players["aaronjudge"]["props"], {
            "strikeouts": [.5], "hits_allowed": [.5], "doubles": [.5], "rbi": [.5],
        })
        self.assertNotIn("stolen_bases", players["aaronjudge"]["props"])

    def test_melbet_player_props_follow_regular_game_sg_link(self):
        game = {"bookmaker_game_id": 123, "home_name": "Home", "away_name": "Away", "starts_at": "2026-07-22T17:05:00+00:00"}
        main = {"SG": [{"TG": "Players' stats", "CI": 456}], "BIG": []}
        props = {"GE": [{"G": 8527, "E": [[
            {"T": 8091, "P": .5, "PL": {"N": "Aaron Judge"}},
            {"T": 8092, "P": .5, "PL": {"N": "Aaron Judge"}},
        ]]}]}

        with patch.object(APP, "_melbet_game_payload", side_effect=[main, props]) as fetch:
            market = APP._fetch_melbet_game_player_props(game)

        self.assertEqual(fetch.call_args_list[0].args, (123,))
        self.assertEqual(fetch.call_args_list[1].args, (456,))
        self.assertEqual(market["player_subgame_id"], 456)
        self.assertEqual(market["players"]["aaronjudge"]["props"], {"hits": [.5]})

    def test_melbet_player_props_preserves_recent_market_after_partial_timeout(self):
        payload = {
            "G": [
                {"CI": 101, "O1": "Toronto Blue Jays", "O2": "Tampa Bay Rays", "S": 1784822400},
                {"CI": 202, "O1": "St. Louis Cardinals", "O2": "Arizona Diamondbacks", "S": 1784826000},
            ],
            "_ninth_melbet_host": APP.MELBET_PRIMARY_BASE,
        }
        blue_jays = {"bookmaker_game_id": 101, "players": {"one": {"props": {"hits": [.5]}}}}
        APP._melbet_player_props_cache.update({
            "updated_at": APP.datetime.now(APP.timezone.utc) - APP.timedelta(minutes=1),
            "markets": [{
                "bookmaker_game_id": 202,
                "players": {"two": {"props": {"strikeouts": [4.5]}}},
                "last_confirmed_at": "2026-07-23T15:00:00+00:00",
            }],
            "error": None,
        })

        with patch.object(APP, "_melbet_champ_payload", return_value=payload), patch.object(
            APP,
            "_safe_fetch_melbet_game_player_props",
            side_effect=[blue_jays, None],
        ) as fetch:
            snapshot = APP.melbet_player_prop_markets(force=True)

        self.assertEqual(fetch.call_count, 2)
        self.assertEqual(
            {market["bookmaker_game_id"] for market in snapshot["markets"]},
            {101, 202},
        )
        preserved = next(market for market in snapshot["markets"] if market["bookmaker_game_id"] == 202)
        self.assertTrue(preserved["stale"])

    def test_player_prop_snapshot_records_exact_recommendation_once(self):
        game = {
            "game_id": 123, "datetime": "2026-07-23T23:05:00+00:00",
            "away": {"id": 1, "name": "Away"}, "home": {"id": 2, "name": "Home"},
            "players": [{
                "player_id": 99, "name": "Test Pitcher", "kind": "pitcher", "team_id": 1,
                "props": [{
                    "prop": "strikeouts", "label": "Strikeouts",
                    "recommended_line": 4.5, "recommended_side": "under",
                    "thresholds": [{"line": 4.5, "over_probability": .42, "under_probability": .58}],
                }],
            }],
        }
        APP.record_player_prop_snapshots([game])
        APP.record_player_prop_snapshots([game])

        rows = Path(APP.PLAYER_PROP_PROJECTION_LOG).read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(len(rows), 1)
        selection = json.loads(rows[0])["selections"][0]
        self.assertEqual(selection["prop"], "strikeouts")
        self.assertEqual(selection["side"], "under")
        self.assertEqual(selection["probability"], .58)

    def test_player_prop_results_page_scores_accuracy_brier_and_breakdown(self):
        rows = [
            {"game_date": "2026-07-23", "starts_at": "2026-07-23T20:00:00Z", "prop": "strikeouts", "label": "Strikeouts", "probability": .7, "correct": True},
            {"game_date": "2026-07-23", "starts_at": "2026-07-23T21:00:00Z", "prop": "strikeouts", "label": "Strikeouts", "probability": .6, "correct": False},
            {"game_date": "2026-07-22", "starts_at": "2026-07-22T21:00:00Z", "prop": "hits", "label": "Hits", "probability": .8, "correct": True},
        ]
        page = APP.player_prop_results_page(rows, "2026-07-23", 1, 10)

        self.assertEqual(page["evaluated"], 2)
        self.assertEqual(page["correct"], 1)
        self.assertEqual(page["accuracy"], .5)
        self.assertAlmostEqual(page["brier_score"], (.3 ** 2 + .6 ** 2) / 2)
        self.assertEqual(page["prop_breakdown"][0]["evaluated"], 2)

    def test_player_prop_actual_voids_non_participants(self):
        selection = {"player_id": 99, "kind": "pitcher", "prop": "strikeouts"}
        boxscore = {"away": {"players": {"ID99": {"stats": {"pitching": {"battersFaced": 20, "strikeOuts": 7}}}}}}
        self.assertEqual(APP._player_prop_actual(boxscore, selection), 7)
        boxscore["away"]["players"]["ID99"]["stats"]["pitching"]["battersFaced"] = 0
        self.assertIsNone(APP._player_prop_actual(boxscore, selection))

    def test_player_projections_are_limited_to_displayed_props_and_lines(self):
        players = [{"name": "Aaron Judge", "props": [
            {"prop": "hits", "recommended_line": 1.5, "thresholds": [
                {"line": .5, "over_probability": .72, "under_probability": .28},
                {"line": 1.5, "over_probability": .41, "under_probability": .59},
            ]},
            {"prop": "walks", "thresholds": [{"line": .5, "over_probability": .55, "under_probability": .45}]},
        ]}]
        market = {"source": "MelBet displayed player props", "observed_at": "now", "players": {
            "aaronjudge": {"name": "Aaron Judge", "props": {"hits": [.5]}},
        }}
        restricted = APP.restrict_player_props_to_available_lines(players, market)
        self.assertEqual([row["prop"] for row in restricted[0]["props"]], ["hits"])
        self.assertEqual(restricted[0]["props"][0]["recommended_line"], .5)
        self.assertEqual(restricted[0]["props"][0]["recommended_side"], "over")

    def test_melbet_doubleheader_matching_uses_scheduled_time(self):
        snapshot = {"updated_at": APP.datetime.now(APP.timezone.utc), "markets": [
            {"bookmaker_game_id": 1, "home_name": "New York Yankees", "away_name": "Pittsburgh Pirates", "starts_at": "2026-07-22T17:05:00+00:00", "lines": [8.5]},
            {"bookmaker_game_id": 2, "home_name": "New York Yankees", "away_name": "Pittsburgh Pirates", "starts_at": "2026-07-22T23:05:00+00:00", "lines": [9.5]},
        ]}
        market = APP.match_melbet_totals("New York Yankees", "Pittsburgh Pirates", "2026-07-22T23:05:00Z", snapshot)
        self.assertEqual(market["bookmaker_game_id"], 2)
        self.assertEqual(market["lines"], [9.5])
        self.assertFalse(market["prices_used"])

    def test_totals_selection_is_limited_to_currently_offered_lines(self):
        projection = {
            "available": True, "input_completeness": .8, "recommended_line": 10.5,
            "thresholds": [
                {"line": 8.5, "over_probability": .62, "under_probability": .35, "push_probability": .03},
                {"line": 9.5, "over_probability": .48, "under_probability": .52, "push_probability": 0},
                {"line": 10.5, "over_probability": .30, "under_probability": .70, "push_probability": 0},
            ],
        }
        market = {"available": True, "lines": [8.5, 9.5], "prices_used": False}
        selected = APP.restrict_totals_to_available_lines(projection, market)
        self.assertEqual([row["line"] for row in selected["thresholds"]], [8.5, 9.5])
        self.assertEqual(selected["recommended_side"], "over")
        self.assertEqual(selected["recommended_line"], 8.5)
        self.assertEqual(selected["recommended_probability"], .62)


if __name__ == "__main__":
    unittest.main()
