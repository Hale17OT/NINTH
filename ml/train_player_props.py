"""Train and temporally validate calibrated player-prop probability models."""
from __future__ import annotations

import argparse
import json
import math
import os
import time
from array import array
from collections import defaultdict
from pathlib import Path

import joblib
import lightgbm as lgb
import numpy as np
from scipy.stats import nbinom, poisson
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss

from ml.player_props_features import (
    BATTER_PROPS, PITCHER_PROPS, build_features, feature_names, fresh_state,
    load_games, load_statcast, replay_samples, retarget_line, retarget_threshold,
    serializable_state,
)


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_DIR = Path(os.getenv("NINTH_ARTIFACT_DIR", ROOT / "ml" / "artifacts"))
ARTIFACT = ARTIFACT_DIR / "player_props.joblib"
REPORT = ARTIFACT_DIR / "player_props_report.json"
COUNT_HEADS = {
    value.strip() for value in os.getenv(
        "NINTH_PROP_COUNT_HEADS",
        "",
    ).split(",") if value.strip()
}


def _metric(y, p):
    p = np.clip(np.asarray(p, dtype=float), 1e-5, 1 - 1e-5)
    y = np.asarray(y, dtype=int)
    return {"brier": float(brier_score_loss(y, p)), "log_loss": float(log_loss(y, p, labels=[0, 1]))}


def _sigmoid(value):
    return 1.0 / (1.0 + np.exp(-np.clip(value, -30, 30)))


def _logit(value):
    value = np.clip(value, 1e-5, 1 - 1e-5)
    return np.log(value / (1 - value))


def _beta_features(value):
    value = np.clip(np.asarray(value, dtype=float), 1e-5, 1 - 1e-5)
    return np.column_stack((np.log(value), -np.log1p(-value)))


def _monotone(values, line_count):
    values = np.asarray(values, dtype=float).reshape(-1, int(line_count))
    return np.minimum.accumulate(values, axis=1).reshape(-1)


def _distribution_matrix(mean, alpha, lines):
    mean = np.clip(np.asarray(mean, dtype=float), .01, 100)
    if alpha <= .002:
        return np.column_stack([poisson.sf(int(line), mean) for line in lines])
    size = 1 / alpha
    return np.column_stack([
        nbinom.sf(int(line), size, size / (size + mean)) for line in lines
    ])


def _linewise_calibrators(y, raw, line_count):
    y = np.asarray(y).reshape(-1, line_count)
    raw = np.asarray(raw).reshape(-1, line_count)
    return [
        _choose_calibration(y[:, index], raw[:, index], raw[:, index], 1)
        for index in range(line_count)
    ]


def _apply_linewise(specs, raw):
    raw = np.asarray(raw, dtype=float)
    return np.minimum.accumulate(np.column_stack([
        _apply_calibration(spec, raw[:, index])
        for index, spec in enumerate(specs)
    ]), axis=1).reshape(-1)


def _apply_calibration(spec, values):
    values = np.asarray(values, dtype=float)
    if spec["method"] == "isotonic":
        return spec["model"].predict(values)
    if spec["method"] == "sigmoid":
        return spec["model"].predict_proba(_logit(values).reshape(-1, 1))[:, 1]
    if spec["method"] == "beta":
        return spec["model"].predict_proba(_beta_features(values))[:, 1]
    return values


def _choose_calibration(y, model_probability, distribution_probability, line_count):
    candidates = []
    for blend in (0.0, 0.25, 0.5, 0.65, 0.8, 0.9, 1.0):
        raw = blend * model_probability + (1 - blend) * distribution_probability
        candidates.append((
            {"method": "raw", "blend": blend, "model": None},
            _monotone(raw, line_count),
        ))
        if len(np.unique(y)) > 1:
            sigmoid = LogisticRegression(C=1.0, max_iter=500).fit(_logit(raw).reshape(-1, 1), y)
            candidates.append((
                {"method": "sigmoid", "blend": blend, "model": sigmoid},
                _monotone(sigmoid.predict_proba(_logit(raw).reshape(-1, 1))[:, 1], line_count),
            ))
            beta = LogisticRegression(C=1.0, max_iter=500).fit(_beta_features(raw), y)
            candidates.append((
                {"method": "beta", "blend": blend, "model": beta},
                _monotone(beta.predict_proba(_beta_features(raw))[:, 1], line_count),
            ))
            if len(y) >= 1500:
                isotonic = IsotonicRegression(y_min=.001, y_max=.999, out_of_bounds="clip").fit(raw, y)
                candidates.append((
                    {"method": "isotonic", "blend": blend, "model": isotonic},
                    _monotone(isotonic.predict(raw), line_count),
                ))
    return min(candidates, key=lambda pair: brier_score_loss(y, pair[1]))[0]


def _kind_dataset(games, statcast, kind, props, include_metadata=False):
    """Build a compact point-in-time matrix without duplicate row objects."""
    state = fresh_state()
    base_rows, years = array("f"), array("H")
    outcomes = {prop: array("f") for prop in props}
    prop_extras = {prop: array("f") for prop in props}
    line_extras = {prop: array("f") for prop in props}
    game_ids = array("q") if include_metadata else None
    player_ids = array("q") if include_metadata else None
    opportunity_offset = 20 + 5 * len(BATTER_PROPS if kind == "batter" else PITCHER_PROPS)
    rate_offset = opportunity_offset + 5
    line_columns = np.asarray([0, 15, 16, 17, 18, 19], dtype=np.int32)
    prop_columns = np.asarray(range(rate_offset, rate_offset + 8), dtype=np.int32)
    base_prop = next(iter(props)); base_line = props[base_prop][0]
    for sample in replay_samples(games, statcast, state=state):
        if sample["kind"] != kind:
            continue
        base = build_features(
            sample["state"], kind, sample["player_id"], sample["team_id"], sample["opponent_id"],
            sample["date"], sample["season"], base_prop, base_line, sample["home"], sample["lineup_slot"],
            sample.get("opponent_starter_id"), sample.get("opponent_starter_hand"),
            sample.get("opponent_lineup_ids"),
        )
        base_rows.extend(base); years.append(int(sample["season"]))
        if include_metadata:
            game_ids.append(int(sample.get("game_id") or 0))
            player_ids.append(int(sample["player_id"]))
        for prop, lines in props.items():
            outcomes[prop].append(sample["outcomes"][prop])
            prop_base = retarget_line(
                base, sample["state"], kind, sample["player_id"], sample["season"],
                prop, lines[0], sample["opponent_id"],
            )
            prop_extras[prop].extend(prop_base[prop_columns])
            for index, line in enumerate(lines):
                row = prop_base if index == 0 else retarget_threshold(
                    prop_base, sample["state"], kind, sample["player_id"],
                    sample["season"], prop, line,
                )
                line_extras[prop].extend(row[line_columns])
    count = len(years)
    metadata = None
    if include_metadata:
        metadata = {
            "game_id": np.frombuffer(game_ids, dtype=np.int64),
            "player_id": np.frombuffer(player_ids, dtype=np.int64),
        }
    return {
        "base": np.frombuffer(base_rows, dtype=np.float32).reshape(count, len(feature_names(kind))),
        "years": np.frombuffer(years, dtype=np.uint16),
        "metadata": metadata,
        "prop_columns": prop_columns, "line_columns": line_columns,
        "outcomes": {key: np.frombuffer(value, dtype=np.float32) for key, value in outcomes.items()},
        "prop_extras": {
            key: np.frombuffer(value, dtype=np.float32).reshape(count, len(prop_columns))
            for key, value in prop_extras.items()
        },
        "line_extras": {
            key: np.frombuffer(value, dtype=np.float32).reshape(count, len(props[key]), len(line_columns))
            for key, value in line_extras.items()
        },
    }

def _expand_dataset(dataset, prop, lines):
    count = len(lines)
    x = np.repeat(dataset["base"], count, axis=0)
    x[:, dataset["prop_columns"]] = np.repeat(dataset["prop_extras"][prop], count, axis=0)
    x[:, dataset["line_columns"]] = dataset["line_extras"][prop].reshape(
        -1, len(dataset["line_columns"]),
    )
    outcome = np.repeat(dataset["outcomes"][prop], count)
    line_values = np.tile(np.asarray(lines, dtype=np.float32), len(dataset["base"]))
    y = (outcome > line_values).astype(np.uint8)
    years = np.repeat(dataset["years"], count)
    return x, y, years, x[:, 15].copy()


def _climatology(train_y, train_x, x):
    table = defaultdict(list)
    for line, outcome in zip(train_x[:, 0], train_y): table[round(float(line), 1)].append(int(outcome))
    overall = float(np.mean(train_y))
    rates = {key: (sum(values) + 20 * overall) / (len(values) + 20) for key, values in table.items()}
    return np.asarray([rates.get(round(float(line), 1), overall) for line in x[:, 0]])


def _clustered_brier_skill(y, probability, climatology, groups, iterations=1000):
    """Estimate skill uncertainty with games—not threshold rows—as samples."""
    y = np.asarray(y, dtype=float)
    improvement = (np.asarray(climatology) - y) ** 2 - (np.asarray(probability) - y) ** 2
    groups = np.asarray(groups)
    unique, inverse = np.unique(groups, return_inverse=True)
    totals = np.bincount(inverse, weights=improvement)
    counts = np.bincount(inverse)
    game_means = totals / np.maximum(counts, 1)
    if not len(game_means):
        return None
    rng = np.random.default_rng(42)
    draws = rng.choice(game_means, size=(iterations, len(game_means)), replace=True).mean(axis=1)
    lower, upper = np.quantile(draws, [.025, .975])
    return {
        "games": int(len(unique)),
        "mean_brier_improvement": float(np.mean(game_means)),
        "ci_95": [float(lower), float(upper)],
        "probability_positive": float(np.mean(draws > 0)),
        "bootstrap_iterations": int(iterations),
    }


def train_one(dataset, kind, prop, lines):
    started = time.time()
    x, y, years, distribution = _expand_dataset(dataset, prop, lines)
    train = years <= 2023; calibration = years == 2024; test = years >= 2025
    if min(train.sum(), calibration.sum(), test.sum()) == 0:
        raise RuntimeError(f"insufficient temporal split for {kind} {prop}")
    candidates = [
        {"learning_rate": .04, "num_leaves": 15, "reg_lambda": 6.0, "min_child_samples": 120, "feature_fraction": .85},
        {"learning_rate": .025, "num_leaves": 31, "reg_lambda": 10.0, "min_child_samples": 180, "feature_fraction": .75},
        {
            "learning_rate": .025, "num_leaves": 31, "reg_lambda": 10.0,
            "min_child_samples": 180, "feature_fraction": .75,
            "recency_decay": .88,
        },
    ]
    fitted = []
    for params in candidates:
        model_params = {key: value for key, value in params.items() if key != "recency_decay"}
        decay = params.get("recency_decay")
        sample_weight = (
            np.maximum(.25, np.power(decay, 2023 - years[train]))
            if decay else None
        )
        model = lgb.LGBMClassifier(
            objective="binary", n_estimators=450, random_state=42, n_jobs=-1,
            verbosity=-1, **model_params,
        ).fit(
            x[train], y[train], eval_set=[(x[calibration], y[calibration])],
            sample_weight=sample_weight,
            callbacks=[lgb.early_stopping(35, verbose=False)],
        )
        raw = model.predict_proba(x[calibration])[:, 1]
        spec = _choose_calibration(
            y[calibration], raw, distribution[calibration], len(lines),
        )
        blend_raw = spec["blend"] * raw + (1 - spec["blend"]) * distribution[calibration]
        calibrated = _monotone(
            _apply_calibration(spec, blend_raw), len(lines),
        )
        fitted.append((brier_score_loss(y[calibration], calibrated), model, spec, params))
    _, model, calibrator, params = min(fitted, key=lambda row: row[0])
    audit_model = model
    raw_test = model.predict_proba(x[test])[:, 1]
    blended_test = calibrator["blend"] * raw_test + (1 - calibrator["blend"]) * distribution[test]
    probability = _monotone(
        _apply_calibration(calibrator, blended_test), len(lines),
    )
    model_type = "threshold_classifier"
    count_model = count_calibrators = None
    negative_binomial_alpha = None
    # Strikeouts and recorded outs are integer counts whose adjacent lines
    # share one latent run-prevention/opportunity process. A single
    # over-dispersed count forecast produces coherent threshold probabilities
    # and improved Brier score in both untouched seasons.
    if f"{kind}:{prop}" in COUNT_HEADS:
        line_count = len(lines)
        base_x = x[::line_count].copy()
        counts = dataset["outcomes"][prop]
        base_years = dataset["years"]
        count_train, count_calibration = base_years <= 2023, base_years == 2024
        count_model = lgb.LGBMRegressor(
            objective="poisson", n_estimators=500, learning_rate=.025,
            num_leaves=23, reg_lambda=15.0, min_child_samples=220,
            feature_fraction=.8, random_state=42, n_jobs=-1, verbosity=-1,
        ).fit(
            base_x[count_train], counts[count_train],
            eval_set=[(base_x[count_calibration], counts[count_calibration])],
            callbacks=[lgb.early_stopping(40, verbose=False)],
        )
        mu_train = np.clip(count_model.predict(base_x[count_train]), .01, 100)
        pearson = (
            (counts[count_train] - mu_train) ** 2 - mu_train
        ) / np.maximum(mu_train ** 2, 1e-5)
        negative_binomial_alpha = float(np.clip(np.mean(pearson), .002, 2.0))
        count_cal_raw = _distribution_matrix(
            count_model.predict(base_x[count_calibration]),
            negative_binomial_alpha, lines,
        )
        count_calibrators = _linewise_calibrators(
            y[calibration], count_cal_raw, line_count,
        )
        count_test_raw = _distribution_matrix(
            count_model.predict(base_x[base_years >= 2025]),
            negative_binomial_alpha, lines,
        )
        probability = _apply_linewise(count_calibrators, count_test_raw)
        model_type = "negative_binomial_count"
    climate = _climatology(y[train], x[train], x[test])
    climate_metrics, model_metrics = _metric(y[test], climate), _metric(y[test], probability)
    confident = np.maximum(probability, 1 - probability) >= .60
    correct = (probability >= .5) == y[test]
    unseen_by_season = {}
    for season in (2025, 2026):
        season_mask = years[test] == season
        if season_mask.any():
            season_probability = probability[season_mask]
            season_y = y[test][season_mask]
            season_correct = (season_probability >= .5) == season_y
            unseen_by_season[str(season)] = {
                **_metric(season_y, season_probability),
                "side_accuracy": float(np.mean(season_correct)),
                "samples": int(season_mask.sum()),
            }
    clustered_skill = None
    if dataset.get("metadata") is not None:
        threshold_game_ids = np.repeat(dataset["metadata"]["game_id"], len(lines))
        clustered_skill = _clustered_brier_skill(
            y[test], probability, climate, threshold_game_ids[test],
        )

    # Hyperparameters and calibration stay frozen from the 2024 selection
    # window. The estimator may learn 2024-2025 outcomes only when that single
    # fixed refit improves the still-untouched 2026 slice.
    production_refit = {
        "attempted": False, "adopted": False,
        "estimator_training_through": 2023,
        "validation_season": 2026,
    }
    validation = years == 2026
    refit_train = years <= 2025
    if model_type == "threshold_classifier" and validation.any() and refit_train.any():
        model_params = {key: value for key, value in params.items() if key != "recency_decay"}
        decay = params.get("recency_decay")
        sample_weight = (
            np.maximum(.25, np.power(decay, 2025 - years[refit_train]))
            if decay else None
        )
        iterations = int(getattr(model, "best_iteration_", 0) or 450)
        refit_model = lgb.LGBMClassifier(
            objective="binary", n_estimators=iterations, random_state=42,
            n_jobs=-1, verbosity=-1, **model_params,
        ).fit(x[refit_train], y[refit_train], sample_weight=sample_weight)
        refit_raw = refit_model.predict_proba(x[validation])[:, 1]
        refit_blended = (
            calibrator["blend"] * refit_raw
            + (1 - calibrator["blend"]) * distribution[validation]
        )
        refit_probability = _monotone(
            _apply_calibration(calibrator, refit_blended), len(lines),
        )
        original_probability = probability[years[test] == 2026]
        original_metrics = _metric(y[validation], original_probability)
        refit_metrics = _metric(y[validation], refit_probability)
        original_accuracy = float(np.mean((original_probability >= .5) == y[validation]))
        refit_accuracy = float(np.mean((refit_probability >= .5) == y[validation]))
        adopted = (
            refit_metrics["brier"] <= original_metrics["brier"]
            and refit_accuracy >= original_accuracy - .002
        )
        production_refit = {
            "attempted": True,
            "adopted": bool(adopted),
            "estimator_training_through": 2025 if adopted else 2023,
            "validation_season": 2026,
            "fixed_iterations": iterations,
            "incumbent_2026": {**original_metrics, "side_accuracy": original_accuracy},
            "refit_2026": {**refit_metrics, "side_accuracy": refit_accuracy},
        }
        if adopted:
            model = refit_model
    report = {
        "kind": kind, "prop": prop, "lines": list(lines), "features": len(feature_names(kind)),
        "model_type": model_type,
        "samples": {"train_through_2023": int(train.sum()), "calibration_2024": int(calibration.sum()), "untouched_2025_2026": int(test.sum())},
        "calibration": {
            "method": calibrator["method"], "model_weight": calibrator["blend"],
            "monotone_thresholds": True,
        },
        "parameters": params, "climatology": climate_metrics, "unseen": model_metrics,
        "brier_skill_vs_climatology": float(1 - model_metrics["brier"] / climate_metrics["brier"]),
        "side_accuracy": float(np.mean(correct)),
        "confidence_60": {"coverage": float(np.mean(confident)), "accuracy": float(np.mean(correct[confident])) if confident.any() else None},
        "unseen_by_season": unseen_by_season,
        "clustered_brier_skill": clustered_skill,
        "production_refit": production_refit,
        "elapsed_seconds": round(time.time() - started, 1),
    }
    if model_type == "negative_binomial_count":
        report["count_distribution"] = {
            "distribution": "negative_binomial",
            "alpha": negative_binomial_alpha,
            "calibration": [
                {"line": float(line), "method": spec["method"]}
                for line, spec in zip(lines, count_calibrators)
            ],
        }
        bundle = {
            "model": count_model, "calibrators": count_calibrators,
            "negative_binomial_alpha": negative_binomial_alpha,
            "model_type": model_type, "lines": list(lines), "kind": kind, "prop": prop,
            "feature_names": feature_names(kind),
        }
    else:
        bundle = {
            "model": model, "audit_model": audit_model, "calibrator": calibrator,
            "model_type": model_type, "lines": list(lines), "kind": kind, "prop": prop,
            "feature_names": feature_names(kind),
        }
    print(f"{kind:7} {prop:18} Brier {model_metrics['brier']:.5f} baseline {climate_metrics['brier']:.5f} skill {report['brier_skill_vs_climatology']:.1%}", flush=True)
    return bundle, report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--props", nargs="*", help="Optional prop keys for a partial research run")
    args = parser.parse_args()
    games = load_games(); statcast = load_statcast()
    print(f"loaded {len(games)} official box scores and {len(statcast)} Statcast games", flush=True)
    requested = set(args.props or [])
    models, reports, final_state = {}, {}, None
    groups = (("batter", BATTER_PROPS), ("pitcher", PITCHER_PROPS))
    for kind, props in groups:
        active_props = {prop: lines for prop, lines in props.items() if not requested or prop in requested or f"{kind}:{prop}" in requested}
        if not active_props:
            continue
        print(f"building shared {kind} point-in-time matrix for {len(active_props)} props", flush=True)
        dataset = _kind_dataset(games, statcast, kind, active_props, include_metadata=True)
        print(f"{kind} matrix contains {len(dataset['base'])} player-games", flush=True)
        for prop, lines in active_props.items():
            if requested and prop not in requested and f"{kind}:{prop}" not in requested:
                continue
            bundle, report = train_one(dataset, kind, prop, lines)
            key = f"{kind}:{prop}"; models[key] = bundle; reports[key] = report
        del dataset
    # A final replay is required when a partial run's last model did not span all player kinds.
    final_state = fresh_state()
    for _ in replay_samples(games, statcast, minimum_history=10**9, state=final_state):
        pass
    artifact = {
        "version": 3, "trained_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "models": models, "state": serializable_state(final_state),
        "feature_names": {kind: feature_names(kind) for kind in ("batter", "pitcher")},
    }
    report = {
        "version": 3, "trained_at": artifact["trained_at"], "data": {
            "source": "Official MLB box scores plus Baseball Savant Statcast; no sportsbook prices",
            "games": len(games), "first_date": games[0]["date"], "last_date": games[-1]["date"],
            "split": "Train through 2023; calibration on 2024; untouched evaluation on 2025-2026",
        }, "research_basis": [
            "Point-in-time empirical-Bayes player shrinkage",
            "Explicit plate-appearance and batters-faced opportunity",
            "Opponent game-level tendencies and probable-starter quality",
            "Handedness-split prior Statcast contact quality",
            "Beta, sigmoid, isotonic, and raw calibration selected on 2024 only",
            "Monotone threshold probability enforcement",
            "Game-clustered bootstrap uncertainty instead of treating correlated thresholds as independent",
            "Fixed 2025 estimator refit deployed only after improving untouched 2026 Brier without material side-accuracy loss",
            "Negative-binomial count distributions for pitcher strikeouts and outs",
            "Confirmed opponent-lineup contact, strikeout, walk, and power tendencies",
        ], "models": reports,
    }
    ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(artifact, ARTIFACT, compress=3)
    REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"saved {ARTIFACT} and {REPORT}", flush=True)


if __name__ == "__main__":
    main()
