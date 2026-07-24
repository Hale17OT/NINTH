import unittest

import numpy as np

from ml.player_props_features import distribution_probability


class PlayerPropDistributionTests(unittest.TestCase):
    def test_over_probability_falls_as_line_rises(self):
        values = [distribution_probability(5.4, 7.1, line) for line in (2.5, 3.5, 4.5, 5.5, 6.5)]
        self.assertTrue(all(left >= right for left, right in zip(values, values[1:])))

    def test_poisson_and_negative_binomial_probabilities_are_valid(self):
        for mean, variance in ((.12, .12), (1.2, 2.1), (5.0, 9.0), (88.0, 140.0)):
            value = distribution_probability(mean, variance, mean - .5)
            self.assertTrue(np.isfinite(value))
            self.assertGreaterEqual(value, 0)
            self.assertLessEqual(value, 1)

    def test_more_dispersion_retains_finite_sparse_event_probability(self):
        value = distribution_probability(.08, .2, .5)
        self.assertGreater(value, 0)
        self.assertLess(value, .5)


if __name__ == "__main__":
    unittest.main()
