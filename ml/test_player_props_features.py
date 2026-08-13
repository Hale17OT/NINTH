import unittest

import numpy as np

from ml.player_props_features import (
    BATTER_PROPS,
    PITCHER_PROPS,
    build_features,
    feature_names,
    fresh_state,
    retarget_line,
    _outcomes,
)


class PlayerPropFeatureTests(unittest.TestCase):
    def _state(self, kind):
        state = fresh_state()
        props = BATTER_PROPS if kind == "batter" else PITCHER_PROPS
        bucket = state["batters" if kind == "batter" else "pitchers"][1]
        for index in range(5):
            row = {
                "date": f"2026-04-{index + 1:02d}",
                "season": 2026,
                "plate_appearances": 4 if kind == "batter" else 24,
            }
            for prop in props:
                row[prop] = float((index + len(prop)) % 3)
            bucket["games"].append(row)
        opponent = state["teams"][20]["pitching" if kind == "batter" else "batting"]
        for _ in range(5):
            opponent.append({
                "plate_appearances": 38, "hits_allowed": 8, "home_runs_allowed": 1,
                "earned_runs": 4, "walks": 3, "strikeouts": 9,
                "hits": 8, "runs": 4, "home_runs": 1,
            })
        return state

    def test_feature_vector_lengths_match_schema(self):
        for kind, prop in (("batter", "hits"), ("pitcher", "strikeouts")):
            vector = build_features(
                fresh_state(), kind, 1, 10, 20, "2026-05-01", 2026, prop, .5,
            )
            self.assertEqual(len(vector), len(feature_names(kind)))

    def test_new_batter_outcomes_are_derived_from_official_box_score_fields(self):
        outcomes = _outcomes("batter", {
            "hits": 4, "doubles": 1, "triples": 1, "homeRuns": 1,
            "runs": 2, "rbi": 3,
        })
        self.assertEqual(outcomes["singles"], 1)
        self.assertEqual(outcomes["triples"], 1)
        self.assertEqual(outcomes["hits_runs_rbi"], 9)

    def test_pitcher_win_uses_official_game_decision(self):
        self.assertEqual(_outcomes("pitcher", {"wins": 1})["win"], 1)
        self.assertEqual(_outcomes("pitcher", {"wins": 0})["win"], 0)

    def test_retargeting_matches_direct_prop_construction(self):
        for kind, base_prop, target_prop in (
            ("batter", "hits", "home_runs"),
            ("pitcher", "strikeouts", "walks"),
        ):
            state = self._state(kind)
            common = (state, kind, 1, 10, 20, "2026-05-01", 2026)
            direct = build_features(*common, target_prop, .5)
            base = build_features(*common, base_prop, .5)
            retargeted = retarget_line(
                base, state, kind, 1, 2026, target_prop, .5, opponent_id=20,
            )
            np.testing.assert_allclose(retargeted, direct)

    def test_pitcher_features_include_known_opposing_lineup_tendencies(self):
        state = self._state("pitcher")
        for player_id in range(100, 109):
            bucket = state["batters"][player_id]
            for index in range(10):
                bucket["games"].append({
                    "date": f"2026-04-{index + 1:02d}", "season": 2026,
                    "plate_appearances": 4, "hits": 2, "strikeouts": 0,
                    "walks": 1, "home_runs": 1,
                })
        without = build_features(
            state, "pitcher", 1, 10, 20, "2026-05-01", 2026,
            "strikeouts", 4.5,
        )
        with_lineup = build_features(
            state, "pitcher", 1, 10, 20, "2026-05-01", 2026,
            "strikeouts", 4.5, opponent_lineup_ids=list(range(100, 109)),
        )
        self.assertEqual(len(with_lineup), len(feature_names("pitcher")))
        names = feature_names("pitcher")
        for name in (
            "opponent_lineup_hit_rate", "opponent_lineup_walk_rate",
            "opponent_lineup_home_run_rate",
        ):
            index = names.index(name)
            self.assertGreater(with_lineup[index], without[index])


if __name__ == "__main__":
    unittest.main()
