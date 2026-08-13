import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from ml.player_props_features import distribution_probability, fresh_state
from ml.player_props_predict import _count_probabilities, inference_state
from ml.evaluate_live_prop_snapshots import outcome
from ml.evaluate_observed_prop_lines import probabilities as audit_probabilities
from ml.train_player_props import _clustered_brier_skill


class _FixedProbabilityModel:
    n_features_in_ = 1

    def __init__(self, value):
        self.value = value

    def predict_proba(self, values):
        probability = np.full(len(values), self.value)
        return np.column_stack((1 - probability, probability))


class PlayerPropDistributionTests(unittest.TestCase):
    @staticmethod
    def _box_game(game_id, game_date, home_runs):
        def side(team_id, player_id, homers):
            return {
                "team_id": team_id,
                "players": [{
                    "player_id": player_id,
                    "name": f"Player {player_id}",
                    "batting_order": "100",
                    "batting": {
                        "plateAppearances": 4, "atBats": 4, "hits": homers,
                        "doubles": 0, "triples": 0, "homeRuns": homers,
                        "runs": homers, "rbi": homers, "baseOnBalls": 0,
                        "strikeOuts": 0, "stolenBases": 0,
                    },
                    "pitching": {},
                }],
            }
        return {
            "game_id": game_id, "date": game_date, "season": 2026,
            "away": side(10, 1, home_runs), "home": side(20, 2, 0),
        }

    def test_inference_state_replays_completed_games_without_future_leakage(self):
        base = fresh_state(); base["season"] = 2026
        base["batters"][1]["games"].append({
            "date": "2026-08-01", "season": 2026,
            "plate_appearances": 4, "home_runs": 0,
        })
        with tempfile.TemporaryDirectory() as directory:
            box_path = Path(directory) / "boxes.jsonl"
            statcast_path = Path(directory) / "missing-statcast.jsonl"
            games = [
                self._box_game(3, "2026-08-10", 7),
                self._box_game(2, "2026-08-09", 2),
                self._box_game(1, "2026-08-08", 0),
            ]
            box_path.write_text(
                "".join(json.dumps(game) + "\n" for game in games),
                encoding="utf-8",
            )
            state = inference_state(
                {"state": base}, "2026-08-10", 2026,
                box_path=box_path, statcast_path=statcast_path,
            )
        rows = list(state["batters"][1]["games"])
        self.assertEqual([row["date"] for row in rows], ["2026-08-08", "2026-08-09"])
        self.assertEqual([row["home_runs"] for row in rows], [0, 2])
        self.assertNotIn("2026-08-01", [row["date"] for row in rows])
        self.assertNotIn("2026-08-10", [row["date"] for row in rows])

    def test_finished_prediction_outcomes_cover_new_markets(self):
        batting = {
            "hits": 4, "doubles": 1, "triples": 1, "homeRuns": 1,
            "runs": 2, "rbi": 3, "strikeOuts": 1,
        }
        self.assertEqual(outcome(batting, "batter", "singles"), 1)
        self.assertEqual(outcome(batting, "batter", "triples"), 1)
        self.assertEqual(outcome(batting, "batter", "hits_runs_rbi"), 9)
        self.assertEqual(outcome(batting, "batter", "strikeouts"), 1)
        self.assertEqual(outcome({"wins": 1}, "pitcher", "win"), 1)

    def test_over_probability_falls_as_line_rises(self):
        values = [distribution_probability(5.4, 7.1, line) for line in (2.5, 3.5, 4.5, 5.5, 6.5)]
        self.assertTrue(all(left >= right for left, right in zip(values, values[1:])))

    def test_poisson_and_negative_binomial_probabilities_are_valid(self):
        for mean, variance in ((.12, .12), (1.2, 2.1), (5.0, 9.0), (88.0, 140.0)):
            value = distribution_probability(mean, variance, mean - .5)
            self.assertTrue(np.isfinite(value))
            self.assertGreaterEqual(value, 0)
            self.assertLessEqual(value, 1)

    def test_more_dispersion_retains_finite_sparse_event_probability(self):
        value = distribution_probability(.08, .2, .5)
        self.assertGreater(value, 0)
        self.assertLess(value, .5)

    def test_count_head_produces_monotone_threshold_probabilities(self):
        values = _count_probabilities(
            np.asarray([5.4, 3.1]), .18, (2.5, 3.5, 4.5, 5.5, 6.5),
        )
        self.assertEqual(values.shape, (2, 5))
        self.assertTrue(np.all(values[:, :-1] >= values[:, 1:]))
        self.assertTrue(np.all((values >= 0) & (values <= 1)))

    def test_clustered_skill_counts_games_instead_of_threshold_rows(self):
        result = _clustered_brier_skill(
            np.asarray([1, 1, 0, 0]),
            np.asarray([.8, .7, .2, .3]),
            np.asarray([.5, .5, .5, .5]),
            np.asarray([11, 11, 22, 22]),
            iterations=100,
        )
        self.assertEqual(result["games"], 2)
        self.assertGreater(result["mean_brier_improvement"], 0)

    def test_temporal_audit_uses_frozen_estimator_not_production_refit(self):
        values = audit_probabilities({
            "model": _FixedProbabilityModel(.9),
            "audit_model": _FixedProbabilityModel(.6),
            "lines": [.5],
            "calibrator": {"method": "raw", "blend": 1, "model": None},
        }, np.ones((2, 1)), np.full(2, .5), 2)
        np.testing.assert_allclose(values, [.6, .6])


if __name__ == "__main__":
    unittest.main()
