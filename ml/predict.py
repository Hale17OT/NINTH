import sys
from pathlib import Path
import joblib, numpy as np
from copy import deepcopy
ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
from ml.features import FEATURE_NAMES, apply_result, matchup_features, reset_season_records
from ml.starter_statcast_experiment import advantages as starter_advantages, summary as starter_statcast_summary
ARTIFACT = ROOT / "ml" / "artifacts" / "moneyline.joblib"
_BUNDLE_CACHE = {"mtime": None, "bundle": None}
LABELS = {"elo_difference":"long-term team strength", "last_5_win_pct_difference":"last-five form adjustment", "last_10_win_pct_difference":"last-ten form adjustment", "last_20_win_pct_difference":"last-twenty form adjustment", "last_10_run_margin_difference":"recent scoring margin", "last_20_run_margin_difference":"twenty-game scoring margin", "rolling_runs_scored_difference":"rolling offense", "rolling_runs_allowed_advantage":"rolling run prevention", "season_win_pct_difference":"season record", "pythagorean_win_pct_difference":"run-based expected record", "home_away_split_difference":"home/road performance split", "rest_days_difference":"team rest adjustment", "starter_elo_difference":"starter track record", "starter_rest_difference":"starter rest adjustment", "starter_era_difference":"starting-pitcher ERA signal", "starter_whip_difference":"starting-pitcher WHIP signal", "lineup_ops_difference":"lineup composition signal", "bullpen_3day_pitches_difference":"recent bullpen workload signal", "temperature_f":"game-time temperature signal", "wind_speed_mph":"game-time wind signal", "context_available":"pregame context coverage"}
LABELS.update({"starter_statcast_long_xwoba_advantage":"starter expected contact quality","starter_statcast_long_hard_hit_advantage":"starter hard-hit suppression","starter_statcast_long_barrel_advantage":"starter barrel suppression","starter_statcast_long_whiff_advantage":"starter swing-and-miss ability","starter_statcast_long_kbb_advantage":"starter strikeout-to-walk quality","starter_statcast_long_velocity_advantage":"starter velocity profile","starter_statcast_joint_reliability":"starter Statcast sample reliability","starter_statcast_start_count_difference":"starter history depth"})
NEUTRAL={"temperature_f":65.0,"context_available":1.0}

def available(): return ARTIFACT.exists()

def load_bundle():
    """Keep the production artifact in memory and reload only after retraining."""
    mtime = ARTIFACT.stat().st_mtime_ns
    if _BUNDLE_CACHE["bundle"] is None or _BUNDLE_CACHE["mtime"] != mtime:
        _BUNDLE_CACHE["bundle"] = joblib.load(ARTIFACT)
        _BUNDLE_CACHE["mtime"] = mtime
    return _BUNDLE_CACHE["bundle"]

def context_completeness(context):
    if not context:return 0.0
    home,away=context.get('home',{}),context.get('away',{});weather=context.get('weather',{})
    starters_present=bool(home.get('starter_id') and away.get('starter_id'));starters_confirmed=home.get('starter_status')=='confirmed' and away.get('starter_status')=='confirmed'
    bullpen_present='bullpen_recent_pitches' in home and 'bullpen_recent_pitches' in away;bullpen_confirmed=home.get('bullpen_status')=='confirmed' and away.get('bullpen_status')=='confirmed'
    weather_available=weather.get('available',weather.get('temperature') is not None)
    return .15*float(starters_present)+.10*float(starters_confirmed)+.30*float(bool(home.get('lineup_confirmed') and away.get('lineup_confirmed')))+.15*float(bullpen_present)+.10*float(bullpen_confirmed)+.20*float(weather_available)

def predict(home_id, away_id, game_date, current_season_games=None, context=None, current_season_contexts=None):
    if not available(): return {"available": False, "message": "The local model has not been trained yet."}
    bundle = load_bundle(); state = deepcopy(bundle["state"])
    version=int(bundle.get('model_version',1));cutoff=bundle.get('trained_through_date')
    if current_season_games is not None and version>=3:
        if cutoff and game_date[:4]>cutoff[:4]:reset_season_records(state)
        for game in current_season_games:
            if not cutoff or game['date']>cutoff:apply_result(state,game,None)
    elif current_season_games is not None:
        reset_season_records(state)
        context_map=current_season_contexts or {}
        for game in current_season_games: apply_result(state, game, context_map.get(str(game['game_id'])))
    feature_context={**context,'context_available':1} if context else None
    values = matchup_features(state, home_id, away_id, game_date,feature_context)
    if version>=3:
        home_starter=str((context or {}).get('home',{}).get('starter_id'));away_starter=str((context or {}).get('away',{}).get('starter_id'));histories=bundle.get('starter_statcast_histories',{})
        home_summary=starter_statcast_summary(histories.get(home_starter,[]),15);away_summary=starter_statcast_summary(histories.get(away_starter,[]),15)
        values+=starter_advantages(home_summary,away_summary)+[min(1.0,min(home_summary['pitches'],away_summary['pitches'])/750.0),home_summary['starts']-away_summary['starts']]
    feature_names=bundle.get('features',FEATURE_NAMES);row = np.asarray([values], dtype=float); probability = float(bundle["model"].predict_proba(row)[0, 1])
    contributions = []
    for index in range(len(values)):
        neutral = row.copy(); neutral[0, index] = NEUTRAL.get(feature_names[index],0.0)
        contributions.append(probability - float(bundle["model"].predict_proba(neutral)[0, 1]))
    ranked = sorted(zip(feature_names, values, contributions), key=lambda item: abs(item[2]), reverse=True)
    reasons = [{"feature": name, "label": LABELS.get(name, name.replace("_", " ")), "direction": "home" if contribution > 0 else "away", "value": round(float(value), 3), "impact": round(float(contribution), 3)} for name, value, contribution in ranked[:4] if abs(contribution) >= 0.01]
    completeness=context_completeness(context);base_confidence=float(bundle['confidence_model'].predict([abs(probability-.5)])[0]);confidence=.5+(base_confidence-.5)*(.7+.3*completeness);selected_probability=max(probability,1-probability)
    tiers=[tier for tier in bundle['report'].get('selective_accuracy',[]) if selected_probability>=tier['minimum_probability']];historical_tier=tiers[-1] if tiers else None
    return {"available": True, "home_win_probability": round(probability, 4), "away_win_probability": round(1-probability, 4), "projected_side": "home" if probability >= 0.5 else "away", "confidence_score":round(confidence*100),"confidence_label":"High" if confidence>=.70 else "Moderate" if confidence>=.60 else "Low","input_completeness":round(completeness,2),"confidence_explanation":"Expected straight-up hit rate for similarly decisive walk-forward predictions, reduced when live inputs are incomplete.","historical_tier":historical_tier,"reasons": reasons, "model": bundle["report"], "market_inputs": False}
