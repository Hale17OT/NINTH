"""Local MelBet history persistence and decision-support analysis for Alter Ego."""

from __future__ import annotations

import json
import math
import os
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_HISTORY_PATH = Path(__file__).resolve().parent / "data" / "melbet_bet_history.json"
HISTORY_PATH = Path(os.getenv("NINTH_MELBET_HISTORY_PATH", DEFAULT_HISTORY_PATH))
SETTLED = {"win", "loss", "lost", "void", "refund", "cancelled", "canceled"}


def _text(value, limit=500):
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def _number(value, minimum=0.0, maximum=1_000_000_000.0):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and minimum <= number <= maximum else None


def _status(value):
    value = _text(value, 30).lower()
    if value == "lost":
        return "loss"
    if value == "won":
        return "win"
    return value if value in SETTLED | {"pending", "open"} else "pending"


def _side(selection):
    text = selection.lower()
    if re.search(r"\bunder\b|\bless\b", text):
        return "Under"
    if re.search(r"\bover\b|\bor more\b|\bmore than\b", text):
        return "Over"
    return "Other"


def _market(selection):
    text = selection.lower().replace("strike-outs", "strikeouts")
    patterns = (
        ("Pitcher strikeouts", r"strikeouts|strike outs"),
        ("Hits + runs + RBIs", r"hits\s*,?\s*runs\s*(?:and|\+|&)\s*rbis?"),
        ("Home runs", r"home runs?"),
        ("Total bases", r"total bases"),
        ("RBIs", r"rbis?"),
        ("Batter walks", r"(?:total )?walks"),
        ("Batter strikeouts", r"batter strikeouts"),
        ("Hits", r"(?:total )?hits"),
        ("Runs", r"(?:total )?runs"),
        ("Moneyline", r"moneyline|\bw1\b|\bw2\b"),
        ("Game total", r"total (?:over|under)"),
    )
    for label, pattern in patterns:
        if re.search(pattern, text):
            return label
    return "Other"


def _odds_bucket(odds):
    if odds is None:
        return "Unknown"
    if odds < 1.2:
        return "< 1.20"
    if odds < 1.4:
        return "1.20–1.39"
    if odds < 1.7:
        return "1.40–1.69"
    if odds < 2.0:
        return "1.70–1.99"
    return "2.00+"


def normalize_slip(raw):
    if not isinstance(raw, dict):
        raise ValueError("MelBet history payload must contain a slip object.")
    slip_id = re.sub(r"[^0-9A-Za-z_-]", "", str(raw.get("slip_id") or ""))[:80]
    if not slip_id:
        raise ValueError("The selected MelBet slip has no readable slip number.")
    raw_legs = raw.get("legs")
    if not isinstance(raw_legs, list) or not raw_legs:
        raise ValueError("No bet legs were found in the selected MelBet drawer.")
    if len(raw_legs) > 100:
        raise ValueError("The selected MelBet slip has an implausible number of legs.")

    legs = []
    for index, raw_leg in enumerate(raw_legs):
        if not isinstance(raw_leg, dict):
            continue
        selection = _text(raw_leg.get("selection"), 500)
        if not selection:
            continue
        is_bonus = bool(raw_leg.get("is_bonus")) or selection.lower() in {"bonus", "accumulator bonus"}
        odds = _number(raw_leg.get("odds"), 1.0, 100_000.0)
        legs.append({
            "index": index + 1,
            "league": _text(raw_leg.get("league"), 160),
            "event": _text(raw_leg.get("event"), 300),
            "event_url": _text(raw_leg.get("event_url"), 600),
            "selection": selection,
            "status": _status(raw_leg.get("status")),
            "odds": odds,
            "result": _text(raw_leg.get("result"), 200),
            "processed_at": _text(raw_leg.get("processed_at"), 80),
            "starts_at": _text(raw_leg.get("starts_at"), 80),
            "game_status": _text(raw_leg.get("game_status"), 80),
            "is_bonus": is_bonus,
            "market": "Bonus" if is_bonus else _market(selection),
            "side": "Other" if is_bonus else _side(selection),
            "odds_bucket": _odds_bucket(odds),
        })
    if not legs:
        raise ValueError("No readable bet legs were found in the selected MelBet drawer.")

    betting_legs = [leg for leg in legs if not leg["is_bonus"]]
    derived_status = "pending"
    if betting_legs and any(leg["status"] == "loss" for leg in betting_legs):
        derived_status = "loss"
    elif betting_legs and all(leg["status"] in {"win", "void", "refund"} for leg in betting_legs):
        derived_status = "win"
    status = _status(raw.get("status"))
    if status in {"pending", "open"} and derived_status != "pending":
        status = derived_status

    return {
        "slip_id": slip_id,
        "placed_at": _text(raw.get("placed_at"), 80),
        "status": status,
        "bet_type": _text(raw.get("bet_type"), 80) or "Unknown",
        "stake": _number(raw.get("stake")) or 0.0,
        "currency": re.sub(r"[^A-Za-z]", "", _text(raw.get("currency"), 8)).upper() or "ETB",
        "total_odds": _number(raw.get("total_odds"), 1.0, 10_000_000.0),
        "potential_winnings": _number(raw.get("potential_winnings")) or 0.0,
        "legs": legs,
        "leg_count": len(betting_legs),
        "source": "melbet-history-drawer",
        "imported_at": datetime.now(timezone.utc).isoformat(),
    }


def load_history(path=HISTORY_PATH):
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        value = {"version": 1, "slips": []}
    return value if isinstance(value, dict) and isinstance(value.get("slips"), list) else {"version": 1, "slips": []}


def save_slip(raw, path=HISTORY_PATH):
    return save_slips([raw], path)["slips"][0]


def save_slips(raw_slips, path=HISTORY_PATH):
    if not isinstance(raw_slips, list) or not raw_slips:
        raise ValueError("MelBet batch import must contain at least one slip.")
    if len(raw_slips) > 500:
        raise ValueError("MelBet batch import is limited to 500 slips at a time.")
    normalized_slips = [normalize_slip(raw) for raw in raw_slips]
    history = load_history(path)
    by_id = {str(item.get("slip_id")): item for item in history["slips"] if isinstance(item, dict)}
    existing_ids = set(by_id)
    for normalized in normalized_slips:
        by_id[normalized["slip_id"]] = normalized
    slips = sorted(by_id.values(), key=lambda item: (item.get("placed_at") or "", item.get("imported_at") or ""), reverse=True)
    document = {"version": 1, "updated_at": datetime.now(timezone.utc).isoformat(), "slips": slips}
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(json.dumps(document, indent=2, ensure_ascii=False), encoding="utf-8")
    temporary.replace(target)
    return {
        "slips": normalized_slips,
        "inserted": sum(item["slip_id"] not in existing_ids for item in normalized_slips),
        "updated": sum(item["slip_id"] in existing_ids for item in normalized_slips),
        "total": len(slips),
    }


def _breakdown(rows, key):
    groups = defaultdict(list)
    for row in rows:
        groups[row.get(key) or "Unknown"].append(row)
    result = []
    for label, items in groups.items():
        settled = [item for item in items if item.get("status") in {"win", "loss"}]
        wins = sum(item.get("status") == "win" for item in settled)
        result.append({
            "label": label,
            "legs": len(items),
            "settled": len(settled),
            "wins": wins,
            "losses": len(settled) - wins,
            "hit_rate": round(wins / len(settled), 4) if settled else None,
        })
    return sorted(result, key=lambda item: (-item["settled"], item["label"]))


def analyse_history(history=None):
    slips = (history or load_history()).get("slips", [])
    settled_slips = [slip for slip in slips if slip.get("status") in {"win", "loss"}]
    won_slips = [slip for slip in settled_slips if slip.get("status") == "win"]
    real_legs = [leg for slip in slips for leg in slip.get("legs", []) if not leg.get("is_bonus")]
    settled_legs = [leg for leg in real_legs if leg.get("status") in {"win", "loss"}]
    won_legs = sum(leg.get("status") == "win" for leg in settled_legs)
    stakes = sum(float(slip.get("stake") or 0) for slip in settled_slips)
    returns = sum(float(slip.get("potential_winnings") or 0) for slip in won_slips)
    net = returns - stakes
    losses_per_slip = [sum(leg.get("status") == "loss" for leg in slip.get("legs", []) if not leg.get("is_bonus")) for slip in settled_slips]
    near_misses = sum(losses == 1 for losses in losses_per_slip)
    avg_legs = sum(int(slip.get("leg_count") or 0) for slip in settled_slips) / len(settled_slips) if settled_slips else 0
    repeated = Counter((leg.get("event"), leg.get("selection")) for leg in settled_legs)
    repeat_exposure = sum(count - 1 for count in repeated.values() if count > 1)

    by_market = _breakdown(settled_legs, "market")
    by_side = _breakdown(settled_legs, "side")
    by_odds = _breakdown(settled_legs, "odds_bucket")
    advice = []
    if avg_legs >= 8:
        advice.append({"severity": "high", "title": "Shorten the 100%-focused cards", "detail": f"Settled slips average {avg_legs:.1f} legs. A strong leg hit rate compounds into a much lower full-slip hit rate; use 3–5 leg Sweep cards and keep all-games cards as coverage only."})
    if settled_slips and near_misses / len(settled_slips) >= 0.25:
        advice.append({"severity": "high", "title": "Separate the final risk leg", "detail": f"{near_misses} of {len(settled_slips)} settled slips missed by exactly one leg. Put the weakest or highest-odds leg on a rotated card instead of every core card."})
    weak_markets = [row for row in by_market if row["settled"] >= 3 and row["hit_rate"] is not None and row["hit_rate"] < 0.65]
    if weak_markets:
        labels = ", ".join(row["label"] for row in weak_markets[:3])
        advice.append({"severity": "medium", "title": "Throttle weak market families", "detail": f"Recent imported evidence is weakest in {labels}. Require post-selection evidence or reduce these markets to one leg per card until the sample recovers."})
    high_odds = next((row for row in by_odds if row["label"] == "2.00+"), None)
    if high_odds and high_odds["settled"] >= 3 and (high_odds["hit_rate"] or 0) < 0.5:
        advice.append({"severity": "medium", "title": "Cap high-odds outliers", "detail": f"2.00+ legs are {high_odds['wins']}-{high_odds['losses']} in this history. Keep them off core Sweep cards unless the reranker and sportsbook price agree."})
    if repeat_exposure:
        advice.append({"severity": "medium", "title": "Reduce correlated repeat exposure", "detail": f"The same event and selection was repeated {repeat_exposure} extra time(s). Cap repeated game, player, team and direction exposure across cards."})
    if not advice:
        advice.append({"severity": "info", "title": "Keep collecting settled slips", "detail": "No stable failure pattern has cleared the minimum sample yet. Import both winning and losing slips so Alter Ego does not learn from a biased subset."})

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "overview": {
            "slips": len(slips), "settled_slips": len(settled_slips), "won_slips": len(won_slips),
            "slip_hit_rate": round(len(won_slips) / len(settled_slips), 4) if settled_slips else None,
            "settled_legs": len(settled_legs), "won_legs": won_legs,
            "leg_hit_rate": round(won_legs / len(settled_legs), 4) if settled_legs else None,
            "near_misses": near_misses, "average_legs": round(avg_legs, 2),
            "stake": round(stakes, 2), "returns": round(returns, 2), "net": round(net, 2),
            "roi": round(net / stakes, 4) if stakes else None,
        },
        "breakdowns": {"markets": by_market, "sides": by_side, "odds": by_odds},
        "advice": advice,
        "slips": slips,
    }


def snapshot():
    return analyse_history(load_history())
