"""Nightly data sync and guarded production-model retraining for NINTH."""
import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "ml" / "data" / "games.jsonl"
ARTIFACTS = ROOT / "ml" / "artifacts"
REPORT = ARTIFACTS / "report.json"
MODEL = ARTIFACTS / "moneyline.joblib"
STATE = ARTIFACTS / "maintenance_state.json"
LOCK = ARTIFACTS / ".maintenance.lock"
CANDIDATE = ARTIFACTS / "candidate"


def read_json(path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf8"))
    except (OSError, ValueError, TypeError):
        return {} if default is None else default


def write_json(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2), encoding="utf8")
    os.replace(temporary, path)


def game_rows():
    if not DATA.exists():
        return []
    return [json.loads(line) for line in DATA.read_text(encoding="utf8").splitlines() if line.strip()]


def metric(report, section, key, default=0.0):
    value = (report.get(section) or {}).get(key, default)
    return float(value if value is not None else default)


def promotion_checks(candidate, incumbent):
    return {
        "new_completed_games": int(candidate.get("deployment_training_games", 0)) > int(incumbent.get("deployment_training_games", 0)),
        "walk_forward_accuracy": metric(candidate, "walk_forward", "accuracy") >= 0.57,
        "qualified_accuracy": float(candidate.get("qualified_accuracy") or 0) >= 0.60,
        "walk_forward_brier": metric(candidate, "walk_forward", "brier_score", 1) <= metric(incumbent, "walk_forward", "brier_score", 1) + 0.0005,
        "recent_accuracy_stability": metric(candidate, "recent_outer", "accuracy") >= metric(incumbent, "recent_outer", "accuracy") - 0.005,
        "recent_brier_stability": metric(candidate, "recent_outer", "brier_score", 1) <= metric(incumbent, "recent_outer", "brier_score", 1) + 0.001,
    }


def run(command, env=None, timeout=3600):
    result = subprocess.run(command, cwd=ROOT, env=env, text=True, capture_output=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError((result.stderr or result.stdout or "maintenance command failed")[-2000:])
    return result.stdout


def maintain(force=False, dry_run=False):
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    state = read_json(STATE, {})
    today = date.today().isoformat()
    if not force and state.get("last_sync_date") == today:
        return {"status": "already_checked", "last_sync_date": today}
    if dry_run:
        return {"status": "dry_run", "would_sync_season": date.today().year}

    run([sys.executable, "ml/collect.py", "--start-season", str(date.today().year), "--end-season", str(date.today().year)])
    run([sys.executable, "ml/enrich.py", "--start-season", str(date.today().year), "--end-season", str(date.today().year), "--workers", os.getenv("NINTH_ENRICH_WORKERS", "6")])
    incumbent = read_json(REPORT, {})
    rows = game_rows()
    trained_through = incumbent.get("trained_through_date", "1900-01-01")
    new_games = sum(row.get("date", "") > trained_through for row in rows)
    last_promotion = state.get("last_promotion_at") or datetime.fromtimestamp(MODEL.stat().st_mtime, timezone.utc).isoformat()
    days_since_promotion = (datetime.now(timezone.utc) - datetime.fromisoformat(last_promotion.replace("Z", "+00:00"))).days
    should_train = new_games >= int(os.getenv("NINTH_RETRAIN_GAME_THRESHOLD", "100")) or (new_games > 0 and days_since_promotion >= int(os.getenv("NINTH_RETRAIN_DAYS", "7")))
    result = {"status": "synced", "completed_games_after_model": new_games, "retrain_due": should_train}

    if should_train:
        shutil.rmtree(CANDIDATE, ignore_errors=True)
        CANDIDATE.mkdir(parents=True)
        env = os.environ.copy(); env["NINTH_ARTIFACT_DIR"] = str(CANDIDATE)
        run([sys.executable, "-m", "ml.train_v3"], env=env)
        candidate = read_json(CANDIDATE / "report.json", {})
        checks = promotion_checks(candidate, incumbent)
        result["promotion_checks"] = checks
        if all(checks.values()):
            os.replace(CANDIDATE / "moneyline.joblib", MODEL)
            os.replace(CANDIDATE / "report.json", REPORT)
            state["last_promotion_at"] = datetime.now(timezone.utc).isoformat()
            result["status"] = "promoted"
        else:
            result["status"] = "candidate_rejected"
        shutil.rmtree(CANDIDATE, ignore_errors=True)

    state.update({"last_sync_date": today, "last_run_at": datetime.now(timezone.utc).isoformat(), "last_result": result})
    write_json(STATE, state)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try:
        fd = os.open(LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        print(json.dumps({"status": "maintenance_already_running"}))
        return
    try:
        os.close(fd)
        print(json.dumps(maintain(force=args.force, dry_run=args.dry_run)))
    finally:
        LOCK.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
