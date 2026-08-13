import unittest

import numpy as np

from ml.pitching_availability import (
    apply_game, features, fresh_state, hydrate_state, serializable_state,
)


class PitchingAvailabilityTests(unittest.TestCase):
    def setUp(self):
        self.game = {
            "game_id": 1, "date": "2026-07-01",
            "home_id": 10, "away_id": 20,
        }
        self.context = {
            "home": {
                "starter_id": 100, "starter_game_outs": 18,
                "starter_game_earned_runs": 1, "starter_game_pitches": 92,
            },
            "away": {
                "starter_id": 200, "starter_game_outs": 12,
                "starter_game_earned_runs": 4, "starter_game_pitches": 88,
            },
        }
        self.statcast = {
            "home_starter": {
                "pitcher_id": 100, "pitches": 92, "plate_appearances": 22,
                "xwoba": .280, "avg_velocity": 94,
            },
            "away_starter": {
                "pitcher_id": 200, "pitches": 88, "plate_appearances": 20,
                "xwoba": .390, "avg_velocity": 91,
            },
            "home_pitcher_lines": [
                {"pitcher_id": 100},
                {"pitcher_id": 101, "pitches": 20, "plate_appearances": 5,
                 "xwoba": .250, "strikeouts": 2, "walks": 0},
            ],
            "away_pitcher_lines": [
                {"pitcher_id": 200},
                {"pitcher_id": 201, "pitches": 35, "plate_appearances": 8,
                 "xwoba": .410, "strikeouts": 0, "walks": 2},
            ],
        }

    def test_current_game_is_not_visible_until_applied(self):
        state = fresh_state()
        before = features(state, self.game, self.context)
        apply_game(state, self.game, self.context, self.statcast)
        future = {**self.game, "game_id": 2, "date": "2026-07-02"}
        after = features(state, future, self.context)
        self.assertFalse(np.allclose(before[0], after[0]))
        self.assertFalse(np.allclose(before[1], after[1]))

    def test_final_boxscore_bullpen_ids_are_not_used_as_pregame_roster(self):
        state = fresh_state()
        clean = features(state, self.game, self.context)
        contaminated = {
            **self.context,
            "home": {**self.context["home"], "bullpen_pitcher_ids": [999999]},
            "away": {**self.context["away"], "bullpen_pitcher_ids": [888888]},
        }
        self.assertEqual(clean, features(state, self.game, contaminated))

    def test_serialized_state_preserves_features(self):
        state = fresh_state()
        apply_game(state, self.game, self.context, self.statcast)
        future = {**self.game, "game_id": 2, "date": "2026-07-03"}
        expected = features(state, future, self.context)
        restored = hydrate_state(serializable_state(state))
        actual = features(restored, future, self.context)
        np.testing.assert_allclose(expected[0], actual[0])
        np.testing.assert_allclose(expected[1], actual[1])


if __name__ == "__main__":
    unittest.main()
