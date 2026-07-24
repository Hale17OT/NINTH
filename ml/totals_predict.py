"""Production inference for the NINTH market-free total-runs model."""
from copy import deepcopy
from pathlib import Path
import sys

import joblib
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ml.predict import context_completeness
from ml.totals_features import apply_totals_result, hydrate_totals_state, reset_totals_season, totals_features

ARTIFACT = ROOT / "ml" / "artifacts" / "totals.joblib"
_CACHE = {"mtime": None, "bundle": None}
LABELS = {
    "league_recent_runs": "recent MLB scoring environment", "home_offense_20": "home offense",
    "away_offense_20": "away offense", "home_runs_allowed_20": "home run prevention",
    "away_runs_allowed_20": "away run prevention", "home_recent_total_10": "home recent game totals",
    "away_recent_total_10": "away recent game totals", "home_total_volatility_20": "home scoring volatility",
    "away_total_volatility_20": "away scoring volatility", "venue_recent_total": "venue run environment",
    "home_starter_era": "home starter ERA", "away_starter_era": "away starter ERA",
    "home_starter_whip": "home starter WHIP", "away_starter_whip": "away starter WHIP",
    "home_starter_fip": "home starter FIP", "away_starter_fip": "away starter FIP",
    "home_starter_k_minus_bb_per_inning": "home starter strikeout-minus-walk rate", "away_starter_k_minus_bb_per_inning": "away starter strikeout-minus-walk rate",
    "home_starter_prior_innings": "home starter track record", "away_starter_prior_innings": "away starter track record",
    "home_lineup_ops": "home lineup quality", "away_lineup_ops": "away lineup quality",
    "home_lineup_ops_spread": "home lineup depth", "away_lineup_ops_spread": "away lineup depth",
    "home_lineup_bottom_ops": "home bottom-of-order quality", "away_lineup_bottom_ops": "away bottom-of-order quality",
    "home_bullpen_3day_pitches": "home bullpen workload", "away_bullpen_3day_pitches": "away bullpen workload",
    "home_rest": "home rest", "away_rest": "away rest",
    "temperature_f": "game-time temperature", "wind_speed_mph": "game-time wind",
    "month_sin": "seasonal run environment", "month_cos": "seasonal run environment",
    "context_available": "official matchup input coverage",
}


def available():
    return ARTIFACT.exists()


def load_bundle():
    mtime = ARTIFACT.stat().st_mtime_ns
    if _CACHE["bundle"] is None or _CACHE["mtime"] != mtime:
        _CACHE.update({"mtime": mtime, "bundle": joblib.load(ARTIFACT)})
    return _CACHE["bundle"]


def predict(home_id, away_id, game_date, current_season_games=None, context=None, selectable_lines=None):
    if not available():
        return {"available": False, "message": "The totals model has not been trained yet."}
    bundle = load_bundle(); state = hydrate_totals_state(bundle["state"])
    cutoff = bundle.get("trained_through_date")
    if cutoff and game_date[:4] > cutoff[:4]:
        reset_totals_season(state)
    for game in current_season_games or []:
        if not cutoff or game["date"] > cutoff:
            apply_totals_result(state, game, None)
    values = totals_features(state, home_id, away_id, game_date, context)
    # V2 appends team-specific columns while preserving the original 21-column
    # prefix, so an older promoted artifact remains safe during shadow tuning.
    values = values[:len(bundle.get("features", values))]
    row = np.asarray([values], dtype=float); model = bundle["model"]
    expected = float(model.predict_expected(row)[0])
    expected_home = expected_away = None
    if hasattr(model, "predict_team_expected"):
        try:
            expected_home_rows, expected_away_rows = model.predict_team_expected(row)
            expected_home, expected_away = float(expected_home_rows[0]), float(expected_away_rows[0])
        except AttributeError:
            pass
    report = bundle["report"]; lines = [float(value) for value in report["lines"]]
    decision_lines = [float(value) for value in report["decision_lines"]]
    if selectable_lines is None:
        low, high = max(0, min(lines) - .5), max(lines) + .5
        selectable_lines = [round(value / 2, 1) for value in range(int(low * 2), int(high * 2) + 1)]
    selectable_lines = sorted({float(value) for value in selectable_lines if max(0, min(lines) - 2) <= float(value) <= max(lines) + 2})
    market = model.predict_market_probabilities(row, selectable_lines)
    thresholds = [
        {
            "line": line,
            "over_probability": round(float(market["over"][0, index]), 4),
            "under_probability": round(float(market["under"][0, index]), 4),
            "push_probability": round(float(market["push"][0, index]), 4),
        }
        for index, line in enumerate(selectable_lines)
    ]
    threshold_by_line = {row["line"]: row for row in thresholds}
    candidates = []
    recommendation_lines = [line for line in decision_lines if line in threshold_by_line]
    if not recommendation_lines:
        recommendation_lines = [line for line in selectable_lines if not float(line).is_integer()]
    for line in recommendation_lines:
        threshold = threshold_by_line[line]
        is_over = threshold["over_probability"] >= threshold["under_probability"]
        candidates.append({"line": line, "side": "over" if is_over else "under", "probability": threshold["over_probability"] if is_over else threshold["under_probability"]})
    recommended = max(candidates, key=lambda value: value["probability"])
    completeness = context_completeness(context)
    adjusted = .5 + (recommended["probability"] - .5) * (.75 + .25 * completeness)
    selected_index = lines.index(recommended["line"])
    selected_is_over = recommended["side"] == "over"
    reference = bundle.get("feature_reference", [0] * len(values)); impacts = []
    for index, (name, value) in enumerate(zip(bundle["features"], values)):
        neutral = row.copy(); neutral[0, index] = reference[index]
        neutral_over = float(model.predict_over_probabilities(neutral)[0, selected_index])
        neutral_selected = neutral_over if selected_is_over else 1 - neutral_over
        impacts.append((name, value, recommended["probability"] - neutral_selected))
    reasons = [
        {"feature": name, "label": LABELS.get(name, name.replace("_", " ")),
         "direction": recommended["side"] if impact >= 0 else ("under" if recommended["side"] == "over" else "over"),
         "value": round(float(value), 3), "impact": round(float(impact), 3)}
        for name, value, impact in sorted(impacts, key=lambda item: abs(item[2]), reverse=True)[:4]
        if abs(impact) >= .005
    ]
    residual = report.get("prediction_interval_residuals", {"lower_80": -5, "upper_80": 5})
    return {
        "available": True, "expected_total_runs": round(expected, 1),
        "expected_home_runs": None if expected_home is None else round(expected_home, 1),
        "expected_away_runs": None if expected_away is None else round(expected_away, 1),
        "prediction_interval_80": [max(0, round(expected + residual["lower_80"], 1)), round(expected + residual["upper_80"], 1)],
        "recommended_line": recommended["line"], "recommended_side": recommended["side"],
        "recommended_probability": round(recommended["probability"], 4),
        "confidence_score": round(adjusted * 100),
        "confidence_label": "High" if adjusted >= .72 else "Moderate" if adjusted >= .60 else "Low",
        "input_completeness": round(completeness, 2), "thresholds": thresholds, "reasons": reasons,
        "selectable_lines_source": "user_or_standard_market_grid",
        "model": report, "market_inputs": False,
        "confidence_explanation": "Calibrated chance of finishing on the selected side of this run line, reduced toward 50% when official matchup inputs are incomplete.",
    }
