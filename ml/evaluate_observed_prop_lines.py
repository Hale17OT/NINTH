"""Compare prop artifacts on the exact lines archived before first pitch.

This is a shadow audit, not a training input. It reconstructs point-in-time
features from official box scores, selects the last archived MelBet snapshot
before each game, and scores only the player/market/line combinations that were
actually listed. The small live archive is reported separately from the locked
multi-season temporal audit.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

import joblib
import numpy as np
from sklearn.metrics import brier_score_loss, log_loss

from ml.player_props_features import (
    BATTER_PROPS, PITCHER_PROPS, feature_names, load_games, load_statcast,
)
from ml.player_props_predict import _calibrate, _count_probabilities
from ml.train_player_props import _expand_dataset, _kind_dataset


ROOT = Path(__file__).resolve().parents[1]
SNAPSHOTS = ROOT / "ml" / "data" / "player_prop_projection_snapshots.jsonl"


def _time(value):
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def observed_lines(path=SNAPSHOTS):
    latest = {}
    if not path.exists():
        return {}
    for text in path.read_text(encoding="utf8").splitlines():
        if not text.strip():
            continue
        row = json.loads(text)
        if _time(row["recorded_at"]) >= _time(row["scheduled_start"]):
            continue
        game_id = int(row["game_id"])
        if game_id not in latest or _time(row["recorded_at"]) > _time(latest[game_id]["recorded_at"]):
            latest[game_id] = row
    lines = {}
    for game_id, row in latest.items():
        for selection in row.get("selections") or []:
            lines[(
                game_id, int(selection["player_id"]),
                selection["kind"], selection["prop"],
            )] = float(selection["line"])
    return lines


def probabilities(model_bundle, x, distribution, base_count):
    # A production refit may learn 2025 after the architecture has passed its
    # locked temporal audit. Always score the frozen audit estimator here so
    # 2025 can never be counted as both training and validation data.
    model = model_bundle.get("audit_model", model_bundle["model"])
    width = int(getattr(model, "n_features_in_", x.shape[1]))
    if model_bundle.get("model_type") == "negative_binomial_count":
        base = x[::len(model_bundle["lines"]), :width]
        mean = model.predict(base)
        raw = _count_probabilities(
            mean, model_bundle["negative_binomial_alpha"], model_bundle["lines"],
        )
        return np.minimum.accumulate(np.column_stack([
            _calibrate(spec, raw[:, index])
            for index, spec in enumerate(model_bundle["calibrators"])
        ]), axis=1).reshape(-1)
    raw = model.predict_proba(x[:, :width])[:, 1]
    spec = model_bundle["calibrator"]
    blended = spec["blend"] * raw + (1 - spec["blend"]) * distribution
    return np.minimum.accumulate(
        _calibrate(spec, blended).reshape(base_count, -1), axis=1,
    ).reshape(-1)


def evaluate(artifact_path, datasets, offered, requested=None):
    artifact = joblib.load(artifact_path)
    actual, forecast = [], []
    by_prop = {}
    temporal_by_prop = {}
    for key, model_bundle in artifact["models"].items():
        if requested and key not in requested:
            continue
        kind, prop = key.split(":", 1)
        dataset = datasets[kind]
        lines = list(model_bundle["lines"])
        x, y, years, distribution = _expand_dataset(dataset, prop, lines)
        current_names = feature_names(kind)
        artifact_names = (artifact.get("feature_names") or {}).get(kind) or current_names
        missing = [name for name in artifact_names if name not in current_names]
        if missing:
            raise RuntimeError(
                f"{artifact_path} requires unavailable {kind} features: {missing[:5]}"
            )
        aligned_x = x[:, [current_names.index(name) for name in artifact_names]]
        p = probabilities(
            model_bundle, aligned_x, distribution, len(dataset["base"]),
        )
        audit = years >= 2025
        temporal_by_prop[key] = {
            "2025_2026": metrics(y[audit], p[audit]),
            **{
                str(season): metrics(y[years == season], p[years == season])
                for season in (2025, 2026) if np.any(years == season)
            },
        }
        y = y.reshape(-1, len(lines)); p = p.reshape(-1, len(lines))
        prop_y, prop_p = [], []
        for index in range(len(dataset["base"])):
            line = offered.get((
                int(dataset["metadata"]["game_id"][index]),
                int(dataset["metadata"]["player_id"][index]), kind, prop,
            ))
            if line is None:
                continue
            try:
                line_index = next(i for i, value in enumerate(lines) if float(value) == line)
            except StopIteration:
                continue
            prop_y.append(int(y[index, line_index]))
            prop_p.append(float(p[index, line_index]))
        if not prop_y:
            continue
        actual.extend(prop_y); forecast.extend(prop_p)
        by_prop[key] = metrics(prop_y, prop_p)
    return {
        "artifact": str(artifact_path),
        "exact_listed_lines": {
            "overall": metrics(actual, forecast), "by_prop": by_prop,
        },
        "all_threshold_temporal": temporal_by_prop,
    }


def metrics(actual, forecast):
    y = np.asarray(actual, dtype=int)
    p = np.clip(np.asarray(forecast, dtype=float), 1e-5, 1 - 1e-5)
    if not len(y):
        return {"samples": 0}
    confidence = np.maximum(p, 1 - p)
    correct = (p >= .5) == y
    result = {
        "samples": int(len(y)),
        "brier": round(float(brier_score_loss(y, p)), 7),
        "log_loss": round(float(log_loss(y, p, labels=[0, 1])), 7),
        "side_accuracy": round(float(np.mean(correct)), 7),
        "mean_confidence": round(float(np.mean(confidence)), 7),
    }
    for floor in (.60, .65, .70):
        mask = confidence >= floor
        result[f"confidence_{int(floor * 100)}"] = {
            "coverage": round(float(np.mean(mask)), 7),
            "accuracy": round(float(np.mean(correct[mask])), 7) if mask.any() else None,
            "samples": int(mask.sum()),
        }
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("artifacts", nargs="+")
    parser.add_argument("--output")
    parser.add_argument("--props", nargs="*")
    args = parser.parse_args()
    offered = observed_lines()
    games, statcast = load_games(), load_statcast()
    requested = set(args.props or [])
    datasets = {}
    for kind, props in (("batter", BATTER_PROPS), ("pitcher", PITCHER_PROPS)):
        active = {
            prop: lines for prop, lines in props.items()
            if not requested or f"{kind}:{prop}" in requested
        }
        if active:
            datasets[kind] = _kind_dataset(
                games, statcast, kind, active, include_metadata=True,
            )
    report = {
        "selection": "Last archived listed line before scheduled first pitch",
        "listed_selections": len(offered),
        "artifacts": [
            evaluate(Path(path), datasets, offered, requested)
            for path in args.artifacts
        ],
    }
    text = json.dumps(report, indent=2)
    if args.output:
        Path(args.output).write_text(text, encoding="utf8")
    print(text)


if __name__ == "__main__":
    main()
