"""Leakage-safe dynamic ratings for teams, players, maps and lineups."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import math


@dataclass
class TimeDecayElo:
    initial: float = 1500.0
    k: float = 24.0
    home_advantage: float = 45.0
    half_life_days: float = 180.0
    ratings: dict[str, float] = field(default_factory=dict)
    last_seen: dict[str, datetime] = field(default_factory=dict)

    def _rating(self, entity: str, at: datetime) -> float:
        rating = self.ratings.get(entity, self.initial)
        previous = self.last_seen.get(entity)
        if previous and at > previous:
            elapsed = (at - previous).total_seconds() / 86400
            retain = .5 ** (elapsed / self.half_life_days)
            rating = self.initial + (rating - self.initial) * retain
        return rating

    def probability(self, home: str, away: str, at: datetime, neutral: bool = False) -> float:
        at = at.astimezone(timezone.utc)
        difference = self._rating(home, at) - self._rating(away, at) + (0 if neutral else self.home_advantage)
        return 1 / (1 + 10 ** (-difference / 400))

    def update(self, home: str, away: str, home_score: float, away_score: float, at: datetime, neutral: bool = False, weight: float = 1.0) -> float:
        """Return the pre-event probability, then update; never update first."""
        at = at.astimezone(timezone.utc)
        home_rating, away_rating = self._rating(home, at), self._rating(away, at)
        probability = self.probability(home, away, at, neutral)
        outcome = 1.0 if home_score > away_score else .5 if home_score == away_score else 0.0
        margin = abs(home_score - away_score)
        multiplier = math.log1p(margin) if margin else 1.0
        change = self.k * weight * multiplier * (outcome - probability)
        self.ratings[home], self.ratings[away] = home_rating + change, away_rating - change
        self.last_seen[home] = self.last_seen[away] = at
        return probability

