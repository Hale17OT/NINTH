import unittest

from ml.evaluate_deployment_selection import central_line_audit


class CentralTotalsAuditTests(unittest.TestCase):
    def test_integer_centre_is_scored_as_a_push_without_lower_line_shift(self):
        report = central_line_audit([{
            "total_runs": 8,
            "archived_audit_line": 7.5,
            "audit_thresholds": [
                {"line": 7.5, "over_probability": .62, "under_probability": .38,
                 "melbet_odds": {"over": 1.65, "under": 2.2}},
                {"line": 8.0, "over_probability": .55, "under_probability": .45,
                 "melbet_odds": {"over": 1.91, "under": 1.91}},
                {"line": 8.5, "over_probability": .48, "under_probability": .52,
                 "melbet_odds": {"over": 2.1, "under": 1.75}},
            ],
        }])

        self.assertEqual(report["forecasts"], 1)
        self.assertEqual(report["selections"], 0)
        self.assertEqual(report["pushes"], 1)
        self.assertEqual(report["lower_half_line_ties_removed"], 1)

    def test_central_audit_does_not_force_side_diversity(self):
        report = central_line_audit([
            {
                "total_runs": 10, "archived_audit_line": 8.5,
                "audit_thresholds": [{"line": 8.5, "over_probability": .6, "under_probability": .4,
                                      "melbet_odds": {"over": 1.91, "under": 1.91}}],
            },
            {
                "total_runs": 11, "archived_audit_line": 9.5,
                "audit_thresholds": [{"line": 9.5, "over_probability": .58, "under_probability": .42,
                                      "melbet_odds": {"over": 1.91, "under": 1.91}}],
            },
        ])

        self.assertEqual(report["over_selections"], 2)
        self.assertEqual(report["under_selections"], 0)
        self.assertEqual(report["accuracy"], 1.0)


if __name__ == "__main__":
    unittest.main()
