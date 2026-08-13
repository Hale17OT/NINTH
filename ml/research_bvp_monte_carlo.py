"""Leakage-safe batter-versus-pitcher plate-appearance simulation research.

This module is shadow-only.  It trains a multinomial plate-appearance model and
an exposure model on games through 2023, uses 2024 only for calibration, and
reports untouched 2025/2026 results.  It never overwrites a production artifact.

The broad temporal audit is evaluated with the exact finite distribution to
avoid adding Monte Carlo noise to model comparisons.  ``simulate_matchup`` is
the production-shaped Monte Carlo engine, and the report checks it against that
exact distribution on held-out matchups.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import joblib
import lightgbm as lgb
import numpy as np
from sklearn.metrics import brier_score_loss, log_loss

from ml.evaluate_observed_prop_lines import (
    observed_lines,
    probabilities as incumbent_probabilities,
)
from ml.player_props_features import (
    BATTER_PROPS,
    feature_names,
    load_games,
    load_statcast,
)
from ml.train_player_props import (
    _apply_linewise,
    _expand_dataset,
    _kind_dataset,
    _linewise_calibrators,
)


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "ml" / "artifacts" / "bvp_monte_carlo_shadow.json"
ARTIFACT = ROOT / "ml" / "artifacts" / "bvp_monte_carlo_shadow.joblib"
INCUMBENT = ROOT / "ml" / "artifacts" / "player_props.joblib"

OUTCOMES = (
    "other_out", "strikeout", "walk", "hit_by_pitch", "single",
    "double", "triple", "home_run",
)
BASE_VALUES = np.asarray((0, 0, 0, 0, 1, 2, 3, 4), dtype=np.int8)
HIT_MASK = np.asarray((0, 0, 0, 0, 1, 1, 1, 1), dtype=np.int8)
HR_MASK = np.asarray((0, 0, 0, 0, 0, 0, 0, 1), dtype=np.int8)
K_MASK = np.asarray((0, 1, 0, 0, 0, 0, 0, 0), dtype=np.int8)
WALK_MASK = np.asarray((0, 0, 1, 0, 0, 0, 0, 0), dtype=np.int8)
DOUBLE_MASK = np.asarray((0, 0, 0, 0, 0, 1, 0, 0), dtype=np.int8)
PA_PROP_LINES = {
    key: BATTER_PROPS[key]
    for key in (
        "hits", "total_bases", "home_runs", "walks", "strikeouts", "doubles",
    )
}
CONTEXT_PROP_LINES = {
    key: BATTER_PROPS[key] for key in ("runs", "rbi", "stolen_bases")
}
PROP_LINES = {**PA_PROP_LINES, **CONTEXT_PROP_LINES}
AUXILIARY_MAX = {"runs": 5, "rbi": 8, "stolen_bases": 3}

# Threshold-specific fields are useful to the deployed binary classifiers but
# would make one supposedly coherent PA distribution depend on an arbitrary
# prop line.  The multinomial model retains the stable player, starter, platoon,
# contact-quality, discipline, opportunity, and context fields.
EXCLUDED_FEATURES = {
    "line", "distribution_over", "over_rate_5", "over_rate_10",
    "over_rate_20", "over_rate_season", "prop_per_opportunity_5",
    "prop_per_opportunity_10", "prop_per_opportunity_20",
    "prop_per_opportunity_season", "prop_per_opportunity_prior",
    "opponent_prop_5", "opponent_prop_10", "opponent_prop_20",
}


def _outcome_labels(games):
    """Return same-game labels keyed by game/player; never used as features."""
    labels = {}
    for game in games:
        for side in ("away", "home"):
            for player in game[side]["players"]:
                batting = player.get("batting") or {}
                pa = int(batting.get("plateAppearances") or 0)
                if pa <= 0:
                    continue
                hits = int(batting.get("hits") or 0)
                doubles = int(batting.get("doubles") or 0)
                triples = int(batting.get("triples") or 0)
                homers = int(batting.get("homeRuns") or 0)
                strikeouts = int(batting.get("strikeOuts") or 0)
                walks = int(batting.get("baseOnBalls") or 0)
                hit_by_pitch = int(batting.get("hitByPitch") or 0)
                singles = hits - doubles - triples - homers
                other_outs = pa - strikeouts - walks - hit_by_pitch - hits
                counts = np.asarray(
                    (
                        other_outs, strikeouts, walks, hit_by_pitch, singles,
                        doubles, triples, homers,
                    ),
                    dtype=np.int16,
                )
                if np.any(counts < 0) or int(counts.sum()) != pa:
                    continue
                order = str(player.get("batting_order") or "")
                labels[(int(game["game_id"]), int(player["player_id"]))] = {
                    "counts": counts,
                    "pa": pa,
                    "starter": len(order) >= 3 and order[1:] == "00",
                }
    return labels


def _calibrate_categorical(raw, counts):
    """Select temperature and prior blending by weighted multinomial log loss."""
    raw = np.clip(np.asarray(raw, dtype=float), 1e-8, 1)
    counts = np.asarray(counts, dtype=float)
    prior = (counts.sum(axis=0) + 1) / (counts.sum() + counts.shape[1])
    best = None
    for temperature in np.linspace(.7, 1.6, 19):
        powered = raw ** (1 / temperature)
        powered /= powered.sum(axis=1, keepdims=True)
        for blend in (0.0, .03, .06, .10, .15, .25):
            probability = (1 - blend) * powered + blend * prior
            loss = -float(
                np.sum(counts * np.log(np.clip(probability, 1e-8, 1)))
                / max(1, counts.sum())
            )
            candidate = (loss, float(temperature), float(blend), prior)
            if best is None or candidate[0] < best[0]:
                best = candidate
    return {
        "temperature": best[1],
        "prior_blend": best[2],
        "prior": best[3],
        "calibration_log_loss": best[0],
    }


def _apply_categorical_calibration(raw, spec):
    raw = np.clip(np.asarray(raw, dtype=float), 1e-8, 1)
    powered = raw ** (1 / float(spec["temperature"]))
    powered /= powered.sum(axis=1, keepdims=True)
    probability = (
        (1 - float(spec["prior_blend"])) * powered
        + float(spec["prior_blend"]) * np.asarray(spec["prior"])
    )
    return probability / probability.sum(axis=1, keepdims=True)


def _expanded_counts(x, counts):
    row = np.repeat(np.arange(len(x)), len(OUTCOMES))
    target = np.tile(np.arange(len(OUTCOMES)), len(x))
    weight = counts.reshape(-1)
    keep = weight > 0
    return x[row[keep]], target[keep], weight[keep]


def _fit_models(x, counts, pa, years):
    train, calibration = years <= 2023, years == 2024
    train_x, train_y, train_weight = _expanded_counts(x[train], counts[train])
    cal_x, cal_y, cal_weight = _expanded_counts(x[calibration], counts[calibration])
    outcome_model = lgb.LGBMClassifier(
        objective="multiclass",
        num_class=len(OUTCOMES),
        n_estimators=450,
        learning_rate=.035,
        num_leaves=31,
        min_child_samples=180,
        reg_lambda=12.0,
        feature_fraction=.8,
        random_state=42,
        n_jobs=-1,
        verbosity=-1,
    ).fit(
        train_x,
        train_y,
        sample_weight=train_weight,
        eval_set=[(cal_x, cal_y)],
        eval_sample_weight=[cal_weight],
        callbacks=[lgb.early_stopping(40, verbose=False)],
    )
    outcome_spec = _calibrate_categorical(
        outcome_model.predict_proba(x[calibration]),
        counts[calibration],
    )

    pa_target = np.clip(pa, 1, 7) - 1
    exposure_model = lgb.LGBMClassifier(
        objective="multiclass",
        num_class=7,
        n_estimators=350,
        learning_rate=.035,
        num_leaves=23,
        min_child_samples=200,
        reg_lambda=12.0,
        feature_fraction=.8,
        random_state=43,
        n_jobs=-1,
        verbosity=-1,
    ).fit(
        x[train],
        pa_target[train],
        eval_set=[(x[calibration], pa_target[calibration])],
        callbacks=[lgb.early_stopping(35, verbose=False)],
    )
    exposure_counts = np.eye(7, dtype=float)[pa_target[calibration]]
    exposure_spec = _calibrate_categorical(
        exposure_model.predict_proba(x[calibration]),
        exposure_counts,
    )
    return outcome_model, outcome_spec, exposure_model, exposure_spec


def _fit_auxiliary_models(x, dataset, selected, years):
    """Fit context-dependent whole-game heads for runs, RBIs, and steals.

    These events depend on runners, following hitters, and steal decisions, so
    they are deliberately separate from the terminal PA head.  Each head still
    yields one coherent count distribution rather than unrelated thresholds.
    """
    train, calibration = years <= 2023, years == 2024
    models, specifications = {}, {}
    for offset, (prop, maximum) in enumerate(AUXILIARY_MAX.items()):
        target = np.clip(
            dataset["outcomes"][prop][selected].astype(int), 0, maximum,
        )
        model = lgb.LGBMClassifier(
            objective="multiclass",
            num_class=maximum + 1,
            n_estimators=400,
            learning_rate=.035,
            num_leaves=23,
            min_child_samples=200,
            reg_lambda=14.0,
            feature_fraction=.8,
            random_state=50 + offset,
            n_jobs=-1,
            verbosity=-1,
        ).fit(
            x[train],
            target[train],
            eval_set=[(x[calibration], target[calibration])],
            callbacks=[lgb.early_stopping(35, verbose=False)],
        )
        counts = np.eye(maximum + 1, dtype=float)[target[calibration]]
        models[prop] = model
        specifications[prop] = _calibrate_categorical(
            model.predict_proba(x[calibration]), counts,
        )
    return models, specifications


def simulate_matchup(
    pa_probabilities,
    outcome_probabilities,
    auxiliary_probabilities=None,
    simulations=100_000,
    seed=42,
):
    """Simulate one batter's full-game hits/TB/HR/K distribution."""
    pa_probability = np.asarray(pa_probabilities, dtype=float)
    outcome_probability = np.asarray(outcome_probabilities, dtype=float)
    if (
        pa_probability.shape != (7,)
        or outcome_probability.shape != (len(OUTCOMES),)
    ):
        raise ValueError(
            "expected seven PA probabilities and one probability per outcome",
        )
    pa_probability = pa_probability / pa_probability.sum()
    outcome_probability = outcome_probability / outcome_probability.sum()
    rng = np.random.default_rng(seed)
    pa = rng.choice(np.arange(1, 8), size=int(simulations), p=pa_probability)
    outcomes = np.empty((int(simulations), 7), dtype=np.int8)
    cumulative = np.cumsum(outcome_probability)
    for index in range(7):
        outcomes[:, index] = np.searchsorted(
            cumulative, rng.random(int(simulations)), side="right",
        )
    active = np.arange(7)[None, :] < pa[:, None]
    return {
        **{
            prop: rng.choice(
                np.arange(len(probability)),
                size=int(simulations),
                p=np.asarray(probability) / np.sum(probability),
            )
            for prop, probability in (auxiliary_probabilities or {}).items()
        },
        "plate_appearances": pa,
        "hits": ((HIT_MASK[outcomes] * active).sum(axis=1)),
        "total_bases": ((BASE_VALUES[outcomes] * active).sum(axis=1)),
        "home_runs": ((HR_MASK[outcomes] * active).sum(axis=1)),
        "walks": ((WALK_MASK[outcomes] * active).sum(axis=1)),
        "strikeouts": ((K_MASK[outcomes] * active).sum(axis=1)),
        "doubles": ((DOUBLE_MASK[outcomes] * active).sum(axis=1)),
    }


def _exact_probability_matrices(
    pa_probability,
    outcome_probability,
    auxiliary_probability=None,
):
    """Exact full-game over probabilities for every configured threshold."""
    pa_probability = np.asarray(pa_probability, dtype=float)
    outcome_probability = np.asarray(outcome_probability, dtype=float)
    sample_count = len(pa_probability)
    result = {
        prop: np.zeros((sample_count, len(lines)), dtype=float)
        for prop, lines in PROP_LINES.items()
    }
    hit_p = outcome_probability[:, 4:].sum(axis=1)
    hr_p = outcome_probability[:, 7]
    walk_p = outcome_probability[:, 2]
    k_p = outcome_probability[:, 1]
    double_p = outcome_probability[:, 5]
    # DP distribution of total bases after exactly n iid plate appearances.
    tb = np.zeros((sample_count, 29), dtype=float)
    tb[:, 0] = 1.0
    for appearances in range(1, 8):
        updated = np.zeros_like(tb)
        for category, bases in enumerate(BASE_VALUES):
            updated[:, bases:] += (
                tb[:, : 29 - bases] * outcome_probability[:, category, None]
            )
        tb = updated
        exposure_weight = pa_probability[:, appearances - 1, None]
        for prop, event_p in (
            ("hits", hit_p),
            ("home_runs", hr_p),
            ("walks", walk_p),
            ("strikeouts", k_p),
            ("doubles", double_p),
        ):
            # A small direct recurrence avoids constructing an N x 7 x 7 cube.
            distribution = np.zeros((sample_count, appearances + 1), dtype=float)
            distribution[:, 0] = (1 - event_p) ** appearances
            for count in range(1, appearances + 1):
                distribution[:, count] = (
                    distribution[:, count - 1]
                    * (appearances - count + 1) / count
                    * event_p / np.clip(1 - event_p, 1e-10, 1)
                )
            for line_index, line in enumerate(PROP_LINES[prop]):
                result[prop][:, line_index] += (
                    exposure_weight[:, 0]
                    * distribution[:, int(np.floor(line)) + 1 :].sum(axis=1)
                )
        for line_index, line in enumerate(PROP_LINES["total_bases"]):
            result["total_bases"][:, line_index] += (
                exposure_weight[:, 0]
                * tb[:, int(np.floor(line)) + 1 :].sum(axis=1)
            )
    for prop, probability in (auxiliary_probability or {}).items():
        for line_index, line in enumerate(PROP_LINES[prop]):
            result[prop][:, line_index] = probability[
                :, int(np.floor(line)) + 1 :
            ].sum(axis=1)
    return result


def exact_matchup_probabilities(
    pa_probabilities,
    outcome_probabilities,
    auxiliary_probabilities=None,
):
    """Convenience form of the exact distribution for a single matchup."""
    matrices = _exact_probability_matrices(
        np.asarray(pa_probabilities, dtype=float).reshape(1, 7),
        np.asarray(outcome_probabilities, dtype=float).reshape(1, len(OUTCOMES)),
        {
            prop: np.asarray(probability, dtype=float).reshape(1, -1)
            for prop, probability in (auxiliary_probabilities or {}).items()
        },
    )
    return {
        prop: {
            float(line): float(values[0, index])
            for index, line in enumerate(PROP_LINES[prop])
        }
        for prop, values in matrices.items()
    }


def _metric(y, probability):
    y = np.asarray(y, dtype=np.uint8)
    probability = np.clip(np.asarray(probability, dtype=float), 1e-5, 1 - 1e-5)
    correct = (probability >= .5) == y
    calibration_parts = []
    for lower in np.linspace(0, .9, 10):
        mask = (probability >= lower) & (probability < lower + .1)
        if np.any(mask):
            calibration_parts.append(
                np.mean(mask)
                * abs(float(np.mean(probability[mask]) - np.mean(y[mask])))
            )
    return {
        "samples": int(len(y)),
        "brier": round(float(brier_score_loss(y, probability)), 7),
        "log_loss": round(float(log_loss(y, probability, labels=[0, 1])), 7),
        "side_accuracy": round(float(np.mean(correct)), 7),
        "expected_calibration_error_10_bin": round(
            float(np.sum(calibration_parts)), 7,
        ),
    }


def paired_game_bootstrap(
    y,
    challenger,
    incumbent,
    game_ids,
    resamples=2_000,
    seed=2026,
):
    """Paired game-block bootstrap of the challenger-minus-incumbent Brier."""
    y = np.asarray(y, dtype=float)
    challenger = np.asarray(challenger, dtype=float)
    incumbent = np.asarray(incumbent, dtype=float)
    game_ids = np.asarray(game_ids)
    delta = (challenger - y) ** 2 - (incumbent - y) ** 2
    unique, inverse = np.unique(game_ids, return_inverse=True)
    sums = np.bincount(inverse, weights=delta)
    counts = np.bincount(inverse)
    game_delta = sums / np.maximum(counts, 1)
    rng = np.random.default_rng(seed)
    samples = np.empty(int(resamples), dtype=float)
    for index in range(int(resamples)):
        samples[index] = np.mean(
            game_delta[rng.integers(0, len(unique), size=len(unique))]
        )
    return {
        "brier_delta_simulator_minus_incumbent": round(float(np.mean(delta)), 7),
        "game_block_bootstrap_95_ci": [
            round(float(value), 7)
            for value in np.quantile(samples, (.025, .975))
        ],
        "bootstrap_probability_of_improvement": round(
            float(np.mean(samples < 0)), 5,
        ),
        "games": int(len(unique)),
        "resamples": int(resamples),
    }


def _incumbent_matrices(dataset, artifact, selected):
    output = {}
    current_names = feature_names("batter")
    artifact_names = (artifact.get("feature_names") or {}).get(
        "batter",
    ) or current_names
    columns = [current_names.index(name) for name in artifact_names]
    for prop, lines in PROP_LINES.items():
        bundle = artifact["models"].get(f"batter:{prop}")
        if not bundle:
            continue
        x, _, _, distribution = _expand_dataset(dataset, prop, lines)
        probability = incumbent_probabilities(
            bundle, x[:, columns], distribution, len(dataset["base"]),
        ).reshape(-1, len(lines))
        output[prop] = probability[selected]
    return output


def _audit(
    dataset,
    selected,
    years,
    exact,
    calibrated,
    incumbent,
    metadata,
):
    report = {}
    offered = observed_lines()
    for prop, lines in PROP_LINES.items():
        actual_count = dataset["outcomes"][prop][selected]
        actual = actual_count[:, None] > np.asarray(lines)[None, :]
        report[prop] = {}
        for label, mask in (
            ("2025_2026", years >= 2025),
            ("2025", years == 2025),
            ("2026", years == 2026),
        ):
            if not np.any(mask):
                continue
            row = {
                "simulator": _metric(actual[mask].reshape(-1), calibrated[prop][mask].reshape(-1)),
                "raw_simulator": _metric(actual[mask].reshape(-1), exact[prop][mask].reshape(-1)),
            }
            if prop in incumbent:
                row["incumbent"] = _metric(
                    actual[mask].reshape(-1), incumbent[prop][mask].reshape(-1),
                )
                row["paired_uncertainty"] = paired_game_bootstrap(
                    actual[mask].reshape(-1),
                    calibrated[prop][mask].reshape(-1),
                    incumbent[prop][mask].reshape(-1),
                    np.repeat(metadata["game_id"][mask], len(lines)),
                    seed=2026 + list(PROP_LINES).index(prop),
                )
                row["per_line"] = {
                    str(line): {
                        "simulator": _metric(
                            actual[mask, line_index],
                            calibrated[prop][mask, line_index],
                        ),
                        "incumbent": _metric(
                            actual[mask, line_index],
                            incumbent[prop][mask, line_index],
                        ),
                    }
                    for line_index, line in enumerate(lines)
                }
            report[prop][label] = row

        listed_y, listed_sim, listed_incumbent = [], [], []
        for index, (game_id, player_id) in enumerate(
            zip(metadata["game_id"], metadata["player_id"])
        ):
            line = offered.get((int(game_id), int(player_id), "batter", prop))
            if line is None or float(line) not in {float(value) for value in lines}:
                continue
            line_index = list(lines).index(float(line))
            listed_y.append(int(actual[index, line_index]))
            listed_sim.append(float(calibrated[prop][index, line_index]))
            if prop in incumbent:
                listed_incumbent.append(float(incumbent[prop][index, line_index]))
        if listed_y:
            report[prop]["exact_listed_lines"] = {
                "simulator": _metric(listed_y, listed_sim),
                **(
                    {"incumbent": _metric(listed_y, listed_incumbent)}
                    if listed_incumbent else {}
                ),
                **(
                    {
                        "paired_uncertainty": paired_game_bootstrap(
                            listed_y,
                            listed_sim,
                            listed_incumbent,
                            [
                                game_id
                                for game_id, player_id in zip(
                                    metadata["game_id"], metadata["player_id"],
                                )
                                if offered.get((
                                    int(game_id), int(player_id),
                                    "batter", prop,
                                )) is not None
                                and float(offered[(
                                    int(game_id), int(player_id),
                                    "batter", prop,
                                )]) in {float(value) for value in lines}
                            ],
                            resamples=5_000,
                            seed=3026 + list(PROP_LINES).index(prop),
                        )
                    }
                    if listed_incumbent else {}
                ),
            }
    return report


def _monte_carlo_check(
    pa_probability,
    outcome_probability,
    auxiliary_probability,
    sample_indexes,
    simulations,
):
    differences = []
    for check_index, row_index in enumerate(sample_indexes):
        exact = exact_matchup_probabilities(
            pa_probability[row_index],
            outcome_probability[row_index],
            {
                prop: probability[row_index]
                for prop, probability in auxiliary_probability.items()
            },
        )
        draws = simulate_matchup(
            pa_probability[row_index],
            outcome_probability[row_index],
            {
                prop: probability[row_index]
                for prop, probability in auxiliary_probability.items()
            },
            simulations=simulations,
            seed=10_000 + check_index,
        )
        for prop, lines in PROP_LINES.items():
            for line in lines:
                monte_carlo = float(np.mean(draws[prop] > line))
                differences.append(abs(monte_carlo - exact[prop][float(line)]))
    return {
        "matchups": int(len(sample_indexes)),
        "simulations_per_matchup": int(simulations),
        "comparisons": int(len(differences)),
        "mean_absolute_error": round(float(np.mean(differences)), 7),
        "maximum_absolute_error": round(float(np.max(differences)), 7),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", default=str(REPORT))
    parser.add_argument("--artifact", default=str(ARTIFACT))
    parser.add_argument("--incumbent", default=str(INCUMBENT))
    parser.add_argument("--mc-check-matchups", type=int, default=40)
    parser.add_argument("--simulations", type=int, default=50_000)
    args = parser.parse_args()

    games, statcast = load_games(), load_statcast()
    labels = _outcome_labels(games)
    dataset = _kind_dataset(
        games, statcast, "batter", PROP_LINES, include_metadata=True,
    )
    metadata = dataset["metadata"]
    label_rows = [
        labels.get((int(game_id), int(player_id)))
        for game_id, player_id in zip(metadata["game_id"], metadata["player_id"])
    ]
    selected = np.asarray([
        row is not None and row["starter"] for row in label_rows
    ])
    selected_labels = [row for row, keep in zip(label_rows, selected) if keep]
    counts = np.asarray([row["counts"] for row in selected_labels], dtype=np.int16)
    pa = np.asarray([row["pa"] for row in selected_labels], dtype=np.int8)
    years = dataset["years"][selected].astype(int)
    all_names = feature_names("batter")
    feature_indexes = np.asarray([
        index for index, name in enumerate(all_names)
        if name not in EXCLUDED_FEATURES
    ])
    x = dataset["base"][selected][:, feature_indexes]

    outcome_model, outcome_spec, exposure_model, exposure_spec = _fit_models(
        x, counts, pa, years,
    )
    auxiliary_models, auxiliary_specs = _fit_auxiliary_models(
        x, dataset, selected, years,
    )
    outcome_probability = _apply_categorical_calibration(
        outcome_model.predict_proba(x), outcome_spec,
    )
    pa_probability = _apply_categorical_calibration(
        exposure_model.predict_proba(x), exposure_spec,
    )
    auxiliary_probability = {
        prop: _apply_categorical_calibration(
            model.predict_proba(x), auxiliary_specs[prop],
        )
        for prop, model in auxiliary_models.items()
    }
    exact = _exact_probability_matrices(
        pa_probability, outcome_probability, auxiliary_probability,
    )

    calibration = years == 2024
    calibrators = {}
    calibrated = {}
    for prop, lines in PROP_LINES.items():
        actual = dataset["outcomes"][prop][selected]
        y = actual[:, None] > np.asarray(lines)[None, :]
        calibrators[prop] = _linewise_calibrators(
            y[calibration].reshape(-1),
            exact[prop][calibration],
            len(lines),
        )
        calibrated[prop] = _apply_linewise(
            calibrators[prop], exact[prop],
        ).reshape(-1, len(lines))

    incumbent_path = Path(args.incumbent)
    incumbent = (
        _incumbent_matrices(dataset, joblib.load(incumbent_path), selected)
        if incumbent_path.exists() else {}
    )
    selected_metadata = {
        key: values[selected] for key, values in metadata.items()
    }
    audit = _audit(
        dataset, selected, years, exact, calibrated, incumbent,
        selected_metadata,
    )
    promotion_summary = {
        "decision": "retain_shadow_only",
        "reason": (
            "Promotion is decided market by market from the broad temporal "
            "audit, paired game-block uncertainty, both audit seasons, and "
            "immutable exact listed-line evidence. The comprehensive decision "
            "is recorded in SIMULATION_FULL_AUDIT.md."
        ),
        "markets_tested": list(PROP_LINES),
        "required_next_gate": (
            "Accumulate materially more immutable exact listed-line samples "
            "and require aggregate plus season-by-season Brier improvement "
            "without a material key-line regression."
        ),
    }
    held_out = np.flatnonzero(years >= 2025)
    rng = np.random.default_rng(2026)
    check_count = min(max(1, args.mc_check_matchups), len(held_out))
    check_indexes = rng.choice(held_out, size=check_count, replace=False)
    mc_check = _monte_carlo_check(
        pa_probability,
        outcome_probability,
        auxiliary_probability,
        check_indexes,
        args.simulations,
    )

    artifact = {
        "status": "shadow_only",
        "outcomes": OUTCOMES,
        "plate_appearances": list(range(1, 8)),
        "prop_lines": PROP_LINES,
        "feature_names": [all_names[index] for index in feature_indexes],
        "outcome_model": outcome_model,
        "outcome_calibration": outcome_spec,
        "exposure_model": exposure_model,
        "exposure_calibration": exposure_spec,
        "auxiliary_models": auxiliary_models,
        "auxiliary_calibrations": auxiliary_specs,
        "prop_calibrators": calibrators,
    }
    artifact_path = Path(args.artifact)
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(artifact, artifact_path)

    report = {
        "status": "shadow_only",
        "production_changed": False,
        "policy": (
            "Train through 2023; calibrate on 2024; audit 2025 and 2026. "
            "Current-game outcomes are labels only and never enter features."
        ),
        "architecture": {
            "plate_appearance_outcomes": list(OUTCOMES),
            "context_dependent_count_heads": list(AUXILIARY_MAX),
            "exposure_values": list(range(1, 8)),
            "advanced_matchup_features": [
                name for name in artifact["feature_names"]
                if name.startswith(("opponent_starter_", "platoon_"))
                or name.startswith(("xwoba_", "hard_hit_", "barrel_", "whiff_"))
            ],
            "broad_audit_engine": "exact finite distribution",
            "serving_engine": "Monte Carlo",
        },
        "samples": {
            "all_starting_batter_games": int(len(years)),
            **{
                str(year): int(np.sum(years == year))
                for year in sorted(set(years))
            },
        },
        "categorical_calibration": {
            "outcome": {
                key: value.tolist() if isinstance(value, np.ndarray) else value
                for key, value in outcome_spec.items()
            },
            "exposure": {
                key: value.tolist() if isinstance(value, np.ndarray) else value
                for key, value in exposure_spec.items()
            },
        },
        "monte_carlo_exactness_check": mc_check,
        "promotion_summary": promotion_summary,
        "audit": audit,
        "artifact": str(artifact_path),
    }
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
