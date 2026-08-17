import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ml.multisport.predict_football_open import model_readiness, refresh_live_audit


class FootballReadinessAuditTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.artifacts = self.root / "artifacts"
        self.artifacts.mkdir()
        for market in ("home_win", "over_2_5", "both_teams_score"):
            (self.artifacts / f"{market}.json").write_text(json.dumps({
                "historical_readiness": {"passed": True},
                "untouched_climatology": {"brier": .25},
            }), encoding="utf-8")

    def tearDown(self):
        self.temporary.cleanup()

    def test_live_gate_is_separate_for_each_exact_market(self):
        audit = {"markets": {
            "home_win": {"passed": True},
            "over_2_5": {"passed": False},
            "both_teams_score": {"passed": False},
        }}
        readiness = model_readiness(self.artifacts, audit)
        self.assertEqual(readiness["automatic_builder_eligible"], {
            "home_win": True, "over_2_5": False, "both_teams_score": False,
        })

    def test_thirty_immutable_correct_snapshots_pass_live_brier(self):
        now = datetime(2026, 8, 14, tzinfo=timezone.utc)
        entries = []
        for index in range(30):
            entries.append({
                "event_id": f"event-{index}",
                "event_time": (now - timedelta(days=1)).isoformat(),
                "generated_at": (now - timedelta(days=2)).isoformat(),
                "competition_code": "E0",
                "markets": {"home_win": .9, "over_2_5": .9, "both_teams_score": .9},
                "result": {"home_score": 2, "away_score": 1},
            })
        ledger = self.root / "audit.jsonl"
        ledger.write_text("\n".join(json.dumps(entry) for entry in entries), encoding="utf-8")
        audit = refresh_live_audit({}, ledger, self.artifacts, now=now)
        for market in audit["markets"].values():
            self.assertEqual(market["samples"], 30)
            self.assertAlmostEqual(market["brier"], .01)
            self.assertTrue(market["passed"])

    def test_first_snapshot_is_not_replaced_by_later_refresh(self):
        now = datetime(2026, 8, 14, tzinfo=timezone.utc)
        ledger = self.root / "audit.jsonl"
        base = {
            "event_id": "fixture-1", "event_time": (now + timedelta(days=1)).isoformat(),
            "generated_at": now.isoformat(), "competition": "Premier League",
            "competition_code": "E0",
            "home_team": "Home", "away_team": "Away",
        }
        refresh_live_audit({}, ledger, self.artifacts, [{**base, "markets": {"home_win": .61}}], now)
        refresh_live_audit({}, ledger, self.artifacts, [{**base, "markets": {"home_win": .88}}], now)
        archived = json.loads(ledger.read_text(encoding="utf-8").strip())
        self.assertEqual(archived["markets"]["home_win"], .61)


if __name__ == "__main__":
    unittest.main()
