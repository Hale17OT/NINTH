"""Collect StatsBomb Open Data team-game features for covered competitions.

StatsBomb Open Data is deliberately incomplete. This collector preserves that
fact in its report and only enriches matching team-games; missing matches fall
back to the transparent Football-Data shot-quality features.
"""
from __future__ import annotations

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

BASE = "https://raw.githubusercontent.com/statsbomb/open-data/master/data"
TOP_FIVE = {"Premier League", "La Liga", "1. Bundesliga", "Serie A", "Ligue 1"}


def get_json(url: str, cache: Path | None = None):
    if cache and cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    request = Request(url, headers={"User-Agent": "NINTH-Research/2.0", "Accept": "application/json"})
    with urlopen(request, timeout=60) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if cache:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(payload), encoding="utf-8")
    return payload


def season_year(value: str) -> int:
    return int(str(value).split("/")[0])


def event_summary(events: list[dict], match: dict, competition: dict) -> list[dict]:
    teams = [match["home_team"]["home_team_name"], match["away_team"]["away_team_name"]]
    stats = {team: {"xg": 0.0, "non_penalty_xg": 0.0, "shots": 0, "pressures": 0, "counterpressures": 0, "progressive_passes": 0, "final_third_entries": 0, "set_piece_xg": 0.0} for team in teams}
    for event in events:
        team = (event.get("team") or {}).get("name")
        if team not in stats:
            continue
        kind = (event.get("type") or {}).get("name")
        if kind == "Shot":
            shot = event.get("shot") or {}
            xg = float(shot.get("statsbomb_xg") or 0)
            stats[team]["shots"] += 1; stats[team]["xg"] += xg
            if (shot.get("type") or {}).get("name") != "Penalty":
                stats[team]["non_penalty_xg"] += xg
            if (event.get("play_pattern") or {}).get("name") not in {"Regular Play", "From Counter"}:
                stats[team]["set_piece_xg"] += xg
        elif kind == "Pressure":
            stats[team]["pressures"] += 1
            stats[team]["counterpressures"] += int(bool(event.get("counterpress")))
        elif kind == "Pass":
            start, end = event.get("location") or [], (event.get("pass") or {}).get("end_location") or []
            complete = not (event.get("pass") or {}).get("outcome")
            if complete and len(start) >= 2 and len(end) >= 2:
                if end[0] >= 80 and start[0] < 80:
                    stats[team]["final_third_entries"] += 1
                if end[0] - start[0] >= 20 and end[0] >= 60:
                    stats[team]["progressive_passes"] += 1
    date = match.get("match_date")
    return [{
        "match_id": match["match_id"], "date": date, "team": team,
        "opponent": teams[1] if team == teams[0] else teams[0],
        "competition": competition["competition_name"], "season": competition["season_name"],
        **values,
    } for team, values in stats.items()]


def collect(start_year: int, end_year: int, output: Path, limit: int | None = None) -> dict:
    competitions = get_json(f"{BASE}/competitions.json")
    selected = [row for row in competitions if row.get("competition_name") in TOP_FIVE and start_year <= season_year(row.get("season_name")) <= end_year]
    rows, errors, matches_seen, work = [], [], 0, []
    cache_dir = output.parent / "source-cache" / "statsbomb"
    for competition in selected:
        matches = get_json(f"{BASE}/matches/{competition['competition_id']}/{competition['season_id']}.json")
        for match in matches:
            if limit is not None and matches_seen >= limit:
                break
            matches_seen += 1
            work.append((match, competition))
        if limit is not None and matches_seen >= limit:
            break
    def fetch_one(item):
        match, competition = item
        events = get_json(f"{BASE}/events/{match['match_id']}.json", cache_dir / f"{match['match_id']}.json")
        return event_summary(events, match, competition)
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(fetch_one, item): item[0].get("match_id") for item in work}
        for future in as_completed(futures):
            try:
                rows.extend(future.result())
            except Exception as error:
                errors.append({"match_id": futures[future], "error": str(error)})
    rows.sort(key=lambda row: (row["date"], row["match_id"], row["team"]))
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(), "source": "StatsBomb Open Data",
        "coverage_is_partial": True, "competitions": [{key: row.get(key) for key in ("competition_id", "competition_name", "season_id", "season_name")} for row in selected],
        "matches": matches_seen, "team_games": len(rows), "errors": errors, "rows": rows,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload), encoding="utf-8")
    return {key: payload[key] for key in ("source", "coverage_is_partial", "matches", "team_games", "errors")}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-year", type=int, default=datetime.now().year - 3)
    parser.add_argument("--end-year", type=int, default=datetime.now().year)
    parser.add_argument("--output", type=Path, default=Path("ml/data/multisport/football/statsbomb_team_games.json"))
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    print(json.dumps(collect(args.start_year, args.end_year, args.output, args.limit), indent=2))


if __name__ == "__main__":
    main()
