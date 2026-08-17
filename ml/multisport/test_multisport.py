from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest

from ml.multisport.evaluation import binary_metrics, promotion_decision
from ml.multisport.ratings import TimeDecayElo
from ml.multisport.score_models import dixon_coles_matrix, series_win_probability
from ml.multisport.train import train
from ml.multisport.refresh_readiness import result_age_hours


class MultisportFoundationTests(unittest.TestCase):
    def test_rating_probability_is_locked_before_update(self):
        rating = TimeDecayElo()
        at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        before = rating.probability("A", "B", at)
        returned = rating.update("A", "B", 3, 0, at)
        self.assertAlmostEqual(before, returned)
        self.assertGreater(rating.probability("A", "B", at + timedelta(days=1)), before)

    def test_dixon_coles_distribution_is_normalized(self):
        result = dixon_coles_matrix(1.55, 1.08)
        self.assertAlmostEqual(sum(result["matrix"].values()), 1.0, places=9)
        self.assertAlmostEqual(result["home_win"] + result["draw"] + result["away_win"], 1.0, places=9)

    def test_series_probability(self):
        self.assertAlmostEqual(series_win_probability([.5, .5, .5]), .5)
        self.assertGreater(series_win_probability([.7, .7, .7]), .7)

    def test_probability_metrics_and_gate_remain_conservative(self):
        candidate = binary_metrics([1, 0, 1, 0], [.8, .2, .7, .3])
        baseline = binary_metrics([1, 0, 1, 0], [.5, .5, .5, .5])
        decision = promotion_decision(candidate, baseline)
        self.assertLess(candidate["brier"], baseline["brier"])
        self.assertFalse(decision["passed"])
        self.assertFalse(decision["checks"]["live_samples"])

    def test_training_contract_excludes_market_and_odds_features(self):
        start = datetime(2022, 1, 1, tzinfo=timezone.utc)
        rows = [{
            "event_id": str(index), "event_time": (start + timedelta(days=index)).isoformat(),
            "_event_time": start + timedelta(days=index), "label": index % 2,
            "features": {"team_rating": float(index % 7), "market_home_probability": .8, "closing_odds": 1.4, "total_line": 44.5},
        } for index in range(120)]
        report = train(rows, "test", "winner")
        self.assertEqual(report["features"], ["team_rating"])
        self.assertTrue(report["odds_independent"])

    def test_readiness_refresh_can_skip_a_recent_result(self):
        now = datetime(2026, 8, 16, 12, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "predictions.json"
            path.write_text(json.dumps({"generated_at": (now - timedelta(hours=2)).isoformat()}), encoding="utf-8")
            self.assertAlmostEqual(result_age_hours(path, now), 2.0)


if __name__ == "__main__":
    unittest.main()
