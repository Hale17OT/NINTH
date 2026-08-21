"""Generate keyless NFL forecasts from nflverse schedules."""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import joblib
import numpy as np

from .collect_nfl_open import State, advanced_summaries, avg, fetch
from .evaluation import no_vig_probabilities
from .train_nfl_scores import probability_above

NFL_TIMEZONE = ZoneInfo("America/New_York")


def artifact_version(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:12]


def _number(value, default: float) -> float:
    try:
        return float(value) if value not in (None, "") else default
    except (TypeError, ValueError):
        return default


def _at(row: dict) -> datetime:
    value = f"{row['gameday']}T{row.get('gametime') or '12:00'}:00"
    return datetime.fromisoformat(value).replace(tzinfo=NFL_TIMEZONE).astimezone(timezone.utc)


def feature_row(row: dict, home: State, away: State) -> dict[str, float]:
    return {
        "home_elo": home.elo, "away_elo": away.elo, "elo_difference": home.elo - away.elo,
        "home_scored_5": avg(list(home.scored)[-5:], 22.5), "away_scored_5": avg(list(away.scored)[-5:], 22.5),
        "home_allowed_5": avg(list(home.allowed)[-5:], 22.5), "away_allowed_5": avg(list(away.allowed)[-5:], 22.5),
        "home_win_rate_10": avg(home.wins, .5), "away_win_rate_10": avg(away.wins, .5),
        "home_rest": _number(row.get("home_rest"), 7), "away_rest": _number(row.get("away_rest"), 7),
        "temperature": _number(row.get("temp"), 65), "wind": _number(row.get("wind"), 5),
        "divisional": _number(row.get("div_game"), 0), "outdoors": float(row.get("roof") == "outdoors"),
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


def model_probability(bundle: dict, features: dict) -> float:
    matrix = np.asarray([[features.get(name, np.nan) for name in bundle["features"]]], dtype=float)
    raw = float(bundle["model"].predict_proba(matrix)[0][1])
    return float(bundle["calibrator"].predict([raw])[0])


def score_projection(bundle: dict, features: dict, total_line: float | None, spread_line: float | None, home_team_total: float | None = None, away_team_total: float | None = None) -> dict:
    matrix = np.asarray([[features.get(name, np.nan) for name in bundle["features"]]], dtype=float)
    expected_total = float(bundle["models"]["total_points"].predict(matrix)[0])
    expected_margin = float(bundle["models"]["home_margin"].predict(matrix)[0])
    total_residuals = np.asarray(bundle["residuals"]["total_points"], dtype=float)
    margin_residuals = np.asarray(bundle["residuals"]["home_margin"], dtype=float)
    home_residuals = (total_residuals + margin_residuals) / 2
    away_residuals = (total_residuals - margin_residuals) / 2
    expected_home = max(0.0, (expected_total + expected_margin) / 2)
    expected_away = max(0.0, (expected_total - expected_margin) / 2)
    return {
        "expected_total": expected_total,
        "expected_margin": expected_margin,
        "expected_home_score": expected_home,
        "expected_away_score": expected_away,
        "team_score_distribution": {
            "home": {"mean":expected_home, "standard_deviation":float(np.std(home_residuals)), "p10":max(0.0,expected_home+float(np.quantile(home_residuals,.1))), "p90":max(0.0,expected_home+float(np.quantile(home_residuals,.9)))},
            "away": {"mean":expected_away, "standard_deviation":float(np.std(away_residuals)), "p10":max(0.0,expected_away+float(np.quantile(away_residuals,.1))), "p90":max(0.0,expected_away+float(np.quantile(away_residuals,.9)))},
        },
        "score_home_win": probability_above(expected_margin, 0, margin_residuals),
        "over_total": None if total_line is None else probability_above(expected_total, total_line, total_residuals),
        "home_spread": None if spread_line is None else probability_above(expected_margin, spread_line, margin_residuals),
        "home_team_over": None if home_team_total is None else probability_above(expected_home, home_team_total, home_residuals),
        "away_team_over": None if away_team_total is None else probability_above(expected_away, away_team_total, away_residuals),
    }


def american_to_decimal(value) -> float | None:
    price = _number(value, 0)
    if price == 0:
        return None
    return round(1 + (price / 100 if price > 0 else 100 / abs(price)), 3)


def _read_report(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def model_readiness(artifact_dir: Path, live_audit: dict | None = None) -> dict:
    live_audit = live_audit or {}
    final_report = _read_report(artifact_dir.parent / "football_nfl_model_report.json")
    decisions = {
        market: next((row.get("decision") for row in final_report.get("models", []) if row.get("sport") == "american-football" and row.get("model_family") == "score" and row.get("market") == market), "UNAVAILABLE")
        for market in ("moneyline", "spread", "total")
    }
    historical = {market: decision == "USE" for market, decision in decisions.items()}
    live = live_audit.get("markets") or {}
    eligible = {
        market: bool(historical[market] and (live.get(market) or {}).get("passed"))
        for market in historical
    }
    return {"historical": historical, "evaluated_decision":decisions, "live": live, "automatic_builder_eligible": eligible}


def refresh_live_audit(rows: list[dict], ledger_path: Path, predictions: list[dict] | None = None) -> dict:
    entries = {}
    if ledger_path.exists():
        for raw in ledger_path.read_text(encoding="utf-8").splitlines():
            try:
                entry = json.loads(raw)
                entries[str(entry["event_id"])] = entry
            except (json.JSONDecodeError, KeyError):
                continue
    completed = {str(row.get("game_id")): row for row in rows if row.get("home_score") not in (None, "") and row.get("away_score") not in (None, "")}
    for event_id, entry in entries.items():
        row = completed.get(event_id)
        if not row or entry.get("result"):
            continue
        home_score, away_score = int(float(row["home_score"])), int(float(row["away_score"]))
        entry["result"] = {"home_score": home_score, "away_score": away_score, "total": home_score + away_score, "home_margin": home_score - away_score}
        entry["settled_at"] = datetime.now(timezone.utc).isoformat()
    for prediction in predictions or []:
        kickoff = datetime.fromisoformat(str(prediction["event_time"]).replace("Z", "+00:00"))
        current = datetime.now(timezone.utc)
        if kickoff <= current or kickoff - current > timedelta(hours=48):
            continue
        entries.setdefault(str(prediction["event_id"]), {
            "event_id": prediction["event_id"], "event_time": prediction["event_time"],
            "generated_at": prediction["generated_at"], "home_team": prediction["home_team"], "away_team": prediction["away_team"],
            "markets": prediction["markets"], "total_line": prediction.get("total_line"), "spread_line": prediction.get("spread_line"),
            "model_versions": prediction.get("model_versions"), "feature_version": prediction.get("feature_version"),
        })
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    ledger_path.write_text("\n".join(json.dumps(entry, separators=(",", ":")) for entry in sorted(entries.values(), key=lambda value: value["event_time"])) + ("\n" if entries else ""), encoding="utf-8")
    scored = {market: [] for market in ("moneyline", "spread", "total")}
    for entry in entries.values():
        result = entry.get("result")
        if not result:
            continue
        scored["moneyline"].append((float(entry["markets"]["home_win"]), int(result["home_margin"] > 0)))
        if entry.get("spread_line") is not None and result["home_margin"] != float(entry["spread_line"]):
            scored["spread"].append((float(entry["markets"]["home_spread"]), int(result["home_margin"] > float(entry["spread_line"]))))
        if entry.get("total_line") is not None and result["total"] != float(entry["total_line"]):
            scored["total"].append((float(entry["markets"]["over_total"]), int(result["total"] > float(entry["total_line"]))))
    markets = {}
    for market, values in scored.items():
        brier = sum((probability - actual) ** 2 for probability, actual in values) / len(values) if values else None
        markets[market] = {
            "samples": len(values), "brier": brier,
            "passed": bool(len(values) >= 30 and brier is not None and brier < .25),
        }
    return {
        "archived": len(entries), "settled": sum(bool(entry.get("result")) for entry in entries.values()),
        "snapshot_rule": "first generated forecast within 48 hours of kickoff", "markets": markets,
    }


def _update_advanced(state: State, own: dict | None, opponent: dict | None) -> None:
    if own:
        state.offensive_epa.append(own["epa_per_play"]); state.success_rate.append(own["success_rate"])
        state.explosive_rate.append(own["explosive_rate"]); state.sack_rate.append(own["sack_rate"])
        state.pressure_allowed.append(own["pressure_rate"]); state.turnover_rate.append(own["turnover_rate"])
        state.third_down_rate.append(own["third_down_rate"]); state.drive_score_rate.append(own["drive_score_rate"])
        state.pass_over_expected.append(own["pass_over_expected"])
    if opponent:
        state.defensive_epa.append(opponent["epa_per_play"]); state.success_allowed.append(opponent["success_rate"])
        state.explosive_allowed.append(opponent["explosive_rate"])


def forecast(rows: list[dict], artifact_dir: Path, now: datetime, advanced: dict | None = None, live_audit: dict | None = None) -> dict:
    advanced = advanced or {}
    states = defaultdict(State)
    home_bundle = joblib.load(artifact_dir / "home_win.joblib")
    score_bundle = joblib.load(artifact_dir / "score.joblib")
    model_versions = {
        "moneyline_classifier": artifact_version(artifact_dir / "home_win.joblib"),
        "score_distribution": artifact_version(artifact_dir / "score.joblib"),
    }
    readiness = model_readiness(artifact_dir, live_audit)
    ordered = sorted((row for row in rows if row.get("gameday") and row.get("home_team") and row.get("away_team")), key=lambda row: (_at(row), row.get("game_id", "")))
    upcoming = []
    for row in ordered:
        at = _at(row); home, away = states[row["home_team"]], states[row["away_team"]]
        completed = row.get("home_score") not in (None, "") and row.get("away_score") not in (None, "")
        if completed and at < now:
            home_score, away_score = int(float(row["home_score"])), int(float(row["away_score"]))
            expected = 1 / (1 + 10 ** (-(home.elo + 50 - away.elo) / 400))
            result = 1 if home_score > away_score else .5 if home_score == away_score else 0
            delta = 24 * (result - expected); home.elo += delta; away.elo -= delta
            for state, scored, allowed, win in ((home, home_score, away_score, result), (away, away_score, home_score, 1 - result)):
                state.scored.append(scored); state.allowed.append(allowed); state.wins.append(win)
            home_advanced = advanced.get((row["game_id"], row["home_team"]))
            away_advanced = advanced.get((row["game_id"], row["away_team"]))
            _update_advanced(home, home_advanced, away_advanced); _update_advanced(away, away_advanced, home_advanced)
            continue
        if at < now or len(upcoming) >= 32:
            continue
        features = feature_row(row, home, away)
        raw_home_win = model_probability(home_bundle, features)
        # Pregame injuries and confirmed participants are not yet point-in-time inputs.
        # Keep the open baseline conservative and shrink current probabilities accordingly.
        home_win = .5 + .65 * (raw_home_win - .5)
        total_line = _number(row.get("total_line"), 0) or None
        spread_line = _number(row.get("spread_line"), 0)
        spread_line = spread_line if row.get("spread_line") not in (None, "") else None
        home_team_total = _number(row.get("home_team_total"), 0) or None
        away_team_total = _number(row.get("away_team_total"), 0) or None
        score = score_projection(score_bundle, features, total_line, spread_line, home_team_total, away_team_total)
        score_agreement = (home_win >= .5) == (score["score_home_win"] >= .5)
        if not score_agreement:
            home_win = .5 + .35 * (home_win - .5)
        total_over = score["over_total"]
        home_spread = score["home_spread"]
        prices = {
            "home_moneyline": american_to_decimal(row.get("home_moneyline")), "away_moneyline": american_to_decimal(row.get("away_moneyline")),
            "over_total": american_to_decimal(row.get("over_odds")), "under_total": american_to_decimal(row.get("under_odds")),
            "home_spread": american_to_decimal(row.get("home_spread_odds")), "away_spread": american_to_decimal(row.get("away_spread_odds")),
        }
        moneyline_no_vig = no_vig_probabilities(prices["home_moneyline"], prices["away_moneyline"])
        total_no_vig = no_vig_probabilities(prices["over_total"], prices["under_total"])
        spread_no_vig = no_vig_probabilities(prices["home_spread"], prices["away_spread"])
        eligible = readiness["automatic_builder_eligible"]
        upcoming.append({
            "event_id": row["game_id"], "event_time": at.isoformat(), "home_team": row["home_team"], "away_team": row["away_team"],
            "markets": {
                "home_win": home_win, "away_win": 1 - home_win,
                "over_total": total_over, "under_total": None if total_over is None else 1 - total_over,
                "home_spread": home_spread, "away_spread": None if home_spread is None else 1 - home_spread,
                "home_team_over": score["home_team_over"], "home_team_under": None if score["home_team_over"] is None else 1-score["home_team_over"],
                "away_team_over": score["away_team_over"], "away_team_under": None if score["away_team_over"] is None else 1-score["away_team_over"],
            },
            "expected_score": {"home": round(score["expected_home_score"], 1), "away": round(score["expected_away_score"], 1), "total": round(score["expected_total"], 1), "home_margin": round(score["expected_margin"], 1)},
            "team_score_distribution":score["team_score_distribution"],
            "total_line": total_line, "spread_line": spread_line, "home_team_total_line":home_team_total, "away_team_total_line":away_team_total,
            "prices": prices,
            "fair_odds": {
                "home_moneyline": round(1 / home_win, 3), "away_moneyline": round(1 / (1 - home_win), 3),
                "over_total": None if total_over is None else round(1 / total_over, 3),
                "under_total": None if total_over is None else round(1 / (1 - total_over), 3),
                "home_spread": None if home_spread is None else round(1 / home_spread, 3),
                "away_spread": None if home_spread is None else round(1 / (1 - home_spread), 3),
            },
            "no_vig_market_probability": {
                "home_moneyline": moneyline_no_vig[0], "away_moneyline": moneyline_no_vig[1],
                "over_total": total_no_vig[0], "under_total": total_no_vig[1],
                "home_spread": spread_no_vig[0], "away_spread": spread_no_vig[1],
            },
            "edge": {
                "home_moneyline": None if moneyline_no_vig[0] is None else home_win - moneyline_no_vig[0],
                "away_moneyline": None if moneyline_no_vig[1] is None else (1 - home_win) - moneyline_no_vig[1],
                "over_total": None if total_over is None or total_no_vig[0] is None else total_over - total_no_vig[0],
                "under_total": None if total_over is None or total_no_vig[1] is None else (1 - total_over) - total_no_vig[1],
                "home_spread": None if home_spread is None or spread_no_vig[0] is None else home_spread - spread_no_vig[0],
                "away_spread": None if home_spread is None or spread_no_vig[1] is None else (1 - home_spread) - spread_no_vig[1],
            },
            "market_eligibility": eligible,
            "status": "builder_eligible" if any(eligible.values()) else "model_forecast", "builder_eligible": any(eligible.values()),
            "model_consensus": {"moneyline": score_agreement, "classifier_home_win": raw_home_win, "score_distribution_home_win": score["score_home_win"]},
            "model_versions": model_versions,
            "feature_version": hashlib.sha256("|".join(score_bundle["features"]).encode()).hexdigest()[:12],
            "readiness": readiness,
            "source": "nflverse open schedules", "uncertainty_adjustment": "35% shrink toward 0.50 until point-in-time availability is captured",
            "generated_at": datetime.now(timezone.utc).isoformat(),
        })
    return {"generated_at": datetime.now(timezone.utc).isoformat(), "count": len(upcoming), "readiness": readiness, "predictions": upcoming}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-dir", type=Path, default=Path("ml/artifacts/multisport/american-football"))
    parser.add_argument("--output", type=Path, default=Path("ml/data/multisport/american-football/predictions.json"))
    args = parser.parse_args()
    rows = fetch()
    ledger_path = args.output.parent / "live_prediction_audit.jsonl"
    live_audit = refresh_live_audit(rows, ledger_path)
    result = forecast(rows, args.artifact_dir, datetime.now(timezone.utc), advanced_summaries(2018, 2025, args.output.parent), live_audit)
    result["live_audit"] = refresh_live_audit(rows, ledger_path, result["predictions"])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({"status": "predictions_refreshed", "count": result["count"]}, indent=2))


if __name__ == "__main__":
    main()
