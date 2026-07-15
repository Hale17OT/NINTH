import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


APP_PATH = Path(__file__).with_name("app.py")
SPEC = importlib.util.spec_from_file_location("ninth_stats_app", APP_PATH)
APP = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(APP)


class ProjectionIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.original_log = APP.PROJECTION_LOG
        APP.PROJECTION_LOG = str(Path(self.temp.name) / "projection_snapshots.jsonl")
        APP._projection_last.clear()
        APP._projection_last_context.clear()
        APP._projection_last_completeness.clear()
        APP._projection_last_game_state.clear()
        APP._projection_recent_alerts.clear()

    def tearDown(self):
        APP.PROJECTION_LOG = self.original_log
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

    def test_live_score_inning_and_base_out_state_move_projection(self):
        projection = {"available": True, "home_win_probability": .50, "away_win_probability": .50, "reasons": [], "historical_tier": {"accuracy": .60}}
        linescore = {"currentInning": 8, "inningState": "Bottom", "teams": {"home": {"runs": 4}, "away": {"runs": 2}}, "offense": {"first": {"id": 1}, "second": None, "third": None}}
        live = APP.apply_live_game_state(projection, linescore, {"outs": 1})
        self.assertGreater(live["home_win_probability"], .50)
        self.assertEqual(live["projection_source"], "live_game_state")
        self.assertEqual(live["projection_phase"], "live")
        self.assertEqual(live["game_state"]["inning"], 8)
        self.assertIsNone(live["historical_tier"])

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


if __name__ == "__main__":
    unittest.main()
