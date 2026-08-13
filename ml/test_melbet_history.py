import tempfile
import unittest
from pathlib import Path

from ml.melbet_history import analyse_history, load_history, normalize_slip, save_slip, save_slips


def sample_slip(slip_id="123", status="Loss"):
    return {
        "slip_id": slip_id,
        "placed_at": "10/08/2026 / 22:39",
        "status": status,
        "bet_type": "Accumulator",
        "total_odds": 4.2,
        "stake": 20,
        "currency": "ETB",
        "potential_winnings": 84,
        "legs": [
            {"selection": "Sonny Gray Total Strike-Outs Over 4.5", "event": "Toronto - Boston", "status": "Loss", "odds": 1.8},
            {"selection": "Jorge Polanco Total RBIs Under 0.5", "event": "Atlanta - New York", "status": "Win", "odds": 1.3},
            {"selection": "Accumulator Bonus", "status": "Win", "odds": 1.07, "is_bonus": True},
        ],
    }


class MelbetHistoryTests(unittest.TestCase):
    def test_normalizes_market_side_and_excludes_bonus_from_leg_count(self):
        slip = normalize_slip(sample_slip())
        self.assertEqual(slip["leg_count"], 2)
        self.assertEqual(slip["legs"][0]["market"], "Pitcher strikeouts")
        self.assertEqual(slip["legs"][0]["side"], "Over")
        self.assertEqual(slip["legs"][1]["market"], "RBIs")
        self.assertEqual(slip["legs"][1]["side"], "Under")

    def test_deduplicates_by_slip_number(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "history.json"
            save_slip(sample_slip(), path)
            updated = sample_slip(status="Win")
            updated["legs"][0]["status"] = "Win"
            save_slip(updated, path)
            self.assertEqual(len(load_history(path)["slips"]), 1)
            self.assertEqual(load_history(path)["slips"][0]["status"], "win")

    def test_batch_import_reports_inserted_and_updated_counts(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "history.json"
            save_slip(sample_slip("existing"), path)
            result = save_slips([sample_slip("existing"), sample_slip("new")], path)
            self.assertEqual(result["inserted"], 1)
            self.assertEqual(result["updated"], 1)
            self.assertEqual(result["total"], 2)
            self.assertEqual(len(load_history(path)["slips"]), 2)

    def test_analysis_computes_near_miss_and_settled_return(self):
        first = normalize_slip(sample_slip("a"))
        second_raw = sample_slip("b", "Win")
        second_raw["legs"][0]["status"] = "Win"
        second = normalize_slip(second_raw)
        report = analyse_history({"slips": [first, second]})
        self.assertEqual(report["overview"]["near_misses"], 1)
        self.assertEqual(report["overview"]["won_slips"], 1)
        self.assertEqual(report["overview"]["stake"], 40)
        self.assertEqual(report["overview"]["returns"], 84)


if __name__ == "__main__":
    unittest.main()
