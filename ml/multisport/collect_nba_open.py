"""Build NBA team-market ledgers from an open, keyless NBA Stats mirror."""
from __future__ import annotations

import argparse
import json
import subprocess
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.request import Request, urlopen


BASE = "https://raw.githubusercontent.com/llimllib/nba_data/main/data"


def fetch_season(season: int) -> list[dict]:
    request = Request(f"{BASE}/team_efficiency_{season}.json", headers={"User-Agent": "NINTH-Research/2.0"})
    with urlopen(request, timeout=45) as response:
        return json.loads(response.read().decode("utf-8"))["games"]


def avg(values: deque, default: float) -> float:
    return sum(values) / len(values) if values else default


@dataclass
class State:
    elo: float = 1500.0
    points: deque = field(default_factory=lambda: deque(maxlen=10))
    allowed: deque = field(default_factory=lambda: deque(maxlen=10))
    offensive: deque = field(default_factory=lambda: deque(maxlen=10))
    defensive: deque = field(default_factory=lambda: deque(maxlen=10))
    pace: deque = field(default_factory=lambda: deque(maxlen=10))
    wins: deque = field(default_factory=lambda: deque(maxlen=10))
    efg: deque = field(default_factory=lambda: deque(maxlen=10))
    efg_allowed: deque = field(default_factory=lambda: deque(maxlen=10))
    turnover_rate: deque = field(default_factory=lambda: deque(maxlen=10))
    turnover_forced: deque = field(default_factory=lambda: deque(maxlen=10))
    offensive_rebound_rate: deque = field(default_factory=lambda: deque(maxlen=10))
    free_throw_rate: deque = field(default_factory=lambda: deque(maxlen=10))
    three_point_rate: deque = field(default_factory=lambda: deque(maxlen=10))
    assist_rate: deque = field(default_factory=lambda: deque(maxlen=10))
    rim_rate: deque = field(default_factory=lambda: deque(maxlen=10))
    net_shooting: deque = field(default_factory=lambda: deque(maxlen=10))
    net_turnover: deque = field(default_factory=lambda: deque(maxlen=10))
    net_rebound: deque = field(default_factory=lambda: deque(maxlen=10))
    last: datetime | None = None


def features(state: State, prefix: str, at: datetime) -> dict:
    rest = 7 if state.last is None else min(14, max(0, (at - state.last).days))
    return {
        f"{prefix}_elo": state.elo, f"{prefix}_points_5": avg(deque(list(state.points)[-5:]), 113),
        f"{prefix}_points_10": avg(state.points, 113), f"{prefix}_allowed_5": avg(deque(list(state.allowed)[-5:]), 113),
        f"{prefix}_allowed_10": avg(state.allowed, 113), f"{prefix}_off_rating_10": avg(state.offensive, 113),
        f"{prefix}_def_rating_10": avg(state.defensive, 113), f"{prefix}_pace_10": avg(state.pace, 100),
        f"{prefix}_win_rate_10": avg(state.wins, .5), f"{prefix}_rest_days": float(rest),
        f"{prefix}_efg_10": avg(state.efg, .54), f"{prefix}_efg_allowed_10": avg(state.efg_allowed, .54),
        f"{prefix}_turnover_rate_10": avg(state.turnover_rate, .13), f"{prefix}_turnover_forced_10": avg(state.turnover_forced, .13),
        f"{prefix}_offensive_rebound_rate_10": avg(state.offensive_rebound_rate, .25),
        f"{prefix}_free_throw_rate_10": avg(state.free_throw_rate, .22), f"{prefix}_three_point_rate_10": avg(state.three_point_rate, .40),
        f"{prefix}_assist_rate_10": avg(state.assist_rate, .62), f"{prefix}_rim_rate_10": avg(state.rim_rate, .28),
        f"{prefix}_net_shooting_10": avg(state.net_shooting, 0.0), f"{prefix}_net_turnover_10": avg(state.net_turnover, 0.0),
        f"{prefix}_net_rebound_10": avg(state.net_rebound, 0.0),
        f"{prefix}_games_seen": float(len(state.points)),
    }


def advanced_lookup(path: Path) -> dict[tuple[str, str], dict]:
    if not path.exists():
        subprocess.run(["node", "ml/multisport/export_nba_advanced.mjs", str(path)], check=True)
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {(str(row["game_id"]), row["tmName"]): row for row in payload.get("rows", [])}


def build(rows: list[dict], advanced: dict[tuple[str, str], dict] | None = None) -> dict[str, list[dict]]:
    advanced = advanced or {}
    by_game = defaultdict(list)
    for row in rows:
        if row.get("pts") is not None and row.get("game_id"):
            by_game[str(row["game_id"])].append(row)
    games = []
    for game_id, sides in by_game.items():
        if len(sides) != 2:
            continue
        home = next((row for row in sides if "vs." in (row.get("matchup") or "")), None)
        away = next((row for row in sides if "@" in (row.get("matchup") or "")), None)
        if not home or not away:
            continue
        at = datetime.fromisoformat(home["game_date"]).replace(tzinfo=timezone.utc)
        games.append((at, game_id, home, away))
    games.sort(key=lambda row: (row[0], row[1]))
    states = defaultdict(State)
    ledgers = {"home_win": [], "over_228_5": []}
    for at, game_id, home_row, away_row in games:
        home_team, away_team = home_row["team_abbreviation"], away_row["team_abbreviation"]
        home, away = states[home_team], states[away_team]
        row_features = {**features(home, "home", at), **features(away, "away", at), "elo_difference": home.elo - away.elo, "neutral": 0.0, "total_line": 228.5}
        common = {"event_id": game_id, "event_time": at.isoformat(), "knowledge_time": (at - timedelta(minutes=1)).isoformat(), "home_team": home_team, "away_team": away_team, "features": row_features}
        home_points, away_points = int(home_row["pts"]), int(away_row["pts"])
        ledgers["home_win"].append({**common, "label": int(home_points > away_points)})
        ledgers["over_228_5"].append({**common, "label": int(home_points + away_points > 228.5)})
        expected = 1 / (1 + 10 ** (-(home.elo + 70 - away.elo) / 400))
        result = 1 if home_points > away_points else 0
        delta = 20 * (result - expected)
        home.elo += delta; away.elo -= delta
        for state, row, opponent_points, won in ((home, home_row, away_points, result), (away, away_row, home_points, 1 - result)):
            state.points.append(float(row["pts"])); state.allowed.append(float(opponent_points))
            state.offensive.append(float(row.get("off_rating") or 113)); state.defensive.append(float(row.get("def_rating") or 113))
            state.pace.append((float(row.get("poss") or 100) + float(row.get("opp_poss") or 100)) / 2)
            state.wins.append(float(won)); state.last = at
        home_detail = advanced.get((game_id, home_team))
        away_detail = advanced.get((game_id, away_team))
        for state, own, opponent in ((home, home_detail, away_detail), (away, away_detail, home_detail)):
            if not own:
                continue
            possessions = max(1.0, float(own.get("totPoss") or own.get("oppPoss") or 100))
            attempts = max(1.0, float(own.get("fgaplyr") or 88))
            opponent_dreb = float((opponent or {}).get("drebounder") or 33)
            state.efg.append(float(own.get("eFG") or .54))
            if opponent:
                state.efg_allowed.append(float(opponent.get("eFG") or .54))
                state.turnover_forced.append(float(opponent.get("tov1") or 13) / max(1.0, float(opponent.get("totPoss") or 100)))
            state.turnover_rate.append(float(own.get("tov1") or 13) / possessions)
            state.offensive_rebound_rate.append(float(own.get("orebounder") or 10) / max(1.0, float(own.get("orebounder") or 10) + opponent_dreb))
            state.free_throw_rate.append(float(own.get("ftaplyr") or 20) / attempts)
            state.three_point_rate.append(float(own.get("fg3aplyr") or 35) / attempts)
            state.assist_rate.append(float(own.get("assister") or 25) / max(1.0, float(own.get("fgmplyr") or 40)))
            state.rim_rate.append(float(own.get("luaplyr") or 24) / attempts)
            state.net_shooting.append(float(own.get("netPtsShooting") or 0)); state.net_turnover.append(float(own.get("netPtsTurnover") or 0))
            state.net_rebound.append(float(own.get("netPtsRebound") or 0))
    return ledgers


def collect(start: int, end: int, output: Path) -> dict:
    rows, downloads = [], []
    for season in range(start, end + 1):
        try:
            batch = fetch_season(season); rows.extend(batch); downloads.append({"season": season, "rows": len(batch)})
        except Exception as error:
            downloads.append({"season": season, "rows": 0, "error": str(error)})
    output.mkdir(parents=True, exist_ok=True)
    advanced = advanced_lookup(output / "nba_advanced.json")
    ledgers = build(rows, advanced)
    for market, records in ledgers.items():
        (output / f"{market}.jsonl").write_text("\n".join(json.dumps(row, separators=(",", ":")) for row in records) + "\n", encoding="utf-8")
    report = {"source": "llimllib/nba_data NBA Stats + ESPN open mirror", "access": "keyless/no-cost", "odds_used": False, "advanced_team_games": len(advanced), "advanced_metrics": ["effective field-goal rate", "turnover rate", "offensive-rebound rate", "free-throw rate", "three-point attempt rate", "assist rate", "rim rate", "possession-value components"], "downloads": downloads, "ledgers": {key: len(value) for key, value in ledgers.items()}, "generated_at": datetime.now(timezone.utc).isoformat()}
    (output / "collection.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(); parser.add_argument("--start-season", type=int, default=2019); parser.add_argument("--end-season", type=int, default=2026); parser.add_argument("--output-dir", type=Path, default=Path("ml/data/multisport/basketball")); args = parser.parse_args()
    print(json.dumps(collect(args.start_season, args.end_season, args.output_dir), indent=2))


if __name__ == "__main__": main()
