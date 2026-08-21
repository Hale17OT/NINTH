import importlib.util
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import mock_open, patch


APP_PATH = Path(__file__).with_name("app.py")
SPEC = importlib.util.spec_from_file_location("ninth_stats_app", APP_PATH)
APP = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(APP)


class ProjectionIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.original_log = APP.PROJECTION_LOG
        self.original_player_prop_log = APP.PLAYER_PROP_PROJECTION_LOG
        self.original_player_prop_priced_board_log = APP.PLAYER_PROP_PRICED_BOARD_LOG
        self.original_player_prop_build_log = APP.PLAYER_PROP_BUILD_LOG
        self.original_melbet_totals_log = APP.MELBET_TOTALS_SNAPSHOT_LOG
        self.original_player_boxscores = APP.PLAYER_BOXSCORES
        self.original_live_player_props_audit = APP.LIVE_PLAYER_PROPS_AUDIT
        APP.PROJECTION_LOG = str(Path(self.temp.name) / "projection_snapshots.jsonl")
        APP.PLAYER_PROP_PROJECTION_LOG = str(Path(self.temp.name) / "player_prop_projection_snapshots.jsonl")
        APP.PLAYER_PROP_PRICED_BOARD_LOG = str(Path(self.temp.name) / "player_prop_priced_board_snapshots.jsonl")
        APP.PLAYER_PROP_BUILD_LOG = str(Path(self.temp.name) / "player_prop_build_snapshots.jsonl")
        APP.MELBET_TOTALS_SNAPSHOT_LOG = str(Path(self.temp.name) / "melbet_totals_snapshots.jsonl")
        APP.PLAYER_BOXSCORES = str(Path(self.temp.name) / "player_boxscores.jsonl")
        APP.LIVE_PLAYER_PROPS_AUDIT = str(Path(self.temp.name) / "live_player_prop_audit.json")
        APP._bullpen_history_cache.update({"fingerprint": None, "rows": []})
        APP._projection_last.clear()
        APP._projection_last_context.clear()
        APP._projection_last_completeness.clear()
        APP._projection_last_game_state.clear()
        APP._projection_recent_alerts.clear()
        APP._totals_projection_last.clear()
        APP._prediction_results_cache = None
        APP._player_prop_results_cache = None
        APP._player_prop_guarantee_cache = None
        APP._player_prop_snapshot_last.clear()
        APP._player_prop_priced_snapshot_last.clear()
        APP._player_prop_priced_snapshot_at.clear()
        APP._player_prop_boxscore_cache.clear()
        APP._weather_cache.clear()
        APP._weather_backoff_until = 0.0
        APP._league_rankings_cache.clear()
        APP._inning_distribution_cache.clear()
        APP._melbet_totals_cache.update({"updated_at": APP.datetime.now(APP.timezone.utc), "last_attempt_at": None, "markets": [], "error": None, "consecutive_failures": 0, "retry_after": None})
        APP._melbet_totals_snapshot_last.clear()
        APP._melbet_totals_snapshot_loaded = False
        APP._melbet_player_props_cache.update({"updated_at": APP.datetime.now(APP.timezone.utc), "last_attempt_at": None, "markets": [], "error": None, "consecutive_failures": 0, "retry_after": None})

    def tearDown(self):
        APP.PROJECTION_LOG = self.original_log
        APP.PLAYER_PROP_PROJECTION_LOG = self.original_player_prop_log
        APP.PLAYER_PROP_PRICED_BOARD_LOG = self.original_player_prop_priced_board_log
        APP.PLAYER_PROP_BUILD_LOG = self.original_player_prop_build_log
        APP.MELBET_TOTALS_SNAPSHOT_LOG = self.original_melbet_totals_log
        APP.PLAYER_BOXSCORES = self.original_player_boxscores
        APP.LIVE_PLAYER_PROPS_AUDIT = self.original_live_player_props_audit
        APP._player_prop_guarantee_cache = None
        APP._bullpen_history_cache.update({"fingerprint": None, "rows": []})
        APP._melbet_totals_snapshot_last.clear()
        APP._melbet_totals_snapshot_loaded = False
        APP._weather_cache.clear()
        APP._weather_backoff_until = 0.0
        APP._league_rankings_cache.clear()
        APP._inning_distribution_cache.clear()
        self.temp.cleanup()

    def test_melbet_runtime_uses_five_minutes_and_tightens_near_first_pitch(self):
        now = APP.datetime(2026, 8, 16, 12, tzinfo=APP.timezone.utc)
        with patch.dict(APP.os.environ, {
            "NINTH_MELBET_REFRESH_SECONDS": "300",
            "NINTH_MELBET_NEAR_START_SECONDS": "60",
            "NINTH_MELBET_NEAR_START_MINUTES": "30",
        }):
            ordinary = [{"starts_at": (now + APP.timedelta(hours=2)).isoformat()}]
            imminent = [{"starts_at": (now + APP.timedelta(minutes=20)).isoformat()}]
            self.assertEqual(APP._melbet_refresh_seconds(games=ordinary, now=now), 300)
            self.assertEqual(APP._melbet_refresh_seconds(games=imminent, now=now), 60)

    def test_melbet_failures_back_off_without_discarding_cached_markets(self):
        now = APP.datetime(2026, 8, 16, 12, tzinfo=APP.timezone.utc)
        cache = {"markets": [{"starts_at": (now + APP.timedelta(hours=2)).isoformat()}], "consecutive_failures": 0}
        with patch.dict(APP.os.environ, {
            "NINTH_MELBET_REFRESH_SECONDS": "300",
            "NINTH_MELBET_MAX_BACKOFF_SECONDS": "1800",
        }):
            APP._record_melbet_failure(cache, now, RuntimeError("temporary"))
            self.assertEqual(cache["refresh_seconds"], 300)
            self.assertEqual(cache["markets"][0]["starts_at"], (now + APP.timedelta(hours=2)).isoformat())
            APP._record_melbet_failure(cache, now, RuntimeError("temporary"))
            self.assertEqual(cache["refresh_seconds"], 600)
            self.assertGreater(cache["retry_after"], now)

    def test_doubleheader_moneylines_are_shrunk_for_builder_ranking_only(self):
        adjusted, multiplier = APP.moneyline_builder_probability(.64, "S", 2)
        ordinary, ordinary_multiplier = APP.moneyline_builder_probability(.64, "N", 1)

        self.assertEqual(adjusted, .605)
        self.assertEqual(multiplier, .75)
        self.assertEqual(ordinary, .64)
        self.assertEqual(ordinary_multiplier, 1.0)

    def test_lightweight_catchup_only_becomes_due_after_a_missed_window(self):
        audit = Path(self.temp.name) / "reranker_shadow.json"
        audit.write_text(json.dumps({"through": "2026-08-16"}), encoding="utf-8")
        before = APP.datetime(2026, 8, 18, 3, 14).astimezone()
        after = APP.datetime(2026, 8, 18, 3, 16).astimezone()

        with (
            patch.object(APP, "PLAYER_PROP_RERANKER_SHADOW_AUDIT", str(audit)),
            patch.dict(APP.os.environ, {
                "NINTH_MAINTENANCE_HOUR": "3",
                "NINTH_MAINTENANCE_MINUTE": "15",
                "NINTH_MAINTENANCE_CATCHUP_ENABLED": "1",
            }),
        ):
            self.assertIsNone(APP.lightweight_maintenance_catchup_due(before))
            self.assertEqual(APP.lightweight_maintenance_catchup_due(after), "2026-08-17")
            audit.write_text(json.dumps({"through": "2026-08-17"}), encoding="utf-8")
            self.assertIsNone(APP.lightweight_maintenance_catchup_due(after))

    def test_guarantee_history_uses_exact_pick_identity_and_sample_aware_rank(self):
        rows = []
        for day in range(1, 11):
            rows.append({
                "player_id": 7, "player": "Established Player", "kind": "batter",
                "prop": "hits", "side": "over", "line": 0.5,
                "official_date": f"2026-08-{day:02d}", "actual": 1 if day < 10 else 0,
                "probability": 0.72,
            })
        for day in range(1, 4):
            rows.append({
                "player_id": 8, "player": "Tiny Sample", "kind": "batter",
                "prop": "hits", "side": "over", "line": 0.5,
                "official_date": f"2026-08-{day:02d}", "actual": 1,
                "probability": 0.80,
            })
        rows.append({
            "player_id": 7, "player": "Established Player", "kind": "batter",
            "prop": "hits", "side": "over", "line": 1.5,
            "official_date": "2026-08-11", "actual": 1, "probability": 0.40,
        })
        Path(APP.LIVE_PLAYER_PROPS_AUDIT).write_text(json.dumps({"rows": rows}), encoding="utf-8")

        result = APP.player_prop_guarantees()

        self.assertEqual(result["exact_picks"], 3)
        self.assertEqual(result["records"][0]["player_name"], "Established Player")
        self.assertEqual(result["records"][0]["line"], 0.5)
        self.assertEqual(result["records"][0]["evidence"], "established")
        tiny = next(row for row in result["records"] if row["player_id"] == 8)
        self.assertEqual(tiny["accuracy"], 1.0)
        self.assertLess(tiny["consistency_score"], result["records"][0]["consistency_score"])
        self.assertIn("not a guarantee", result["warning"].lower())

    def test_baseball_innings_are_converted_to_decimal_innings(self):
        self.assertAlmostEqual(APP._innings_pitched("123.2"), 123 + 2 / 3)
        self.assertAlmostEqual(APP._innings_pitched("7.1"), 7 + 1 / 3)
        self.assertEqual(APP._innings_pitched(None), 0)

    def test_team_league_rankings_use_rate_direction_and_all_team_context(self):
        hitting = [
            {"team": {"id": 1, "name": "A"}, "stat": {"gamesPlayed": 10, "runs": 60, "ops": ".800", "strikeOuts": 80, "baseOnBalls": 50, "plateAppearances": 400}},
            {"team": {"id": 2, "name": "B"}, "stat": {"gamesPlayed": 10, "runs": 50, "ops": ".750", "strikeOuts": 100, "baseOnBalls": 40, "plateAppearances": 400}},
            {"team": {"id": 3, "name": "C"}, "stat": {"gamesPlayed": 10, "runs": 40, "ops": ".700", "strikeOuts": 120, "baseOnBalls": 30, "plateAppearances": 400}},
        ]
        pitching = [
            {"team": {"id": 1, "name": "A"}, "stat": {"gamesPlayed": 10, "runs": 30, "era": "3.00", "whip": "1.10", "inningsPitched": "90.0", "strikeOuts": 100, "baseOnBalls": 25, "homeRuns": 8, "battersFaced": 380, "strikeoutsPer9Inn": "10.00"}},
            {"team": {"id": 2, "name": "B"}, "stat": {"gamesPlayed": 10, "runs": 40, "era": "4.00", "whip": "1.20", "inningsPitched": "90.0", "strikeOuts": 90, "baseOnBalls": 30, "homeRuns": 10, "battersFaced": 390, "strikeoutsPer9Inn": "9.00"}},
            {"team": {"id": 3, "name": "C"}, "stat": {"gamesPlayed": 10, "runs": 50, "era": "5.00", "whip": "1.30", "inningsPitched": "90.0", "strikeOuts": 80, "baseOnBalls": 35, "homeRuns": 12, "battersFaced": 400, "strikeoutsPer9Inn": "8.00"}},
        ]

        result = APP.build_team_league_rankings(hitting, pitching)
        rows = {row["key"]: row for row in result[1]["rankings"]}

        self.assertEqual(rows["hitter_k_rate"]["rank"], 1)
        self.assertEqual(rows["pitcher_k9"]["rank"], 1)
        self.assertEqual(rows["pitcher_k_rate"]["rank"], 1)
        self.assertEqual(rows["pitcher_walk_rate"]["rank"], 1)
        self.assertEqual(rows["runs_allowed_per_game"]["rank"], 1)
        self.assertEqual(rows["hitter_k_rate"]["teams"], 3)
        self.assertEqual(rows["hitter_k_rate"]["display"], "20.0%")
        self.assertEqual(rows["ops"]["display"], ".800")

    def test_team_schedule_preserves_links_results_starters_and_upcoming_games(self):
        payload = {"dates": [{"date": "2026-08-15", "games": [{
            "gamePk": 11, "gameDate": "2026-08-15T23:00:00Z", "gameType": "R", "gameNumber": 1,
            "status": {"abstractGameState": "Final", "detailedState": "Final", "statusCode": "F"},
            "teams": {
                "away": {"team": {"id": 1, "name": "A"}, "score": 5, "probablePitcher": {"id": 101, "fullName": "Away Starter"}},
                "home": {"team": {"id": 2, "name": "B"}, "score": 3, "probablePitcher": {"id": 202, "fullName": "Home Starter"}},
            },
            "venue": {"id": 9, "name": "Park"}, "seriesDescription": "Regular Season", "doubleHeader": "N",
        }, {
            "gamePk": 12, "gameDate": "2026-08-16T23:00:00Z", "gameType": "R", "gameNumber": 1,
            "status": {"abstractGameState": "Preview", "detailedState": "Scheduled", "statusCode": "S"},
            "teams": {"away": {"team": {"id": 2, "name": "B"}}, "home": {"team": {"id": 1, "name": "A"}}},
            "venue": {"id": 10, "name": "Next Park"}, "seriesDescription": "Regular Season", "doubleHeader": "N",
        }, {
            "gamePk": 13, "gameDate": "2026-02-01T23:00:00Z", "gameType": "E", "gameNumber": 1,
            "status": {"abstractGameState": "Final", "detailedState": "Final", "statusCode": "F"},
            "teams": {"away": {"team": {"id": 1, "name": "A"}}, "home": {"team": {"id": 900, "name": "Exhibition Club"}}},
            "venue": {"id": 11, "name": "Exhibition Park"}, "seriesDescription": "Exhibition", "doubleHeader": "N",
        }, {
            "gamePk": 14, "gameDate": "2026-08-17T23:00:00Z", "gameType": "R", "gameNumber": 1,
            "status": {"abstractGameState": "Final", "detailedState": "Postponed", "statusCode": "DR"},
            "teams": {"away": {"team": {"id": 1, "name": "A"}}, "home": {"team": {"id": 2, "name": "B"}}},
            "venue": {"id": 12, "name": "Rain Park"}, "seriesDescription": "Regular Season", "doubleHeader": "N",
        }]}]}

        rows = APP.normalize_team_schedule(payload, 1)

        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["opponent_id"], 2)
        self.assertEqual(rows[0]["result"], "W")
        self.assertEqual(rows[0]["team_starter_id"], 101)
        self.assertEqual(rows[0]["opponent_starter_id"], 202)
        self.assertFalse(rows[1]["is_final"])
        self.assertIsNone(rows[1]["team_score"])
        self.assertEqual(rows[2]["status"], "Postponed")
        self.assertFalse(rows[2]["is_final"])
        self.assertIsNone(rows[2]["result"])

    def test_player_game_logs_preserve_game_team_opponent_and_all_stat_fields(self):
        payload = {"people": [{"stats": [{
            "group": {"displayName": "hitting"}, "splits": [{
                "date": "2026-08-15", "season": "2026", "isHome": True, "isWin": True,
                "game": {"gamePk": 99, "gameNumber": 1, "dayNight": "night"},
                "team": {"id": 1, "name": "A"}, "opponent": {"id": 2, "name": "B"},
                "positionsPlayed": [{"abbreviation": "RF"}],
                "stat": {"summary": "2-4, HR", "atBats": 4, "hits": 2, "homeRuns": 1, "customFutureField": 7},
            }],
        }, {
            "group": {"displayName": "pitching"}, "splits": [{
                "date": "2026-08-16", "season": "2026", "isHome": False, "isWin": False,
                "game": {"gamePk": 100}, "team": {"id": 1, "name": "A"}, "opponent": {"id": 3, "name": "C"},
                "stat": {"inningsPitched": "6.0", "strikeOuts": 8, "losses": 1, "numberOfPitches": 94},
            }],
        }]}]}

        rows = APP.normalize_player_game_logs(payload)

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["game_id"], 99)
        self.assertEqual(rows[0]["opponent_id"], 2)
        self.assertEqual(rows[0]["positions"], ["RF"])
        self.assertEqual(rows[0]["stats"]["customFutureField"], 7)
        self.assertEqual(rows[1]["decision"], "L")
        self.assertEqual(rows[1]["stats"]["numberOfPitches"], 94)

    def test_inning_distribution_normalizes_by_team_games_and_buckets_extras(self):
        def game(game_id, home_id, away_id, innings):
            return {
                "gamePk": game_id,
                "status": {"abstractGameState": "Final"},
                "teams": {"home": {"team": {"id": home_id}}, "away": {"team": {"id": away_id}}},
                "linescore": {"innings": innings},
            }

        payload = {"dates": [{"games": [
            game(1, 2, 1, [
                {"num": 1, "away": {"runs": 1}, "home": {"runs": 0}},
                {"num": 2, "away": {"runs": 2}, "home": {"runs": 1}},
            ]),
            game(2, 1, 3, [
                {"num": 1, "away": {"runs": 1}, "home": {"runs": 0}},
                {"num": 10, "away": {"runs": 0}, "home": {"runs": 1}},
            ]),
            game(3, 1, 4, [{"num": 1, "away": {"runs": 0}, "home": {"runs": 9}}]),
        ]}]}

        result = APP.summarize_inning_distribution(payload, 1, excluded_game_id=3)

        self.assertEqual(result["sample_games"], 2)
        self.assertEqual(result["scored_per_game"][0], 0.5)
        self.assertEqual(result["scored_per_game"][1], 1.0)
        self.assertEqual(result["scored_per_game"][9], 0.5)
        self.assertEqual(result["scoring_game_rate"][0], 50.0)
        self.assertEqual(result["phases"][0]["scored_per_game"], 1.5)
        self.assertEqual(result["phases"][3]["innings"], "10+")

    def test_melbet_snapshots_retain_prices_and_record_price_changes(self):
        market = {
            "bookmaker_game_id": 12345,
            "starts_at": "2026-08-07T23:10:00+00:00",
            "home_name": "Home Team",
            "away_name": "Away Team",
            "lines": [8.5],
            "total_odds": {8.5: {"over": 1.90, "under": 1.95}},
            "moneyline_odds": {"home": 1.70, "away": 2.20},
            "feed_host": "example.test",
        }
        observed = APP.datetime(2026, 8, 6, 12, 0, tzinfo=APP.timezone.utc)

        self.assertEqual(APP.record_melbet_totals_snapshots([market], observed), 1)
        market["total_odds"][8.5]["over"] = 1.91
        self.assertEqual(APP.record_melbet_totals_snapshots([market], observed + APP.timedelta(minutes=1)), 1)

        rows = [json.loads(line) for line in Path(APP.MELBET_TOTALS_SNAPSHOT_LOG).read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["total_odds"]["8.5"], {"over": 1.9, "under": 1.95})
        self.assertEqual(rows[0]["moneyline_odds"], {"home": 1.7, "away": 2.2})
        self.assertEqual(rows[1]["total_odds"]["8.5"]["over"], 1.91)

    def test_pitcher_profile_includes_splits_and_five_prior_starts(self):
        game_logs = []
        for day in range(1, 8):
            game_logs.append({
                "date": f"2026-07-{day:02d}",
                "isHome": day % 2 == 0,
                "isWin": day % 2 == 1,
                "opponent": {"id": 100 + day, "name": f"Opponent {day}"},
                "game": {"gamePk": 900000 + day},
                "stat": {
                    "gamesStarted": 0 if day == 6 else 1,
                    "wins": 1 if day == 5 else 0,
                    "losses": 1 if day == 4 else 0,
                    "inningsPitched": "6.0", "hits": day, "runs": 2,
                    "earnedRuns": 1, "baseOnBalls": 2, "strikeOuts": 7,
                    "homeRuns": 1, "numberOfPitches": 94,
                },
            })
        response = {"people": [{
            "currentTeam": {"name": "Test Club"},
            "primaryPosition": {"abbreviation": "P"},
            "stats": [
                {"type": {"displayName": "season"}, "group": {"displayName": "pitching"}, "splits": [{"stat": {"inningsPitched": "100.0", "strikeOuts": 120, "baseOnBalls": 30, "homeRuns": 10, "wins": 8, "losses": 4, "era": "3.20", "whip": "1.10"}}]},
                {"type": {"displayName": "gameLog"}, "group": {"displayName": "pitching"}, "splits": game_logs},
                {"type": {"displayName": "homeAndAway"}, "group": {"displayName": "pitching"}, "splits": [
                    {"isHome": True, "stat": {"wins": 5, "losses": 1, "gamesStarted": 8, "inningsPitched": "50.0", "era": "2.70", "whip": "1.00"}},
                    {"isHome": False, "stat": {"wins": 3, "losses": 3, "gamesStarted": 8, "inningsPitched": "50.0", "era": "3.70", "whip": "1.20"}},
                ]},
            ],
        }]}
        APP._pitcher_profile_cache.clear()
        with patch.object(APP.statsapi, "get", return_value=response) as get_person:
            profile = APP.pitcher_profile(
                {"id": 42, "fullName": "Test Pitcher"},
                "2026-07-31T23:00:00Z", 900007,
            )

        self.assertEqual(profile["home_away"]["home"]["record"], "5-1")
        self.assertEqual(profile["home_away"]["away"]["era"], "3.70")
        self.assertEqual(len(profile["recent_starts"]), 5)
        self.assertEqual(profile["recent_starts"][0]["game_id"], 900005)
        self.assertEqual(profile["recent_starts"][0]["decision"], "W")
        self.assertNotIn(900006, [start["game_id"] for start in profile["recent_starts"]])
        self.assertNotIn(900007, [start["game_id"] for start in profile["recent_starts"]])
        self.assertEqual(profile["runs_per_start"], 2.0)
        self.assertEqual(profile["starts_before_matchup"], 5)
        self.assertIn("type=[season,gameLog,homeAndAway]", get_person.call_args.args[1]["hydrate"])

    def test_bullpen_performance_separates_relievers_and_is_point_in_time(self):
        def game(game_id, game_date, relief_runs, relief_er, relief_outs):
            def side(team_id, starter_id, reliever_id, runs):
                return {
                    "team_id": team_id,
                    "players": [
                        {"player_id": starter_id, "pitching": {
                            "gamesStarted": 1, "runs": 3, "earnedRuns": 2, "outs": 15,
                        }},
                        {"player_id": reliever_id, "pitching": {
                            "gamesStarted": 0, "runs": runs, "earnedRuns": relief_er,
                            "outs": relief_outs,
                        }},
                    ],
                }
            return {
                "game_id": game_id, "date": game_date, "season": 2026,
                "away": side(10, 1, 2, relief_runs),
                "home": side(20, 3, 4, 0),
            }

        rows = [
            game(1, "2026-08-08", 2, 1, 12),
            game(2, "2026-08-09", 0, 0, 9),
            game(3, "2026-08-10", 9, 9, 3),
        ]
        Path(APP.PLAYER_BOXSCORES).write_text(
            "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8",
        )
        result = APP.bullpen_performance([10], "2026-08-10T19:00:00Z", 3)[10]

        self.assertEqual(result["bullpen_games"], 2)
        self.assertEqual(result["bullpen_runs_per_game"], 1.0)
        self.assertEqual(result["bullpen_era"], 1.29)
        self.assertEqual(result["bullpen_runs_basis"], "runs")
        self.assertEqual(result["through"], "2026-08-09")

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
        self.assertEqual(locked["audit_side"], "under")
        self.assertEqual(locked["audit_line"], 10.5)
        self.assertEqual(locked["audit_probability"], .69)
        self.assertFalse(locked["automatic_builder_eligible"])
        self.assertEqual(locked["projection_source"], "pregame_locked")

    def test_totals_snapshot_without_a_listed_line_can_refresh_repeatedly(self):
        projection = {"available": True, "home_win_probability": .55, "away_win_probability": .45, "reasons": []}
        totals = {
            "available": True,
            "expected_total_runs": 8.9,
            "recommended_line": None,
            "recommended_side": None,
            "recommended_probability": None,
            "selection_available": False,
        }

        APP.record_projection(823515, dict(projection), {}, "Preview", "2026-08-07T23:05:00Z", totals)
        refreshed = APP.record_projection(823515, dict(projection), {}, "Preview", "2026-08-07T23:05:00Z", totals)

        self.assertTrue(refreshed["available"])
        self.assertIsNone(APP._totals_projection_last["823515"]["recommended_probability"])

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

        with patch.object(APP.requests, "get", return_value=RateLimitedResponse()) as weather_request:
            result = APP.open_meteo_weather(40.82919482, -73.9264977, "2026-07-17T23:05:00Z")

        self.assertIsNone(result)
        self.assertGreater(APP._weather_backoff_until, 0.0)
        self.assertEqual(weather_request.call_args.kwargs["timeout"], (1.5, 3.0))

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

    def test_game_detail_returns_partial_shell_while_background_refresh_owns_lock(self):
        game_id = 823750
        APP._summary_cache[game_id] = {
            "game_id": game_id,
            "status": "Scheduled",
            "datetime": "2026-08-07T23:40:00Z",
            "venue": {"name": "American Family Field"},
            "away": {"id": 142, "name": "Minnesota Twins", "abbr": "MIN"},
            "home": {"id": 158, "name": "Milwaukee Brewers", "abbr": "MIL"},
        }
        lock = APP.detail_lock(game_id)
        lock.acquire()
        try:
            started = time.monotonic()
            result = APP.game_detail(game_id)
        finally:
            lock.release()
            APP._summary_cache.pop(game_id, None)

        self.assertLess(time.monotonic() - started, .1)
        self.assertTrue(result["partial"])
        self.assertFalse(result["projection"]["available"])

    def test_forced_refresh_does_not_queue_behind_existing_refresh(self):
        game_id = 823750
        lock = APP.detail_lock(game_id)
        lock.acquire()
        try:
            with self.assertRaisesRegex(RuntimeError, "already in progress"):
                APP.game_detail(game_id, force=True)
        finally:
            lock.release()

    def test_uncached_game_detail_starts_enrichment_without_blocking_request(self):
        game_id = 823750
        APP._detail_cache.pop(game_id, None)
        APP._summary_cache[game_id] = {
            "game_id": game_id,
            "status": "Scheduled",
            "datetime": "2026-08-07T23:40:00Z",
            "venue": {"name": "American Family Field"},
            "away": {"id": 142, "name": "Minnesota Twins", "abbr": "MIN"},
            "home": {"id": 158, "name": "Milwaukee Brewers", "abbr": "MIL"},
        }
        started_threads = []

        class DeferredThread:
            def __init__(self, target, **kwargs):
                self.target = target

            def start(self):
                started_threads.append(self)

        try:
            with patch.object(APP.threading, "Thread", DeferredThread):
                started = time.monotonic()
                result = APP.game_detail(game_id)
            self.assertLess(time.monotonic() - started, .1)
            self.assertTrue(result["partial"])
            self.assertEqual(len(started_threads), 1)
        finally:
            lock = APP.detail_lock(game_id)
            if lock.locked():
                lock.release()
            APP._summary_cache.pop(game_id, None)

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

    def test_completed_totals_results_recover_audit_selection_from_legacy_thresholds(self):
        snapshot = {
            "game_id": 823999,
            "recorded_at": "2026-08-10T16:00:00+00:00",
            "scheduled_start": "2026-08-10T23:00:00Z",
            "phase": "pregame",
            "home_win_probability": .55,
            "away_win_probability": .45,
            "totals_projection": {
                "expected_total_runs": 8.8,
                "recommended_line": None,
                "recommended_side": None,
                "recommended_probability": None,
                "thresholds": [
                    {"line": 8.0, "over_probability": .56, "under_probability": .38,
                     "melbet_odds": {"over": 1.91, "under": 1.91}},
                    {"line": 8.5, "over_probability": .53, "under_probability": .47,
                     "melbet_odds": {"over": 2.0, "under": 1.8}},
                    {"line": 9.5, "over_probability": .42, "under_probability": .58,
                     "melbet_odds": {"over": 2.2, "under": 1.65}},
                ],
            },
        }
        Path(APP.PROJECTION_LOG).write_text(json.dumps(snapshot) + "\n", encoding="utf-8")
        final_game = {
            "game_id": 823999, "status": "Final", "game_date": "2026-08-10",
            "game_datetime": "2026-08-10T23:00:00Z", "home_id": 1,
            "away_id": 2, "home_name": "Home", "away_name": "Away",
            "home_score": 5, "away_score": 4,
        }

        with patch.object(APP.statsapi, "schedule", return_value=[final_game]):
            page = APP._completed_prediction_results(
                target_date="2026-08-10", page_size=50, market="totals",
            )

        self.assertEqual(page["evaluated"], 1)
        self.assertEqual(page["games"][0]["total_line"], 8.0)
        self.assertEqual(page["games"][0]["total_side"], "over")
        self.assertEqual(page["games"][0]["total_probability"], .56)
        self.assertFalse(page["games"][0]["total_automatic_builder_eligible"])
        self.assertTrue(page["games"][0]["total_correct"])

    def test_completed_integer_central_total_is_a_push_not_a_miss(self):
        snapshot = {
            "game_id": 824000, "recorded_at": "2026-08-10T16:00:00+00:00",
            "scheduled_start": "2026-08-10T23:00:00Z", "phase": "pregame",
            "home_win_probability": .55, "away_win_probability": .45,
            "totals_projection": {
                "expected_total_runs": 8.2,
                "thresholds": [{
                    "line": 8.0, "over_probability": .56, "under_probability": .44,
                    "push_probability": .08, "melbet_odds": {"over": 1.91, "under": 1.91},
                }],
            },
        }
        Path(APP.PROJECTION_LOG).write_text(json.dumps(snapshot) + "\n", encoding="utf-8")
        final_game = {
            "game_id": 824000, "status": "Final", "game_date": "2026-08-10",
            "game_datetime": "2026-08-10T23:00:00Z", "home_id": 1, "away_id": 2,
            "home_name": "Home", "away_name": "Away", "home_score": 5, "away_score": 3,
        }
        with patch.object(APP.statsapi, "schedule", return_value=[final_game]):
            page = APP._completed_prediction_results(
                target_date="2026-08-10", page_size=50, market="totals",
            )
        self.assertEqual(page["evaluated"], 0)
        self.assertEqual(page["pushes"], 1)
        self.assertTrue(page["games"][0]["total_push"])
        self.assertIsNone(page["games"][0]["total_correct"])

    def test_melbet_full_game_total_parser_keeps_display_odds_outside_models(self):
        payload = {"Value": {"GE": [{"G": 1, "E": [[
            {"T": 1, "C": 1.724}, {"T": 3, "C": 2.271},
        ]]}, {"G": 17, "E": [
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
        self.assertEqual(market["moneyline_odds"], {"home": 1.724, "away": 2.271})
        self.assertEqual(market["total_odds"][8.5], {"over": 1.7, "under": 2.1})
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

    def test_deferred_melbet_refresh_returns_cached_board_state_immediately(self):
        APP._melbet_totals_cache.update({
            "updated_at": None, "last_attempt_at": None, "markets": [],
            "error": None, "refreshing": False,
        })
        with patch.object(APP.threading, "Thread") as thread:
            snapshot = APP.melbet_totals_markets(defer_refresh=True)
        self.assertEqual(snapshot["markets"], [])
        self.assertTrue(snapshot["refreshing"])
        thread.assert_called_once()
        thread.return_value.start.assert_called_once()

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

    def test_melbet_player_prop_parser_preserves_one_sided_lines_and_display_odds(self):
        payload = {"GE": [{"G": 8527, "E": [[
            {"T": 8091, "P": .5, "PL": {"N": "Aaron Judge", "I": 1}, "C": 1.4},
            {"T": 8092, "P": .5, "PL": {"N": "Aaron Judge", "I": 1}, "C": 2.8},
            {"T": 8091, "P": 1.5, "PL": {"N": "Aaron Judge", "I": 1}, "C": 2.2},
        ]]}]}
        players = APP._parse_melbet_player_prop_groups(payload)
        self.assertEqual(players["aaronjudge"]["props"], {"hits": [.5, 1.5]})
        one_sided = [row for row in players["aaronjudge"]["offers"] if row["line"] == 1.5]
        self.assertEqual([row["side"] for row in one_sided], ["over"])
        self.assertEqual(one_sided[0]["decimal_odds"], 2.2)
        self.assertNotIn("C", json.dumps(players))

    def test_melbet_direct_home_run_selection_maps_to_over_point_five(self):
        players = APP._parse_melbet_player_prop_groups({"GE": [{"G": 3425, "E": [[
            {"T": 4743, "PL": {"N": "Mike Trout", "I": 1}, "C": 4.4},
        ]]}]})

        batter = players["miketrout"]
        self.assertEqual(batter["props"], {"home_runs": [.5]})
        self.assertEqual(batter["offers"][0]["market_name"], "Player To Score Home Run")
        self.assertEqual(batter["offers"][0]["selection_name"], "Mike Trout")
        self.assertEqual(batter["offers"][0]["side"], "over")

    def test_melbet_player_prop_group_ids_match_visible_market_labels(self):
        def group(group_id, over_type, under_type):
            return {"G": group_id, "E": [[
                {"T": over_type, "P": .5, "PL": {"N": "Aaron Judge"}},
                {"T": under_type, "P": .5, "PL": {"N": "Aaron Judge"}},
            ]]}

        players = APP._parse_melbet_player_prop_groups({"GE": [
            group(2891, 3868, 3869), group(10713, 14506, 14507),
            group(10956, 15214, 15215), group(10714, 14508, 14509),
            group(10469, 13838, 13839), group(10957, 15216, 15217),
            group(11325, 16064, 16065), group(11326, 16062, 16063),
            group(11327, 16066, 16067),
        ]})

        self.assertEqual(players["aaronjudge"]["props"], {
            "strikeouts": [.5], "hits_allowed": [.5], "doubles": [.5], "rbi": [.5],
            "singles": [.5], "triples": [.5], "hits_runs_rbi": [.5], "walks": [.5],
        })

    def test_all_observed_melbet_player_groups_are_mapped_with_exact_types(self):
        observed = {
            2891: {3868, 3869}, 8527: {8091, 8092},
            10465: {13827, 13828}, 10466: {13829, 13830},
            10469: {13838, 13839}, 10710: {14500, 14501},
            10711: {14502, 14503}, 10712: {14504, 14505},
            10713: {14506, 14507}, 10714: {14508, 14509},
            10955: {15212, 15213}, 10956: {15214, 15215},
            10957: {15216, 15217}, 11325: {16064, 16065},
            11326: {16062, 16063}, 11327: {16066, 16067},
            11328: {16068, 16069}, 11351: {16125},
            11352: {16126}, 11353: {16127}, 11354: {16128},
            11355: {16129}, 11356: {16130}, 11357: {16131},
            11358: {16132},
        }
        self.assertTrue(observed.keys() <= APP.MELBET_PLAYER_PROP_MARKETS.keys())
        for group_id, type_ids in observed.items():
            market = APP.MELBET_PLAYER_PROP_MARKETS[group_id]
            self.assertEqual(set(market["types"]), type_ids)
            self.assertTrue(market["name"])
            self.assertIn(market["kind"], {"batter", "pitcher"})

    def test_complete_player_feed_follows_advertised_selection_count(self):
        initial = {"EC": 2100, "GE": [{"G": 8527, "E": [[
            {"T": 8091, "P": .5, "PL": {"N": "Aaron Judge"}},
        ]]}]}
        complete = {**initial, "EC": 2100}
        with patch.object(APP, "_melbet_game_payload", side_effect=[initial, complete]) as fetch:
            payload = APP._melbet_complete_player_payload(456)

        self.assertIs(payload, complete)
        self.assertEqual(fetch.call_args_list[0].kwargs["count"], 2000)
        self.assertEqual(fetch.call_args_list[1].kwargs["count"], 2200)

    def test_melbet_pitcher_to_win_preserves_exact_yes_no_selections(self):
        players = APP._parse_melbet_player_prop_groups({"GE": [{"G": 10711, "E": [[
            {"T": 14502, "PL": {"N": "Aaron Nola"}, "C": 2.4},
            {"T": 14503, "PL": {"N": "Aaron Nola"}, "C": 1.5},
        ]]}]})

        offers = players["aaronnola"]["offers"]
        self.assertEqual(players["aaronnola"]["props"], {"win": [.5]})
        self.assertEqual([row["selection_name"] for row in offers], [
            "Aaron Nola - Yes", "Aaron Nola - No",
        ])
        self.assertEqual([row["side"] for row in offers], ["over", "under"])

    def test_melbet_extra_strikeouts_are_preserved_as_at_least_selections(self):
        players = APP._parse_melbet_player_prop_groups({"GE": [{"G": 11358, "E": [[
            {"T": 16132, "P": 6, "PL": {"N": "Kevin Gausman", "I": 1}, "C": 1.75},
        ]]}]})

        pitcher = players["kevingausman"]
        self.assertEqual(pitcher["props"], {"strikeouts": [5.5]})
        self.assertEqual(pitcher["offers"], [{
            "prop": "strikeouts", "line": 5.5, "group_id": 11358,
            "type_id": 16132, "side": "over", "format": "at_least",
            "market_name": "Pitchers. Extra Total Strikeouts",
            "player_name": "Kevin Gausman",
            "display_line": 6.0,
            "decimal_odds": 1.75,
            "selection_name": "Kevin Gausman (6) Or More",
        }])
        self.assertNotIn("C", json.dumps(players))

    def test_melbet_home_run_only_player_listing_is_marked_partial(self):
        starts_at = "2026-08-07T22:45:00+00:00"
        snapshot = {"markets": [{
            "bookmaker_game_id": 123,
            "player_subgame_id": 124,
            "home_name": "Washington Nationals",
            "away_name": "Cincinnati Reds",
            "starts_at": starts_at,
            "players": {"ellydelacruz": {
                "offers": [{"prop": "home_runs", "side": "over"}],
            }},
        }]}

        market = APP.match_melbet_player_props(
            "Washington Nationals", "Cincinnati Reds", starts_at, snapshot,
        )

        self.assertTrue(market["partial"])
        self.assertEqual(market["market_status"], "home_runs_only")
        self.assertEqual(market["listed_prop_types"], ["home_runs"])

    def test_player_prop_restriction_respects_one_sided_melbet_ladder(self):
        projections = [{
            "name": "Kevin Gausman",
            "props": [{
                "prop": "strikeouts", "label": "Strikeouts",
                "thresholds": [{
                    "line": 5.5, "over_probability": .62, "under_probability": .38,
                }],
            }],
        }]
        market = {
            "source": "MelBet displayed player props", "observed_at": "2026-08-01T00:00:00Z",
            "players": {"kevingausman": {
                "props": {"strikeouts": [5.5]},
                "offers": [{
                    "prop": "strikeouts", "line": 5.5, "side": "over",
                    "format": "at_least", "group_id": 11358, "type_id": 16132,
                    "market_name": "Pitchers. Extra Total Strikeouts",
                    "display_line": 6.0, "selection_name": "Kevin Gausman (6) Or More",
                }],
            }},
        }

        restricted = APP.restrict_player_props_to_available_lines(projections, market)

        prop = restricted[0]["props"][0]
        self.assertEqual(prop["recommended_side"], "over")
        self.assertEqual(prop["melbet_market_names"], ["Pitchers. Extra Total Strikeouts"])
        self.assertEqual(prop["thresholds"][0]["available_sides"], ["over"])

    def test_player_prop_restriction_matches_conservative_name_spelling_variant(self):
        projections = [{
            "name": "Zack Wheeler", "kind": "pitcher", "team_id": 143,
            "props": [{
                "prop": "strikeouts", "label": "Strikeouts",
                "thresholds": [{"line": 7.5, "over_probability": .56, "under_probability": .44}],
            }],
        }]
        market = {
            "source": "MelBet displayed player props", "observed_at": "2026-08-02T00:00:00Z",
            "players": {"zachwheeler": {
                "name": "Zach Wheeler", "props": {"strikeouts": [7.5]},
                "offers": [
                    {"prop": "strikeouts", "line": 7.5, "side": "over", "market_name": "Pitchers. Total Strikeouts"},
                    {"prop": "strikeouts", "line": 7.5, "side": "under", "market_name": "Pitchers. Total Strikeouts"},
                ],
            }},
        }

        restricted = APP.restrict_player_props_to_available_lines(projections, market)

        self.assertEqual(len(restricted), 1)
        self.assertEqual(restricted[0]["name"], "Zack Wheeler")
        self.assertEqual(restricted[0]["props"][0]["thresholds"][0]["available_sides"], ["over", "under"])

    def test_player_name_matching_handles_middle_names_initials_suffixes_and_accents(self):
        offered = {
            "michaelataylorjr": {"name": "Michael A. Taylor Jr."},
            "jtrealmuto": {"name": "JT Realmuto"},
            "joseramirez": {"name": "José Ramírez"},
            "michaelharrisii": {"name": "Michael Harris II"},
        }

        self.assertEqual(APP._match_melbet_player(offered, "Michael Taylor")["name"], "Michael A. Taylor Jr.")
        self.assertEqual(APP._match_melbet_player(offered, "J. T. Realmuto")["name"], "JT Realmuto")
        self.assertEqual(APP._match_melbet_player(offered, "Jose Ramirez")["name"], "José Ramírez")
        self.assertEqual(APP._match_melbet_player(offered, "Micheal Harris")["name"], "Michael Harris II")

    def test_player_name_matching_rejects_ambiguous_initial_only_identity(self):
        offered = {
            "josegarcia": {"name": "Jose Garcia"},
            "javiergarcia": {"name": "Javier Garcia"},
        }

        self.assertIsNone(APP._match_melbet_player(offered, "J Garcia"))

    def test_player_prop_restriction_uses_official_alternate_names(self):
        projections = [{
            "name": "JR Ritchie", "market_names": ["JR Ritchie", "Ian Ritchie"],
            "kind": "pitcher", "team_id": 144,
            "props": [{
                "prop": "walks", "label": "Walks",
                "thresholds": [{"line": 1.5, "over_probability": .51, "under_probability": .49}],
            }],
        }]
        market = {
            "source": "MelBet displayed player props", "observed_at": "2026-08-02T00:00:00Z",
            "players": {"ianritchiejr": {
                "name": "Ian Ritchie Jr.", "props": {"walks": [1.5]},
                "offers": [
                    {"prop": "walks", "line": 1.5, "side": "over", "market_name": "Pitchers. Total Walks Allowed"},
                    {"prop": "walks", "line": 1.5, "side": "under", "market_name": "Pitchers. Total Walks Allowed"},
                ],
            }},
        }

        restricted = APP.restrict_player_props_to_available_lines(projections, market)

        self.assertEqual(len(restricted), 1)
        self.assertEqual(restricted[0]["name"], "JR Ritchie")
        self.assertNotIn("market_names", restricted[0])

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
        self.assertEqual(fetch.call_args_list[1].kwargs["count"], 2000)
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

    def test_player_prop_snapshot_separately_records_every_priced_candidate(self):
        game = {
            "game_id": 123, "datetime": "2026-07-23T23:05:00+00:00",
            "away": {"id": 1, "name": "Away"}, "home": {"id": 2, "name": "Home"},
            "players": [{
                "player_id": 99, "name": "Test Pitcher", "kind": "pitcher", "team_id": 1,
                "opponent_id": 2, "lineup_status": "confirmed", "history_games": 80,
                "props": [{
                    "prop": "strikeouts", "label": "Strikeouts", "recent_10_average": 6.1,
                    "recommended_line": 4.5, "recommended_side": "over",
                    "thresholds": [{
                        "line": 4.5, "over_probability": .64, "under_probability": .36,
                        "melbet_selections": {
                            "over": [{"decimal_odds": 1.8, "group_id": 2891, "type_id": 3868}],
                            "under": [{"decimal_odds": 2.0, "group_id": 2891, "type_id": 3869}],
                        },
                    }, {
                        "line": 5.5, "over_probability": .51, "under_probability": .49,
                        "melbet_selections": {
                            "over": [{"decimal_odds": 2.2, "group_id": 2891, "type_id": 3868}],
                            "under": [{"decimal_odds": 1.7, "group_id": 2891, "type_id": 3869}],
                        },
                    }],
                }],
            }],
        }
        APP.record_player_prop_snapshots([game])
        row = json.loads(Path(APP.PLAYER_PROP_PRICED_BOARD_LOG).read_text(encoding="utf-8"))
        self.assertEqual(len(row["candidates"]), 4)
        self.assertEqual(row["snapshot_rule"], "Every displayed MelBet player-prop price before first pitch")
        self.assertIsNotNone(row["candidates"][0]["sportsbook_probability"])

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

    def test_player_prop_actual_supports_every_new_combined_market(self):
        batter = {"away": {"players": {"ID11": {"stats": {"batting": {
            "plateAppearances": 5, "hits": 4, "doubles": 1, "triples": 1,
            "homeRuns": 1, "runs": 2, "rbi": 3, "strikeOuts": 1,
        }}}}}}
        base = {"player_id": 11, "kind": "batter"}
        self.assertEqual(APP._player_prop_actual(batter, {**base, "prop": "singles"}), 1)
        self.assertEqual(APP._player_prop_actual(batter, {**base, "prop": "triples"}), 1)
        self.assertEqual(APP._player_prop_actual(batter, {**base, "prop": "strikeouts"}), 1)
        self.assertEqual(APP._player_prop_actual(batter, {**base, "prop": "hits_runs_rbi"}), 9)

        pitcher = {"home": {"players": {"ID22": {"stats": {"pitching": {
            "battersFaced": 24, "wins": 1,
        }}}}}}
        self.assertEqual(APP._player_prop_actual(
            pitcher, {"player_id": 22, "kind": "pitcher", "prop": "win"},
        ), 1)

    def test_automatic_policy_blocks_sparse_markets_and_allows_audited_home_runs(self):
        report = {"models": {
            "batter:hits": {}, "batter:total_bases": {},
            "batter:home_runs": {}, "batter:hits_runs_rbi": {}, "batter:rbi": {},
            "pitcher:outs": {},
        }}
        audit = {
            "automatic_one_per_game_excluding_home_runs": {"0.65": {
                "accuracy": .72, "mean_confidence": .78,
            }},
            "by_prop": {
                "batter:hits": {"selections": 500, "accuracy": .70, "mean_confidence": .75, "brier": .19},
                "batter:total_bases": {"selections": 14, "accuracy": .57, "mean_confidence": .68, "brier": .26},
                "batter:home_runs": {"selections": 800, "accuracy": .91, "mean_confidence": .88, "brier": .08},
                "batter:rbi": {"selections": 100, "accuracy": .64, "mean_confidence": .67, "brier": .22},
                "pitcher:outs": {"selections": 300, "accuracy": .52, "mean_confidence": .60, "brier": .255},
            },
        }
        with patch("builtins.open", side_effect=[
            mock_open(read_data=json.dumps(report)).return_value,
            mock_open(read_data=json.dumps(audit)).return_value,
            mock_open(read_data=json.dumps({"by_style": {}})).return_value,
            mock_open(read_data=json.dumps({"by_market_side_line": {}})).return_value,
            mock_open(read_data=json.dumps({"policy_id": "forward-test"})).return_value,
        ]):
            policy = APP.player_prop_automatic_policy()
        self.assertTrue(policy["market_rules"]["batter:hits"]["automatic_eligible"])
        self.assertFalse(policy["market_rules"]["batter:total_bases"]["automatic_eligible"])
        self.assertTrue(policy["market_rules"]["batter:home_runs"]["automatic_eligible"])
        self.assertEqual(policy["market_rules"]["batter:home_runs"]["blocked_sides"], [])
        self.assertFalse(policy["market_rules"]["batter:hits_runs_rbi"]["automatic_eligible"])
        self.assertTrue(policy["market_rules"]["batter:rbi"]["automatic_eligible"])
        self.assertFalse(policy["market_rules"]["pitcher:outs"]["automatic_eligible"])
        self.assertFalse(policy["market_rules"]["pitcher:outs"]["quality_checks"]["maximum_brier"])

    def test_unmapped_player_market_groups_are_observable_but_not_guessed(self):
        payload = {"GE": [{"G": 99999, "E": [[{
            "PL": {"N": "Test Pitcher"}, "P": 2.5, "T": 88, "C": 1.7,
        }]]}]}
        self.assertEqual(APP._parse_melbet_player_prop_groups(payload), {})
        unknown = APP._unmapped_melbet_player_prop_groups(payload)
        self.assertEqual(unknown[0]["group_id"], 99999)
        self.assertEqual(unknown[0]["thresholds"], [2.5])
        self.assertEqual(unknown[0]["selection_types"], [88])

    def test_build_best_snapshot_archives_exact_ranked_card(self):
        result = APP.record_player_prop_build({
            "start_date": "2026-08-04", "days": 1, "target_legs": 1,
            "build_style": "sweep",
            "build_side": "both", "minimum_odds": "1.50",
            "portfolio_mode": "independent", "prop_preset": "guarantee",
            "guarantee_robust_floor": .6,
            "rotation_depth": 2,
            "selected_prop_types": ["hits"],
            "selected_prop_sides": {"batter:hits": "under"}, "policy": {
                "minimum_probability": .65, "forward_test_policy_id": "forward-test-v1",
            },
            "entries": [{
                "game_id": 123, "player_id": 456, "player_name": "Test Batter",
                "kind": "batter", "prop": "hits", "label": "Hits", "line": 1.5,
                "side": "under", "model_probability": .86,
                "recommendation_probability": .77, "decimal_odds": 1.55,
                "robust_probability": .71, "sportsbook_probability": .60,
                "process_probability": .66, "candidate_rank": 3,
                "within_game_rank": 2, "rerank_score": .61,
                "expected_value": 1.1, "raw_line_clearance": .4,
                "normalized_line_clearance": .3, "fragility_penalty": .02,
                "fragility_reasons": ["participant_not_confirmed"],
                "sportsbook_disagreement": .06, "reranker_version": "within_game_v1",
                "selection_action": "alternate",
                "replaced_selection": {"player_id": 111, "prop": "walks", "line": .5},
                "post_selection_samples": 18,
                "official_date": "2026-08-04", "scheduled_start": "2026-08-04T23:00:00Z",
                "exact_audit_samples": 306, "selection_audit_samples": 14,
                "market_name": "Batters. Total Hits", "selection_name": "Under (1.5)",
                "audit_samples": 500,
                "selection_source": "guarantee", "guarantee_samples": 12,
                "guarantee_correct": 10, "guarantee_accuracy": 10 / 12,
                "guarantee_wilson_lower": .67, "guarantee_evidence": "established",
                "guarantee_score": .72, "guarantee_robust_floor": .6,
            }],
        })
        self.assertTrue(result["ok"])
        archived = json.loads(Path(APP.PLAYER_PROP_BUILD_LOG).read_text(encoding="utf-8"))
        self.assertEqual(archived["entries"][0]["line"], 1.5)
        self.assertEqual(archived["entries"][0]["recommendation_probability"], .77)
        self.assertEqual(archived["entries"][0]["robust_probability"], .71)
        self.assertEqual(archived["entries"][0]["process_probability"], .66)
        self.assertEqual(archived["entries"][0]["candidate_rank"], 3)
        self.assertEqual(archived["entries"][0]["within_game_rank"], 2)
        self.assertEqual(archived["entries"][0]["selection_action"], "alternate")
        self.assertEqual(archived["entries"][0]["selection_source"], "guarantee")
        self.assertEqual(archived["entries"][0]["guarantee_samples"], 12)
        self.assertEqual(archived["entries"][0]["guarantee_correct"], 10)
        self.assertEqual(archived["entries"][0]["guarantee_wilson_lower"], .67)
        self.assertEqual(archived["entries"][0]["guarantee_score"], .72)
        self.assertEqual(archived["entries"][0]["guarantee_robust_floor"], .6)
        self.assertEqual(archived["entries"][0]["replaced_selection"]["player_id"], 111)
        self.assertEqual(archived["entries"][0]["official_date"], "2026-08-04")
        self.assertEqual(archived["build_style"], "sweep")
        self.assertEqual(archived["rotation_depth"], 2)
        self.assertEqual(archived["guarantee_robust_floor"], .6)
        self.assertEqual(archived["selected_prop_sides"], {"batter:hits": "under"})
        self.assertEqual(archived["forward_test_policy_id"], "forward-test-v1")
        self.assertEqual(archived["snapshot_rule"], "Exact Build Best selections before first pitch")

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
            "model": {"decision_lines": [7.5, 8.5, 9.5, 10.5]},
            "thresholds": [
                {"line": 8.5, "over_probability": .62, "under_probability": .35, "push_probability": .03},
                {"line": 9.5, "over_probability": .48, "under_probability": .52, "push_probability": 0},
                {"line": 10.5, "over_probability": .30, "under_probability": .70, "push_probability": 0},
            ],
        }
        market = {"available": True, "lines": [8.5, 9.5], "prices_used": False, "total_odds": {
            8.5: {"over": 1.91, "under": 1.91}, 9.5: {"over": 2.2, "under": 1.65},
        }}
        policy = {"totals": {"calibration": {"promoted": True, "logit_offset": 0}}}
        with patch.object(APP, "deployment_selection_policy", return_value=policy):
            selected = APP.restrict_totals_to_available_lines(projection, market)
        self.assertEqual([row["line"] for row in selected["thresholds"]], [8.5, 9.5])
        self.assertIsNone(selected["recommended_side"])
        self.assertIsNone(selected["recommended_line"])
        self.assertFalse(selected["automatic_selection_available"])
        self.assertFalse(selected["automatic_builder_eligible"])
        self.assertEqual(selected["thresholds"][0]["melbet_odds"], {"over": 1.91, "under": 1.91})

    def test_totals_auto_selection_ignores_unvalidated_grid_extremes(self):
        projection = {
            "available": True, "input_completeness": 1,
            "model": {"decision_lines": [7.5, 8.5, 9.5, 10.5]},
            "thresholds": [
                {"line": 6.0, "over_probability": .91, "under_probability": .06, "push_probability": .03},
                {"line": 7.0, "over_probability": .82, "under_probability": .10, "push_probability": .08},
                {"line": 7.5, "over_probability": .72, "under_probability": .28, "push_probability": 0},
                {"line": 10.5, "over_probability": .31, "under_probability": .69, "push_probability": 0},
                {"line": 11.0, "over_probability": .20, "under_probability": .74, "push_probability": .06},
            ],
        }
        policy = {"totals": {"calibration": {"promoted": True, "logit_offset": 0}}}
        with patch.object(APP, "deployment_selection_policy", return_value=policy):
            selected = APP.restrict_totals_to_available_lines(
                projection, {"available": True, "lines": [6, 7, 7.5, 10.5, 11]},
            )
        self.assertIsNone(selected["recommended_line"])
        self.assertIsNone(selected["recommended_side"])
        self.assertEqual(selected["automatic_selection_lines"], [])
        self.assertEqual(selected["calibrated_decision_lines"], [7.5, 10.5])
        self.assertEqual(len(selected["thresholds"]), 5)

    def test_totals_without_tested_line_remain_manual_only(self):
        projection = {
            "available": True, "input_completeness": 1,
            "model": {"decision_lines": [7.5, 8.5, 9.5, 10.5]},
            "thresholds": [
                {"line": 6.0, "over_probability": .8, "under_probability": .1, "push_probability": .1},
                {"line": 11.0, "over_probability": .2, "under_probability": .7, "push_probability": .1},
            ],
        }
        selected = APP.restrict_totals_to_available_lines(
            projection, {"available": True, "lines": [6, 11]},
        )
        self.assertTrue(selected["selection_available"])
        self.assertFalse(selected["automatic_selection_available"])
        self.assertFalse(selected["automatic_builder_eligible"])
        self.assertIsNone(selected["recommended_line"])
        self.assertEqual(selected["audit_line"], 6.0)
        self.assertEqual(selected["audit_side"], "over")
        self.assertEqual(selected["audit_probability"], .8889)

    def test_totals_without_promoted_calibration_remain_manual_only(self):
        projection = {
            "available": True, "input_completeness": 1,
            "model": {"decision_lines": [7.5, 8.5, 9.5, 10.5]},
            "thresholds": [
                {"line": 7.5, "over_probability": .68, "under_probability": .32, "push_probability": 0},
            ],
        }
        policy = {"totals": {"calibration": {"promoted": False}}}
        with patch.object(APP, "deployment_selection_policy", return_value=policy):
            selected = APP.restrict_totals_to_available_lines(
                projection, {"available": True, "lines": [7.5]},
            )
        self.assertTrue(selected["selection_available"])
        self.assertFalse(selected["automatic_selection_available"])
        self.assertFalse(selected["automatic_builder_eligible"])
        self.assertIsNone(selected["recommended_line"])
        self.assertEqual(selected["audit_line"], 7.5)
        self.assertEqual(selected["audit_side"], "over")
        self.assertEqual(selected["audit_probability"], .68)

    def test_promoted_totals_calibration_can_correct_moderate_over_to_under(self):
        projection = {
            "available": True, "input_completeness": 1,
            "model": {"decision_lines": [7.5]},
            "thresholds": [
                {"line": 7.5, "over_probability": .55, "under_probability": .45, "push_probability": 0},
            ],
        }
        policy = {"totals": {"calibration": {
            "promoted": True, "intercept": -.20819285, "logit_slope": .4,
        }}}
        with patch.object(APP, "deployment_selection_policy", return_value=policy):
            selected = APP.restrict_totals_to_available_lines(
                projection, {"available": True, "lines": [7.5]},
            )
        self.assertFalse(selected["automatic_selection_available"])
        self.assertIsNone(selected["recommended_side"])
        self.assertEqual(selected["thresholds"][0]["probability_calibration"], "production_logit_offset")

    def test_totals_reject_material_distribution_contradiction_without_evidence(self):
        projection = {
            "available": True, "input_completeness": 1, "expected_total_runs": 11.5,
            "model": {"decision_lines": [9.5]},
            "thresholds": [
                {"line": 9.5, "over_probability": .52, "under_probability": .48, "push_probability": 0},
            ],
        }
        policy = {"totals": {"calibration": {
            "promoted": True, "logit_slope": 1,
            "global_intercepts": {"over": -1, "under": 1},
            "line_side_intercepts": {"9.5:over": -1, "9.5:under": 1},
            "consistency_margin_runs": 1, "consistency_override_probability": .62,
            "line_side_validation": {"9.5:under": {"automatic_eligible": False}},
        }}}
        with patch.object(APP, "deployment_selection_policy", return_value=policy):
            selected = APP.restrict_totals_to_available_lines(
                projection, {"available": True, "lines": [9.5], "total_odds": {9.5: {"over": 1.91, "under": 1.91}}},
            )
        self.assertFalse(selected["automatic_selection_available"])
        self.assertIsNone(selected["recommended_side"])
        self.assertEqual(selected["thresholds"][0]["consistency_adjustment"], "rejected_contradictory_under_used_conservative_raw_over")
        self.assertTrue(any(row["side"] == "under" and "exact line/side" in row["reason"] for row in selected["automatic_selection_rejections"]))

    def test_totals_uses_distinct_line_side_intercepts(self):
        projection = {
            "available": True, "input_completeness": 1,
            "model": {"decision_lines": [7.5, 10.5]},
            "thresholds": [
                {"line": 7.5, "over_probability": .5, "under_probability": .5, "push_probability": 0},
                {"line": 10.5, "over_probability": .5, "under_probability": .5, "push_probability": 0},
            ],
        }
        policy = {"totals": {"calibration": {
            "promoted": True, "logit_slope": 1,
            "global_intercepts": {"over": 0, "under": 0},
            "line_side_intercepts": {
                "7.5:over": 1, "7.5:under": -1,
                "10.5:over": -1, "10.5:under": 1,
            },
        }}}
        with patch.object(APP, "deployment_selection_policy", return_value=policy):
            selected = APP.restrict_totals_to_available_lines(
                projection, {"available": True, "lines": [7.5, 10.5]},
            )
        self.assertIsNone(selected["recommended_line"])
        self.assertIsNone(selected["recommended_side"])
        self.assertEqual(selected["thresholds"][0]["probability_calibration"], "hierarchical_line_side_platt")

    def test_totals_caps_near_line_confidence_with_residual_distribution(self):
        projection = {
            "available": True, "input_completeness": 1,
            "expected_total_runs": 9.2,
            "prediction_interval_80": [3.4, 15.0],
            "model": {"decision_lines": [9.5]},
            "thresholds": [
                {"line": 9.5, "over_probability": .4, "under_probability": .6, "push_probability": 0},
            ],
        }
        policy = {"totals": {"calibration": {
            "promoted": True, "logit_slope": 1,
            "global_intercepts": {"over": -.8, "under": .8},
            "line_side_intercepts": {"9.5:over": -.8, "9.5:under": .8},
            "empirical_residuals": [-1.0] * 80,
            "minimum_empirical_residuals": 60,
        }, "rules": {"9.5:under": {"automatic_eligible": True, "selections": 80}}}}
        with patch.object(APP, "deployment_selection_policy", return_value=policy):
            selected = APP.restrict_totals_to_available_lines(
                projection, {"available": True, "lines": [9.5], "total_odds": {9.5: {"over": 1.91, "under": 1.91}}},
            )
        threshold = selected["thresholds"][0]
        self.assertTrue(selected["automatic_selection_available"])
        self.assertEqual(selected["recommended_side"], "under")
        self.assertLess(selected["recommended_probability"], .54)
        self.assertAlmostEqual(
            selected["recommended_probability"],
            threshold["distribution_under_probability"],
            places=4,
        )
        self.assertGreater(threshold["under_probability"], selected["recommended_probability"])

    def test_totals_automatic_selection_anchors_to_central_market_line(self):
        projection = {
            "available": True, "input_completeness": 1, "expected_total_runs": 9,
            "model": {"decision_lines": [7.5, 9.5, 10.5]},
            "thresholds": [
                {"line": 7.5, "over_probability": .75, "under_probability": .25, "push_probability": 0},
                {"line": 8.0, "over_probability": .62, "under_probability": .32, "push_probability": .06},
                {"line": 9.5, "over_probability": .48, "under_probability": .52, "push_probability": 0},
                {"line": 10.5, "over_probability": .25, "under_probability": .75, "push_probability": 0},
            ],
        }
        market = {
            "available": True, "lines": [7.5, 8, 9.5, 10.5],
            "total_odds": {
                7.5: {"over": 1.5, "under": 2.4},
                8.0: {"over": 1.91, "under": 1.91},
                9.5: {"over": 2.05, "under": 1.78},
                10.5: {"over": 2.5, "under": 1.45},
            },
        }
        policy = {"totals": {"calibration": {"promoted": True, "logit_offset": 0}}}
        with patch.object(APP, "deployment_selection_policy", return_value=policy):
            selected = APP.restrict_totals_to_available_lines(projection, market)
        self.assertEqual(selected["central_market_line"], 8.0)
        self.assertEqual(selected["audit_line"], 8.0)
        self.assertEqual(selected["audit_selection_rule"], "exact_balanced_market_line_max_probability_side_push_aware")
        self.assertFalse(selected["automatic_selection_available"])
        self.assertIsNone(selected["recommended_line"])

    def test_totals_automatic_selection_uses_nearest_consistent_fallback_line(self):
        projection = {
            "available": True, "input_completeness": 1, "expected_total_runs": 9,
            "prediction_interval_80": [4, 14],
            "model": {"decision_lines": [7.5, 8.5, 9.5]},
            "thresholds": [
                {"line": 7.5, "over_probability": .70, "under_probability": .30, "push_probability": 0},
                {"line": 8.5, "over_probability": .40, "under_probability": .60, "push_probability": 0},
                {"line": 9.5, "over_probability": .30, "under_probability": .70, "push_probability": 0},
            ],
        }
        market = {
            "available": True, "lines": [7.5, 8.5, 9.5],
            "total_odds": {
                7.5: {"over": 1.65, "under": 2.2},
                8.5: {"over": 1.91, "under": 1.91},
                9.5: {"over": 2.2, "under": 1.65},
            },
        }
        policy = {"totals": {"calibration": {"promoted": True, "logit_offset": 0}}}
        with patch.object(APP, "deployment_selection_policy", return_value=policy):
            selected = APP.restrict_totals_to_available_lines(projection, market)

        self.assertFalse(selected["automatic_selection_available"])
        self.assertEqual(selected["central_market_line"], 8.5)
        self.assertIsNone(selected["recommended_line"])
        self.assertIsNone(selected["recommended_side"])

    def test_totals_automatic_selection_uses_consistent_central_integer_as_last_fallback(self):
        projection = {
            "available": True, "input_completeness": 1, "expected_total_runs": 8.4,
            "prediction_interval_80": [3.8, 13.0],
            "model": {"decision_lines": [7.5]},
            "thresholds": [
                {"line": 7.0, "over_probability": .62, "under_probability": .38, "push_probability": 0},
                {"line": 7.5, "over_probability": .35, "under_probability": .65, "push_probability": 0},
            ],
        }
        market = {
            "available": True, "lines": [7.0, 7.5],
            "total_odds": {
                7.0: {"over": 1.91, "under": 1.91},
                7.5: {"over": 2.1, "under": 1.75},
            },
        }
        policy = {"totals": {"calibration": {"promoted": True, "logit_offset": 0}}}
        with patch.object(APP, "deployment_selection_policy", return_value=policy):
            selected = APP.restrict_totals_to_available_lines(projection, market)

        self.assertFalse(selected["automatic_selection_available"])
        self.assertIsNone(selected["recommended_line"])
        self.assertEqual(selected["audit_line"], 7.0)
        self.assertEqual(selected["automatic_selection_policy"]["status"], "distribution_consistency_rejected")

    def test_totals_empirical_disagreement_forces_abstention(self):
        projection = {
            "available": True, "input_completeness": 1,
            "expected_total_runs": 9.2, "prediction_interval_80": [4.0, 14.5],
            "model": {"decision_lines": [9.5]},
            "thresholds": [
                {"line": 9.5, "over_probability": .64, "under_probability": .36, "push_probability": 0},
            ],
        }
        policy = {"totals": {"calibration": {
            "promoted": True, "logit_slope": 1,
            "empirical_residuals": [-2.0] * 80,
            "minimum_empirical_residuals": 60,
        }, "rules": {"9.5:over": {"automatic_eligible": True, "selections": 80}}}}
        with patch.object(APP, "deployment_selection_policy", return_value=policy):
            selected = APP.restrict_totals_to_available_lines(
                projection,
                {"available": True, "lines": [9.5], "total_odds": {9.5: {"over": 1.91, "under": 1.91}}},
            )
        self.assertFalse(selected["automatic_builder_eligible"])
        self.assertIsNone(selected["recommended_line"])
        self.assertTrue(any("empirical residuals" in row.get("reason", "") for row in selected["automatic_selection_rejections"]))


if __name__ == "__main__":
    unittest.main()
