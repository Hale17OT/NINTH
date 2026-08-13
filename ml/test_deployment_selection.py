import unittest

from ml.evaluate_deployment_selection import (
    _calibrated_line_probabilities,
    build_report,
    calibrated_over_probability,
    fit_line_side_calibration,
    fit_logit_offset,
)


class DeploymentSelectionAuditTests(unittest.TestCase):
    def test_inaccurate_exact_total_rule_is_reported_without_blocking_moneyline(self):
        snapshots = {}
        scores = {}
        for game_id in range(1, 61):
            home_wins = game_id <= 42
            snapshots[game_id] = {
                "home_win_probability": .55,
                "totals_projection": {
                    "recommended_line": 7.5, "recommended_side": "over",
                    "recommended_probability": .62,
                },
            }
            # Only 26 of 60 totals finish over 7.5.
            total = 9 if game_id <= 26 else 7
            scores[game_id] = {
                "home": total if home_wins else 0,
                "away": 0 if home_wins else total,
            }
        report = build_report(snapshots, scores)
        self.assertTrue(report["moneyline"]["automatic_eligible"])
        self.assertIsNone(report["moneyline"]["minimum_probability"])
        self.assertEqual(report["moneyline"]["selections"], 60)
        self.assertFalse(report["totals"]["rules"]["7.5:over"]["automatic_eligible"])
        self.assertEqual(report["totals"]["automatic_eligible_rules"], 0)

    def test_regularized_offset_reduces_systematic_over_probability(self):
        rows = [
            {"over_probability": .62, "actual_over": int(index < 35)}
            for index in range(100)
        ]
        offset = fit_logit_offset(rows)
        self.assertLess(offset, 0)
        self.assertLess(calibrated_over_probability(.62, offset), .62)

    def test_hierarchical_calibration_is_line_and_side_aware(self):
        rows = []
        for index in range(80):
            rows.extend((
                {"line": 7.5, "over_probability": .5, "actual_over": int(index < 64)},
                {"line": 10.5, "over_probability": .5, "actual_over": int(index < 16)},
            ))
        calibration = fit_line_side_calibration(rows, penalty=5, logit_slope=1)
        low_line_over, _ = _calibrated_line_probabilities(.5, 7.5, calibration)
        high_line_over, _ = _calibrated_line_probabilities(.5, 10.5, calibration)
        self.assertGreater(low_line_over, .5)
        self.assertLess(high_line_over, .5)
        self.assertNotEqual(
            calibration["line_side_intercepts"]["7.5:over"],
            calibration["line_side_intercepts"]["10.5:over"],
        )


if __name__ == "__main__":
    unittest.main()
