"""Probability-first evaluation shared by every NINTH sport.

All metrics operate on forecasts that were locked before the event.  The
module intentionally has no random train/test split helper: callers must pass
chronologically ordered folds.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, asdict
from typing import Iterable, Sequence

import numpy as np
from sklearn.metrics import log_loss, roc_auc_score


def _bounded(probabilities: Iterable[float]) -> np.ndarray:
    return np.clip(np.asarray(list(probabilities), dtype=float), 1e-6, 1 - 1e-6)


def wilson_lower(wins: int, samples: int, z: float = 1.645) -> float | None:
    if samples <= 0:
        return None
    rate = wins / samples
    denominator = 1 + z * z / samples
    centre = rate + z * z / (2 * samples)
    margin = z * math.sqrt(rate * (1 - rate) / samples + z * z / (4 * samples * samples))
    return max(0.0, (centre - margin) / denominator)


def expected_calibration_error(y_true: Sequence[int], probabilities: Sequence[float], bins: int = 10) -> float:
    y = np.asarray(y_true, dtype=int)
    p = _bounded(probabilities)
    if not len(y):
        return float("nan")
    edges = np.linspace(0, 1, bins + 1)
    total = 0.0
    for left, right in zip(edges[:-1], edges[1:]):
        mask = (p >= left) & (p < right if right < 1 else p <= right)
        if mask.any():
            total += float(mask.mean()) * abs(float(y[mask].mean()) - float(p[mask].mean()))
    return total


def binary_metrics(y_true: Sequence[int], probabilities: Sequence[float], confidence_floor: float = .60) -> dict:
    y = np.asarray(y_true, dtype=int)
    p = _bounded(probabilities)
    if not len(y):
        return {"samples": 0}
    picked = (p >= .5).astype(int)
    correct = (picked == y).astype(int)
    confidence = np.maximum(p, 1 - p)
    qualified = confidence >= confidence_floor
    try:
        auc = float(roc_auc_score(y, p)) if len(np.unique(y)) > 1 else None
    except ValueError:
        auc = None
    q_samples = int(qualified.sum())
    q_wins = int(correct[qualified].sum()) if q_samples else 0
    return {
        "samples": int(len(y)), "accuracy": float(correct.mean()),
        "brier": float(np.mean((p - y) ** 2)), "log_loss": float(log_loss(y, p, labels=[0, 1])),
        "roc_auc": auc, "expected_calibration_error": expected_calibration_error(y, p),
        "mean_confidence": float(confidence.mean()),
        "qualified": {
            "floor": confidence_floor, "samples": q_samples,
            "coverage": q_samples / len(y), "accuracy": q_wins / q_samples if q_samples else None,
            "wilson_lower": wilson_lower(q_wins, q_samples),
        },
    }


@dataclass(frozen=True)
class PromotionGate:
    minimum_test_samples: int = 300
    minimum_historical_samples: int = 500
    minimum_recent_samples: int = 150
    minimum_live_samples: int = 30
    minimum_brier_skill: float = .01
    maximum_ece: float = .05
    maximum_log_loss_regression: float = 0.0
    minimum_qualified_lower_bound: float = .52


def historical_readiness(
    candidate: dict,
    baseline: dict,
    recent_candidate: dict,
    recent_baseline: dict,
    gate: PromotionGate | None = None,
) -> dict:
    """Assess leak-free historical evidence separately from live operations.

    A historical audit can establish statistical readiness, but it cannot prove
    that the live collection and locking path works.  That remains a smaller,
    separate forward-shadow gate.
    """
    gate = gate or PromotionGate()
    checks = {
        "minimum_historical_samples": int(candidate.get("samples") or 0) >= gate.minimum_historical_samples,
        "minimum_recent_samples": int(recent_candidate.get("samples") or 0) >= gate.minimum_recent_samples,
        "brier_skill": float(baseline.get("brier") or 1) - float(candidate.get("brier") or 1) >= gate.minimum_brier_skill,
        "recent_brier_skill": float(recent_candidate.get("brier") or 1) < float(recent_baseline.get("brier") or 1),
        "log_loss": float(candidate.get("log_loss") or 99) <= float(baseline.get("log_loss") or 99) + gate.maximum_log_loss_regression,
        "calibration": float(candidate.get("expected_calibration_error") or 1) <= gate.maximum_ece,
        "qualified_lower_bound": float((candidate.get("qualified") or {}).get("wilson_lower") or 0) >= gate.minimum_qualified_lower_bound,
    }
    return {"passed": all(checks.values()), "checks": checks, "gate": asdict(gate)}


def promotion_decision(candidate: dict, baseline: dict, live: dict | None = None, gate: PromotionGate | None = None) -> dict:
    gate = gate or PromotionGate()
    baseline_brier = float(baseline.get("brier") or 1)
    candidate_brier = float(candidate.get("brier") or 1)
    checks = {
        "minimum_untouched_samples": int(candidate.get("samples") or 0) >= gate.minimum_test_samples,
        "brier_skill": baseline_brier - candidate_brier >= gate.minimum_brier_skill,
        "log_loss": float(candidate.get("log_loss") or 99) <= float(baseline.get("log_loss") or 99) + gate.maximum_log_loss_regression,
        "calibration": float(candidate.get("expected_calibration_error") or 1) <= gate.maximum_ece,
        "qualified_lower_bound": float((candidate.get("qualified") or {}).get("wilson_lower") or 0) >= gate.minimum_qualified_lower_bound,
        "live_samples": live is not None and int(live.get("samples") or 0) >= gate.minimum_live_samples,
        "live_brier": live is not None and float(live.get("brier") or 1) < baseline_brier,
    }
    return {"passed": all(checks.values()), "checks": checks, "gate": asdict(gate)}
