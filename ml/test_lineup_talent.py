import unittest

from ml.lineup_talent import apply_boxscore, features, fresh_state, start_season
from ml.totals_predict import neutralize_missing_lineup_talent


def box(season, player_id, hits=0, home_runs=0, plate_appearances=4):
    return {
        "season": season,
        "home": {"players": [{
            "player_id": player_id,
            "batting": {
                "plateAppearances": plate_appearances, "atBats": plate_appearances,
                "hits": hits, "homeRuns": home_runs, "doubles": 0, "triples": 0,
                "baseOnBalls": 0, "hitByPitch": 0, "sacFlies": 0,
                "strikeOuts": 0,
            },
        }]},
        "away": {"players": []},
    }


class LineupTalentTests(unittest.TestCase):
    def test_current_game_is_not_visible_until_applied(self):
        state = fresh_state()
        context = {
            "home": {"lineup_ids": [1]},
            "away": {"lineup_ids": [2]},
        }
        before = features(state, context)
        apply_boxscore(state, box(2026, 1, hits=4, home_runs=2))
        after = features(state, context)
        self.assertEqual(before[0], 0)
        self.assertGreater(after[0], 0)
        self.assertGreater(after[3], 0)

    def test_offseason_retains_but_regresses_player_evidence(self):
        state = fresh_state()
        context = {
            "home": {"lineup_ids": [1]},
            "away": {"lineup_ids": [2]},
        }
        for _ in range(20):
            apply_boxscore(state, box(2025, 1, hits=2, home_runs=1))
        before = features(state, context)[0]
        start_season(state, 2026)
        after = features(state, context)[0]
        self.assertGreater(after, 0)
        self.assertLess(after, before)

    def test_missing_lineup_is_neutral(self):
        self.assertEqual(features(fresh_state(), None)[:5], [0, 0, 0, 0, 0])

    def test_missing_totals_lineup_uses_training_reference(self):
        values = [.63, .064, -.26, 0]
        reference = [.651, .066, -.264, .623]
        self.assertEqual(
            neutralize_missing_lineup_talent(values, None, reference),
            reference,
        )

    def test_partial_totals_lineup_is_shrunk_toward_training_reference(self):
        values = [.69, .08, -.20, .4]
        reference = [.65, .06, -.26, .62]
        context = {
            "home": {"lineup_ids": [1, 2, 3]},
            "away": {"lineup_ids": [4, 5, 6]},
        }
        adjusted = neutralize_missing_lineup_talent(values, context, reference)
        self.assertAlmostEqual(adjusted[0], .65 + (.69 - .65) / 3)
        self.assertAlmostEqual(adjusted[3], .62 + (.4 - .62) / 3)


if __name__ == "__main__":
    unittest.main()
