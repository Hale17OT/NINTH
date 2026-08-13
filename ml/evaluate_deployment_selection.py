"""Audit the exact production moneyline/totals selection policy.

Training audits answer whether each model generalizes.  This audit answers the
separate deployment question: whether the line/side that the live Builder
actually selected has enough settled evidence to be selected automatically.
"""
from __future__ import annotations

import json
import math
import os
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import requests


ROOT = Path(__file__).resolve().parents[1]
SNAPSHOTS = ROOT / "ml" / "data" / "projection_snapshots.jsonl"
OUTPUT = ROOT / "ml" / "artifacts" / "deployment_selection_audit.json"
MIN_TOTAL_SELECTIONS = int(os.getenv("NINTH_TOTALS_AUTOMATIC_MIN_SAMPLES", "50"))
TOTALS_CALIBRATION_L2 = float(os.getenv("NINTH_TOTALS_CALIBRATION_L2", "20"))
TOTALS_DECISION_LINES = {7.5, 8.5, 9.5, 10.5}
TOTALS_MIN_SIDE_SHARE = float(os.getenv("NINTH_TOTALS_MIN_SIDE_SHARE", ".10"))
TOTALS_CONSISTENCY_MARGIN = float(os.getenv("NINTH_TOTALS_CONSISTENCY_MARGIN", "1.0"))
TOTALS_CONSISTENCY_OVERRIDE = float(os.getenv("NINTH_TOTALS_CONSISTENCY_OVERRIDE", ".62"))
TOTALS_MIN_LINE_ROWS = int(os.getenv("NINTH_TOTALS_MIN_LINE_CALIBRATION_ROWS", "25"))


def read_snapshots():
    selected = {}
    if not SNAPSHOTS.exists():
        return selected
    with SNAPSHOTS.open(encoding="utf-8") as handle:
        for line in handle:
            try:
                row = json.loads(line)
                game_id = int(row["game_id"])
                recorded = datetime.fromisoformat(row["recorded_at"].replace("Z", "+00:00"))
                starts = datetime.fromisoformat(row["scheduled_start"].replace("Z", "+00:00"))
            except (ValueError, TypeError, KeyError, json.JSONDecodeError):
                continue
            if row.get("phase") != "pregame" or recorded > starts:
                continue
            current = selected.get(game_id)
            if current is None or row["recorded_at"] > current["recorded_at"]:
                selected[game_id] = row
    return selected


def completed_scores(snapshots):
    if not snapshots:
        return {}
    dates = sorted({str(row.get("scheduled_start") or "")[:10] for row in snapshots.values()})
    response = requests.get(
        "https://statsapi.mlb.com/api/v1/schedule",
        params={
            "sportId": 1, "startDate": dates[0], "endDate": dates[-1],
            "hydrate": "linescore",
        },
        headers={"User-Agent": "NINTH deployment audit/1.0"}, timeout=60,
    )
    response.raise_for_status()
    scores = {}
    for date_row in response.json().get("dates", []):
        for game in date_row.get("games", []):
            if game.get("status", {}).get("abstractGameState") != "Final":
                continue
            scores[int(game["gamePk"])] = {
                "home": int(game.get("teams", {}).get("home", {}).get("score") or 0),
                "away": int(game.get("teams", {}).get("away", {}).get("score") or 0),
            }
    return scores


def metrics(rows):
    if not rows:
        return {"selections": 0, "accuracy": None, "mean_probability": None, "brier": None}
    return {
        "selections": len(rows),
        "accuracy": round(sum(row["actual"] for row in rows) / len(rows), 6),
        "mean_probability": round(sum(row["probability"] for row in rows) / len(rows), 6),
        "brier": round(sum((row["probability"] - row["actual"]) ** 2 for row in rows) / len(rows), 6),
    }


def central_line_audit(games):
    """Score the exact balanced sportsbook line, treating integer ties as pushes."""
    rows = []
    shifted_lower_half_lines = 0
    for game in games:
        candidates = []
        for threshold in game.get("audit_thresholds") or game.get("thresholds") or []:
            odds = threshold.get("melbet_odds") or {}
            try:
                over_implied = 1 / float(odds["over"])
                under_implied = 1 / float(odds["under"])
                balance = abs(over_implied / (over_implied + under_implied) - .5)
                candidates.append((balance, float(threshold["line"]), threshold))
            except (KeyError, TypeError, ValueError, ZeroDivisionError):
                continue
        if not candidates:
            continue
        _, line, threshold = min(candidates, key=lambda value: (value[0], value[1]))
        over = float(threshold["over_probability"])
        under = float(threshold.get("under_probability", 1 - over))
        side = "over" if over >= under else "under"
        probability = over if side == "over" else under
        total_runs = float(game["total_runs"])
        push = total_runs == line
        actual = None if push else int((total_runs > line) == (side == "over"))
        archived_line = game.get("archived_audit_line")
        if archived_line is not None and float(archived_line) == line - .5:
            shifted_lower_half_lines += 1
        rows.append({
            "line": line, "side": side, "probability": probability,
            "actual": actual, "push": push,
        })
    scored = [row for row in rows if not row["push"]]
    summary = metrics(scored)
    summary.update({
        "forecasts": len(rows), "pushes": len(rows) - len(scored),
        "over_selections": sum(row["side"] == "over" for row in rows),
        "under_selections": sum(row["side"] == "under" for row in rows),
        "over_share": round(sum(row["side"] == "over" for row in rows) / len(rows), 6) if rows else None,
        "lower_half_line_ties_removed": shifted_lower_half_lines,
        "selection_rule": "exact balanced market line; integer results can push",
    })
    return summary


def wilson_lower(successes, samples, z=1.96):
    if not samples:
        return 0.0
    p = successes / samples
    denominator = 1 + z * z / samples
    centre = p + z * z / (2 * samples)
    radius = z * math.sqrt(p * (1 - p) / samples + z * z / (4 * samples * samples))
    return (centre - radius) / denominator


def _logit(value):
    probability = max(1e-6, min(1 - 1e-6, float(value)))
    return math.log(probability / (1 - probability))


def calibrated_over_probability(probability, logit_offset, logit_slope=1.0):
    value = float(logit_offset) + float(logit_slope) * _logit(probability)
    return 1 / (1 + math.exp(-value))


def fit_logit_offset(rows, penalty=TOTALS_CALIBRATION_L2, logit_slope=1.0):
    """Fit a regularized intercept while preserving the model's probability ordering."""
    offset = 0.0
    for _ in range(50):
        probabilities = [calibrated_over_probability(row["over_probability"], offset, logit_slope) for row in rows]
        gradient = sum(probability - row["actual_over"] for probability, row in zip(probabilities, rows)) + 2 * penalty * offset
        curvature = sum(probability * (1 - probability) for probability in probabilities) + 2 * penalty
        updated = offset - gradient / max(curvature, 1e-9)
        if abs(updated - offset) < 1e-10:
            return updated
        offset = updated
    return offset


def _fit_probability_offset(rows, base_offset=0.0, penalty=TOTALS_CALIBRATION_L2, logit_slope=1.0):
    """Fit a ridge-regularized residual around a broader side calibration."""
    residual = 0.0
    for _ in range(50):
        probabilities = [
            calibrated_over_probability(row["raw_probability"], base_offset + residual, logit_slope)
            for row in rows
        ]
        gradient = sum(probability - row["actual"] for probability, row in zip(probabilities, rows)) + 2 * penalty * residual
        curvature = sum(probability * (1 - probability) for probability in probabilities) + 2 * penalty
        updated = residual - gradient / max(curvature, 1e-9)
        if abs(updated - residual) < 1e-10:
            return base_offset + updated
        residual = updated
    return base_offset + residual


def _side_rows(rows):
    values = []
    for row in rows:
        over = float(row["over_probability"])
        values.extend((
            {"line": float(row["line"]), "side": "over", "raw_probability": over, "actual": int(row["actual_over"])},
            {"line": float(row["line"]), "side": "under", "raw_probability": 1 - over, "actual": 1 - int(row["actual_over"])},
        ))
    return values


def fit_line_side_calibration(rows, penalty=TOTALS_CALIBRATION_L2, logit_slope=1.0):
    """Fit side baselines and shrink each line/side correction toward its baseline."""
    side_rows = _side_rows(rows)
    global_intercepts = {}
    line_side_intercepts = {}
    line_side_samples = {}
    for side in ("over", "under"):
        broad = [row for row in side_rows if row["side"] == side]
        base = _fit_probability_offset(broad, penalty=penalty, logit_slope=logit_slope)
        global_intercepts[side] = base
        for line in sorted(TOTALS_DECISION_LINES):
            key = f"{line:g}:{side}"
            local = [row for row in broad if row["line"] == line]
            line_side_samples[key] = len(local)
            line_side_intercepts[key] = (
                _fit_probability_offset(local, base, penalty, logit_slope)
                if len(local) >= TOTALS_MIN_LINE_ROWS else base
            )
    return {
        "logit_slope": float(logit_slope),
        "global_intercepts": global_intercepts,
        "line_side_intercepts": line_side_intercepts,
        "line_side_samples": line_side_samples,
    }


def _calibrated_line_probabilities(over_probability, line, calibration=None):
    if not calibration:
        return float(over_probability), 1 - float(over_probability)
    slope = float(calibration.get("logit_slope", 1))
    globals_ = calibration.get("global_intercepts") or {}
    locals_ = calibration.get("line_side_intercepts") or {}
    scores = {}
    for side, raw in (("over", over_probability), ("under", 1 - over_probability)):
        key = f"{float(line):g}:{side}"
        intercept = float(locals_.get(key, globals_.get(side, 0)))
        scores[side] = calibrated_over_probability(raw, intercept, slope)
    total = scores["over"] + scores["under"]
    return scores["over"] / total, scores["under"] / total


def _materially_contradicts(expected_total, line, side, margin=TOTALS_CONSISTENCY_MARGIN):
    if expected_total is None:
        return False
    difference = float(expected_total) - float(line)
    return (side == "under" and difference >= margin) or (side == "over" and difference <= -margin)


def _selection_metrics(games, calibration=None, enforce_consistency=False, evidence=None, enforce_diversity=False):
    selections = []
    game_candidates = []
    rejected_conflicts = 0
    for game in games:
        candidates = []
        for row in game["thresholds"]:
            over_probability, under_probability = _calibrated_line_probabilities(
                row["over_probability"], row["line"], calibration,
            )
            candidates.extend((
                {"probability": over_probability, "actual": row["actual_over"], "side": "over", "line": row["line"]},
                {"probability": under_probability, "actual": 1 - row["actual_over"], "side": "under", "line": row["line"]},
            ))
        if enforce_consistency:
            allowed = []
            for candidate in candidates:
                conflict = _materially_contradicts(game.get("expected_total_runs"), candidate["line"], candidate["side"])
                rule = (evidence or {}).get(f"{float(candidate['line']):g}:{candidate['side']}", {})
                sufficient_override = candidate["probability"] >= TOTALS_CONSISTENCY_OVERRIDE and rule.get("automatic_eligible") is True
                if conflict and not sufficient_override:
                    rejected_conflicts += 1
                else:
                    allowed.append(candidate)
            candidates = allowed
        if candidates:
            best = max(candidates, key=lambda row: row["probability"])
            selections.append(best)
            game_candidates.append(candidates)
    if enforce_diversity and selections:
        minimum_each_side = math.ceil(len(selections) * TOTALS_MIN_SIDE_SHARE)
        for required_side in ("over", "under"):
            deficit = minimum_each_side - sum(row["side"] == required_side for row in selections)
            if deficit <= 0:
                continue
            swaps = []
            for index, (selected, available) in enumerate(zip(selections, game_candidates)):
                if selected["side"] == required_side:
                    continue
                alternatives = [row for row in available if row["side"] == required_side]
                if alternatives:
                    alternative = max(alternatives, key=lambda row: row["probability"])
                    swaps.append((selected["probability"] - alternative["probability"], index, alternative))
            for _, index, alternative in sorted(swaps, key=lambda row: row[0])[:deficit]:
                selections[index] = alternative
    value = metrics(selections)
    value.update({
        "over_selections": sum(row["side"] == "over" for row in selections),
        "under_selections": sum(row["side"] == "under" for row in selections),
        "minimum_side_share": round(min(
            sum(row["side"] == "over" for row in selections),
            sum(row["side"] == "under" for row in selections),
        ) / len(selections), 6) if selections else 0,
        "rejected_distribution_conflicts": rejected_conflicts,
    })
    return value


def _line_side_evidence(games, calibration):
    groups = defaultdict(list)
    for game in games:
        for row in game["thresholds"]:
            over, under = _calibrated_line_probabilities(row["over_probability"], row["line"], calibration)
            for side, probability, actual in (
                ("over", over, row["actual_over"]), ("under", under, 1 - row["actual_over"]),
            ):
                groups[f"{float(row['line']):g}:{side}"].append({"probability": probability, "actual": actual})
    report = {}
    for key, rows in sorted(groups.items()):
        value = metrics(rows)
        successes = sum(row["actual"] for row in rows)
        eligible = (
            len(rows) >= 20 and value["brier"] < .25
            and value["accuracy"] >= value["mean_probability"] - .03
            and wilson_lower(successes, len(rows)) > .50
        )
        report[key] = {
            **value, "wilson_95_lower": round(wilson_lower(successes, len(rows)), 6),
            "automatic_eligible": eligible,
        }
    return report


def totals_calibration_report(games):
    """Chronologically validate hierarchical line/side calibration and safety gates."""
    ordered = sorted(games, key=lambda row: (row["scheduled_start"], row["game_id"]))
    split = max(1, int(len(ordered) * .75))
    training, validation = ordered[:split], ordered[split:]
    training_rows = [row for game in training for row in game["thresholds"]]
    all_rows = [row for game in ordered for row in game["thresholds"]]
    training_residuals = [
        float(game["total_runs"]) - float(game["expected_total_runs"])
        for game in training
        if game.get("total_runs") is not None and game.get("expected_total_runs") is not None
    ]
    all_residuals = [
        float(game["total_runs"]) - float(game["expected_total_runs"])
        for game in ordered
        if game.get("total_runs") is not None and game.get("expected_total_runs") is not None
    ]
    if len(training) < 60 or len(validation) < 20 or not training_rows:
        return {
            "promoted": False, "method": "hierarchical_line_side_platt",
            "reason": "Not enough chronologically separated production games to validate calibration.",
        }
    candidates = []
    for logit_slope in (.75, 1.0):
        for penalty in (5.0, 20.0, 50.0):
            fold_briers = []
            fold_valid = True
            for fraction in (.5, .625, .75):
                fold_split = int(len(training) * fraction)
                fold_end = min(len(training), fold_split + int(len(training) * .125))
                fold_train = [row for game in training[:fold_split] for row in game["thresholds"]]
                fold_validation = training[fold_split:fold_end]
                fitted = fit_line_side_calibration(fold_train, penalty, logit_slope)
                fold_metric = _selection_metrics(fold_validation, fitted, enforce_diversity=True)
                fold_briers.append(fold_metric["brier"])
                fold_valid = fold_valid and fold_metric["minimum_side_share"] >= TOTALS_MIN_SIDE_SHARE
            if fold_valid:
                candidates.append((sum(fold_briers) / len(fold_briers), logit_slope, penalty))
    if not candidates:
        return {
            "promoted": False, "method": "hierarchical_line_side_platt",
            "reason": "No line/side calibration retained the required side diversity in temporal folds.",
            "minimum_side_share_required": TOTALS_MIN_SIDE_SHARE,
        }
    _, selected_slope, selected_penalty = min(candidates, key=lambda row: row[0])
    validation_calibration = fit_line_side_calibration(training_rows, selected_penalty, selected_slope)
    validation_evidence = _line_side_evidence(training, validation_calibration)
    raw = _selection_metrics(validation)
    calibrated = _selection_metrics(validation, validation_calibration, True, validation_evidence, True)
    empirical_rows = []
    prior_strength = 8.0
    if len(training_residuals) >= 60:
        for game in validation:
            expected = game.get("expected_total_runs")
            if expected is None:
                continue
            for row in game["thresholds"]:
                threshold = float(row["line"]) - float(expected)
                over = (sum(value > threshold for value in training_residuals) + prior_strength / 2) / (
                    len(training_residuals) + prior_strength
                )
                empirical_rows.append({"probability": over, "actual": int(row["actual_over"])})
    empirical_validation = metrics(empirical_rows)
    promoted = (
        calibrated["brier"] is not None and raw["brier"] is not None
        and calibrated["brier"] < raw["brier"]
        and calibrated["minimum_side_share"] >= TOTALS_MIN_SIDE_SHARE
    )
    fitted = fit_line_side_calibration(all_rows, selected_penalty, selected_slope) if promoted else {}
    validation_line_side = _line_side_evidence(validation, validation_calibration)
    return {
        "promoted": promoted,
        "method": "chronologically_validated_hierarchical_line_side_platt",
        "logit_slope": selected_slope,
        "global_intercepts": {key: round(value, 8) for key, value in fitted.get("global_intercepts", {}).items()},
        "line_side_intercepts": {key: round(value, 8) for key, value in fitted.get("line_side_intercepts", {}).items()},
        "line_side_samples": fitted.get("line_side_samples", {}),
        "empirical_residuals": [round(value, 4) for value in all_residuals[-400:]],
        "minimum_empirical_residuals": 60,
        "empirical_residual_method": "smoothed chronological actual-minus-expected residual CDF",
        "empirical_validation": empirical_validation,
        "line_side_validation": validation_line_side,
        "l2_penalty": selected_penalty,
        "minimum_side_share_required": TOTALS_MIN_SIDE_SHARE,
        "consistency_margin_runs": TOTALS_CONSISTENCY_MARGIN,
        "consistency_override_probability": TOTALS_CONSISTENCY_OVERRIDE,
        "training_games": len(training), "validation_games": len(validation),
        "raw_validation": raw, "calibrated_validation": calibrated,
        "reason": (
            "Promoted: improved newest-quarter selection Brier, retained side diversity, and applied the expected-runs consistency veto."
            if promoted else
            "Not promoted: the line/side correction failed the Brier or side-diversity gate on the newest quarter."
        ),
    }


def build_report(snapshots, scores):
    moneyline = []
    totals = []
    calibration_games = []
    for game_id, snapshot in snapshots.items():
        score = scores.get(game_id)
        if not score:
            continue
        home_probability = float(snapshot.get("home_win_probability") or 0)
        selected_home = home_probability >= .5
        probability = max(home_probability, 1 - home_probability)
        moneyline.append({
            "probability": probability,
            "actual": int((score["home"] > score["away"]) == selected_home),
        })
        projection = snapshot.get("totals_projection") or {}
        calibration_thresholds = []
        audit_thresholds = []
        total_runs = score["home"] + score["away"]
        for threshold in projection.get("thresholds") or []:
            try:
                threshold_line = float(threshold["line"])
                over_probability = float(threshold["over_probability"])
            except (KeyError, TypeError, ValueError):
                continue
            audit_row = {
                "line": threshold_line, "over_probability": over_probability,
                "under_probability": float(threshold.get("under_probability", 1 - over_probability)),
                "actual_over": int(total_runs > threshold_line),
                "push_probability": float(threshold.get("push_probability") or 0),
                "melbet_odds": threshold.get("melbet_odds") or {},
            }
            audit_thresholds.append(audit_row)
            if threshold_line in TOTALS_DECISION_LINES:
                calibration_thresholds.append(audit_row)
        if calibration_thresholds:
            try:
                expected_total_runs = float(projection.get("expected_total_runs"))
            except (TypeError, ValueError):
                expected_total_runs = None
            calibration_games.append({
                "game_id": game_id,
                "scheduled_start": snapshot.get("scheduled_start") or snapshot.get("recorded_at") or str(game_id),
                "expected_total_runs": expected_total_runs,
                "total_runs": total_runs,
                "archived_audit_line": projection.get("audit_line"),
                "thresholds": calibration_thresholds,
                "audit_thresholds": audit_thresholds,
            })
        line = projection.get("recommended_line")
        side = projection.get("recommended_side")
        probability = projection.get("recommended_probability")
        if line is None or side not in ("over", "under") or probability is None:
            continue
        if float(line).is_integer() and total_runs == float(line):
            continue
        over = total_runs > float(line)
        totals.append({
            "line": float(line), "side": side, "probability": float(probability),
            "actual": int(over if side == "over" else not over),
        })

    moneyline_metrics = metrics(moneyline)
    moneyline_successes = sum(row["actual"] for row in moneyline)
    groups = defaultdict(list)
    for row in totals:
        groups[f"{row['line']:g}:{row['side']}"].append(row)
    total_rules = {}
    for key, rows in sorted(groups.items()):
        value = metrics(rows)
        successes = sum(row["actual"] for row in rows)
        eligible = (
            len(rows) >= MIN_TOTAL_SELECTIONS
            and wilson_lower(successes, len(rows)) > .50
            and value["brier"] < .25
            and value["accuracy"] >= value["mean_probability"] - .02
        )
        total_rules[key] = {
            **value, "wilson_95_lower": round(wilson_lower(successes, len(rows)), 6),
            "automatic_eligible": eligible,
            "reason": (
                "Cleared prospective deployment evidence gates."
                if eligible else
                f"Manual only until at least {MIN_TOTAL_SELECTIONS} exact deployment selections are both accurate and calibrated."
            ),
        }
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "snapshot_rule": "Last immutable pregame selection before scheduled first pitch",
        "moneyline": {
            **moneyline_metrics, "minimum_probability": None,
            "automatic_eligible": True,
            "wilson_95_lower": round(wilson_lower(moneyline_successes, len(moneyline)), 6),
            "eligibility_rule": "No hard probability cutoff; Build Best ranks every available moneyline.",
        },
        "totals": {
            **metrics(totals), "minimum_exact_selection_samples": MIN_TOTAL_SELECTIONS,
            "automatic_eligible_rules": sum(rule["automatic_eligible"] for rule in total_rules.values()),
            "rules": total_rules, "calibration": totals_calibration_report(calibration_games),
            "central_line_audit": central_line_audit(calibration_games),
        },
    }


def main():
    snapshots = read_snapshots()
    report = build_report(snapshots, completed_scores(snapshots))
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    temporary = OUTPUT.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(report, indent=2), encoding="utf-8")
    os.replace(temporary, OUTPUT)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
