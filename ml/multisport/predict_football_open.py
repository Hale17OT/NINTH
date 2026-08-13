"""Generate free-source Football shadow forecasts for current fixtures."""
from __future__ import annotations

import argparse
import json
import math
import time
import unicodedata
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import joblib
import numpy as np

from .collect_football_open import LEAGUES, build_ledgers_and_states, load_statsbomb, parse_date, state_features
from .score_models import dixon_coles_matrix


SPORTS_DB = "https://www.thesportsdb.com/api/v1/json/123"
COMPETITIONS = {
    "4328": ("E0", "Premier League"), "4335": ("SP1", "La Liga"), "4331": ("D1", "Bundesliga"),
    "4332": ("I1", "Serie A"), "4334": ("F1", "Ligue 1"), "4480": ("UCL", "UEFA Champions League"),
    "4481": ("UEL", "UEFA Europa League"), "5071": ("UECL", "UEFA Conference League"),
    "4482": ("FAC", "FA Cup"), "4570": ("EFL", "EFL Cup"), "4483": ("CDR", "Copa del Rey"),
    "4485": ("DFB", "DFB-Pokal"), "4506": ("CIT", "Coppa Italia"), "4484": ("CDF", "Coupe de France"),
}
ALIASES = {
    "manchester united": "man united", "manchester city": "man city", "paris saint germain": "paris sg",
    "internazionale": "inter", "inter milan": "inter", "athletic club": "ath bilbao",
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


def current_fixtures() -> list[dict]:
    fixtures = []
    for competition_id, (code, name) in COMPETITIONS.items():
        try:
            payload = read_json(f"{SPORTS_DB}/eventsnextleague.php?{urlencode({'id': competition_id})}")
        except Exception:
            time.sleep(.3)
            continue
        for event in payload.get("events") or []:
            fixtures.append({
                "event_id": str(event.get("idEvent")), "competition_id": competition_id,
                "competition_code": code, "competition": event.get("strLeague") or name,
                "event_time": event.get("strTimestamp") or f"{event.get('dateEvent')}T{event.get('strTime') or '12:00:00'}Z",
                "home_team": event.get("strHomeTeam"), "away_team": event.get("strAwayTeam"),
            })
        time.sleep(.3)
    return fixtures


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


def consistency_blend(trained: float | None, structural: float, trained_weight: float = .25) -> float:
    """Keep a discriminative candidate subordinate to the joint score model."""
    if trained is None or not math.isfinite(trained):
        return structural
    value = trained_weight * trained + (1 - trained_weight) * structural
    return min(.98, max(.02, value))


def forecast(raw_path: Path, artifact_dir: Path) -> dict:
    rows = [json.loads(line) for line in raw_path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    _, states = build_ledgers_and_states(rows, load_statsbomb(raw_path.parent / "statsbomb_team_games.json"))
    bundles = {path.stem: joblib.load(path) for path in artifact_dir.glob("*.joblib")}
    predictions = []
    for fixture in current_fixtures():
        home, away = resolve_state(states, fixture["home_team"]), resolve_state(states, fixture["away_team"])
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
        raw_home_xg = .55 * features["home_goals_for_10"] + .45 * features["away_goals_against_10"] + .12
        raw_away_xg = .55 * features["away_goals_for_10"] + .45 * features["home_goals_against_10"]
        home_xg = max(.35, min(2.8, .68 * raw_home_xg + .32 * 1.45))
        away_xg = max(.30, min(2.5, .68 * raw_away_xg + .32 * 1.15))
        score = dixon_coles_matrix(home_xg, away_xg)
        home_probability = consistency_blend(trained.get("home_win"), score["home_win"])
        remaining = max(0.0, 1 - home_probability)
        away_draw_mass = score["away_win"] + score["draw"]
        draw_probability = remaining * score["draw"] / away_draw_mass if away_draw_mass else remaining / 2
        away_probability = remaining - draw_probability
        likely_scores = sorted(score["matrix"].items(), key=lambda item: item[1], reverse=True)[:3]
        predictions.append({
            **fixture, "generated_at": datetime.now(timezone.utc).isoformat(),
            "expected_goals": {"home": home_xg, "away": away_xg, "total": home_xg + away_xg},
            "markets": {
                "home_win": home_probability, "draw": draw_probability, "away_win": away_probability,
                "over_2_5": consistency_blend(trained.get("over_2_5"), score["over_2_5"]),
                "under_2_5": 1 - consistency_blend(trained.get("over_2_5"), score["over_2_5"]),
                "both_teams_score": consistency_blend(trained.get("both_teams_score"), score["both_teams_score"]),
            },
            "likely_scores": [{"score": value, "probability": probability} for value, probability in likely_scores],
            "status": "shadow_only", "builder_eligible": False,
            "source": "Football-Data.co.uk + TheSportsDB public feed",
        })
    return {"generated_at": datetime.now(timezone.utc).isoformat(), "count": len(predictions), "predictions": predictions}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw", type=Path, default=Path("ml/data/multisport/football/raw_matches.jsonl"))
    parser.add_argument("--artifact-dir", type=Path, default=Path("ml/artifacts/multisport/football"))
    parser.add_argument("--output", type=Path, default=Path("ml/data/multisport/football/predictions.json"))
    args = parser.parse_args()
    result = forecast(args.raw, args.artifact_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({"status": "shadow_predictions_refreshed", "count": result["count"]}, indent=2))


if __name__ == "__main__":
    main()
