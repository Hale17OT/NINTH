"""Shadow-only pitcher-vs-lineup Monte Carlo distribution research.

The model separates workload from per-batter outcomes.  It simulates batters
faced, then samples strikeout, walk, non-HR hit, HR, or other plate appearance
for every matchup. Outs, earned runs, and pitch count use separate
overdispersed whole-start count heads because double plays and run attribution
cannot be reconstructed from terminal plate-appearance categories alone.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import joblib
import lightgbm as lgb
import numpy as np
from scipy.stats import nbinom, poisson

from ml.evaluate_observed_prop_lines import (
    observed_lines,
    probabilities as incumbent_probabilities,
)
from ml.player_props_features import (
    PITCHER_PROPS,
    feature_names,
    load_games,
    load_statcast,
)
from ml.research_bvp_monte_carlo import (
    _apply_categorical_calibration,
    _calibrate_categorical,
    _metric,
    paired_game_bootstrap,
)
from ml.train_player_props import (
    _apply_linewise,
    _expand_dataset,
    _kind_dataset,
    _linewise_calibrators,
)


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "ml" / "artifacts" / "pitcher_monte_carlo_shadow.json"
ARTIFACT = ROOT / "ml" / "artifacts" / "pitcher_monte_carlo_shadow.joblib"
INCUMBENT = ROOT / "ml" / "artifacts" / "player_props.joblib"

OUTCOMES = (
    "strikeout", "walk", "non_hr_hit", "home_run", "other_pa",
)
EVENT_PROPS = {
    "strikeouts": (0,),
    "walks": (1,),
    "hits_allowed": (2, 3),
    "home_runs_allowed": (3,),
}
AUXILIARY_PROPS = {"outs": 27, "earned_runs": 15, "pitches": 140}
PROP_LINES = {
    key: PITCHER_PROPS[key]
    for key in (
        "strikeouts", "outs", "walks", "hits_allowed",
        "earned_runs", "home_runs_allowed", "pitches",
    )
}
EXCLUDED_FEATURES = {
    "line", "distribution_over", "over_rate_5", "over_rate_10",
    "over_rate_20", "over_rate_season", "prop_per_opportunity_5",
    "prop_per_opportunity_10", "prop_per_opportunity_20",
    "prop_per_opportunity_season", "prop_per_opportunity_prior",
    "opponent_prop_5", "opponent_prop_10", "opponent_prop_20",
}
MAX_BATTERS_FACED = 40


def _pitcher_labels(games):
    labels = {}
    for game in games:
        for side in ("away", "home"):
            for player in game[side]["players"]:
                pitching = player.get("pitching") or {}
                if not pitching.get("gamesStarted"):
                    continue
                bf = int(pitching.get("battersFaced") or 0)
                strikeouts = int(pitching.get("strikeOuts") or 0)
                outs = int(pitching.get("outs") or 0)
                walks = int(pitching.get("baseOnBalls") or 0)
                hits = int(pitching.get("hits") or 0)
                homers = int(pitching.get("homeRuns") or 0)
                counts = np.asarray(
                    (
                        strikeouts,
                        walks,
                        hits - homers,
                        homers,
                        bf - strikeouts - walks - hits,
                    ),
                    dtype=np.int16,
                )
                labels[(int(game["game_id"]), int(player["player_id"]))] = {
                    "bf": bf,
                    "counts": counts,
                    "valid": (
                        bf > 0
                        and np.all(counts >= 0)
                        and int(counts.sum()) == bf
                    ),
                }
    return labels


def _dispersion(actual, mean):
    pearson = (
        (actual - mean) ** 2 - mean
    ) / np.maximum(mean ** 2, 1e-5)
    return float(np.clip(np.mean(pearson), .002, 2.0))


def _expanded_outcomes(x, counts):
    row = np.repeat(np.arange(len(x)), len(OUTCOMES))
    target = np.tile(np.arange(len(OUTCOMES)), len(x))
    weight = counts.reshape(-1)
    keep = weight > 0
    return x[row[keep]], target[keep], weight[keep]


def _count_distribution(mean, alpha, maximum, minimum=0):
    mean = np.clip(np.asarray(mean, dtype=float), .01, maximum)
    values = np.arange(minimum, maximum + 1)
    if alpha <= .002:
        probability = poisson.pmf(values[None, :], mean[:, None])
        probability[:, -1] += poisson.sf(maximum, mean)
    else:
        size = 1 / alpha
        success = size / (size + mean)
        probability = nbinom.pmf(values[None, :], size, success[:, None])
        probability[:, -1] += nbinom.sf(maximum, size, success)
    probability /= probability.sum(axis=1, keepdims=True)
    return probability


def _fit(dataset, x, counts, bf, years):
    train, calibration = years <= 2023, years == 2024
    train_x, train_y, train_weight = _expanded_outcomes(
        x[train], counts[train],
    )
    cal_x, cal_y, cal_weight = _expanded_outcomes(
        x[calibration], counts[calibration],
    )
    outcome_model = lgb.LGBMClassifier(
        objective="multiclass",
        num_class=len(OUTCOMES),
        n_estimators=450,
        learning_rate=.035,
        num_leaves=23,
        min_child_samples=120,
        reg_lambda=12.0,
        feature_fraction=.8,
        random_state=61,
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
        outcome_model.predict_proba(x[calibration]), counts[calibration],
    )
    workload = lgb.LGBMRegressor(
        objective="poisson",
        n_estimators=450,
        learning_rate=.03,
        num_leaves=23,
        min_child_samples=140,
        reg_lambda=14.0,
        feature_fraction=.8,
        random_state=62,
        n_jobs=-1,
        verbosity=-1,
    ).fit(
        x[train],
        bf[train],
        eval_set=[(x[calibration], bf[calibration])],
        callbacks=[lgb.early_stopping(40, verbose=False)],
    )
    train_mean = np.clip(workload.predict(x[train]), .1, MAX_BATTERS_FACED)
    workload_alpha = _dispersion(bf[train], train_mean)

    auxiliary_models, auxiliary_alpha = {}, {}
    for offset, prop in enumerate(AUXILIARY_PROPS):
        target = dataset["outcomes"][prop].astype(float)
        model = lgb.LGBMRegressor(
            objective="poisson",
            n_estimators=450,
            learning_rate=.03,
            num_leaves=23,
            min_child_samples=140,
            reg_lambda=14.0,
            feature_fraction=.8,
            random_state=70 + offset,
            n_jobs=-1,
            verbosity=-1,
        ).fit(
            x[train],
            target[train],
            eval_set=[(x[calibration], target[calibration])],
            callbacks=[lgb.early_stopping(40, verbose=False)],
        )
        mean = np.clip(model.predict(x[train]), .01, AUXILIARY_PROPS[prop])
        auxiliary_models[prop] = model
        auxiliary_alpha[prop] = _dispersion(target[train], mean)
    return {
        "outcome_model": outcome_model,
        "outcome_spec": outcome_spec,
        "workload_model": workload,
        "workload_alpha": workload_alpha,
        "auxiliary_models": auxiliary_models,
        "auxiliary_alpha": auxiliary_alpha,
    }


def _event_probability_matrices(bf_probability, outcome_probability):
    sample_count = len(bf_probability)
    result = {
        prop: np.zeros((sample_count, len(PROP_LINES[prop])), dtype=float)
        for prop in EVENT_PROPS
    }
    event_probability = {
        prop: outcome_probability[:, list(indexes)].sum(axis=1)
        for prop, indexes in EVENT_PROPS.items()
    }
    for batters in range(1, MAX_BATTERS_FACED + 1):
        exposure = bf_probability[:, batters - 1]
        for prop, probability in event_probability.items():
            for line_index, line in enumerate(PROP_LINES[prop]):
                cutoff = int(np.floor(line))
                result[prop][:, line_index] += exposure * nbinom_or_binomial_sf(
                    cutoff, batters, probability,
                )
    return result


def nbinom_or_binomial_sf(cutoff, trials, probability):
    """Stable vectorized Binomial survival function via a short recurrence."""
    probability = np.asarray(probability, dtype=float)
    distribution = np.zeros((len(probability), trials + 1), dtype=float)
    distribution[:, 0] = (1 - probability) ** trials
    for count in range(1, trials + 1):
        distribution[:, count] = (
            distribution[:, count - 1]
            * (trials - count + 1) / count
            * probability / np.clip(1 - probability, 1e-10, 1)
        )
    return distribution[:, cutoff + 1 :].sum(axis=1)


def simulate_pitcher_matchup(
    bf_probability,
    outcome_probability,
    auxiliary_probability=None,
    simulations=100_000,
    seed=42,
):
    bf_probability = np.asarray(bf_probability, dtype=float)
    outcome_probability = np.asarray(outcome_probability, dtype=float)
    if bf_probability.shape != (MAX_BATTERS_FACED,):
        raise ValueError("invalid batters-faced distribution")
    if outcome_probability.shape != (len(OUTCOMES),):
        raise ValueError("invalid pitcher outcome distribution")
    rng = np.random.default_rng(seed)
    bf = rng.choice(
        np.arange(1, MAX_BATTERS_FACED + 1),
        size=int(simulations),
        p=bf_probability / bf_probability.sum(),
    )
    outcomes = np.empty((int(simulations), MAX_BATTERS_FACED), dtype=np.int8)
    cumulative = np.cumsum(outcome_probability / outcome_probability.sum())
    for index in range(MAX_BATTERS_FACED):
        outcomes[:, index] = np.searchsorted(
            cumulative, rng.random(int(simulations)), side="right",
        )
    active = np.arange(MAX_BATTERS_FACED)[None, :] < bf[:, None]
    return {
        "batters_faced": bf,
        **{
            prop: (np.isin(outcomes, indexes) * active).sum(axis=1)
            for prop, indexes in EVENT_PROPS.items()
        },
        **{
            prop: rng.choice(
                np.arange(len(probability)),
                size=int(simulations),
                p=probability / np.sum(probability),
            )
            for prop, probability in (auxiliary_probability or {}).items()
        },
    }


def _incumbent(dataset, artifact):
    output = {}
    current_names = feature_names("pitcher")
    artifact_names = (artifact.get("feature_names") or {}).get(
        "pitcher",
    ) or current_names
    columns = [current_names.index(name) for name in artifact_names]
    for prop, lines in PROP_LINES.items():
        bundle = artifact["models"].get(f"pitcher:{prop}")
        if not bundle:
            continue
        x, _, _, distribution = _expand_dataset(dataset, prop, lines)
        output[prop] = incumbent_probabilities(
            bundle, x[:, columns], distribution, len(dataset["base"]),
        ).reshape(-1, len(lines))
    return output


def _audit(dataset, years, probability, incumbent, metadata):
    offered, report = observed_lines(), {}
    for prop, lines in PROP_LINES.items():
        actual_count = dataset["outcomes"][prop]
        actual = actual_count[:, None] > np.asarray(lines)[None, :]
        report[prop] = {}
        for label, mask in (
            ("2025_2026", years >= 2025),
            ("2025", years == 2025),
            ("2026", years == 2026),
        ):
            if not np.any(mask):
                continue
            report[prop][label] = {
                "simulator": _metric(
                    actual[mask].reshape(-1), probability[prop][mask].reshape(-1),
                ),
                "incumbent": _metric(
                    actual[mask].reshape(-1), incumbent[prop][mask].reshape(-1),
                ),
                "paired_uncertainty": paired_game_bootstrap(
                    actual[mask].reshape(-1),
                    probability[prop][mask].reshape(-1),
                    incumbent[prop][mask].reshape(-1),
                    np.repeat(metadata["game_id"][mask], len(lines)),
                    seed=4026 + list(PROP_LINES).index(prop),
                ),
                "per_line": {
                    str(line): {
                        "simulator": _metric(
                            actual[mask, line_index],
                            probability[prop][mask, line_index],
                        ),
                        "incumbent": _metric(
                            actual[mask, line_index],
                            incumbent[prop][mask, line_index],
                        ),
                    }
                    for line_index, line in enumerate(lines)
                },
            }
        listed_y, listed_sim, listed_inc = [], [], []
        for index, (game_id, player_id) in enumerate(
            zip(metadata["game_id"], metadata["player_id"])
        ):
            line = offered.get((int(game_id), int(player_id), "pitcher", prop))
            if line is None or float(line) not in {float(value) for value in lines}:
                continue
            line_index = list(lines).index(float(line))
            listed_y.append(int(actual[index, line_index]))
            listed_sim.append(float(probability[prop][index, line_index]))
            listed_inc.append(float(incumbent[prop][index, line_index]))
        if listed_y:
            report[prop]["exact_listed_lines"] = {
                "simulator": _metric(listed_y, listed_sim),
                "incumbent": _metric(listed_y, listed_inc),
                "paired_uncertainty": paired_game_bootstrap(
                    listed_y,
                    listed_sim,
                    listed_inc,
                    [
                        game_id
                        for game_id, player_id in zip(
                            metadata["game_id"], metadata["player_id"],
                        )
                        if offered.get((
                            int(game_id), int(player_id), "pitcher", prop,
                        )) is not None
                        and float(offered[(
                            int(game_id), int(player_id), "pitcher", prop,
                        )]) in {float(value) for value in lines}
                    ],
                    resamples=5_000,
                    seed=5026 + list(PROP_LINES).index(prop),
                ),
            }
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", default=str(REPORT))
    parser.add_argument("--artifact", default=str(ARTIFACT))
    parser.add_argument("--incumbent", default=str(INCUMBENT))
    args = parser.parse_args()

    games, statcast = load_games(), load_statcast()
    dataset = _kind_dataset(
        games, statcast, "pitcher", PROP_LINES, include_metadata=True,
    )
    labels = _pitcher_labels(games)
    label_rows = [
        labels.get((int(game_id), int(player_id)))
        for game_id, player_id in zip(
            dataset["metadata"]["game_id"], dataset["metadata"]["player_id"],
        )
    ]
    valid = np.asarray([
        row is not None and row["valid"] for row in label_rows
    ])
    selected_labels = [row for row, keep in zip(label_rows, valid) if keep]
    counts = np.asarray(
        [row["counts"] for row in selected_labels], dtype=np.int16,
    )
    bf = np.asarray([row["bf"] for row in selected_labels], dtype=np.int16)
    # Invalid reconstructions are rare and excluded before any split/model fit.
    dataset = {
        **dataset,
        "base": dataset["base"][valid],
        "years": dataset["years"][valid],
        "metadata": {
            key: value[valid] for key, value in dataset["metadata"].items()
        },
        "outcomes": {
            key: value[valid] for key, value in dataset["outcomes"].items()
        },
        "prop_extras": {
            key: value[valid] for key, value in dataset["prop_extras"].items()
        },
        "line_extras": {
            key: value[valid] for key, value in dataset["line_extras"].items()
        },
    }
    years = dataset["years"].astype(int)
    names = feature_names("pitcher")
    indexes = np.asarray([
        index for index, name in enumerate(names)
        if name not in EXCLUDED_FEATURES
    ])
    x = dataset["base"][:, indexes]
    fitted = _fit(dataset, x, counts, bf, years)
    outcome_probability = _apply_categorical_calibration(
        fitted["outcome_model"].predict_proba(x), fitted["outcome_spec"],
    )
    bf_probability = _count_distribution(
        fitted["workload_model"].predict(x),
        fitted["workload_alpha"],
        MAX_BATTERS_FACED,
        minimum=1,
    )
    probability = _event_probability_matrices(
        bf_probability, outcome_probability,
    )
    auxiliary_probability = {}
    for prop, maximum in AUXILIARY_PROPS.items():
        auxiliary_probability[prop] = _count_distribution(
            fitted["auxiliary_models"][prop].predict(x),
            fitted["auxiliary_alpha"][prop],
            maximum,
        )
        probability[prop] = np.column_stack([
            auxiliary_probability[prop][:, int(np.floor(line)) + 1 :].sum(axis=1)
            for line in PROP_LINES[prop]
        ])

    calibration = years == 2024
    calibrators = {}
    for prop, lines in PROP_LINES.items():
        actual = dataset["outcomes"][prop]
        y = actual[:, None] > np.asarray(lines)[None, :]
        calibrators[prop] = _linewise_calibrators(
            y[calibration].reshape(-1),
            probability[prop][calibration],
            len(lines),
        )
        probability[prop] = _apply_linewise(
            calibrators[prop], probability[prop],
        ).reshape(-1, len(lines))

    incumbent = _incumbent(dataset, joblib.load(args.incumbent))
    audit = _audit(
        dataset, years, probability, incumbent, dataset["metadata"],
    )
    artifact = {
        "status": "shadow_only",
        "outcomes": OUTCOMES,
        "feature_names": [names[index] for index in indexes],
        **fitted,
        "prop_calibrators": calibrators,
    }
    Path(args.artifact).parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(artifact, args.artifact)
    report = {
        "status": "shadow_only",
        "production_changed": False,
        "policy": "Train through 2023; calibrate on 2024; audit 2025 and 2026.",
        "architecture": {
            "workload": "negative-binomial batters faced",
            "per_batter_outcomes": list(OUTCOMES),
            "auxiliary_counts": list(AUXILIARY_PROPS),
        },
        "samples": {
            "valid_starts": int(len(years)),
            "excluded_invalid_reconstructions": int(np.sum(~valid)),
        },
        "audit": audit,
        "artifact": str(Path(args.artifact)),
    }
    Path(args.report).write_text(json.dumps(report, indent=2), encoding="utf8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
