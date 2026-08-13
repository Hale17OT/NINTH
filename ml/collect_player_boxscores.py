"""Resumable MLB Stats API box-score collector for player-prop training.

The output intentionally contains game outcomes only.  Pregame features are
constructed later by replaying these rows chronologically, which keeps the
training pipeline point-in-time safe.
"""
from __future__ import annotations

import argparse
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests


ROOT = Path(__file__).resolve().parents[1]
GAMES_PATH = ROOT / "ml" / "data" / "games.jsonl"
OUTPUT_PATH = ROOT / "ml" / "data" / "player_boxscores.jsonl"
URL = "https://statsapi.mlb.com/api/v1/game/{game_id}/boxscore"
FIELDS = ",".join(
    (
        "teams", "home", "away", "team", "id", "name", "abbreviation",
        "players", "person", "fullName", "position", "type", "battingOrder",
        "stats", "batting", "pitching", "gamesStarted", "runs", "doubles",
        "triples", "homeRuns", "strikeOuts", "baseOnBalls", "hits", "atBats",
        "caughtStealing", "stolenBases", "plateAppearances", "totalBases", "rbi",
        "hitByPitch", "sacFlies", "numberOfPitches", "outs", "battersFaced",
        "earnedRuns", "pitchesThrown", "gameStatus", "isSubstitute",
        "wins", "losses",
    )
)
THREAD_LOCAL = threading.local()


def _session() -> requests.Session:
    if not hasattr(THREAD_LOCAL, "session"):
        value = requests.Session()
        value.headers.update({"User-Agent": "NINTH player-prop research/1.0"})
        THREAD_LOCAL.session = value
    return THREAD_LOCAL.session


def _number(mapping: dict, key: str) -> int:
    try:
        return int(mapping.get(key) or 0)
    except (TypeError, ValueError):
        return 0


def _player_rows(side: dict) -> list[dict]:
    rows = []
    for value in side.get("players", {}).values():
        person = value.get("person") or {}
        player_id = person.get("id")
        if not player_id:
            continue
        batting = (value.get("stats") or {}).get("batting") or {}
        pitching = (value.get("stats") or {}).get("pitching") or {}
        if not batting and not pitching:
            continue
        row = {
            "player_id": int(player_id),
            "name": person.get("fullName") or "Unknown player",
            "position": (value.get("position") or {}).get("abbreviation") or "",
            "batting_order": value.get("battingOrder") or "",
        }
        if batting:
            row["batting"] = {
                key: _number(batting, key)
                for key in (
                    "runs", "doubles", "triples", "homeRuns", "strikeOuts",
                    "baseOnBalls", "hits", "atBats", "caughtStealing",
                    "stolenBases", "plateAppearances", "totalBases", "rbi",
                    "hitByPitch", "sacFlies",
                )
            }
        if pitching:
            row["pitching"] = {
                key: _number(pitching, key)
                for key in (
                    "gamesStarted", "strikeOuts", "baseOnBalls", "hits",
                    "runs", "homeRuns", "numberOfPitches", "outs", "battersFaced",
                    "earnedRuns", "pitchesThrown",
                    "wins", "losses",
                )
            }
        rows.append(row)
    return rows


def _fetch(game: dict, attempts: int = 5) -> dict:
    game_id = int(game["game_id"])
    for attempt in range(attempts):
        try:
            response = _session().get(
                URL.format(game_id=game_id), params={"fields": FIELDS}, timeout=30
            )
            if response.status_code in (429, 500, 502, 503, 504):
                raise requests.HTTPError(f"retryable status {response.status_code}")
            response.raise_for_status()
            payload = response.json()
            teams = payload.get("teams") or {}
            output = {
                "game_id": game_id,
                "date": game["date"],
                "season": int(game["season"]),
            }
            for side_name in ("away", "home"):
                side = teams.get(side_name) or {}
                team = side.get("team") or {}
                output[side_name] = {
                    "team_id": int(team.get("id") or game[f"{side_name}_id"]),
                    "team_name": team.get("name") or game[f"{side_name}_name"],
                    "players": _player_rows(side),
                }
            return output
        except (requests.RequestException, ValueError, KeyError) as exc:
            if attempt == attempts - 1:
                raise RuntimeError(f"game {game_id}: {exc}") from exc
            time.sleep(min(12.0, 0.75 * (2**attempt)))
    raise AssertionError("unreachable")


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--start-season", type=int, default=2018)
    parser.add_argument("--limit", type=int)
    parser.add_argument(
        "--refresh-existing", action="store_true",
        help="Re-fetch cached games and atomically replace rows (used when outcome fields are added).",
    )
    args = parser.parse_args()

    games = [row for row in _read_jsonl(GAMES_PATH) if int(row["season"]) >= args.start_season]
    existing_rows = _read_jsonl(OUTPUT_PATH)
    completed = {int(row["game_id"]) for row in existing_rows}
    pending = list(games) if args.refresh_existing else [row for row in games if int(row["game_id"]) not in completed]
    if args.limit:
        pending = pending[: args.limit]
    action = "refresh" if args.refresh_existing else "pending"
    print(f"player box scores: {len(completed)} cached, {len(pending)} {action}", flush=True)
    if not pending:
        return

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    errors = []
    written = 0
    lock = threading.Lock()
    refreshed = []
    target_path = OUTPUT_PATH.with_suffix(".jsonl.tmp") if args.refresh_existing else OUTPUT_PATH
    mode = "w" if args.refresh_existing else "a"
    with target_path.open(mode, encoding="utf-8", buffering=1) as output:
        with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
            futures = {pool.submit(_fetch, game): game for game in pending}
            for future in as_completed(futures):
                try:
                    row = future.result()
                    with lock:
                        output.write(json.dumps(row, separators=(",", ":")) + "\n")
                        refreshed.append(row)
                        written += 1
                        if written % 250 == 0:
                            print(f"collected {written}/{len(pending)}", flush=True)
                except Exception as exc:  # noqa: BLE001 - retain failures for a resumable rerun
                    errors.append(str(exc))
                    print(f"WARNING {exc}", flush=True)
    print(f"complete: {written} written, {len(errors)} failed", flush=True)
    if args.refresh_existing:
        refreshed_ids = {int(row["game_id"]) for row in refreshed}
        if args.limit or errors:
            # A transient API failure must not discard a successful full
            # refresh. Keep the prior row for only the games that failed, then
            # a small follow-up refresh can fill those remaining fields.
            retained = [row for row in existing_rows if int(row["game_id"]) not in refreshed_ids]
            with target_path.open("a", encoding="utf-8") as output:
                for row in retained:
                    output.write(json.dumps(row, separators=(",", ":")) + "\n")
        target_path.replace(OUTPUT_PATH)
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
