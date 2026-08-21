"""Build odds-free NFL ledgers with nflverse play-by-play evidence."""
from __future__ import annotations

import argparse, csv, gzip, io, json, math, subprocess, time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

URL = "https://github.com/nflverse/nflverse-data/releases/download/schedules/games.csv"
PBP_URL = "https://github.com/nflverse/nflverse-data/releases/download/pbp/play_by_play_{season}.csv.gz"
NFL_TIMEZONE = ZoneInfo("America/New_York")


def fetch() -> list[dict]:
    with urlopen(Request(URL, headers={"User-Agent": "NINTH-Research/2.0"}), timeout=60) as response:
        return list(csv.DictReader(io.StringIO(response.read().decode("utf-8-sig"))))


def avg(values, default): return sum(values) / len(values) if values else default


@dataclass
class State:
    elo: float = 1500
    scored: deque = field(default_factory=lambda: deque(maxlen=10))
    allowed: deque = field(default_factory=lambda: deque(maxlen=10))
    wins: deque = field(default_factory=lambda: deque(maxlen=10))
    offensive_epa: deque = field(default_factory=lambda: deque(maxlen=10))
    defensive_epa: deque = field(default_factory=lambda: deque(maxlen=10))
    success_rate: deque = field(default_factory=lambda: deque(maxlen=10))
    success_allowed: deque = field(default_factory=lambda: deque(maxlen=10))
    explosive_rate: deque = field(default_factory=lambda: deque(maxlen=10))
    explosive_allowed: deque = field(default_factory=lambda: deque(maxlen=10))
    sack_rate: deque = field(default_factory=lambda: deque(maxlen=10))
    pressure_allowed: deque = field(default_factory=lambda: deque(maxlen=10))
    turnover_rate: deque = field(default_factory=lambda: deque(maxlen=10))
    third_down_rate: deque = field(default_factory=lambda: deque(maxlen=10))
    drive_score_rate: deque = field(default_factory=lambda: deque(maxlen=10))
    pass_over_expected: deque = field(default_factory=lambda: deque(maxlen=10))


def _float(value, default=0.0):
    try:
        result = float(value)
        return result if math.isfinite(result) else default
    except (TypeError, ValueError):
        return default


def _american_to_decimal(value) -> float | None:
    price = _float(value, 0.0)
    if not price:
        return None
    return round(1 + (price / 100 if price > 0 else 100 / abs(price)), 6)


def _download(url: str, path: Path) -> Path:
    complete = path.with_suffix(path.suffix + ".complete")
    if path.exists() and path.stat().st_size > 1_000_000 and complete.exists():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    error = None
    for attempt in range(3):
        try:
            request = Request(url, headers={"User-Agent": "NINTH-Research/2.0", "Accept": "application/octet-stream"})
            with urlopen(request, timeout=90) as response, path.open("wb") as target:
                while chunk := response.read(1024 * 1024):
                    target.write(chunk)
            complete.write_text("ok", encoding="ascii")
            return path
        except Exception as caught:
            error = caught
            if path.exists():
                path.unlink()
            if complete.exists():
                complete.unlink()
            time.sleep(2 ** attempt)
    raise RuntimeError(f"Could not download {url}: {error}")


def pbp_summaries(seasons: list[int], cache_dir: Path) -> dict[tuple[str, str], dict]:
    """Aggregate play-by-play to game/team rows without retaining giant files."""
    summaries: dict[tuple[str, str], dict] = {}
    for season in seasons:
        path = _download(PBP_URL.format(season=season), cache_dir / f"play_by_play_{season}.csv.gz")
        with gzip.open(path, "rt", encoding="utf-8", errors="replace", newline="") as stream:
            for row in csv.DictReader(stream):
                game_id, team = row.get("game_id"), row.get("posteam")
                if not game_id or not team or row.get("play_type") not in {"pass", "run"}:
                    continue
                key = (game_id, team)
                item = summaries.setdefault(key, {
                    "plays": 0, "epa": 0.0, "success": 0.0, "explosive": 0,
                    "dropbacks": 0, "sacks": 0, "qb_hits": 0, "turnovers": 0,
                    "third_attempts": 0, "third_converted": 0, "pass_oe": [],
                    "drives": set(), "scoring_drives": set(),
                })
                item["plays"] += 1
                item["epa"] += _float(row.get("epa"))
                item["success"] += _float(row.get("success"))
                yards = _float(row.get("yards_gained"))
                item["explosive"] += int((row.get("play_type") == "pass" and yards >= 20) or (row.get("play_type") == "run" and yards >= 10))
                item["dropbacks"] += int(_float(row.get("qb_dropback")) > 0)
                item["sacks"] += int(_float(row.get("sack")) > 0)
                item["qb_hits"] += int(_float(row.get("qb_hit")) > 0)
                item["turnovers"] += int(_float(row.get("interception")) > 0 or _float(row.get("fumble_lost")) > 0)
                third = _float(row.get("third_down_converted")) > 0 or _float(row.get("third_down_failed")) > 0
                item["third_attempts"] += int(third)
                item["third_converted"] += int(_float(row.get("third_down_converted")) > 0)
                if row.get("pass_oe") not in (None, ""):
                    item["pass_oe"].append(_float(row.get("pass_oe")))
                drive = row.get("fixed_drive") or row.get("drive")
                if drive:
                    item["drives"].add(drive)
                    if _float(row.get("drive_ended_with_score")) > 0:
                        item["scoring_drives"].add(drive)
    result = {}
    for key, item in summaries.items():
        plays, dropbacks = max(1, item["plays"]), max(1, item["dropbacks"])
        result[key] = {
            "epa_per_play": item["epa"] / plays,
            "success_rate": item["success"] / plays,
            "explosive_rate": item["explosive"] / plays,
            "sack_rate": item["sacks"] / dropbacks,
            "pressure_rate": item["qb_hits"] / dropbacks,
            "turnover_rate": item["turnovers"] / plays,
            "third_down_rate": item["third_converted"] / max(1, item["third_attempts"]),
            "drive_score_rate": len(item["scoring_drives"]) / max(1, len(item["drives"])),
            "pass_over_expected": sum(item["pass_oe"]) / len(item["pass_oe"]) if item["pass_oe"] else 0.0,
        }
    return result


def advanced_summaries(start: int, end: int, output: Path) -> dict[tuple[str, str], dict]:
    path = output / "nflverse_advanced.json"
    payload = None
    if path.exists():
        try:
            cached = json.loads(path.read_text(encoding="utf-8"))
            cached_start, cached_end = cached.get("seasons", [None, None])
            if cached_start is not None and int(cached_start) <= start and int(cached_end) >= end:
                payload = cached
        except (ValueError, TypeError, OSError):
            payload = None
    if payload is None:
        subprocess.run(["node", "ml/multisport/export_nfl_advanced.mjs", str(path), str(start), str(end)], check=True)
        payload = json.loads(path.read_text(encoding="utf-8"))
    return {(row["game_id"], row["team"]): row for row in payload.get("rows", [])}


def build(rows: list[dict], start_season: int, advanced: dict[tuple[str, str], dict] | None = None) -> dict[str, list[dict]]:
    advanced = advanced or {}
    rows = [row for row in rows if int(row.get("season") or 0) >= start_season and row.get("home_score") != "" and row.get("away_score") != ""]
    rows.sort(key=lambda row: (row["gameday"], row["game_id"]))
    states = defaultdict(State); ledgers = {"home_win": [], "score": []}
    for row in rows:
        home, away = states[row["home_team"]], states[row["away_team"]]
        at = datetime.fromisoformat(f"{row['gameday']}T{row.get('gametime') or '12:00'}:00").replace(tzinfo=NFL_TIMEZONE).astimezone(timezone.utc)
        features = {
            "home_elo": home.elo, "away_elo": away.elo, "elo_difference": home.elo - away.elo,
            "home_scored_5": avg(list(home.scored)[-5:], 22.5), "away_scored_5": avg(list(away.scored)[-5:], 22.5),
            "home_allowed_5": avg(list(home.allowed)[-5:], 22.5), "away_allowed_5": avg(list(away.allowed)[-5:], 22.5),
            "home_win_rate_10": avg(home.wins, .5), "away_win_rate_10": avg(away.wins, .5),
            "home_rest": float(row.get("home_rest") or 7), "away_rest": float(row.get("away_rest") or 7),
            "temperature": float(row.get("temp") or 65), "wind": float(row.get("wind") or 5),
            "divisional": float(row.get("div_game") or 0), "outdoors": float(row.get("roof") == "outdoors"),
            "home_off_epa_10": avg(home.offensive_epa, 0.0), "away_off_epa_10": avg(away.offensive_epa, 0.0),
            "home_def_epa_10": avg(home.defensive_epa, 0.0), "away_def_epa_10": avg(away.defensive_epa, 0.0),
            "home_success_10": avg(home.success_rate, .43), "away_success_10": avg(away.success_rate, .43),
            "home_success_allowed_10": avg(home.success_allowed, .43), "away_success_allowed_10": avg(away.success_allowed, .43),
            "home_explosive_10": avg(home.explosive_rate, .105), "away_explosive_10": avg(away.explosive_rate, .105),
            "home_explosive_allowed_10": avg(home.explosive_allowed, .105), "away_explosive_allowed_10": avg(away.explosive_allowed, .105),
            "home_sack_rate_10": avg(home.sack_rate, .065), "away_sack_rate_10": avg(away.sack_rate, .065),
            "home_pressure_allowed_10": avg(home.pressure_allowed, .18), "away_pressure_allowed_10": avg(away.pressure_allowed, .18),
            "home_turnover_rate_10": avg(home.turnover_rate, .022), "away_turnover_rate_10": avg(away.turnover_rate, .022),
            "home_third_down_10": avg(home.third_down_rate, .40), "away_third_down_10": avg(away.third_down_rate, .40),
            "home_drive_score_10": avg(home.drive_score_rate, .36), "away_drive_score_10": avg(away.drive_score_rate, .36),
            "home_pass_oe_10": avg(home.pass_over_expected, 0.0), "away_pass_oe_10": avg(away.pass_over_expected, 0.0),
        }
        common = {
            "event_id": row["game_id"], "event_time": at.isoformat(),
            "knowledge_time": (at - timedelta(minutes=1)).isoformat(),
            "season": int(row["season"]), "week": row.get("week"),
            "home_team": row["home_team"], "away_team": row["away_team"],
            "features": features,
            "archived_prices": {
                "provider": "nflverse schedules",
                "closing": {
                    "home": _american_to_decimal(row.get("home_moneyline")),
                    "away": _american_to_decimal(row.get("away_moneyline")),
                    "over": _american_to_decimal(row.get("over_odds")),
                    "under": _american_to_decimal(row.get("under_odds")),
                    "home_spread": _american_to_decimal(row.get("home_spread_odds")),
                    "away_spread": _american_to_decimal(row.get("away_spread_odds")),
                },
                "timestamp_note": "nflverse archived pregame line; exact price timestamp unavailable",
            },
        }
        home_score, away_score = int(float(row["home_score"])), int(float(row["away_score"]))
        ledgers["home_win"].append({**common, "label": int(home_score > away_score)})
        ledgers["score"].append({
            **common,
            "home_score": home_score,
            "away_score": away_score,
            "total_points": home_score + away_score,
            "home_margin": home_score - away_score,
            # Pregame market anchors are outcomes for evaluation only. They are
            # deliberately kept outside ``features`` and never fitted by the model.
            "market_total_line": _float(row.get("total_line"), None),
            "market_spread_line": _float(row.get("spread_line"), None),
        })
        expected = 1 / (1 + 10 ** (-(home.elo + 50 - away.elo) / 400)); result = 1 if home_score > away_score else .5 if home_score == away_score else 0; delta = 24 * (result - expected); home.elo += delta; away.elo -= delta
        for state, scored, allowed, win in ((home, home_score, away_score, result), (away, away_score, home_score, 1 - result)):
            state.scored.append(scored); state.allowed.append(allowed); state.wins.append(win)
        home_advanced = advanced.get((row["game_id"], row["home_team"]))
        away_advanced = advanced.get((row["game_id"], row["away_team"]))
        for state, own, opponent in ((home, home_advanced, away_advanced), (away, away_advanced, home_advanced)):
            if own:
                state.offensive_epa.append(own["epa_per_play"]); state.success_rate.append(own["success_rate"])
                state.explosive_rate.append(own["explosive_rate"]); state.sack_rate.append(own["sack_rate"])
                state.pressure_allowed.append(own["pressure_rate"]); state.turnover_rate.append(own["turnover_rate"])
                state.third_down_rate.append(own["third_down_rate"]); state.drive_score_rate.append(own["drive_score_rate"])
                state.pass_over_expected.append(own["pass_over_expected"])
            if opponent:
                state.defensive_epa.append(opponent["epa_per_play"]); state.success_allowed.append(opponent["success_rate"])
                state.explosive_allowed.append(opponent["explosive_rate"])
    return ledgers


def collect(start: int, output: Path, advanced_start: int | None = None) -> dict:
    advanced_start = advanced_start or max(start, datetime.now().year - 3)
    seasons = list(range(advanced_start, datetime.now().year))
    advanced = advanced_summaries(seasons[0], seasons[-1], output)
    ledgers = build(fetch(), start, advanced); output.mkdir(parents=True, exist_ok=True)
    for market, records in ledgers.items(): (output / f"{market}.jsonl").write_text("\n".join(json.dumps(row, separators=(",", ":")) for row in records) + "\n", encoding="utf-8")
    report = {"source": "nflverse", "access": "keyless/no-cost", "odds_used": False, "start_season": start, "advanced_seasons": seasons, "advanced_team_games": len(advanced), "advanced_metrics": ["EPA/play", "success rate", "explosive rate", "pressure and sack rates", "turnover rate", "third-down rate", "drive scoring rate", "pass rate over expected"], "ledgers": {key: len(value) for key, value in ledgers.items()}, "generated_at": datetime.now(timezone.utc).isoformat()}; (output / "collection.json").write_text(json.dumps(report, indent=2), encoding="utf-8"); return report


def main() -> None:
    parser=argparse.ArgumentParser(); parser.add_argument("--start-season",type=int,default=2010); parser.add_argument("--advanced-start",type=int); parser.add_argument("--output-dir",type=Path,default=Path("ml/data/multisport/american-football")); args=parser.parse_args(); print(json.dumps(collect(args.start_season,args.output_dir,args.advanced_start),indent=2))


if __name__ == "__main__": main()
