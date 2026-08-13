"""Auditable score and best-of-series distribution helpers."""
from __future__ import annotations

import math


def poisson_probability(goals: int, expectation: float) -> float:
    return math.exp(-expectation) * expectation ** goals / math.factorial(goals)


def _dixon_coles_tau(home_goals: int, away_goals: int, home_xg: float, away_xg: float, rho: float) -> float:
    if home_goals == 0 and away_goals == 0:
        return 1 - home_xg * away_xg * rho
    if home_goals == 0 and away_goals == 1:
        return 1 + home_xg * rho
    if home_goals == 1 and away_goals == 0:
        return 1 + away_xg * rho
    if home_goals == 1 and away_goals == 1:
        return 1 - rho
    return 1.0


def dixon_coles_matrix(home_xg: float, away_xg: float, rho: float = -.08, max_goals: int = 10) -> dict:
    """Return a normalized exact-score matrix and derived football markets."""
    if home_xg <= 0 or away_xg <= 0:
        raise ValueError("Expected goals must be positive")
    cells = {}
    total = 0.0
    for home in range(max_goals + 1):
        for away in range(max_goals + 1):
            value = poisson_probability(home, home_xg) * poisson_probability(away, away_xg)
            value *= _dixon_coles_tau(home, away, home_xg, away_xg, rho)
            value = max(0.0, value)
            cells[(home, away)] = value
            total += value
    cells = {key: value / total for key, value in cells.items()}
    home = sum(value for (h, a), value in cells.items() if h > a)
    draw = sum(value for (h, a), value in cells.items() if h == a)
    away = 1 - home - draw
    over_25 = sum(value for (h, a), value in cells.items() if h + a > 2.5)
    btts = sum(value for (h, a), value in cells.items() if h > 0 and a > 0)
    return {
        "matrix": {f"{h}-{a}": value for (h, a), value in cells.items()},
        "home_win": home, "draw": draw, "away_win": away,
        "over_2_5": over_25, "under_2_5": 1 - over_25,
        "both_teams_score": btts, "expected_total": home_xg + away_xg,
    }


def series_win_probability(map_probabilities: list[float], maps_to_win: int | None = None) -> float:
    """Calculate a series win chance for an ordered set of independent map forecasts."""
    if not map_probabilities:
        raise ValueError("At least one map probability is required")
    maps_to_win = maps_to_win or len(map_probabilities) // 2 + 1
    states = {(0, 0): 1.0}
    for probability in map_probabilities:
        probability = min(.999999, max(.000001, float(probability)))
        next_states = {}
        for (wins, losses), mass in states.items():
            if wins >= maps_to_win or losses >= maps_to_win:
                next_states[(wins, losses)] = next_states.get((wins, losses), 0) + mass
                continue
            next_states[(wins + 1, losses)] = next_states.get((wins + 1, losses), 0) + mass * probability
            next_states[(wins, losses + 1)] = next_states.get((wins, losses + 1), 0) + mass * (1 - probability)
        states = next_states
    return sum(mass for (wins, _), mass in states.items() if wins >= maps_to_win)

