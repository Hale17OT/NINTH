import unittest

from ml.totals_features import TOTAL_FEATURE_NAMES, apply_totals_result, fresh_totals_state, totals_features
from ml.totals_predict import predict


class TotalsModelTests(unittest.TestCase):
    def test_current_game_bullpen_usage_is_not_a_pregame_feature(self):
        state = fresh_totals_state()
        context = {"home": {"bullpen_pitches": 999}, "away": {"bullpen_pitches": 999}}
        values = totals_features(state, 1, 2, "2026-07-01", context)
        index = TOTAL_FEATURE_NAMES.index("bullpen_3day_pitches_sum")
        self.assertEqual(values[index], 0)

        completed = {"game_id": 1, "date": "2026-07-01", "home_id": 1, "away_id": 2, "home_score": 4, "away_score": 3}
        apply_totals_result(state, completed, {"home": {"bullpen_pitches": 40}, "away": {"bullpen_pitches": 55}})
        next_values = totals_features(state, 1, 2, "2026-07-02")
        self.assertEqual(next_values[index], 95)

    def test_threshold_distribution_is_ordered_and_complementary(self):
        projection = predict(147, 142, "2026-07-21")
        self.assertTrue(projection["available"])
        rows = projection["thresholds"]
        over = [row["over_probability"] for row in rows]
        self.assertEqual(over, sorted(over, reverse=True))
        for row in rows:
            self.assertAlmostEqual(row["over_probability"] + row["under_probability"] + row["push_probability"], 1, places=3)
            if float(row["line"]).is_integer():
                self.assertGreater(row["push_probability"], 0)
            else:
                self.assertEqual(row["push_probability"], 0)
        self.assertIn(projection["recommended_line"], projection["model"]["decision_lines"])

    def test_user_supplied_market_grid_is_scored_without_odds(self):
        projection = predict(147, 142, "2026-07-21", selectable_lines=[7, 7.5, 8, 8.5, 9, 9.5, 10])
        self.assertEqual([row["line"] for row in projection["thresholds"]], [7, 7.5, 8, 8.5, 9, 9.5, 10])
        self.assertFalse(projection["market_inputs"])


if __name__ == "__main__":
    unittest.main()
