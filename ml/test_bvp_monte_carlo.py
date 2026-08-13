import unittest

import numpy as np

from ml.research_bvp_monte_carlo import (
    PA_PROP_LINES,
    exact_matchup_probabilities,
    paired_game_bootstrap,
    simulate_matchup,
)


class BatterPitcherMonteCarloTests(unittest.TestCase):
    def setUp(self):
        self.pa = np.asarray((.01, .04, .20, .40, .25, .08, .02))
        self.outcomes = np.asarray((.43, .22, .08, .01, .17, .05, .01, .03))

    def test_simulation_outputs_coherent_counts(self):
        draws = simulate_matchup(self.pa, self.outcomes, simulations=20_000, seed=7)
        self.assertTrue(np.all(draws["hits"] >= draws["home_runs"]))
        self.assertTrue(np.all(draws["total_bases"] >= draws["hits"]))
        self.assertTrue(np.all(draws["hits"] + draws["strikeouts"] <= draws["plate_appearances"]))
        self.assertTrue(np.all(draws["plate_appearances"] >= 1))
        self.assertTrue(np.all(draws["plate_appearances"] <= 7))

    def test_exact_probabilities_are_monotone_by_line(self):
        exact = exact_matchup_probabilities(self.pa, self.outcomes)
        for prop, lines in PA_PROP_LINES.items():
            values = [exact[prop][float(line)] for line in lines]
            self.assertTrue(all(left >= right for left, right in zip(values, values[1:])))
            self.assertTrue(all(0 <= value <= 1 for value in values))

    def test_monte_carlo_agrees_with_exact_distribution(self):
        exact = exact_matchup_probabilities(self.pa, self.outcomes)
        draws = simulate_matchup(
            self.pa, self.outcomes, simulations=150_000, seed=19,
        )
        for prop, lines in PA_PROP_LINES.items():
            for line in lines:
                observed = float(np.mean(draws[prop] > line))
                self.assertAlmostEqual(
                    observed, exact[prop][float(line)], delta=.008,
                )

    def test_invalid_probability_shapes_are_rejected(self):
        with self.assertRaises(ValueError):
            simulate_matchup(np.ones(6), self.outcomes, simulations=10)

    def test_game_block_bootstrap_detects_clear_improvement(self):
        actual = np.asarray([0, 0, 1, 1] * 25)
        simulator = np.where(actual == 1, .9, .1)
        incumbent = np.full(len(actual), .5)
        games = np.repeat(np.arange(25), 4)
        result = paired_game_bootstrap(
            actual, simulator, incumbent, games, resamples=500, seed=5,
        )
        self.assertLess(
            result["game_block_bootstrap_95_ci"][1], 0,
        )
        self.assertEqual(
            result["bootstrap_probability_of_improvement"], 1.0,
        )


if __name__ == "__main__":
    unittest.main()
