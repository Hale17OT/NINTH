"""Serializable totals model shared by training and production inference."""
import numpy as np
from scipy.stats import nbinom, poisson


def _is_integer_line(line):
    return abs(float(line) - round(float(line))) < 1e-9


def _market_rows(lines, over, under, push):
    return {
        "lines": [float(value) for value in lines],
        "over": np.asarray(over, dtype=float),
        "under": np.asarray(under, dtype=float),
        "push": np.asarray(push, dtype=float),
    }


class TotalsProbabilityModel:
    def __init__(self, mean_model, line_models, lines):
        self.mean_model = mean_model
        self.line_models = line_models
        self.lines = [float(value) for value in lines]

    def predict_expected(self, rows):
        return np.clip(np.asarray(self.mean_model.predict(rows), dtype=float), 3.0, 18.0)

    def predict_over_probabilities(self, rows):
        raw = np.column_stack([
            self.line_models[str(line)].predict_proba(rows)[:, 1] for line in self.lines
        ])
        # P(total > x) must not increase as x increases. Independent binary
        # fits can cross slightly, so enforce the probability ordering.
        return np.minimum.accumulate(raw, axis=1)

    def predict_market_probabilities(self, rows, market_lines):
        """Price arbitrary full-game lines without treating an integer push as a loss."""
        trained = np.asarray(self.lines, dtype=float)
        survival = self.predict_over_probabilities(rows)
        over_rows, under_rows, push_rows = [], [], []
        for row in survival:
            over_values, under_values, push_values = [], [], []
            for value in market_lines:
                line = float(value)
                over_cutoff = np.floor(line) + .5
                over_probability = float(np.interp(over_cutoff, trained, row))
                if _is_integer_line(line):
                    lower_cutoff = line - .5
                    at_or_above = float(np.interp(lower_cutoff, trained, row))
                    under_probability = 1 - at_or_above
                    push_probability = max(0.0, at_or_above - over_probability)
                else:
                    under_probability = 1 - over_probability
                    push_probability = 0.0
                over_values.append(over_probability); under_values.append(under_probability); push_values.append(push_probability)
            over_rows.append(over_values); under_rows.append(under_values); push_rows.append(push_values)
        return _market_rows(market_lines, over_rows, under_rows, push_rows)


class CountDistributionTotalsModel:
    """Poisson-mean model with Poisson or negative-binomial run variance."""
    def __init__(self, mean_model, lines, distribution="negative_binomial", dispersion=.1):
        self.mean_model = mean_model
        self.lines = [float(value) for value in lines]
        self.distribution = distribution
        self.dispersion = float(dispersion)

    def predict_expected(self, rows):
        return np.clip(np.asarray(self.mean_model.predict(rows), dtype=float), 3.0, 18.0)

    def predict_over_probabilities(self, rows):
        mean = self.predict_expected(rows)
        if self.distribution == "poisson":
            return np.column_stack([poisson.sf(int(line), mean) for line in self.lines])
        size = 1 / max(.001, self.dispersion)
        probability = size / (size + mean)
        return np.column_stack([nbinom.sf(int(line), size, probability) for line in self.lines])

    def predict_market_probabilities(self, rows, market_lines):
        mean = self.predict_expected(rows)
        over, under, push = [], [], []
        for line in market_lines:
            value = float(line); cutoff = int(np.floor(value))
            if self.distribution == "poisson":
                over.append(poisson.sf(cutoff, mean))
                under.append(poisson.cdf(int(np.ceil(value)) - 1, mean) if not _is_integer_line(value) else poisson.cdf(cutoff - 1, mean))
                push.append(poisson.pmf(cutoff, mean) if _is_integer_line(value) else np.zeros_like(mean))
            else:
                size = 1 / max(.001, self.dispersion); probability = size / (size + mean)
                over.append(nbinom.sf(cutoff, size, probability))
                under.append(nbinom.cdf(int(np.ceil(value)) - 1, size, probability) if not _is_integer_line(value) else nbinom.cdf(cutoff - 1, size, probability))
                push.append(nbinom.pmf(cutoff, size, probability) if _is_integer_line(value) else np.zeros_like(mean))
        return _market_rows(market_lines, np.column_stack(over), np.column_stack(under), np.column_stack(push))


class MeanCalibratedTotalsModel:
    """Monotone threshold calibration driven by a count model's expected mean."""
    def __init__(self, mean_model, calibrators, lines):
        self.mean_model = mean_model
        self.calibrators = list(calibrators)
        self.lines = [float(value) for value in lines]

    def predict_expected(self, rows):
        return np.clip(np.asarray(self.mean_model.predict(rows), dtype=float), 3.0, 18.0)

    def predict_over_probabilities(self, rows):
        mean = self.predict_expected(rows)
        raw = np.column_stack([model.predict(mean) for model in self.calibrators])
        return np.minimum.accumulate(raw, axis=1)

    def predict_market_probabilities(self, rows, market_lines):
        trained = np.asarray(self.lines, dtype=float)
        survival = self.predict_over_probabilities(rows)
        over_rows, under_rows, push_rows = [], [], []
        for row in survival:
            over_values, under_values, push_values = [], [], []
            for value in market_lines:
                line = float(value); over_cutoff = np.floor(line) + .5
                over_probability = float(np.interp(over_cutoff, trained, row))
                if _is_integer_line(line):
                    at_or_above = float(np.interp(line - .5, trained, row))
                    under_probability = 1 - at_or_above
                    push_probability = max(0., at_or_above - over_probability)
                else:
                    under_probability, push_probability = 1-over_probability, 0.
                over_values.append(over_probability);under_values.append(under_probability);push_values.append(push_probability)
            over_rows.append(over_values);under_rows.append(under_values);push_rows.append(push_values)
        return _market_rows(market_lines, over_rows, under_rows, push_rows)


class TeamRunDistributionTotalsModel:
    """Separate home/away run means with covariance-aware total variance."""
    def __init__(self, home_model, away_model, lines, distribution="negative_binomial", dispersion=.1):
        self.home_model = home_model
        self.away_model = away_model
        self.lines = [float(value) for value in lines]
        self.distribution = distribution
        self.dispersion = float(dispersion)

    def predict_team_expected(self, rows):
        home = np.clip(np.asarray(self.home_model.predict(rows), dtype=float), .2, 15.0)
        away = np.clip(np.asarray(self.away_model.predict(rows), dtype=float), .2, 15.0)
        return home, away

    def predict_expected(self, rows):
        home, away = self.predict_team_expected(rows)
        return np.clip(home + away, 3.0, 18.0)

    def predict_over_probabilities(self, rows):
        mean = self.predict_expected(rows)
        if self.distribution == "poisson":
            return np.column_stack([poisson.sf(int(line), mean) for line in self.lines])
        size = 1 / max(.001, self.dispersion)
        probability = size / (size + mean)
        return np.column_stack([nbinom.sf(int(line), size, probability) for line in self.lines])

    def predict_market_probabilities(self, rows, market_lines):
        mean = self.predict_expected(rows)
        proxy = CountDistributionTotalsModel(self.home_model, market_lines, self.distribution, self.dispersion)
        proxy.predict_expected = lambda _rows: mean
        return proxy.predict_market_probabilities(rows, market_lines)


class TotalsModelBlend:
    """Convex probability blend with a stable expected-runs forecast."""
    def __init__(self, models, weights):
        self.models = list(models)
        self.weights = np.asarray(weights, dtype=float) / np.sum(weights)
        self.lines = self.models[0].lines

    def predict_expected(self, rows):
        values = [model.predict_expected(rows) for model in self.models]
        return sum(weight * value for weight, value in zip(self.weights, values))

    def predict_over_probabilities(self, rows):
        values = [model.predict_over_probabilities(rows) for model in self.models]
        probability = sum(weight * value for weight, value in zip(self.weights, values))
        return np.minimum.accumulate(probability, axis=1)

    def predict_team_expected(self, rows):
        for model in self.models:
            if hasattr(model, "predict_team_expected"):
                try:
                    return model.predict_team_expected(rows)
                except AttributeError:
                    continue
        raise AttributeError("No team-specific component is available")

    def predict_market_probabilities(self, rows, market_lines):
        values = [model.predict_market_probabilities(rows, market_lines) for model in self.models]
        return _market_rows(
            market_lines,
            sum(weight * value["over"] for weight, value in zip(self.weights, values)),
            sum(weight * value["under"] for weight, value in zip(self.weights, values)),
            sum(weight * value["push"] for weight, value in zip(self.weights, values)),
        )


class FeatureSubsetTotalsModel:
    """Allow legacy and richer totals models to share one production row."""
    def __init__(self, model, indices):
        self.model = model
        self.indices = list(indices)
        self.lines = model.lines

    def _rows(self, rows):
        return np.asarray(rows)[:, self.indices]

    def predict_expected(self, rows):
        return self.model.predict_expected(self._rows(rows))

    def predict_over_probabilities(self, rows):
        return self.model.predict_over_probabilities(self._rows(rows))

    def predict_team_expected(self, rows):
        return self.model.predict_team_expected(self._rows(rows))

    def predict_market_probabilities(self, rows, market_lines):
        return self.model.predict_market_probabilities(self._rows(rows), market_lines)
