"""Refresh immutable NFL and Football forecasts and their live readiness audits."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
STATUS_PATH = ROOT / "ml" / "data" / "multisport" / "readiness_refresh.json"
PIPELINES = {
    "american-football": {
        "module": "ml.multisport.predict_nfl_open",
        "result": ROOT / "ml" / "data" / "multisport" / "american-football" / "predictions.json",
    },
    "football": {
        "module": "ml.multisport.predict_football_open",
        "result": ROOT / "ml" / "data" / "multisport" / "football" / "predictions.json",
    },
}


def result_age_hours(path: Path, now: datetime | None = None) -> float | None:
    """Prefer the immutable result timestamp and fall back to file age."""
    now = now or datetime.now(timezone.utc)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        generated = datetime.fromisoformat(str(payload.get("generated_at") or "").replace("Z", "+00:00"))
        if generated.tzinfo is None:
            generated = generated.replace(tzinfo=timezone.utc)
        return max(0.0, (now - generated).total_seconds() / 3600)
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        try:
            modified = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
            return max(0.0, (now - modified).total_seconds() / 3600)
        except OSError:
            return None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-age-hours", type=float, default=6.0)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    runs = []
    failed = False
    for sport, pipeline in PIPELINES.items():
        module, result_path = pipeline["module"], pipeline["result"]
        age = result_age_hours(result_path)
        if not args.force and age is not None and age < max(0.0, args.max_age_hours):
            runs.append({
                "sport": sport,
                "module": module,
                "passed": True,
                "skipped": True,
                "reason": f"existing result is {age:.2f} hours old",
                "result": str(result_path.relative_to(ROOT)),
            })
            continue
        started = time.monotonic()
        completed = subprocess.run(
            [sys.executable, "-m", module], cwd=ROOT, text=True,
            capture_output=True, check=False,
        )
        failed = failed or completed.returncode != 0
        runs.append({
            "sport": sport,
            "module": module,
            "passed": completed.returncode == 0,
            "skipped": False,
            "return_code": completed.returncode,
            "duration_seconds": round(time.monotonic() - started, 3),
            "stdout": completed.stdout[-2000:].strip(),
            "stderr": completed.stderr[-4000:].strip(),
        })
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "passed": not failed,
        "runs": runs,
    }
    STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATUS_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
