import unittest
from unittest.mock import patch

from ml import player_prop_reranker_shadow_candidate as shadow


def _card(wins, losses):
    return {
        "complete": True,
        "clean_sweep": losses == 0,
        "legs": wins + losses,
        "wins": wins,
        "losses": losses,
        "unresolved": 0,
        "pushes": 0,
    }


class PlayerPropRerankerShadowCandidateTests(unittest.TestCase):
    def test_scope_is_fixed_and_cannot_promote_itself(self):
        candidate = shadow.candidate_definition()

        self.assertEqual(candidate["build_style"], "sweep")
        self.assertEqual(candidate["target_legs"], 3)
        self.assertEqual(candidate["minimum_odds"], 1.3)
        self.assertEqual(candidate["minimum_process_probability"], .65)
        self.assertFalse(candidate["promoted"])
        self.assertFalse(candidate["automatic_promotion"])

    def test_only_post_start_dates_count_toward_forward_gate(self):
        builds = [
            {"start_date": "2026-08-14"},
            {"start_date": "2026-08-15"},
            {"start_date": "2026-08-17"},
        ]
        row = {"game_id": 1, "process_probability": .70}

        def replay(_board, _target, _cap, score_name, rotations):
            card = _card(3, 0) if score_name == "rerank_score" else _card(2, 1)
            return [card.copy() for _ in range(rotations)]

        with (
            patch.object(shadow, "candidates_by_date", return_value={
                "2026-08-14": [row], "2026-08-15": [row], "2026-08-17": [row],
            }),
            patch.object(shadow, "history", return_value={}),
            patch.object(shadow, "evaluated_rows", return_value=[]),
            patch.object(shadow, "build_selection_report", return_value={}),
            patch.object(shadow, "scored_board", return_value=[row]),
            patch.object(shadow, "rerank", side_effect=lambda value, *_: {
                **value, "rerank_score": .75,
            }),
            patch.object(shadow, "replay_cards", side_effect=replay),
        ):
            report = shadow.evaluate(builds, {}, "2026-08-17", historical_days=1)

        self.assertEqual(report["historical_context"]["dates"], ["2026-08-15"])
        self.assertEqual(report["all_archived_context"]["dates"], ["2026-08-14", "2026-08-15"])
        self.assertEqual(report["forward_observation"]["dates"], ["2026-08-17"])
        self.assertEqual(report["forward_observation"]["attempted_dates"], ["2026-08-17"])
        self.assertEqual(report["forward_observation"]["incomplete_dates"], [])
        self.assertEqual(report["promotion_gate"]["observed_forward_dates"], 1)
        self.assertFalse(report["promotion_gate"]["eligible"])

    def test_incomplete_forward_cards_do_not_count_toward_gate(self):
        builds = [{"start_date": "2026-08-17"}]
        row = {"game_id": 1, "process_probability": .70}

        def replay(_board, _target, _cap, score_name, rotations):
            card = {
                **_card(2, 0),
                "complete": False,
                "clean_sweep": False,
                "legs": 2,
            }
            return [card.copy() for _ in range(rotations)]

        with (
            patch.object(shadow, "candidates_by_date", return_value={"2026-08-17": [row]}),
            patch.object(shadow, "history", return_value={}),
            patch.object(shadow, "evaluated_rows", return_value=[]),
            patch.object(shadow, "build_selection_report", return_value={}),
            patch.object(shadow, "scored_board", return_value=[row]),
            patch.object(shadow, "rerank", side_effect=lambda value, *_: {
                **value, "rerank_score": .75,
            }),
            patch.object(shadow, "replay_cards", side_effect=replay),
        ):
            report = shadow.evaluate(builds, {}, "2026-08-17", historical_days=1)

        self.assertEqual(report["forward_observation"]["attempted_dates"], ["2026-08-17"])
        self.assertEqual(report["forward_observation"]["dates"], [])
        self.assertEqual(report["forward_observation"]["incomplete_dates"], ["2026-08-17"])
        self.assertEqual(report["promotion_gate"]["observed_forward_dates"], 0)
        self.assertEqual(report["forward_observation"]["baseline"]["cards"], 0)


if __name__ == "__main__":
    unittest.main()
