from ml.multisport.collect_nba_open import build as build_nba
from ml.multisport.collect_nfl_open import build as build_nfl


def test_nba_pairs_home_and_away_without_result_leakage():
    rows = [
        {"game_id": "1", "game_date": "2025-10-01T00:00:00", "team_abbreviation": "AAA", "matchup": "AAA vs. BBB", "pts": 120, "poss": 100, "opp_poss": 100, "off_rating": 120, "def_rating": 110},
        {"game_id": "1", "game_date": "2025-10-01T00:00:00", "team_abbreviation": "BBB", "matchup": "BBB @ AAA", "pts": 110, "poss": 100, "opp_poss": 100, "off_rating": 110, "def_rating": 120},
    ]
    ledgers = build_nba(rows)
    assert ledgers["home_win"][0]["label"] == 1
    assert ledgers["home_win"][0]["features"]["elo_difference"] == 0
    assert ledgers["home_win"][0]["knowledge_time"] < ledgers["home_win"][0]["event_time"]


def test_nba_advanced_features_only_update_future_games():
    rows = [
        {"game_id": "1", "game_date": "2025-10-01T00:00:00", "team_abbreviation": "AAA", "matchup": "AAA vs. BBB", "pts": 120, "poss": 100, "opp_poss": 100, "off_rating": 120, "def_rating": 110},
        {"game_id": "1", "game_date": "2025-10-01T00:00:00", "team_abbreviation": "BBB", "matchup": "BBB @ AAA", "pts": 110, "poss": 100, "opp_poss": 100, "off_rating": 110, "def_rating": 120},
        {"game_id": "2", "game_date": "2025-10-03T00:00:00", "team_abbreviation": "AAA", "matchup": "AAA vs. BBB", "pts": 115, "poss": 99, "opp_poss": 99, "off_rating": 116, "def_rating": 112},
        {"game_id": "2", "game_date": "2025-10-03T00:00:00", "team_abbreviation": "BBB", "matchup": "BBB @ AAA", "pts": 111, "poss": 99, "opp_poss": 99, "off_rating": 112, "def_rating": 116},
    ]
    advanced = {
        ("1", "AAA"): {"eFG": .62, "totPoss": 100, "fgaplyr": 90, "fg3aplyr": 40, "ftaplyr": 20, "orebounder": 12, "drebounder": 32, "tov1": 10, "assister": 30, "fgmplyr": 45, "luaplyr": 28},
        ("1", "BBB"): {"eFG": .48, "totPoss": 100, "fgaplyr": 90, "fg3aplyr": 36, "ftaplyr": 18, "orebounder": 8, "drebounder": 30, "tov1": 15, "assister": 20, "fgmplyr": 38, "luaplyr": 22},
    }
    ledger = build_nba(rows, advanced)["home_win"]
    assert ledger[0]["features"]["home_efg_10"] == .54
    assert ledger[1]["features"]["home_efg_10"] == .62


def test_nfl_score_ledger_keeps_market_lines_outside_features():
    row = {"season": "2025", "game_id": "g1", "gameday": "2025-09-01", "gametime": "20:00", "home_team": "AAA", "away_team": "BBB", "home_score": "24", "away_score": "21", "total_line": "44.5", "home_rest": "7", "away_rest": "7", "div_game": "0"}
    ledgers = build_nfl([row], 2020)
    assert ledgers["score"][0]["total_points"] == 45
    assert ledgers["score"][0]["market_total_line"] == 44.5
    assert "total_line" not in ledgers["score"][0]["features"]
    assert "spread_line" not in ledgers["home_win"][0]["features"]
