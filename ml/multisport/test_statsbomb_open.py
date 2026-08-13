from ml.multisport.collect_football_statsbomb import event_summary


def test_statsbomb_events_become_team_game_features():
    match = {"match_id": 1, "match_date": "2025-01-01", "home_team": {"home_team_name": "A"}, "away_team": {"away_team_name": "B"}}
    competition = {"competition_name": "Ligue 1", "season_name": "2024/2025"}
    events = [
        {"team": {"name": "A"}, "type": {"name": "Shot"}, "shot": {"statsbomb_xg": .4, "type": {"name": "Open Play"}}, "play_pattern": {"name": "Regular Play"}},
        {"team": {"name": "A"}, "type": {"name": "Pass"}, "location": [55, 40], "pass": {"end_location": [85, 42]}},
        {"team": {"name": "B"}, "type": {"name": "Pressure"}, "counterpress": True},
    ]
    rows = event_summary(events, match, competition)
    home = next(row for row in rows if row["team"] == "A")
    away = next(row for row in rows if row["team"] == "B")
    assert home["xg"] == .4 and home["progressive_passes"] == 1 and home["final_third_entries"] == 1
    assert away["pressures"] == 1 and away["counterpressures"] == 1
