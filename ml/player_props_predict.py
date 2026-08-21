"""Inference utilities for calibrated NINTH player-prop forecasts."""
from __future__ import annotations

import math
import os
import threading
import warnings
from collections import deque
from pathlib import Path

import joblib
import numpy as np
from scipy.stats import nbinom, poisson

from ml.player_props_features import (
    BOX_PATH, STATCAST_PATH, PROP_LABELS, build_features, feature_names,
    hydrate_state, load_games_before, load_statcast, replay_samples,
    retarget_threshold, serializable_state,
)


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = Path(os.getenv("NINTH_ARTIFACT_DIR", ROOT / "ml" / "artifacts")) / "player_props.joblib"
PRIMARY_BATTER_LINES = {
    "hits": .5, "total_bases": 1.5, "home_runs": .5, "runs": .5, "rbi": .5,
    "walks": .5, "strikeouts": .5, "doubles": .5, "stolen_bases": .5,
    "singles": .5, "triples": .5, "hits_runs_rbi": 1.5,
}
AUTOMATIC_RECOMMENDATION_FLOOR = .65
_INFERENCE_STATE_LOCK = threading.Lock()


def load_bundle(path=ARTIFACT):
    value = joblib.load(path)
    value["state"] = hydrate_state(value["state"])
    return value


def _source_fingerprint(path):
    path = Path(path)
    try:
        stat = path.stat()
        return (stat.st_mtime_ns, stat.st_size)
    except OSError:
        return (0, 0)


def _rebuild_season_state(base_state, games, statcast, season):
    """Recreate the current-season rolling state from authoritative outcomes."""
    state = hydrate_state(serializable_state(base_state))
    season = int(season)
    if state.get("season") is not None and int(state["season"]) == season:
        # Artifacts are immutable model snapshots, but their rolling histories can
        # be incomplete on the training cutoff date. Replaying the whole season
        # avoids both that boundary gap and duplicate games.
        for group in ("batters", "pitchers"):
            for bucket in state[group].values():
                bucket["games"] = deque(
                    (
                        row for row in bucket.get("games", [])
                        if int(row.get("season") or 0) != season
                    ),
                    maxlen=50,
                )
        for bucket in state["teams"].values():
            bucket["batting"] = deque(maxlen=50)
            bucket["pitching"] = deque(maxlen=50)
            bucket["lineups"] = deque(maxlen=12)
    for _ in replay_samples(games, statcast=statcast, state=state):
        pass
    return state


def inference_state(bundle, game_date, season, box_path=None, statcast_path=None):
    """Return a cached, leakage-safe state using results before ``game_date``."""
    box_path = Path(box_path) if box_path is not None else BOX_PATH
    statcast_path = Path(statcast_path) if statcast_path is not None else STATCAST_PATH
    key = (
        str(game_date)[:10], int(season),
        _source_fingerprint(box_path), _source_fingerprint(statcast_path),
    )
    cache = bundle.setdefault("_inference_state_cache", {})
    if key in cache:
        return cache[key]
    with _INFERENCE_STATE_LOCK:
        if key in cache:
            return cache[key]
        games = load_games_before(game_date, season, path=box_path)
        statcast = load_statcast(
            (game["game_id"] for game in games), path=statcast_path,
        )
        state = _rebuild_season_state(bundle["state"], games, statcast, season)
        # Keep only a few dates. Multi-day boards need adjacent states, while a
        # nightly file refresh gets a new fingerprint and naturally invalidates.
        if len(cache) >= 4:
            cache.pop(next(iter(cache)))
        cache[key] = state
        return state


def _logit(value):
    value = np.clip(value, 1e-5, 1 - 1e-5)
    return np.log(value / (1 - value))


def _beta_features(value):
    value = np.clip(np.asarray(value, dtype=float), 1e-5, 1 - 1e-5)
    return np.column_stack((np.log(value), -np.log1p(-value)))


def _calibrate(spec, values):
    if spec["method"] == "isotonic":
        return spec["model"].predict(values)
    if spec["method"] == "sigmoid":
        return spec["model"].predict_proba(_logit(values).reshape(-1, 1))[:, 1]
    if spec["method"] == "beta":
        return spec["model"].predict_proba(_beta_features(values))[:, 1]
    return values


def _confidence(probability, games):
    edge = abs(float(probability) - .5)
    score = min(99, round(50 + 100 * edge * min(1.0, max(0.35, games / 30))))
    label = "High" if score >= 68 else "Moderate" if score >= 58 else "Cautious"
    return score, label


def _predict_probability(model, matrix):
    # LightGBM assigns synthetic Column_N names even when trained from NumPy.
    # Inference uses the same positional schema stored in the artifact.
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message="X does not have valid feature names, but LGBMClassifier was fitted with feature names",
            category=UserWarning,
        )
        return model.predict_proba(matrix)[:, 1]


def _predict_count(model, matrix):
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message="X does not have valid feature names, but LGBMRegressor was fitted with feature names",
            category=UserWarning,
        )
        return model.predict(matrix)


def _count_probabilities(mean, alpha, lines):
    mean = np.clip(np.asarray(mean, dtype=float), .01, 100)
    if float(alpha) <= .002:
        return np.column_stack([poisson.sf(int(line), mean) for line in lines])
    size = 1 / float(alpha)
    return np.column_stack([
        nbinom.sf(int(line), size, size / (size + mean)) for line in lines
    ])


def predict_candidates(bundle, candidates, game_date, season):
    state = inference_state(bundle, game_date, season)
    results = []
    for candidate in candidates:
        kind, player_id = candidate["kind"], int(candidate["player_id"])
        bucket = state["batters" if kind == "batter" else "pitchers"].get(player_id)
        results.append(None if not bucket or len(bucket["games"]) < 3 else {
            **candidate, "name": candidate.get("name") or bucket.get("name") or f"Player {player_id}",
            "history_games": len(bucket["games"]), "props": [], "_bucket": bucket,
        })
    for model_bundle in bundle["models"].values():
        kind, prop, lines = model_bundle["kind"], model_bundle["prop"], model_bundle["lines"]
        matrices, owners = [], []
        for result_index, result in enumerate(results):
            if not result or result["kind"] != kind:
                continue
            player_id = int(result["player_id"])
            base = build_features(
                state, kind, player_id, int(result["team_id"]), int(result["opponent_id"]),
                game_date, season, prop, lines[0], bool(result.get("home")),
                int(result.get("lineup_slot") or 0),
                result.get("opponent_starter_id") if kind == "batter" or prop == "win" else None,
                result.get("opponent_starter_hand"), result.get("opponent_lineup_ids"),
            )
            matrix = np.asarray([
                base if index == 0 else retarget_threshold(
                    base, state, kind, player_id, season, prop, line,
                )
                for index, line in enumerate(lines)
            ], dtype=np.float32)
            stored_names = model_bundle.get("feature_names")
            if stored_names:
                current_names = feature_names(kind)
                missing = [name for name in stored_names if name not in current_names]
                if missing:
                    raise RuntimeError(
                        f"Deployed {kind} prop model requires unavailable features: {missing[:5]}"
                    )
                matrix = matrix[:, [current_names.index(name) for name in stored_names]]
            matrices.append(matrix); owners.append(result_index)
        if not matrices:
            continue
        model_type = model_bundle.get("model_type", "threshold_classifier")
        if model_type == "negative_binomial_count":
            means = _predict_count(
                model_bundle["model"],
                np.vstack([matrix[0] for matrix in matrices]),
            )
            probability_rows = _count_probabilities(
                means, model_bundle["negative_binomial_alpha"], lines,
            )
            probability_rows = np.minimum.accumulate(np.column_stack([
                _calibrate(spec, probability_rows[:, index])
                for index, spec in enumerate(model_bundle["calibrators"])
            ]), axis=1)
        else:
            combined = np.vstack(matrices)
            raw_all = _predict_probability(model_bundle["model"], combined)
        offset = 0
        for owner_index, (matrix, result_index) in enumerate(zip(matrices, owners)):
            result = results[result_index]; bucket = result["_bucket"]
            recent = list(bucket["games"])[-10:]
            recent_average = sum(float(row.get(prop, 0) or 0) for row in recent) / max(1, len(recent))
            if model_type == "negative_binomial_count":
                probabilities = np.clip(probability_rows[owner_index], .01, .99)
            else:
                raw = raw_all[offset:offset + len(lines)]; offset += len(lines)
                spec = model_bundle["calibrator"]
                blended = spec["blend"] * raw + (1 - spec["blend"]) * matrix[:, 15]
                probabilities = np.minimum.accumulate(
                    np.clip(_calibrate(spec, blended), .01, .99),
                )
            thresholds = []
            for line, over in zip(lines, probabilities):
                under = 1 - float(over); side = "over" if over >= under else "under"
                probability = max(float(over), under); score, label = _confidence(probability, len(bucket["games"]))
                thresholds.append({"line": float(line), "over_probability": float(over), "under_probability": under})
            primary_line = PRIMARY_BATTER_LINES.get(prop) if kind == "batter" else min(lines, key=lambda line: abs(float(line) - recent_average))
            best = min(thresholds, key=lambda row: abs(float(row["line"]) - float(primary_line)))
            result["props"].append({
                "prop": prop, "label": PROP_LABELS.get(prop, prop.replace("_", " ").title()),
                "recent_10_average": round(recent_average, 2), "thresholds": thresholds,
                "recommended_line": best["line"], "recommended_side": "over" if best["over_probability"] >= best["under_probability"] else "under",
                "recommended_probability": max(best["over_probability"], best["under_probability"]),
                "automatic_recommendation_eligible": (
                    max(best["over_probability"], best["under_probability"])
                    >= AUTOMATIC_RECOMMENDATION_FLOOR
                ),
                "automatic_recommendation_floor": AUTOMATIC_RECOMMENDATION_FLOOR,
                "confidence_score": _confidence(max(best["over_probability"], best["under_probability"]), len(bucket["games"]))[0],
                "confidence_label": _confidence(max(best["over_probability"], best["under_probability"]), len(bucket["games"]))[1],
            })
    output = []
    for result in results:
        if not result:
            continue
        result.pop("_bucket", None)
        result["best_projection"] = max(result["props"], key=lambda row: row["recommended_probability"], default=None)
        output.append(result)
    return output


def predict_player(bundle, candidate, game_date, season):
    values = predict_candidates(bundle, [candidate], game_date, season)
    return values[0] if values else None


def _legacy_predict_player_body(bundle, candidate, game_date, season):
    """Kept out of the hot path as a readable single-player reference."""
    kind = candidate["kind"]; player_id = int(candidate["player_id"]); state = bundle["state"]
    bucket = state["batters" if kind == "batter" else "pitchers"].get(player_id)
    if not bucket or len(bucket["games"]) < 3: return None
    projections = []
    for model_bundle in (value for value in bundle["models"].values() if value["kind"] == kind):
        prop, lines = model_bundle["prop"], model_bundle["lines"]
        base = build_features(state, kind, player_id, int(candidate["team_id"]), int(candidate["opponent_id"]), game_date, season, prop, lines[0], bool(candidate.get("home")), int(candidate.get("lineup_slot") or 0), candidate.get("opponent_starter_id"), candidate.get("opponent_starter_hand"), candidate.get("opponent_lineup_ids"))
        matrix = np.asarray([
            base if index == 0 else retarget_threshold(
                base, state, kind, player_id, season, prop, line,
            )
            for index, line in enumerate(lines)
        ], dtype=np.float32)
        raw = _predict_probability(model_bundle["model"], matrix)
        spec = model_bundle["calibrator"]
        blended = spec["blend"] * raw + (1 - spec["blend"]) * matrix[:, 15]
        probabilities = np.minimum.accumulate(
            np.clip(_calibrate(spec, blended), .01, .99),
        )
        thresholds = []
        for line, over in zip(lines, probabilities):
            under = 1 - float(over)
            side = "over" if over >= under else "under"
            probability = max(float(over), under)
            score, label = _confidence(probability, len(bucket["games"]))
            thresholds.append({
                "line": float(line), "over_probability": float(over), "under_probability": under,
                "recommended_side": side, "recommended_probability": probability,
                "confidence_score": score, "confidence_label": label,
            })
        recent = list(bucket["games"])[-10:]
        recent_average = sum(float(row.get(prop, 0) or 0) for row in recent) / max(1, len(recent))
        primary_line = PRIMARY_BATTER_LINES.get(prop) if kind == "batter" else min(lines, key=lambda line: abs(float(line) - recent_average))
        best = min(thresholds, key=lambda row: abs(float(row["line"]) - float(primary_line)))
        projections.append({
            "prop": prop, "label": PROP_LABELS.get(prop, prop.replace("_", " ").title()),
            "recent_10_average": round(recent_average, 2), "thresholds": thresholds,
            "recommended_line": best["line"], "recommended_side": best["recommended_side"],
            "recommended_probability": best["recommended_probability"],
            "confidence_score": best["confidence_score"], "confidence_label": best["confidence_label"],
        })
    best = max(
        (prop for prop in projections if prop["recommended_probability"] >= .5),
        key=lambda prop: prop["recommended_probability"], default=None,
    )
    return {
        **candidate, "name": candidate.get("name") or bucket.get("name") or f"Player {player_id}",
        "history_games": len(bucket["games"]), "props": projections, "best_projection": best,
    }


def projected_lineup(bundle, team_id, game_date=None, season=None):
    state = (
        inference_state(bundle, game_date, season)
        if game_date is not None and season is not None else bundle["state"]
    )
    lineups = list(state["teams"].get(int(team_id), {}).get("lineups", []))
    if not lineups:
        return []
    scores = {}
    for age, lineup in enumerate(reversed(lineups)):
        weight = .85 ** age
        for slot, player_id in enumerate(lineup[:9], 1):
            value = scores.setdefault(int(player_id), {"weight": 0.0, "slot": 0.0})
            value["weight"] += weight; value["slot"] += weight * slot
    ranked = sorted(scores.items(), key=lambda pair: pair[1]["weight"], reverse=True)[:9]
    return [
        {"player_id": player_id, "lineup_slot": max(1, min(9, round(value["slot"] / value["weight"]))),
         "name": state["batters"].get(player_id, {}).get("name") or f"Player {player_id}"}
        for player_id, value in sorted(ranked, key=lambda pair: pair[1]["slot"] / pair[1]["weight"])
    ]
