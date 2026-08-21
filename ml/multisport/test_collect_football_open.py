from ml.multisport.collect_football_open import LEAGUES, build_ledgers, devig, parse_date, season_slug
from ml.multisport.predict_football_open import consistency_blend


def test_season_slug_and_dates():
    assert season_slug(2025) == "2526"
    assert parse_date("15/08/25", "20:00").isoformat() == "2025-08-15T20:00:00+00:00"


def test_devig_probabilities_are_normalized():
    values = devig(2.0, 3.5, 4.0)
    assert abs(sum(values) - 1) < 1e-12


def test_features_are_locked_before_result_update():
    base = {"Div": "E0", "Time": "15:00", "HS": "12", "AS": "8", "HST": "5", "AST": "3", "HC": "7", "AC": "3", "HF": "11", "AF": "9", "HY": "2", "AY": "1", "HR": "0", "AR": "0"}
    rows = [
        {**base, "Date": "01/08/2025", "HomeTeam": "Alpha", "AwayTeam": "Beta", "FTHG": "3", "FTAG": "0"},
        {**base, "Date": "08/08/2025", "HomeTeam": "Alpha", "AwayTeam": "Beta", "FTHG": "1", "FTAG": "1"},
    ]
    ledger = build_ledgers(rows)["home_win"]
    assert ledger[0]["features"]["elo_difference"] == 0
    assert ledger[1]["features"]["elo_difference"] > 0
    assert ledger[0]["knowledge_time"] < ledger[0]["event_time"]
    assert not any("market" in name or "odds" in name for name in ledger[0]["features"])
    assert ledger[1]["features"]["home_shot_share_10"] > .5


def test_championship_score_and_archived_prices_are_preserved_outside_features():
    row = {
        "Div": "E1", "Date": "01/08/2025", "Time": "15:00",
        "HomeTeam": "Alpha", "AwayTeam": "Beta", "FTHG": "2", "FTAG": "1",
        "AvgH": "2.10", "AvgD": "3.20", "AvgA": "3.70",
        "AvgCH": "2.00", "AvgCD": "3.30", "AvgCA": "3.90",
        "Avg>2.5": "1.90", "Avg<2.5": "1.95",
        "AvgC>2.5": "1.85", "AvgC<2.5": "2.00", "NINTHSeason": 2025,
    }
    ledgers = build_ledgers([row])
    assert LEAGUES["E1"] == "Championship"
    assert ledgers["score"][0]["home_goals"] == 2
    assert ledgers["score"][0]["season"] == 2025
    assert ledgers["home_win"][0]["archived_prices"]["closing"]["home"] == 2.0
    assert "archived_prices" not in ledgers["home_win"][0]["features"]


def test_discriminative_extremes_cannot_override_score_distribution():
    assert .70 < consistency_blend(1.0, .70) < .80
    assert .20 < consistency_blend(0.0, .30) < .30
