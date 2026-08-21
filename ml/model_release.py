"""Build and restore immutable NINTH production-model releases.

The release directory is deliberately outside Git.  Code is deployed by Git,
while approved model binaries, calibration policy and compact runtime history
are published separately and switched by a manifest written last.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path

import joblib


ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = Path(os.getenv("NINTH_ARTIFACT_DIR", ROOT / "ml" / "artifacts"))
DATA = Path(os.getenv("NINTH_DATA_DIR", ROOT / "ml" / "data"))
RELEASES = Path(os.getenv("NINTH_RELEASE_DIR", ROOT / "ml" / "releases"))

REQUIRED_ARTIFACTS = (
    "moneyline.joblib", "report.json",
    "totals.joblib", "totals_report.json",
    "player_props.joblib", "player_props_report.json",
)
OPTIONAL_ARTIFACTS = (
    "market_slip_calibration.json",
    "maintenance_state.json",
    "live_player_prop_audit.json",
    "live_player_prop_build_audit.json",
    "player_prop_priced_board_audit.json",
    "player_prop_forward_policy.json",
    "player_prop_reranker_shadow_candidate.json",
    "deployment_selection_audit.json",
)
RUNTIME_DATA = (
    "player_boxscores.jsonl",
    "statcast_rich_games.jsonl",
    "projection_snapshots.jsonl",
    "player_prop_projection_snapshots.jsonl",
    "melbet_totals_snapshots.jsonl",
)
MODEL_FILES = ("moneyline.joblib", "totals.joblib", "player_props.joblib")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _git_revision() -> str | None:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True,
            text=True, timeout=10, check=True,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None


def _git_dirty() -> bool | None:
    try:
        return bool(subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=all"],
            cwd=ROOT, capture_output=True, text=True, timeout=10, check=True,
        ).stdout.strip())
    except (OSError, subprocess.SubprocessError):
        return None


def _parse_time(value):
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return datetime.min.replace(tzinfo=timezone.utc)


def _compact_last_pregame(source: Path, output) -> int:
    """Retain one immutable pregame board per game instead of multi-GB polling logs."""
    selected = {}
    with source.open(encoding="utf-8") as handle:
        for line in handle:
            try:
                row = json.loads(line)
                game_id = int(row["game_id"])
                recorded = _parse_time(row.get("recorded_at"))
                scheduled = _parse_time(row.get("scheduled_start"))
            except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                continue
            if row.get("phase") == "live":
                continue
            if scheduled != datetime.min.replace(tzinfo=timezone.utc) and recorded > scheduled:
                continue
            current = selected.get(game_id)
            if current is None or recorded > current[0]:
                selected[game_id] = (recorded, row)
    for _, row in sorted(selected.values(), key=lambda item: item[0]):
        output.write((json.dumps(row, separators=(",", ":")) + "\n").encode("utf-8"))
    return len(selected)


def _current_season(source: Path, output, year: int) -> int:
    count = 0
    with source.open(encoding="utf-8") as handle:
        for line in handle:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            season = int(row.get("season") or str(row.get("date") or "")[:4] or 0)
            if season != year:
                continue
            output.write((json.dumps(row, separators=(",", ":")) + "\n").encode("utf-8"))
            count += 1
    return count


def _copy_payload(source: Path, stored: Path, logical_path: str) -> dict:
    stored.parent.mkdir(parents=True, exist_ok=True)
    compression = None
    rows = None
    compress = source.suffix in {".json", ".jsonl"}
    if compress:
        stored = stored.with_name(stored.name + ".gz")
        compression = "gzip"
        with gzip.open(stored, "wb", compresslevel=6) as output:
            if source.name in {"projection_snapshots.jsonl", "player_prop_projection_snapshots.jsonl"}:
                rows = _compact_last_pregame(source, output)
            elif source.name in {"player_boxscores.jsonl", "statcast_rich_games.jsonl"}:
                rows = _current_season(source, output, date.today().year)
            else:
                with source.open("rb") as handle:
                    shutil.copyfileobj(handle, output, length=1024 * 1024)
    else:
        shutil.copy2(source, stored)
    return {
        "logical_path": logical_path,
        "stored_path": stored.relative_to(stored.parents[2]).as_posix(),
        "compression": compression,
        "source_bytes": source.stat().st_size,
        "stored_bytes": stored.stat().st_size,
        "sha256": _sha256(stored),
        **({"rows": rows} if rows is not None else {}),
    }


def validate_production_sources() -> None:
    missing = [name for name in REQUIRED_ARTIFACTS if not (ARTIFACTS / name).is_file()]
    if missing:
        raise RuntimeError(f"production model release is incomplete: {', '.join(missing)}")
    for name in MODEL_FILES:
        value = joblib.load(ARTIFACTS / name)
        valid = isinstance(value, dict) and (
            bool(value.get("report")) if name != "player_props.joblib"
            else bool(value.get("models")) and bool(value.get("state"))
        )
        if not valid:
            raise RuntimeError(f"{name} is not a valid NINTH production bundle")


def build_release(release_id: str | None = None) -> dict:
    validate_production_sources()
    release_id = release_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destination = RELEASES / release_id
    if destination.exists():
        raise FileExistsError(f"release already exists: {release_id}")
    destination.mkdir(parents=True)
    files = []
    try:
        for name in REQUIRED_ARTIFACTS + OPTIONAL_ARTIFACTS:
            source = ARTIFACTS / name
            if source.is_file():
                files.append(_copy_payload(source, destination / "artifacts" / name, f"artifacts/{name}"))
        for name in RUNTIME_DATA:
            source = DATA / name
            if source.is_file():
                files.append(_copy_payload(source, destination / "data" / name, f"data/{name}"))
        reports = {
            "moneyline": _read_json(ARTIFACTS / "report.json"),
            "totals": _read_json(ARTIFACTS / "totals_report.json"),
            "player_props": _read_json(ARTIFACTS / "player_props_report.json"),
        }
        manifest = {
            "schema_version": 1,
            "release_id": release_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "git_revision": _git_revision(),
            "git_dirty": _git_dirty(),
            "models": {
                "moneyline": {"trained_through": reports["moneyline"].get("trained_through_date"), "model": reports["moneyline"].get("model")},
                "totals": {"trained_through": reports["totals"].get("trained_through_date"), "model": reports["totals"].get("model")},
                "player_props": {"trained_through": (reports["player_props"].get("data") or {}).get("last_date"), "version": reports["player_props"].get("version")},
            },
            "files": files,
        }
        canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
        manifest["release_sha256"] = hashlib.sha256(canonical).hexdigest()
        (destination / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return manifest
    except Exception:
        shutil.rmtree(destination, ignore_errors=True)
        raise


def _release_root(entry: dict, release_dir: Path) -> Path:
    stored_path = Path(entry["stored_path"])
    # stored_path is always rooted at the release ID.
    return release_dir.parent / stored_path


def restore_release(release_id: str, include_runtime_data: bool = False) -> dict:
    """Restore production models; compact cloud data is opt-in to protect training history."""
    release_dir = RELEASES / release_id
    manifest = _read_json(release_dir / "manifest.json")
    if manifest.get("release_id") != release_id:
        raise RuntimeError(f"invalid release manifest: {release_id}")
    staged = Path(tempfile.mkdtemp(prefix="ninth-restore-", dir=str(RELEASES)))
    try:
        for entry in manifest.get("files", []):
            if not include_runtime_data and not entry["logical_path"].startswith("artifacts/"):
                continue
            source = _release_root(entry, release_dir)
            if _sha256(source) != entry["sha256"]:
                raise RuntimeError(f"checksum mismatch: {entry['stored_path']}")
            target = staged / entry["logical_path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            if entry.get("compression") == "gzip":
                with gzip.open(source, "rb") as reader, target.open("wb") as writer:
                    shutil.copyfileobj(reader, writer, length=1024 * 1024)
            else:
                shutil.copy2(source, target)
        for entry in manifest.get("files", []):
            if not include_runtime_data and not entry["logical_path"].startswith("artifacts/"):
                continue
            logical = Path(entry["logical_path"])
            root = ARTIFACTS if logical.parts[0] == "artifacts" else DATA
            source = staged / logical
            target = root / Path(*logical.parts[1:])
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(source, target)
        return manifest
    finally:
        shutil.rmtree(staged, ignore_errors=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--release-id")
    parser.add_argument("--restore")
    parser.add_argument("--restore-runtime-data", action="store_true")
    args = parser.parse_args()
    manifest = (
        restore_release(args.restore, include_runtime_data=args.restore_runtime_data)
        if args.restore else build_release(args.release_id)
    )
    print(json.dumps({
        "release_id": manifest["release_id"],
        "release_sha256": manifest.get("release_sha256"),
        "files": len(manifest.get("files", [])),
        "stored_bytes": sum(int(row.get("stored_bytes") or 0) for row in manifest.get("files", [])),
    }))


if __name__ == "__main__":
    main()
