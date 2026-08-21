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


def no_vig_probabilities(*decimal_odds: float | None) -> list[float | None]:
    if any(value is None or not math.isfinite(float(value)) or float(value) <= 1 for value in decimal_odds):
        return [None for _ in decimal_odds]
    implied = [1 / float(value) for value in decimal_odds]
    margin = sum(implied)
    return [value / margin for value in implied]


def _selection_price(row: dict, market: str, positive: bool) -> tuple[float | None, float | None]:
    prices = row.get("archived_prices") or {}
    closing = prices.get("closing") or {}
    if market == "home_win":
        # Football's negative class is draw-or-away and is not one bettable
        # selection. NFL is binary and can safely map it to the away price.
        if row.get("competition"):
            home, draw, away = closing.get("home"), closing.get("draw"), closing.get("away")
            no_vig = no_vig_probabilities(home, draw, away)
            return (home, no_vig[0]) if positive else (None, None)
        home, away = closing.get("home"), closing.get("away")
        no_vig = no_vig_probabilities(home, away)
        return (home, no_vig[0]) if positive else (away, no_vig[1])
    if market == "over_2_5":
        over, under = closing.get("over_2_5"), closing.get("under_2_5")
        no_vig = no_vig_probabilities(over, under)
        return (over, no_vig[0]) if positive else (under, no_vig[1])
    return None, None


def closing_line_betting_metrics(rows: Sequence[dict], probabilities: Sequence[float], market: str) -> dict:
    """Evaluate a declared closing-line zero-edge strategy without inventing prices.

    These results are never labelled as prediction-time ROI or CLV because the
    source does not provide the exact price timestamp matching knowledge_time.
    """
    bets = []
    for row, probability in zip(rows, probabilities):
        positive = float(probability) >= .5
        selected_probability = float(probability) if positive else 1 - float(probability)
        price, no_vig = _selection_price(row, market, positive)
        if price is None or no_vig is None:
            continue
        edge = selected_probability - float(no_vig)
        if edge <= 0:
            continue
        actual = int(row["label"])
        won = actual == int(positive)
        profit = float(price) - 1 if won else -1.0
        bets.append({"won": won, "price": float(price), "edge": edge, "profit": profit})
    cumulative = peak = drawdown = 0.0
    losing = longest_losing = 0
    for bet in bets:
        cumulative += bet["profit"]
        peak = max(peak, cumulative)
        drawdown = max(drawdown, peak - cumulative)
        losing = 0 if bet["won"] else losing + 1
        longest_losing = max(longest_losing, losing)
    wins = sum(int(bet["won"]) for bet in bets)
    profit = sum(bet["profit"] for bet in bets)
    return {
        "strategy": "closing-line positive model edge; no threshold optimization",
        "odds_at_prediction_available": False,
        "qualifying_bets": len(bets), "wins": wins, "losses": len(bets) - wins,
        "hit_rate": wins / len(bets) if bets else None,
        "average_market_odds": sum(bet["price"] for bet in bets) / len(bets) if bets else None,
        "average_estimated_edge": sum(bet["edge"] for bet in bets) / len(bets) if bets else None,
        "roi": profit / len(bets) if bets else None,
        "yield": profit / len(bets) if bets else None,
        "clv": None,
        "maximum_drawdown_units": drawdown,
        "longest_losing_streak": longest_losing,
        "limitation": "Archived closing prices are available, but exact prediction-time prices are not; this is a closing-line strategy audit, not live-simulated ROI or CLV.",
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
