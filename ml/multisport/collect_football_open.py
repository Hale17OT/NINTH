"""Build leak-safe Football ledgers from no-cost, keyless CSV releases.

Football-Data.co.uk publishes results, match statistics and archived prices for
the top five domestic leagues. Features are locked before each match updates
the rolling team state. The output feeds ``ml.multisport.train`` and is never
treated as a live-forward audit.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.request import Request, urlopen


BASE_URL = "https://www.football-data.co.uk/mmz4281"
LEAGUES = {
    "E0": "Premier League",
    "SP1": "La Liga",
    "D1": "Bundesliga",
    "I1": "Serie A",
    "F1": "Ligue 1",
}
MARKETS = ("home_win", "over_2_5", "both_teams_score")


def season_slug(start_year: int) -> str:
    return f"{str(start_year)[-2:]}{str(start_year + 1)[-2:]}"


def fetch_csv(league: str, start_year: int) -> list[dict[str, str]]:
    url = f"{BASE_URL}/{season_slug(start_year)}/{league}.csv"
    request = Request(url, headers={"User-Agent": "NINTH-Research/2.0", "Accept": "text/csv,*/*"})
    with urlopen(request, timeout=45) as response:
        body = response.read().decode("utf-8-sig", errors="replace")
    rows = list(csv.DictReader(io.StringIO(body)))
    return [row for row in rows if row.get("Div") == league and row.get("HomeTeam") and row.get("AwayTeam")]


def parse_date(value: str, kickoff: str = "") -> datetime:
    parsed = None
    for pattern in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            parsed = datetime.strptime(value.strip(), pattern)
            break
        except ValueError:
            continue
    if parsed is None:
        raise ValueError(f"Unsupported Football date: {value}")
    try:
        hour, minute = (int(part) for part in kickoff.split(":", 1))
        parsed = parsed.replace(hour=hour, minute=minute)
    except (TypeError, ValueError):
        parsed = parsed.replace(hour=12)
    return parsed.replace(tzinfo=timezone.utc)


def number(row: dict, *names: str) -> float | None:
    for name in names:
        try:
            value = row.get(name)
            if value not in (None, ""):
                return float(value)
        except (TypeError, ValueError):
            continue
    return None


def devig(*odds: float | None) -> list[float | None]:
    if any(value is None or value <= 1 for value in odds):
        return [None for _ in odds]
    inverses = [1 / float(value) for value in odds]
    total = sum(inverses)
    return [value / total for value in inverses]


def average(values: deque[float], default: float) -> float:
    return sum(values) / len(values) if values else default


@dataclass
class TeamState:
    elo: float = 1500.0
    goals_for: deque[float] = field(default_factory=lambda: deque(maxlen=10))
    goals_against: deque[float] = field(default_factory=lambda: deque(maxlen=10))
    points: deque[float] = field(default_factory=lambda: deque(maxlen=10))
    shots: deque[float] = field(default_factory=lambda: deque(maxlen=10))
    shots_on_target: deque[float] = field(default_factory=lambda: deque(maxlen=10))
    shots_against: deque[float] = field(default_factory=lambda: deque(maxlen=10))
    shots_on_target_against: deque[float] = field(default_factory=lambda: deque(maxlen=10))
    corners: deque[float] = field(default_factory=lambda: deque(maxlen=10))
    corners_against: deque[float] = field(default_factory=lambda: deque(maxlen=10))
    fouls: deque[float] = field(default_factory=lambda: deque(maxlen=10))
    yellow_cards: deque[float] = field(default_factory=lambda: deque(maxlen=10))
    red_cards: deque[float] = field(default_factory=lambda: deque(maxlen=10))
    shot_quality_proxy: deque[float] = field(default_factory=lambda: deque(maxlen=10))
    shot_quality_against: deque[float] = field(default_factory=lambda: deque(maxlen=10))
    statsbomb_xg: deque[float] = field(default_factory=lambda: deque(maxlen=10))
    statsbomb_xga: deque[float] = field(default_factory=lambda: deque(maxlen=10))
    progressive_passes: deque[float] = field(default_factory=lambda: deque(maxlen=10))
    final_third_entries: deque[float] = field(default_factory=lambda: deque(maxlen=10))
    pressure_rate: deque[float] = field(default_factory=lambda: deque(maxlen=10))
    last_played: datetime | None = None


def state_features(state: TeamState, prefix: str, at: datetime) -> dict[str, float]:
    rest = 14.0 if state.last_played is None else min(30.0, max(0.0, (at - state.last_played).total_seconds() / 86400))
    shots = average(state.shots, 11.5)
    shots_against = average(state.shots_against, 11.5)
    on_target = average(state.shots_on_target, 4.1)
    on_target_against = average(state.shots_on_target_against, 4.1)
    return {
        f"{prefix}_elo": state.elo,
        f"{prefix}_goals_for_5": average(deque(list(state.goals_for)[-5:]), 1.3),
        f"{prefix}_goals_against_5": average(deque(list(state.goals_against)[-5:]), 1.3),
        f"{prefix}_goals_for_10": average(state.goals_for, 1.3),
        f"{prefix}_goals_against_10": average(state.goals_against, 1.3),
        f"{prefix}_points_5": average(deque(list(state.points)[-5:]), 1.35),
        f"{prefix}_shots_5": average(deque(list(state.shots)[-5:]), 11.5),
        f"{prefix}_shots_on_target_5": average(deque(list(state.shots_on_target)[-5:]), 4.1),
        f"{prefix}_shots_against_10": shots_against,
        f"{prefix}_shots_on_target_against_10": on_target_against,
        f"{prefix}_shot_share_10": shots / max(1.0, shots + shots_against),
        f"{prefix}_sot_share_10": on_target / max(1.0, on_target + on_target_against),
        f"{prefix}_shot_accuracy_10": on_target / max(1.0, shots),
        f"{prefix}_shot_quality_proxy_10": average(state.shot_quality_proxy, 1.3),
        f"{prefix}_shot_quality_against_10": average(state.shot_quality_against, 1.3),
        f"{prefix}_statsbomb_xg_10": average(state.statsbomb_xg, 1.3),
        f"{prefix}_statsbomb_xga_10": average(state.statsbomb_xga, 1.3),
        f"{prefix}_progressive_passes_10": average(state.progressive_passes, 28.0),
        f"{prefix}_final_third_entries_10": average(state.final_third_entries, 32.0),
        f"{prefix}_pressure_rate_10": average(state.pressure_rate, .18),
        f"{prefix}_corners_for_10": average(state.corners, 5.0),
        f"{prefix}_corners_against_10": average(state.corners_against, 5.0),
        f"{prefix}_fouls_10": average(state.fouls, 11.0),
        f"{prefix}_yellow_cards_10": average(state.yellow_cards, 1.8),
        f"{prefix}_red_cards_10": average(state.red_cards, .08),
        f"{prefix}_goal_difference_10": average(state.goals_for, 1.3) - average(state.goals_against, 1.3),
        f"{prefix}_clean_sheet_rate_10": sum(value == 0 for value in state.goals_against) / len(state.goals_against) if state.goals_against else .28,
        f"{prefix}_rest_days": rest,
        f"{prefix}_matches_seen": float(len(state.goals_for)),
    }


def team_key(value: str) -> str:
    return "".join(character for character in str(value or "").lower() if character.isalnum())


def load_statsbomb(path: Path) -> dict[tuple[str, str], dict]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {(row["date"], team_key(row["team"])): row for row in payload.get("rows", [])}


def build_ledgers_and_states(raw_rows: list[dict], statsbomb: dict[tuple[str, str], dict] | None = None) -> tuple[dict[str, list[dict]], dict[tuple[str, str], TeamState]]:
    statsbomb = statsbomb or {}
    matches = []
    for row in raw_rows:
        if row.get("FTHG") in (None, "") or row.get("FTAG") in (None, ""):
            continue
        try:
            at = parse_date(row["Date"], row.get("Time", ""))
        except ValueError:
            continue
        matches.append((at, row))
    matches.sort(key=lambda item: (item[0], item[1].get("Div", ""), item[1].get("HomeTeam", "")))

    states: dict[tuple[str, str], TeamState] = defaultdict(TeamState)
    ledgers = {market: [] for market in MARKETS}
    for at, row in matches:
        league = row["Div"]
        home_name, away_name = row["HomeTeam"], row["AwayTeam"]
        home, away = states[(league, home_name)], states[(league, away_name)]
        features = {
            **state_features(home, "home", at),
            **state_features(away, "away", at),
            "elo_difference": home.elo - away.elo,
            "league_home_goal_prior": 1.45,
            "league_away_goal_prior": 1.15,
        }
        home_goals, away_goals = int(float(row["FTHG"])), int(float(row["FTAG"]))
        event_id = f"{league}:{at.date().isoformat()}:{home_name}:{away_name}"
        common = {
            "event_id": event_id,
            "event_time": at.isoformat(),
            "knowledge_time": (at - timedelta(minutes=1)).isoformat(),
            "competition": LEAGUES.get(league, league),
            "home_team": home_name,
            "away_team": away_name,
            "features": features,
        }
        labels = {
            "home_win": int(home_goals > away_goals),
            "over_2_5": int(home_goals + away_goals >= 3),
            "both_teams_score": int(home_goals > 0 and away_goals > 0),
        }
        for market, label in labels.items():
            ledgers[market].append({**common, "label": label})

        expected = 1 / (1 + 10 ** (-(home.elo + 65 - away.elo) / 400))
        result = 1.0 if home_goals > away_goals else .5 if home_goals == away_goals else 0.0
        change = 24 * (result - expected)
        home.elo += change
        away.elo -= change
        for state, goals_for, goals_against, shots, shots_on_target, shots_against, shots_on_target_against, corners, corners_against, fouls, yellow, red in (
            (home, home_goals, away_goals, number(row, "HS"), number(row, "HST"), number(row, "AS"), number(row, "AST"), number(row, "HC"), number(row, "AC"), number(row, "HF"), number(row, "HY"), number(row, "HR")),
            (away, away_goals, home_goals, number(row, "AS"), number(row, "AST"), number(row, "HS"), number(row, "HST"), number(row, "AC"), number(row, "HC"), number(row, "AF"), number(row, "AY"), number(row, "AR")),
        ):
            state.goals_for.append(goals_for)
            state.goals_against.append(goals_against)
            state.points.append(3 if goals_for > goals_against else 1 if goals_for == goals_against else 0)
            if shots is not None:
                state.shots.append(shots)
            if shots_on_target is not None:
                state.shots_on_target.append(shots_on_target)
            if shots_against is not None:
                state.shots_against.append(shots_against)
            if shots_on_target_against is not None:
                state.shots_on_target_against.append(shots_on_target_against)
            if corners is not None:
                state.corners.append(corners)
            if corners_against is not None:
                state.corners_against.append(corners_against)
            if fouls is not None:
                state.fouls.append(fouls)
            if yellow is not None:
                state.yellow_cards.append(yellow)
            if red is not None:
                state.red_cards.append(red)
            # Transparent non-Opta proxy: on-target attempts carry more scoring
            # information than other shots. It is never presented as true xG.
            if shots is not None and shots_on_target is not None:
                state.shot_quality_proxy.append(.06 * max(0.0, shots - shots_on_target) + .28 * shots_on_target)
            if shots_against is not None and shots_on_target_against is not None:
                state.shot_quality_against.append(.06 * max(0.0, shots_against - shots_on_target_against) + .28 * shots_on_target_against)
            state.last_played = at
        home_sb = statsbomb.get((at.date().isoformat(), team_key(home_name)))
        away_sb = statsbomb.get((at.date().isoformat(), team_key(away_name)))
        for state, own, opponent in ((home, home_sb, away_sb), (away, away_sb, home_sb)):
            if own:
                state.statsbomb_xg.append(float(own.get("non_penalty_xg") or own.get("xg") or 0))
                state.progressive_passes.append(float(own.get("progressive_passes") or 0))
                state.final_third_entries.append(float(own.get("final_third_entries") or 0))
                state.pressure_rate.append(float(own.get("counterpressures") or 0) / max(1.0, float(own.get("pressures") or 0)))
            if opponent:
                state.statsbomb_xga.append(float(opponent.get("non_penalty_xg") or opponent.get("xg") or 0))
    return ledgers, states


def build_ledgers(raw_rows: list[dict], statsbomb: dict[tuple[str, str], dict] | None = None) -> dict[str, list[dict]]:
    return build_ledgers_and_states(raw_rows, statsbomb)[0]


def collect(start_season: int, end_season: int, output_dir: Path) -> dict:
    rows = []
    downloads = []
    for season in range(start_season, end_season + 1):
        for league in LEAGUES:
            try:
                batch = fetch_csv(league, season)
            except Exception as error:  # individual releases can appear at different times
                downloads.append({"league": league, "season": season, "rows": 0, "error": str(error)})
                continue
            rows.extend(batch)
            downloads.append({"league": league, "season": season, "rows": len(batch)})
    statsbomb = load_statsbomb(output_dir / "statsbomb_team_games.json")
    ledgers = build_ledgers(rows, statsbomb)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "raw_matches.jsonl").write_text(
        "\n".join(json.dumps(row, separators=(",", ":")) for row in rows) + "\n",
        encoding="utf-8",
    )
    for market, records in ledgers.items():
        path = output_dir / f"{market}.jsonl"
        path.write_text("\n".join(json.dumps(record, separators=(",", ":")) for record in records) + "\n", encoding="utf-8")
    report = {
        "source": "Football-Data.co.uk", "access": "keyless/no-cost", "odds_used": False,
        "statsbomb_team_games": len(statsbomb),
        "advanced_metrics": ["shot and SOT shares", "shot-quality proxy", "StatsBomb xG where covered", "progressive passes", "final-third entries", "counterpressure share", "corners", "discipline", "rest", "time-decayed Elo"],
        "seasons": [start_season, end_season], "downloads": downloads,
        "ledgers": {market: len(records) for market, records in ledgers.items()},
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    (output_dir / "collection.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-season", type=int, default=2020)
    parser.add_argument("--end-season", type=int, default=datetime.now().year - 1)
    parser.add_argument("--output-dir", type=Path, default=Path("ml/data/multisport/football"))
    args = parser.parse_args()
    print(json.dumps(collect(args.start_season, args.end_season, args.output_dir), indent=2))


if __name__ == "__main__":
    main()
