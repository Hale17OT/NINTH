"""Settle completed prop slates and atomically refresh live selection policy.

This lightweight job is intentionally independent from model retraining. It can
run at service startup and each maintenance tick so yesterday's settled props
are available before today's builder is used.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from pathlib import Path

import requests

from ml.collect_player_boxscores import _fetch


ROOT = Path(__file__).resolve().parents[1]
BUILDS = ROOT / "ml" / "data" / "player_prop_build_snapshots.jsonl"
SNAPSHOTS = ROOT / "ml" / "data" / "player_prop_projection_snapshots.jsonl"
PRICED_BOARDS = ROOT / "ml" / "data" / "player_prop_priced_board_snapshots.jsonl"
BOXES = ROOT / "ml" / "data" / "player_boxscores.jsonl"
PROJECTION_AUDIT = ROOT / "ml" / "artifacts" / "live_player_prop_audit.json"
BUILD_AUDIT = ROOT / "ml" / "artifacts" / "live_player_prop_build_audit.json"
PRICED_BOARD_AUDIT = ROOT / "ml" / "artifacts" / "player_prop_priced_board_audit.json"
STATUS_URL = "https://statsapi.mlb.com/api/v1.1/game/{game_id}/feed/live"


def _lines(path: Path):
    if not path.exists():
        return
    with path.open(encoding="utf-8-sig") as handle:
        for raw in handle:
            if not raw.strip():
                continue
            try:
                yield json.loads(raw.replace("\x00", ""))
            except json.JSONDecodeError:
                continue


def target_games(through: str) -> dict[int, str]:
    targets = {}
    for build in _lines(BUILDS) or []:
        for entry in build.get("entries") or []:
            played = str(entry.get("official_date") or build.get("start_date") or "")[:10]
            if played and played <= through:
                targets[int(entry["game_id"])] = played
    # Projection-only games also feed automatic-market promotion evidence.
    for snapshot in _lines(SNAPSHOTS) or []:
        played = str(snapshot.get("official_date") or snapshot.get("game_date") or "")[:10]
        if played and played <= through:
            targets[int(snapshot["game_id"])] = played
    for snapshot in _lines(PRICED_BOARDS) or []:
        played = str(snapshot.get("official_date") or snapshot.get("game_date") or "")[:10]
        if played and played <= through:
            targets[int(snapshot["game_id"])] = played
    return targets


def _is_final(game_id: int) -> bool:
    response = requests.get(STATUS_URL.format(game_id=game_id), timeout=20)
    response.raise_for_status()
    status = response.json().get("gameData", {}).get("status", {})
    return status.get("abstractGameState") == "Final"


def _fetch_target(item: tuple[int, str]) -> dict | None:
    game_id, played = item
    if not _is_final(game_id):
        return None
    return _fetch({
        "game_id": game_id, "date": played, "season": int(played[:4]),
        "home_id": 0, "away_id": 0, "home_name": "", "away_name": "",
    })


def _audit_stale(output: Path, *inputs: Path) -> bool:
    if not output.exists():
        return True
    return any(path.exists() and path.stat().st_mtime > output.stat().st_mtime for path in inputs)


def refresh(through: str | None = None, workers: int = 8) -> dict:
    through = through or (date.today() - timedelta(days=1)).isoformat()
    targets = target_games(through)
    existing = {int(row["game_id"]) for row in (_lines(BOXES) or [])}
    pending = sorted((game_id, played) for game_id, played in targets.items() if game_id not in existing)
    completed, deferred, errors = [], [], []
    if pending:
        with ThreadPoolExecutor(max_workers=max(1, min(workers, len(pending)))) as pool:
            futures = {pool.submit(_fetch_target, item): item for item in pending}
            for future in as_completed(futures):
                item = futures[future]
                try:
                    row = future.result()
                    if row:
                        completed.append(row)
                    else:
                        deferred.append(item[0])
                except Exception as exc:  # noqa: BLE001 - leave the job resumable
                    errors.append(f"game {item[0]}: {exc}")
    if completed:
        BOXES.parent.mkdir(parents=True, exist_ok=True)
        with BOXES.open("a", encoding="utf-8", buffering=1) as output:
            for row in sorted(completed, key=lambda value: int(value["game_id"])):
                output.write(json.dumps(row, separators=(",", ":")) + "\n")

    projection_stale = bool(completed) or _audit_stale(PROJECTION_AUDIT, SNAPSHOTS, BOXES)
    build_stale = bool(completed) or _audit_stale(BUILD_AUDIT, BUILDS, BOXES)
    if projection_stale:
        subprocess.run(
            [sys.executable, "-m", "ml.evaluate_live_prop_snapshots"],
            cwd=ROOT, check=True, capture_output=True, text=True,
        )
    if build_stale:
        subprocess.run(
            [sys.executable, "-m", "ml.evaluate_player_prop_builds"],
            cwd=ROOT, check=True, capture_output=True, text=True,
        )
    priced_board_stale = bool(completed) or _audit_stale(PRICED_BOARD_AUDIT, PRICED_BOARDS, BOXES)
    if priced_board_stale:
        subprocess.run(
            [sys.executable, "-m", "ml.evaluate_player_prop_priced_board"],
            cwd=ROOT, check=True, capture_output=True, text=True,
        )
    frozen = subprocess.run(
        [sys.executable, "-m", "ml.freeze_player_prop_forward_policy"],
        cwd=ROOT, check=True, capture_output=True, text=True,
    )
    forward_policy = json.loads(frozen.stdout.strip() or "{}")
    return {
        "through": through,
        "target_games": len(targets),
        "new_boxscores": len(completed),
        "deferred_games": deferred,
        "errors": errors,
        "projection_audit_refreshed": projection_stale,
        "build_audit_refreshed": build_stale,
        "priced_board_audit_refreshed": priced_board_stale,
        "forward_policy_id": forward_policy.get("policy_id"),
        "forward_policy_reused": forward_policy.get("reused"),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--through")
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()
    print(json.dumps(refresh(args.through, args.workers)))


if __name__ == "__main__":
    main()
