"""Inference utilities for calibrated NINTH player-prop forecasts."""
from __future__ import annotations

import math
from pathlib import Path

import joblib
import numpy as np

from ml.player_props_features import (
    PROP_LABELS, build_features, hydrate_state, retarget_line,
)


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "ml" / "artifacts" / "player_props.joblib"
PRIMARY_BATTER_LINES = {
    "hits": .5, "total_bases": 1.5, "home_runs": .5, "runs": .5, "rbi": .5,
    "walks": .5, "strikeouts": .5, "doubles": .5, "stolen_bases": .5,
}


def load_bundle(path=ARTIFACT):
    value = joblib.load(path)
    value["state"] = hydrate_state(value["state"])
    return value


def _logit(value):
    value = np.clip(value, 1e-5, 1 - 1e-5)
    return np.log(value / (1 - value))


def _calibrate(spec, values):
    if spec["method"] == "isotonic":
        return spec["model"].predict(values)
    if spec["method"] == "sigmoid":
        return spec["model"].predict_proba(_logit(values).reshape(-1, 1))[:, 1]
    return values


def _confidence(probability, games):
    edge = abs(float(probability) - .5)
    score = min(99, round(50 + 100 * edge * min(1.0, max(0.35, games / 30))))
    label = "High" if score >= 68 else "Moderate" if score >= 58 else "Cautious"
    return score, label


def predict_candidates(bundle, candidates, game_date, season):
    state = bundle["state"]
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
                int(result.get("lineup_slot") or 0), result.get("opponent_starter_id"),
            )
            matrix = np.asarray([
                base if index == 0 else retarget_line(base, state, kind, player_id, season, prop, line)
                for index, line in enumerate(lines)
            ], dtype=np.float32)
            matrices.append(matrix); owners.append(result_index)
        if not matrices:
            continue
        combined = np.vstack(matrices)
        raw_all = model_bundle["model"].predict_proba(combined)[:, 1]
        offset = 0
        for matrix, result_index in zip(matrices, owners):
            raw = raw_all[offset:offset + len(lines)]; offset += len(lines)
            result = results[result_index]; bucket = result["_bucket"]
            recent = list(bucket["games"])[-10:]
            recent_average = sum(float(row.get(prop, 0) or 0) for row in recent) / max(1, len(recent))
            spec = model_bundle["calibrator"]
            blended = spec["blend"] * raw + (1 - spec["blend"]) * matrix[:, 15]
            probabilities = np.clip(_calibrate(spec, blended), .01, .99)
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
        base = build_features(state, kind, player_id, int(candidate["team_id"]), int(candidate["opponent_id"]), game_date, season, prop, lines[0], bool(candidate.get("home")), int(candidate.get("lineup_slot") or 0), candidate.get("opponent_starter_id"))
        matrix = np.asarray([base if index == 0 else retarget_line(base, state, kind, player_id, season, prop, line) for index, line in enumerate(lines)], dtype=np.float32)
        raw = model_bundle["model"].predict_proba(matrix)[:, 1]
        spec = model_bundle["calibrator"]
        blended = spec["blend"] * raw + (1 - spec["blend"]) * matrix[:, 15]
        probabilities = np.clip(_calibrate(spec, blended), .01, .99)
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


def projected_lineup(bundle, team_id):
    state = bundle["state"]
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
