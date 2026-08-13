from datetime import datetime, timezone

import joblib

from .predict_nfl_open import feature_row, forecast
from .collect_nfl_open import State


class ConstantModel:
    def __init__(self, probability): self.probability = probability
    def predict_proba(self, rows): return [[1 - self.probability, self.probability] for _ in rows]


class IdentityCalibrator:
    def predict(self, rows): return rows


class ConstantRegressor:
    def __init__(self, value): self.value = value
    def predict(self, rows): return [self.value for _ in rows]


def _bundle(probability):
    return {"features": ["home_elo", "away_elo", "elo_difference"], "model": ConstantModel(probability), "calibrator": IdentityCalibrator()}


def _score_bundle():
    return {
        "features": ["home_elo", "away_elo", "elo_difference"],
        "models": {"total_points": ConstantRegressor(45), "home_margin": ConstantRegressor(3)},
        "residuals": {"total_points": [0] * 80, "home_margin": [0] * 80},
    }


def test_feature_row_uses_only_pre_event_state():
    home, away = State(), State()
    home.scored.extend([20, 30]); away.allowed.extend([10, 14])
    row = feature_row({"total_line": "47.5"}, home, away)
    assert row["home_scored_5"] == 25
    assert row["away_allowed_5"] == 12
    assert "total_line" not in row


def test_forecast_updates_completed_state_and_emits_future_only(tmp_path):
    joblib.dump(_bundle(.70), tmp_path / "home_win.joblib")
    joblib.dump(_score_bundle(), tmp_path / "score.joblib")
    (tmp_path / "home_win.json").write_text('{"historical_readiness":{"passed":true}}')
    (tmp_path / "score.json").write_text('{"historical_readiness":{"moneyline":true,"spread":false,"total":false}}')
    rows = [
        {"game_id": "old", "gameday": "2026-01-01", "gametime": "12:00", "home_team": "A", "away_team": "B", "home_score": "28", "away_score": "14"},
        {"game_id": "future", "gameday": "2026-09-01", "gametime": "12:00", "home_team": "A", "away_team": "B", "home_score": "", "away_score": "", "total_line": "45.5"},
    ]
    result = forecast(rows, tmp_path, datetime(2026, 8, 12, tzinfo=timezone.utc))
    assert result["count"] == 1
    assert result["predictions"][0]["event_id"] == "future"
    assert result["predictions"][0]["markets"]["home_win"] == .63
    assert result["predictions"][0]["total_line"] == 45.5
    assert result["predictions"][0]["expected_score"]["total"] == 45
    assert result["predictions"][0]["builder_eligible"] is False
