import unittest

import numpy as np

from ml.research_pitcher_monte_carlo import (
    MAX_BATTERS_FACED,
    PROP_LINES,
    _event_probability_matrices,
    simulate_pitcher_matchup,
)


class PitcherMonteCarloTests(unittest.TestCase):
    def test_counts_are_coherent(self):
        bf = np.zeros(MAX_BATTERS_FACED)
        bf[19:24] = .2
        outcomes = np.asarray((.25, .08, .14, .03, .50))
        auxiliary = {
            "outs": np.eye(28)[15],
        }
        draws = simulate_pitcher_matchup(
            bf, outcomes, auxiliary, simulations=20_000, seed=91,
        )
        self.assertTrue(np.all(draws["hits_allowed"] >= draws["home_runs_allowed"]))
        for prop in (
            "strikeouts", "walks", "hits_allowed",
            "home_runs_allowed",
        ):
            self.assertTrue(np.all(draws[prop] <= draws["batters_faced"]))

    def test_invalid_shapes_are_rejected(self):
        with self.assertRaises(ValueError):
            simulate_pitcher_matchup(np.ones(10), np.ones(5), simulations=10)

    def test_monte_carlo_agrees_with_exact_event_distribution(self):
        bf = np.zeros(MAX_BATTERS_FACED)
        bf[17:22] = .2
        outcomes = np.asarray((.24, .09, .15, .03, .49))
        exact = _event_probability_matrices(
            bf.reshape(1, -1), outcomes.reshape(1, -1),
        )
        draws = simulate_pitcher_matchup(
            bf, outcomes, simulations=180_000, seed=112,
        )
        for prop in (
            "strikeouts", "walks", "hits_allowed",
            "home_runs_allowed",
        ):
            for line_index, line in enumerate(PROP_LINES[prop]):
                observed = float(np.mean(draws[prop] > line))
                self.assertAlmostEqual(
                    observed,
                    float(exact[prop][0, line_index]),
                    delta=.007,
                )


if __name__ == "__main__":
    unittest.main()
