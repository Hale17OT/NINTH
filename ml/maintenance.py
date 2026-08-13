"""Nightly data sync and guarded production-model retraining for NINTH."""
import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "ml" / "data" / "games.jsonl"
CONTEXTS_V3 = ROOT / "ml" / "data" / "contexts_v3.jsonl"
STATCAST_RICH = ROOT / "ml" / "data" / "statcast_rich_games.jsonl"
STATCAST_RICH_DAYS = ROOT / "ml" / "data" / "statcast_rich_days.txt"
ARTIFACTS = ROOT / "ml" / "artifacts"
REPORT = ARTIFACTS / "report.json"
MODEL = ARTIFACTS / "moneyline.joblib"
TOTALS_REPORT = ARTIFACTS / "totals_report.json"
TOTALS_MODEL = ARTIFACTS / "totals.joblib"
PLAYER_PROPS_REPORT = ARTIFACTS / "player_props_report.json"
PLAYER_PROPS_MODEL = ARTIFACTS / "player_props.joblib"
DEPLOYMENT_SELECTION_AUDIT = ARTIFACTS / "deployment_selection_audit.json"
PROJECTION_SNAPSHOTS = ROOT / "ml" / "data" / "projection_snapshots.jsonl"
PLAYER_PROP_AUDIT = ARTIFACTS / "live_player_prop_audit.json"
PLAYER_PROP_BUILD_AUDIT = ARTIFACTS / "live_player_prop_build_audit.json"
PLAYER_PROP_PRICED_BOARD_AUDIT = ARTIFACTS / "player_prop_priced_board_audit.json"
PLAYER_PROP_SNAPSHOTS = ROOT / "ml" / "data" / "player_prop_projection_snapshots.jsonl"
PLAYER_PROP_BUILD_SNAPSHOTS = ROOT / "ml" / "data" / "player_prop_build_snapshots.jsonl"
PLAYER_PROP_PRICED_BOARD_SNAPSHOTS = ROOT / "ml" / "data" / "player_prop_priced_board_snapshots.jsonl"
PLAYER_BOXSCORES = ROOT / "ml" / "data" / "player_boxscores.jsonl"
STATE = ARTIFACTS / "maintenance_state.json"
LOCK = ARTIFACTS / ".maintenance.lock"
CANDIDATE = ARTIFACTS / "candidate"
MULTISPORT_ARTIFACTS = ARTIFACTS / "multisport"


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
        "walk_forward_brier": metric(candidate, "walk_forward", "brier_score", 1) <= metric(incumbent, "walk_forward", "brier_score", 1),
        "recent_accuracy_stability": metric(candidate, "recent_outer", "accuracy") >= metric(incumbent, "recent_outer", "accuracy") - 0.005,
        "recent_brier_stability": metric(candidate, "recent_outer", "brier_score", 1) <= metric(incumbent, "recent_outer", "brier_score", 1) + 0.00025,
    }


def totals_promotion_checks(candidate, incumbent):
    candidate_brier = metric(candidate, "unseen_2025_2026", "mean_brier", 1)
    incumbent_brier = metric(incumbent, "unseen_2025_2026", "mean_brier", 1)
    return {
        "new_completed_games": int(candidate.get("training_games", 0)) > int(incumbent.get("training_games", 0)),
        "positive_unseen_brier_skill": (
            float(candidate.get("unseen_brier_skill") or 0) > 0
            or bool((candidate.get("promotion_gate") or {}).get("passed"))
        ),
        "unseen_brier_improvement": candidate_brier <= incumbent_brier,
        "selected_line_brier": metric(candidate, "unseen_recommended", "brier_score", 1) <= metric(incumbent, "unseen_recommended", "brier_score", 1),
    }


def player_prop_summary(report):
    rows = list((report.get("models") or {}).values())
    weights = [int((row.get("samples") or {}).get("untouched_2025_2026", 0)) for row in rows]
    total = sum(weights)
    if not rows or not total:
        return {"brier": 1.0, "climatology_brier": 1.0, "accuracy": 0.0}
    weighted = lambda key, section=None: sum(  # noqa: E731 - compact weighted report reducer
        weight * float(((row.get(section) or {}).get(key, 0) if section else row.get(key, 0)) or 0)
        for row, weight in zip(rows, weights)
    ) / total
    return {
        "brier": weighted("brier", "unseen"),
        "climatology_brier": weighted("brier", "climatology"),
        "accuracy": weighted("side_accuracy"),
    }


def player_prop_promotion_checks(candidate, incumbent):
    candidate_summary = player_prop_summary(candidate)
    incumbent_summary = player_prop_summary(incumbent)
    candidate_rows = candidate.get("models") or {}
    incumbent_rows = incumbent.get("models") or {}
    shared = set(candidate_rows) & set(incumbent_rows)
    worst_regression = max((
        float(candidate_rows[key]["unseen"]["brier"]) - float(incumbent_rows[key]["unseen"]["brier"])
        for key in shared
    ), default=1.0)
    season_regressions = []
    for key in shared:
        candidate_seasons = (
            candidate_rows[key].get("unseen_by_season")
            or candidate_rows[key].get("guarded_temporal_audit")
            or {}
        )
        incumbent_seasons = (
            incumbent_rows[key].get("unseen_by_season")
            or incumbent_rows[key].get("guarded_temporal_audit")
            or {}
        )
        for season in set(candidate_seasons) & set(incumbent_seasons):
            season_regressions.append(
                float(candidate_seasons[season]["brier"])
                - float(incumbent_seasons[season]["brier"])
            )
    return {
        "new_completed_games": int((candidate.get("data") or {}).get("games", 0)) > int((incumbent.get("data") or {}).get("games", 0)),
        "all_prop_models_present": set(incumbent_rows).issubset(candidate_rows),
        "clustered_uncertainty_present": bool(candidate_rows) and all(
            (
                row.get("clustered_brier_skill")
                or row.get("challenger_clustered_brier_skill")
                or {}
            ).get("games", 0) > 0
            for row in candidate_rows.values()
        ),
        "positive_aggregate_brier_skill": candidate_summary["brier"] < candidate_summary["climatology_brier"],
        "unseen_brier_improvement": candidate_summary["brier"] <= incumbent_summary["brier"],
        "side_accuracy_stability": candidate_summary["accuracy"] >= incumbent_summary["accuracy"] - .002,
        "worst_prop_brier_regression": worst_regression <= .00001,
        "worst_prop_season_brier_regression": (
            max(season_regressions, default=0.0) <= .00001
        ),
    }


def run(command, env=None, timeout=3600):
    result = subprocess.run(command, cwd=ROOT, env=env, text=True, capture_output=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError((result.stderr or result.stdout or "maintenance command failed")[-2000:])
    return result.stdout


def refresh_open_multisport_models():
    """Refresh no-cost research ledgers without affecting production MLB."""
    now = datetime.now(timezone.utc)
    end_season = now.year if now.month >= 7 else now.year - 1
    data_dir = ROOT / "ml" / "data" / "multisport" / "football"
    artifact_dir = MULTISPORT_ARTIFACTS / "football"
    run([
        sys.executable, "-m", "ml.multisport.collect_football_open",
        "--start-season", "2020", "--end-season", str(end_season),
        "--output-dir", str(data_dir),
    ])
    artifact_dir.mkdir(parents=True, exist_ok=True)
    refreshed = {}
    for market in ("home_win", "over_2_5", "both_teams_score"):
        target = artifact_dir / f"{market}.json"
        run([
            sys.executable, "-m", "ml.multisport.train", str(data_dir / f"{market}.jsonl"),
            "--sport", "football", "--market", market, "--output", str(target),
        ])
        report = read_json(target, {})
        refreshed[market] = {
            "samples": (report.get("samples") or {}).get("all", 0),
            "brier": (report.get("untouched_candidate") or {}).get("brier"),
            "status": report.get("status"),
        }
    prediction_output = data_dir / "predictions.json"
    run([
        sys.executable, "-m", "ml.multisport.predict_football_open",
        "--raw", str(data_dir / "raw_matches.jsonl"),
        "--artifact-dir", str(artifact_dir), "--output", str(prediction_output),
    ])
    prediction_report = read_json(prediction_output, {})
    result = {"source": "keyless/no-cost", "football": refreshed, "shadow_predictions": prediction_report.get("count", 0)}
    collectors = {
        "american-football": ([sys.executable, "-m", "ml.multisport.collect_nfl_open", "--start-season", "2010", "--output-dir", str(ROOT / "ml" / "data" / "multisport" / "american-football")], ("home_win",)),
        "basketball": ([sys.executable, "-m", "ml.multisport.collect_nba_open", "--start-season", "2019", "--end-season", str(now.year), "--output-dir", str(ROOT / "ml" / "data" / "multisport" / "basketball")], ("home_win", "over_228_5")),
    }
    for sport, (command, markets) in collectors.items():
        run(command)
        sport_data = ROOT / "ml" / "data" / "multisport" / sport
        sport_artifacts = MULTISPORT_ARTIFACTS / sport
        sport_artifacts.mkdir(parents=True, exist_ok=True)
        result[sport] = {}
        for market in markets:
            target = sport_artifacts / f"{market}.json"
            run([sys.executable, "-m", "ml.multisport.train", str(sport_data / f"{market}.jsonl"), "--sport", sport, "--market", market, "--output", str(target)])
            report = read_json(target, {})
            result[sport][market] = {"samples": (report.get("samples") or {}).get("all", 0), "brier": (report.get("untouched_candidate") or {}).get("brier"), "status": report.get("status")}
        if sport == "american-football":
            score_report = sport_artifacts / "score.json"
            run([
                sys.executable, "-m", "ml.multisport.train_nfl_scores",
                str(sport_data / "score.jsonl"), "--output", str(score_report),
            ])
            score = read_json(score_report, {})
            result[sport]["score"] = {
                "samples": (score.get("samples") or {}).get("all", 0),
                "total_brier": ((score.get("line_aware_audit") or {}).get("total") or {}).get("brier"),
                "spread_brier": ((score.get("line_aware_audit") or {}).get("spread") or {}).get("brier"),
                "status": score.get("status"),
            }
            prediction_output = sport_data / "predictions.json"
            run([
                sys.executable, "-m", "ml.multisport.predict_nfl_open",
                "--artifact-dir", str(sport_artifacts), "--output", str(prediction_output),
            ])
            result[sport]["shadow_predictions"] = read_json(prediction_output, {}).get("count", 0)
    return result


def atomic_promote(source, target):
    """Copy a validated candidate into production without a partial write."""
    temporary = target.with_suffix(target.suffix + ".promoting")
    shutil.copy2(source, temporary)
    os.replace(temporary, target)


def promote_available_candidates(candidate_dir=CANDIDATE):
    """Promote every independently passing staged model.

    A slow or failed player-prop training job must not prevent a separately
    validated moneyline or totals artifact from reaching production.
    Candidates are copied rather than consumed so an interrupted maintenance
    cycle remains inspectable and resumable.
    """
    result = {"promoted_models": [], "promotion_checks": {}}
    candidates = (
        (
            "moneyline", candidate_dir / "report.json", candidate_dir / "moneyline.joblib",
            REPORT, MODEL, promotion_checks,
        ),
        (
            "totals", candidate_dir / "totals_report.json", candidate_dir / "totals.joblib",
            TOTALS_REPORT, TOTALS_MODEL, totals_promotion_checks,
        ),
        (
            "player_props", candidate_dir / "player_props_report.json", candidate_dir / "player_props.joblib",
            PLAYER_PROPS_REPORT, PLAYER_PROPS_MODEL, player_prop_promotion_checks,
        ),
    )
    for name, candidate_report_path, candidate_model_path, report_path, model_path, checker in candidates:
        if not candidate_report_path.exists() or not candidate_model_path.exists():
            result["promotion_checks"][name] = {"candidate_complete": False}
            continue
        candidate_report = read_json(candidate_report_path, {})
        incumbent_report = read_json(report_path, {})
        checks = checker(candidate_report, incumbent_report)
        checks["candidate_complete"] = True
        result["promotion_checks"][name] = checks
        if all(checks.values()):
            atomic_promote(candidate_model_path, model_path)
            atomic_promote(candidate_report_path, report_path)
            result["promoted_models"].append(name)
    return result


def refresh_production_slip_calibration():
    """Regenerate card calibration only from the models actually deployed."""
    run([sys.executable, "-m", "ml.calibrate_market_slips"])


def artifact_stale(output, *inputs):
    if not output.exists():
        return True
    return any(path.exists() and path.stat().st_mtime > output.stat().st_mtime for path in inputs)


def refresh_player_prop_audit(force=False):
    stale = force or artifact_stale(
        PLAYER_PROP_AUDIT,
        PLAYER_PROP_SNAPSHOTS,
        PLAYER_BOXSCORES,
    )
    if stale:
        run([sys.executable, "-m", "ml.evaluate_live_prop_snapshots"])
    build_stale = force or artifact_stale(
        PLAYER_PROP_BUILD_AUDIT,
        PLAYER_PROP_BUILD_SNAPSHOTS,
        PLAYER_BOXSCORES,
    )
    if build_stale:
        run([sys.executable, "-m", "ml.evaluate_player_prop_builds"])
    priced_stale = force or artifact_stale(
        PLAYER_PROP_PRICED_BOARD_AUDIT,
        PLAYER_PROP_PRICED_BOARD_SNAPSHOTS,
        PLAYER_BOXSCORES,
    )
    if priced_stale:
        run([sys.executable, "-m", "ml.evaluate_player_prop_priced_board"])
    return stale or build_stale or priced_stale


def maintenance_day(now=None):
    """Return the MLB-results day after a configurable UTC morning cutoff.

    The server runs in Ethiopia, where local midnight arrives while many west
    coast MLB games are still active. Delaying the day boundary prevents an
    incomplete overnight run from marking the new results day as synchronized.
    """
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    cutoff_hour = min(23, max(0, int(os.getenv("NINTH_MAINTENANCE_ROLLOVER_UTC_HOUR", "9"))))
    return (current.astimezone(timezone.utc) - timedelta(hours=cutoff_hour)).date().isoformat()


def maintain(force=False, dry_run=False):
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    state = read_json(STATE, {})
    today = maintenance_day()
    if dry_run:
        return {"status": "dry_run", "would_sync_season": date.today().year}

    # Outcome settlement is a lightweight daily policy dependency, not a model
    # retraining dependency. Run it before the same-day maintenance shortcut so
    # yesterday's exact Build Best results cannot leave today's policy stale.
    policy_refresh = json.loads(run([
        sys.executable, "-m", "ml.refresh_player_prop_policy",
    ]).strip() or "{}")
    if not force and state.get("last_sync_date") == today:
        deployment_audit_stale = artifact_stale(
            DEPLOYMENT_SELECTION_AUDIT,
            PROJECTION_SNAPSHOTS,
        )
        if deployment_audit_stale:
            run([sys.executable, "-m", "ml.evaluate_deployment_selection"])
        player_prop_audit_refreshed = refresh_player_prop_audit()
        return {
            "status": "already_checked",
            "last_sync_date": today,
            "deployment_audit_refreshed": deployment_audit_stale,
            "player_prop_audit_refreshed": player_prop_audit_refreshed,
            "player_prop_policy_refresh": policy_refresh,
        }

    run([sys.executable, "ml/collect.py", "--start-season", str(date.today().year), "--end-season", str(date.today().year)])
    run([
        sys.executable, "ml/enrich.py", "--start-season", str(date.today().year),
        "--end-season", str(date.today().year), "--workers",
        os.getenv("NINTH_ENRICH_WORKERS", "6"), "--output", str(CONTEXTS_V3),
    ])
    # Keep the point-in-time Statcast source used by all three deployed models
    # current. The resumable day manifest makes this a small incremental sync.
    run([
        sys.executable, "ml/statcast_collect.py",
        "--start", f"{date.today().year}-01-01",
        "--end", (date.today() - timedelta(days=1)).isoformat(),
        "--workers", os.getenv("NINTH_STATCAST_WORKERS", "3"),
        "--output", str(STATCAST_RICH), "--manifest", str(STATCAST_RICH_DAYS),
    ])
    run([sys.executable, "ml/collect_player_boxscores.py", "--start-season", str(date.today().year), "--workers", os.getenv("NINTH_PLAYER_PROP_WORKERS", "12")])
    player_prop_audit_refreshed = refresh_player_prop_audit(force=True)
    run([sys.executable, "-m", "ml.evaluate_deployment_selection"])
    try:
        open_multisport_refresh = refresh_open_multisport_models()
    except Exception as exc:  # an open-source outage must not block MLB maintenance
        open_multisport_refresh = {"status": "refresh_failed", "error": str(exc)[-2000:]}
    incumbent = read_json(REPORT, {})
    rows = game_rows()
    trained_through = incumbent.get("trained_through_date", "1900-01-01")
    new_games = sum(row.get("date", "") > trained_through for row in rows)
    last_promotion = state.get("last_promotion_at") or datetime.fromtimestamp(MODEL.stat().st_mtime, timezone.utc).isoformat()
    days_since_promotion = (datetime.now(timezone.utc) - datetime.fromisoformat(last_promotion.replace("Z", "+00:00"))).days
    should_train = new_games >= int(os.getenv("NINTH_RETRAIN_GAME_THRESHOLD", "100")) or (new_games > 0 and days_since_promotion >= int(os.getenv("NINTH_RETRAIN_DAYS", "7")))
    result = {
        "status": "synced",
        "completed_games_after_model": new_games,
        "retrain_due": should_train,
        "player_prop_audit_refreshed": player_prop_audit_refreshed,
        "player_prop_policy_refresh": policy_refresh,
        "open_multisport_refresh": open_multisport_refresh,
    }

    if should_train:
        CANDIDATE.mkdir(parents=True, exist_ok=True)
        env = os.environ.copy(); env["NINTH_ARTIFACT_DIR"] = str(CANDIDATE)
        training_errors = {}
        training_steps = (
            ("moneyline", [
                [sys.executable, "-m", "ml.train_v3"],
            ], (CANDIDATE / "report.json", CANDIDATE / "moneyline.joblib")),
            ("totals", [
                [sys.executable, "-m", "ml.research_pitching_availability_v1"],
                [sys.executable, "-m", "ml.train_totals_v5"],
            ], (CANDIDATE / "totals_report.json", CANDIDATE / "totals.joblib")),
        )
        for name, commands, outputs in training_steps:
            for output in outputs:
                output.unlink(missing_ok=True)
            try:
                for command in commands:
                    run(command, env=env)
            except Exception as exc:  # keep other independently gated models moving
                training_errors[name] = str(exc)[-2000:]
        try:
            raw_props = CANDIDATE / "player_props_full"
            raw_props.mkdir(parents=True, exist_ok=True)
            for output in (
                raw_props / "player_props_report.json",
                raw_props / "player_props.joblib",
                CANDIDATE / "player_props_report.json",
                CANDIDATE / "player_props.joblib",
            ):
                output.unlink(missing_ok=True)
            prop_env = env.copy()
            prop_env["NINTH_ARTIFACT_DIR"] = str(raw_props)
            prop_env.setdefault("NINTH_PROP_COUNT_HEADS", "batter:hits_runs_rbi")
            run([sys.executable, "-m", "ml.train_player_props"], env=prop_env)
            comparison = CANDIDATE / "player_props_comparison.json"
            run([
                sys.executable, "-m", "ml.evaluate_observed_prop_lines",
                str(PLAYER_PROPS_MODEL), str(raw_props / "player_props.joblib"),
                "--output", str(comparison),
            ])
            run([
                sys.executable, "-m", "ml.build_player_props_hybrid",
                "--incumbent-artifact", str(PLAYER_PROPS_MODEL),
                "--incumbent-report", str(PLAYER_PROPS_REPORT),
                "--candidate-artifact", str(raw_props / "player_props.joblib"),
                "--candidate-report", str(raw_props / "player_props_report.json"),
                "--audit", str(comparison),
                "--output-dir", str(CANDIDATE),
            ])
        except Exception as exc:
            training_errors["player_props"] = str(exc)[-2000:]
        promotion = promote_available_candidates()
        promoted = promotion["promoted_models"]
        result["promotion_checks"] = promotion["promotion_checks"]
        result["training_errors"] = training_errors
        result["promoted_models"] = promoted
        if promoted:
            state["last_promotion_at"] = datetime.now(timezone.utc).isoformat()
            if any(name in promoted for name in ("moneyline", "totals")):
                try:
                    refresh_production_slip_calibration()
                except Exception as exc:
                    training_errors["slip_calibration"] = str(exc)[-2000:]
            result["status"] = "partially_promoted" if training_errors else "promoted"
        elif training_errors:
            result["status"] = "training_failed"
        else:
            result["status"] = "candidates_rejected"

    state.update({"last_sync_date": today, "last_run_at": datetime.now(timezone.utc).isoformat(), "last_result": result})
    write_json(STATE, state)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--promote-candidates", action="store_true")
    args = parser.parse_args()
    try:
        fd = os.open(LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        print(json.dumps({"status": "maintenance_already_running"}))
        return
    try:
        os.close(fd)
        if args.promote_candidates:
            result = promote_available_candidates()
            if any(name in result["promoted_models"] for name in ("moneyline", "totals")):
                refresh_production_slip_calibration()
            state = read_json(STATE, {})
            state.update({
                "last_run_at": datetime.now(timezone.utc).isoformat(),
                "last_result": {"status": "candidate_promotion", **result},
            })
            if result["promoted_models"]:
                state["last_promotion_at"] = datetime.now(timezone.utc).isoformat()
            write_json(STATE, state)
            print(json.dumps(result))
        else:
            print(json.dumps(maintain(force=args.force, dry_run=args.dry_run)))
    finally:
        LOCK.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
