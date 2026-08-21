"""Generate free-source Football forecasts for current fixtures."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import time
import unicodedata
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import joblib
import numpy as np

from .collect_football_open import LEAGUES, TeamState, build_ledgers_and_states, load_statsbomb, parse_date, state_features
from .score_models import dixon_coles_matrix


SPORTS_DB = "https://www.thesportsdb.com/api/v1/json/123"
FPL_API = "https://fantasy.premierleague.com/api"
COMPETITIONS = {
    "4328": ("E0", "Premier League"), "4329": ("E1", "Championship"),
    "4335": ("SP1", "La Liga"), "4331": ("D1", "Bundesliga"),
    "4332": ("I1", "Serie A"), "4334": ("F1", "Ligue 1"), "4480": ("UCL", "UEFA Champions League"),
    "4481": ("UEL", "UEFA Europa League"), "5071": ("UECL", "UEFA Conference League"),
    "4482": ("FAC", "FA Cup"), "4570": ("EFL", "EFL Cup"), "4483": ("CDR", "Copa del Rey"),
    "4485": ("DFB", "DFB-Pokal"), "4506": ("CIT", "Coppa Italia"), "4484": ("CDF", "Coupe de France"),
}
ALIASES = {
    "manchester united": "man united", "manchester city": "man city", "paris saint germain": "paris sg",
    "internazionale": "inter", "inter milan": "inter", "athletic club": "ath bilbao", "spurs": "tottenham",
    "real betis": "betis", "real sociedad": "sociedad", "bayern munich": "bayern munich",
    "borussia monchengladbach": "mgladbach", "olympique lyonnais": "lyon", "olympique marseille": "marseille",
}


def normalized(value: str) -> str:
    plain = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode().lower()
    words = [word for word in "".join(character if character.isalnum() else " " for character in plain).split() if word not in {"fc", "cf", "afc", "calcio"}]
    result = " ".join(words)
    return ALIASES.get(result, result)


def read_json(url: str) -> dict:
    request = Request(url, headers={"User-Agent": "NINTH-Research/2.0", "Accept": "application/json"})
    with urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def _read_report(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def artifact_version(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:12]


def model_readiness(artifact_dir: Path, live_audit: dict | None = None) -> dict:
    live_audit = live_audit or {}
    final_report = _read_report(artifact_dir.parent / "football_nfl_model_report.json")
    decisions = {
        market: next((row.get("decision") for row in final_report.get("models", []) if row.get("sport") == "football" and row.get("model_family") == "score_distribution" and row.get("market") == market), "UNAVAILABLE")
        for market in ("home_win", "over_2_5", "both_teams_score")
    }
    historical = {market: decision == "USE" for market, decision in decisions.items()}
    live = live_audit.get("markets") or {}
    eligible = {
        market: bool(historical[market] and (live.get(market) or {}).get("passed"))
        for market in historical
    }
    return {"historical": historical, "evaluated_decision":decisions, "live": live, "automatic_builder_eligible": eligible}


def _fpl_events(now: datetime, horizon_days: int = 21) -> tuple[list[dict], dict[str, dict]]:
    """Return current Premier League fixtures plus completed-result lookup.

    FPL is already a configured keyless NINTH source. Using its canonical event
    IDs gives the live audit full Premier League coverage without a paid feed.
    """
    bootstrap = read_json(f"{FPL_API}/bootstrap-static/")
    fixtures = read_json(f"{FPL_API}/fixtures/")
    teams = {int(row["id"]): row.get("name") or row.get("short_name") for row in bootstrap.get("teams") or []}
    upcoming, results = [], {}
    limit = now + timedelta(days=horizon_days)
    for row in fixtures or []:
        kickoff_raw = row.get("kickoff_time")
        if not kickoff_raw:
            continue
        kickoff = datetime.fromisoformat(str(kickoff_raw).replace("Z", "+00:00"))
        event_id = f"fpl:{row['id']}"
        home, away = teams.get(int(row.get("team_h") or 0)), teams.get(int(row.get("team_a") or 0))
        if not home or not away:
            continue
        if row.get("finished") and row.get("team_h_score") is not None and row.get("team_a_score") is not None:
            results[event_id] = {
                "home_score": int(row["team_h_score"]), "away_score": int(row["team_a_score"]),
                "home_team": home, "away_team": away, "event_time": kickoff.isoformat(),
                "competition_code": "E0",
            }
        if now <= kickoff <= limit and not row.get("finished"):
            upcoming.append({
                "event_id": event_id, "competition_id": "4328", "competition_code": "E0",
                "competition": "Premier League", "event_time": kickoff.isoformat(),
                "home_team": home, "away_team": away,
            })
    return upcoming, results


def current_fixtures(now: datetime | None = None) -> tuple[list[dict], dict[str, dict]]:
    now = now or datetime.now(timezone.utc)
    fixtures = []
    results = {}
    try:
        fpl, results = _fpl_events(now)
        fixtures.extend(fpl)
    except Exception:
        pass
    for competition_id, (code, name) in COMPETITIONS.items():
        try:
            payload = read_json(f"{SPORTS_DB}/eventsnextleague.php?{urlencode({'id': competition_id})}")
        except Exception:
            time.sleep(.3)
            continue
        for event in payload.get("events") or []:
            candidate = {
                "event_id": str(event.get("idEvent")), "competition_id": competition_id,
                "competition_code": code, "competition": event.get("strLeague") or name,
                "event_time": event.get("strTimestamp") or f"{event.get('dateEvent')}T{event.get('strTime') or '12:00:00'}Z",
                "home_team": event.get("strHomeTeam"), "away_team": event.get("strAwayTeam"),
            }
            key = (candidate["event_time"][:10], normalized(candidate["home_team"]), normalized(candidate["away_team"]))
            existing = {(row["event_time"][:10], normalized(row["home_team"]), normalized(row["away_team"])) for row in fixtures}
            if key not in existing:
                fixtures.append(candidate)
        if code in LEAGUES:
            try:
                past = read_json(f"{SPORTS_DB}/eventspastleague.php?{urlencode({'id': competition_id})}")
            except Exception:
                past = {}
            for event in past.get("events") or []:
                if event.get("intHomeScore") is None or event.get("intAwayScore") is None:
                    continue
                event_id = str(event.get("idEvent"))
                results.setdefault(event_id, {
                    "home_score": int(event["intHomeScore"]), "away_score": int(event["intAwayScore"]),
                    "home_team": event.get("strHomeTeam"), "away_team": event.get("strAwayTeam"),
                    "event_time": event.get("strTimestamp") or f"{event.get('dateEvent')}T{event.get('strTime') or '12:00:00'}Z",
                    "competition_code": code,
                })
        time.sleep(.3)
    return fixtures, results


def resolve_state(states, team_name: str):
    target = normalized(team_name)
    exact = [state for (_, name), state in states.items() if normalized(name) == target]
    if exact:
        return max(exact, key=lambda state: state.last_played or datetime.min.replace(tzinfo=timezone.utc))
    ranked = sorted(((SequenceMatcher(None, target, normalized(name)).ratio(), state) for (_, name), state in states.items()), key=lambda item: item[0], reverse=True)
    return ranked[0][1] if ranked and ranked[0][0] >= .60 else None


def feature_row(home, away, at: datetime) -> dict[str, float | None]:
    return {
        **state_features(home, "home", at), **state_features(away, "away", at),
        "elo_difference": home.elo - away.elo,
        "league_home_goal_prior": 1.45, "league_away_goal_prior": 1.15,
    }


def model_probability(bundle: dict, features: dict) -> float:
    row = np.asarray([[features.get(name, np.nan) for name in bundle["features"]]], dtype=float)
    raw = float(bundle["model"].predict_proba(row)[0, 1])
    return float(bundle["calibrator"].predict([raw])[0])


def score_distribution(bundle: dict, features: dict) -> tuple[float, float, dict]:
    row = np.asarray([[features.get(name, np.nan) for name in bundle["features"]]], dtype=float)
    home_xg = max(.08, float(bundle["models"]["home_goals"].predict(row)[0]))
    away_xg = max(.08, float(bundle["models"]["away_goals"].predict(row)[0]))
    return home_xg, away_xg, dixon_coles_matrix(home_xg, away_xg)


def consistency_blend(trained: float | None, structural: float, trained_weight: float = .25) -> float:
    """Keep a discriminative candidate subordinate to the joint score model."""
    if trained is None or not math.isfinite(trained):
        return structural
    value = trained_weight * trained + (1 - trained_weight) * structural
    return min(.98, max(.02, value))


def refresh_live_audit(
    completed: dict[str, dict], ledger_path: Path, artifact_dir: Path,
    predictions: list[dict] | None = None, now: datetime | None = None,
) -> dict:
    """Settle immutable pregame predictions and evaluate each market separately."""
    now = now or datetime.now(timezone.utc)
    entries = {}
    if ledger_path.exists():
        for raw in ledger_path.read_text(encoding="utf-8").splitlines():
            try:
                entry = json.loads(raw)
                entries[str(entry["event_id"])] = entry
            except (json.JSONDecodeError, KeyError):
                continue
    for event_id, entry in entries.items():
        result = completed.get(event_id)
        if result and not entry.get("result"):
            entry["result"] = result
            entry["settled_at"] = now.isoformat()
    for prediction in predictions or []:
        kickoff = datetime.fromisoformat(str(prediction["event_time"]).replace("Z", "+00:00"))
        if kickoff.tzinfo is None:
            kickoff = kickoff.replace(tzinfo=timezone.utc)
        if kickoff <= now or kickoff - now > timedelta(days=14):
            continue
        if str(prediction["event_id"]) in entries:
            entries[str(prediction["event_id"])].setdefault("competition_code", prediction.get("competition_code"))
        entries.setdefault(str(prediction["event_id"]), {
            "event_id": prediction["event_id"], "event_time": prediction["event_time"],
            "generated_at": prediction["generated_at"], "competition": prediction.get("competition"),
            "competition_code": prediction.get("competition_code"),
            "home_team": prediction["home_team"], "away_team": prediction["away_team"],
            "markets": prediction["markets"], "model_version": prediction.get("model_version"),
            "feature_version": prediction.get("feature_version"),
        })
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    ledger_path.write_text(
        "\n".join(json.dumps(entry, separators=(",", ":")) for entry in sorted(entries.values(), key=lambda value: value["event_time"]))
        + ("\n" if entries else ""), encoding="utf-8",
    )
    scored = {market: [] for market in ("home_win", "over_2_5", "both_teams_score")}
    for entry in entries.values():
        if entry.get("competition_code") not in LEAGUES:
            continue
        result = entry.get("result")
        if not result:
            continue
        home_score, away_score = int(result["home_score"]), int(result["away_score"])
        actual = {
            "home_win": int(home_score > away_score),
            "over_2_5": int(home_score + away_score >= 3),
            "both_teams_score": int(home_score > 0 and away_score > 0),
        }
        for market in scored:
            probability = (entry.get("markets") or {}).get(market)
            if probability is not None:
                scored[market].append((float(probability), actual[market]))
    markets = {}
    for market, values in scored.items():
        report = _read_report(artifact_dir / f"{market}.json")
        baseline = float(
            (report.get("holdout_results", {}).get("combined", {}).get("baseline") or {}).get("brier")
            or (report.get("untouched_climatology") or {}).get("brier") or .25
        )
        brier = sum((probability - actual) ** 2 for probability, actual in values) / len(values) if values else None
        markets[market] = {
            "samples": len(values), "brier": brier, "baseline_brier": baseline,
            "passed": bool(len(values) >= 30 and brier is not None and brier < baseline),
        }
    return {
        "archived": len(entries), "settled": sum(bool(entry.get("result")) for entry in entries.values()),
        "snapshot_rule": "first generated forecast within fourteen days of kickoff",
        "markets": markets,
    }


def forecast(raw_path: Path, artifact_dir: Path, now: datetime | None = None, live_audit: dict | None = None) -> tuple[dict, dict[str, dict]]:
    now = now or datetime.now(timezone.utc)
    rows = [json.loads(line) for line in raw_path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    fixtures, completed = current_fixtures(now)
    existing = {(row.get("Date"), normalized(row.get("HomeTeam")), normalized(row.get("AwayTeam"))) for row in rows}
    for result in completed.values():
        kickoff = datetime.fromisoformat(str(result["event_time"]).replace("Z", "+00:00"))
        key = (kickoff.strftime("%d/%m/%Y"), normalized(result["home_team"]), normalized(result["away_team"]))
        if key in existing:
            continue
        rows.append({
            "Div": result.get("competition_code") or "E0", "Date": key[0], "Time": kickoff.strftime("%H:%M"),
            "HomeTeam": result["home_team"], "AwayTeam": result["away_team"],
            "FTHG": str(result["home_score"]), "FTAG": str(result["away_score"]),
        })
    _, states = build_ledgers_and_states(rows, load_statsbomb(raw_path.parent / "statsbomb_team_games.json"))
    bundles = {
        path.stem: joblib.load(path) for path in artifact_dir.glob("*.joblib")
        if path.stem in {"home_win", "over_2_5", "both_teams_score"}
    }
    score_bundle = joblib.load(artifact_dir / "score_distribution.joblib")
    score_version = artifact_version(artifact_dir / "score_distribution.joblib")
    readiness = model_readiness(artifact_dir, live_audit)
    predictions = []
    for fixture in fixtures:
        home, away = resolve_state(states, fixture["home_team"]), resolve_state(states, fixture["away_team"])
        if fixture["competition_code"] in LEAGUES:
            home, away = home or TeamState(), away or TeamState()
        if home is None or away is None:
            continue
        try:
            at = datetime.fromisoformat(fixture["event_time"].replace("Z", "+00:00"))
            if at.tzinfo is None:
                at = at.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            at = parse_date(fixture["event_time"][:10])
        features = feature_row(home, away, at)
        trained = {market: model_probability(bundle, features) for market, bundle in bundles.items()}
        home_xg, away_xg, score = score_distribution(score_bundle, features)
        home_probability, draw_probability, away_probability = score["home_win"], score["draw"], score["away_win"]
        likely_scores = sorted(score["matrix"].items(), key=lambda item: item[1], reverse=True)[:3]
        eligibility = readiness["automatic_builder_eligible"]
        audited_scope = fixture["competition_code"] in LEAGUES
        market_eligibility = {
            "home_win": audited_scope and eligibility["home_win"], "draw": False, "away_win": False,
            "over_2_5": audited_scope and eligibility["over_2_5"], "under_2_5": audited_scope and eligibility["over_2_5"],
            "both_teams_score": audited_scope and eligibility["both_teams_score"],
        }
        predictions.append({
            **fixture, "generated_at": datetime.now(timezone.utc).isoformat(),
            "expected_goals": {"home": home_xg, "away": away_xg, "total": home_xg + away_xg},
            "markets": {
                "home_win": home_probability, "draw": draw_probability, "away_win": away_probability,
                "over_2_5": score["over_2_5"], "under_2_5": score["under_2_5"],
                "both_teams_score": score["both_teams_score"],
            },
            "likely_scores": [{"score": value, "probability": probability} for value, probability in likely_scores],
            "market_eligibility": market_eligibility,
            "status": "builder_eligible" if any(market_eligibility.values()) else "model_forecast",
            "builder_eligible": any(market_eligibility.values()), "readiness": readiness,
            "model_consensus": {
                market: (trained.get(market, .5) >= .5) == (score[market] >= .5)
                for market in ("home_win", "over_2_5", "both_teams_score")
            },
            "model": "Coherent score distribution",
            "model_version": score_version,
            "feature_version": hashlib.sha256("|".join(score_bundle["features"]).encode()).hexdigest()[:12],
            "fair_odds": {
                "home_win": round(1 / home_probability, 3), "draw": round(1 / draw_probability, 3),
                "away_win": round(1 / away_probability, 3), "over_2_5": round(1 / score["over_2_5"], 3),
                "under_2_5": round(1 / score["under_2_5"], 3),
                "both_teams_score": round(1 / score["both_teams_score"], 3),
            },
            "market_analysis": {"state": "no_edge_data", "reason": "No current matched price snapshot is attached to this fixture."},
            "source": "Football-Data.co.uk + Fantasy Premier League + TheSportsDB public feeds",
        })
    return {"generated_at": now.isoformat(), "count": len(predictions), "readiness": readiness, "predictions": predictions}, completed


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw", type=Path, default=Path("ml/data/multisport/football/raw_matches.jsonl"))
    parser.add_argument("--artifact-dir", type=Path, default=Path("ml/artifacts/multisport/football"))
    parser.add_argument("--output", type=Path, default=Path("ml/data/multisport/football/predictions.json"))
    args = parser.parse_args()
    now = datetime.now(timezone.utc)
    ledger_path = args.output.parent / "live_prediction_audit.jsonl"
    previous_audit = refresh_live_audit({}, ledger_path, args.artifact_dir, now=now)
    result, completed = forecast(args.raw, args.artifact_dir, now=now, live_audit=previous_audit)
    result["live_audit"] = refresh_live_audit(completed, ledger_path, args.artifact_dir, result["predictions"], now=now)
    result["readiness"] = model_readiness(args.artifact_dir, result["live_audit"])
    for prediction in result["predictions"]:
        eligibility = result["readiness"]["automatic_builder_eligible"]
        audited_scope = prediction.get("competition_code") in LEAGUES
        prediction["market_eligibility"].update({
            "home_win": audited_scope and eligibility["home_win"],
            "over_2_5": audited_scope and eligibility["over_2_5"],
            "under_2_5": audited_scope and eligibility["over_2_5"],
            "both_teams_score": audited_scope and eligibility["both_teams_score"],
        })
        prediction["builder_eligible"] = any(prediction["market_eligibility"].values())
        prediction["status"] = "builder_eligible" if prediction["builder_eligible"] else "model_forecast"
        prediction["readiness"] = result["readiness"]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({"status": "predictions_refreshed", "count": result["count"]}, indent=2))


if __name__ == "__main__":
    main()
