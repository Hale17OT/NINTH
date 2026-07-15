"""Leakage-safe confirmed-lineup hitter Statcast shadow experiment."""
import json
from collections import defaultdict, deque
from pathlib import Path

import numpy as np

from ml.starter_statcast_experiment import margin_probability, rolling_margin_predictions, starter_matrix
from ml.v2_experiment import CONTEXTS, DATA, logistic, matrix, read_jsonl, score

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "ml" / "data" / "statcast_player_games.jsonl"
CONTEXTS_V3 = ROOT / "ml" / "data" / "contexts_v3.jsonl"
OUTPUT = ROOT / "ml" / "artifacts" / "hitter_statcast_experiment.json"
ORDER_WEIGHTS = np.asarray([1.12, 1.10, 1.08, 1.06, 1.02, .98, .93, .88, .83])
RATE_NAMES = ("xwoba", "woba", "hard_hit_rate", "barrel_rate", "discipline")
FEATURE_NAMES = [f"confirmed_lineup_recent_{name}_advantage" for name in RATE_NAMES]
FEATURE_NAMES += [f"confirmed_lineup_long_{name}_advantage" for name in RATE_NAMES]
FEATURE_NAMES += ["confirmed_lineup_joint_reliability"]
ORDERED_LINEUP_FEATURE_NAMES = ["ordered_lineup_shrunk_ops_advantage", "ordered_lineup_top_four_advantage", "ordered_lineup_depth_advantage", "ordered_lineup_joint_reliability"]
BULLPEN_FEATURE_NAMES = ["available_bullpen_xwoba_advantage", "available_bullpen_hard_hit_advantage", "available_bullpen_barrel_advantage", "available_bullpen_whiff_advantage", "available_bullpen_kbb_advantage", "available_bullpen_velocity_advantage", "available_bullpen_freshness_advantage", "available_bullpen_joint_reliability"]


def finite(value):
    try:
        result = float(value)
        return result if np.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def weighted(rows, field, weight_field, fallback):
    numerator = denominator = 0.0
    for row in rows:
        value, weight = finite(row.get(field)), finite(row.get(weight_field))
        if value is not None and weight is not None and weight > 0:
            numerator += value * weight; denominator += weight
    return numerator / denominator if denominator else fallback


def player_summary(history, limit):
    rows = list(history)[-limit:]
    pa = sum(finite(row.get("plate_appearances")) or 0 for row in rows)
    bip = sum(finite(row.get("balls_in_play")) or 0 for row in rows)
    strikeouts = sum(finite(row.get("strikeouts")) or 0 for row in rows)
    walks = sum(finite(row.get("walks")) or 0 for row in rows)

    def shrink(value, prior, sample, stabilization):
        reliability = sample / (sample + stabilization)
        return prior + reliability * (value - prior)

    return {
        "xwoba": shrink(weighted(rows, "xwoba", "plate_appearances", .320), .320, pa, 100),
        "woba": shrink(weighted(rows, "woba", "plate_appearances", .315), .315, pa, 100),
        "hard_hit_rate": shrink(weighted(rows, "hard_hit_rate", "balls_in_play", .385), .385, bip, 80),
        "barrel_rate": shrink(weighted(rows, "barrel_rate", "balls_in_play", .075), .075, bip, 80),
        "discipline": shrink((walks - strikeouts) / pa if pa else -.12, -.12, pa, 100),
        "reliability": pa / (pa + 100),
    }


def lineup_summary(ids, histories, limit):
    values = [player_summary(histories[str(player_id)], limit) for player_id in ids[:9]]
    while len(values) < 9:
        values.append(player_summary((), limit))
    weights = ORDER_WEIGHTS / ORDER_WEIGHTS.sum()
    return {name: float(sum(weight * value[name] for weight, value in zip(weights, values))) for name in (*RATE_NAMES, "reliability")}


def hitter_matrix():
    games = sorted(read_jsonl(DATA), key=lambda row: (row["date"], row["game_id"]))
    contexts = {str(row["game_id"]): row for row in read_jsonl(CONTEXTS)}
    raw = {str(row["game_id"]): row for row in read_jsonl(RAW)}
    histories = defaultdict(lambda: deque(maxlen=30))
    output, expected_lineup_players, observed_lineup_players = [], 0, 0
    for game in games:
        context, current = contexts.get(str(game["game_id"]), {}), raw.get(str(game["game_id"]), {})
        home_ids = (context.get("home") or {}).get("lineup_ids") or []
        away_ids = (context.get("away") or {}).get("lineup_ids") or []
        home_recent, away_recent = lineup_summary(home_ids, histories, 10), lineup_summary(away_ids, histories, 10)
        home_long, away_long = lineup_summary(home_ids, histories, 30), lineup_summary(away_ids, histories, 30)
        output.append(
            [home_recent[name] - away_recent[name] for name in RATE_NAMES]
            + [home_long[name] - away_long[name] for name in RATE_NAMES]
            + [min(home_long["reliability"], away_long["reliability"])]
        )
        for side, lineup_ids in (("home", home_ids), ("away", away_ids)):
            observed = current.get(f"{side}_batters") or []
            observed_ids = {str(item.get("batter_id")) for item in observed}
            if current:
                expected_lineup_players += len(lineup_ids[:9])
                observed_lineup_players += sum(str(player_id) in observed_ids for player_id in lineup_ids[:9])
            for batter in observed:
                if batter.get("batter_id"):
                    histories[str(batter["batter_id"])].append(batter)
    return np.asarray(output, dtype=float), {
        "raw_games": len(raw),
        "first_raw_date": min((row.get("date") for row in raw.values()), default=None),
        "last_raw_date": max((row.get("date") for row in raw.values()), default=None),
        "expected_confirmed_lineup_players": expected_lineup_players,
        "observed_confirmed_lineup_players": observed_lineup_players,
        "lineup_player_match_rate": round(observed_lineup_players / expected_lineup_players, 5) if expected_lineup_players else 0,
    }


def ordered_lineup_matrix():
    games = sorted(read_jsonl(DATA), key=lambda row: (row["date"], row["game_id"]))
    contexts = {str(row["game_id"]): row for row in read_jsonl(CONTEXTS_V3)}
    output = []
    for game in games:
        context = contexts.get(str(game["game_id"]), {})
        summaries = []
        for side in ("home", "away"):
            players = (context.get(side) or {}).get("lineup_players") or []
            values = [finite(player.get("shrunk_ops")) or .710 for player in players[:9]]
            pas = [finite(player.get("pa")) or 0 for player in players[:9]]
            while len(values) < 9: values.append(.710); pas.append(0)
            weights = ORDER_WEIGHTS / ORDER_WEIGHTS.sum()
            summaries.append({"weighted":float(np.dot(weights, values)), "top":float(np.mean(values[:4])), "depth":float(np.mean(values[4:])), "reliability":min(1.0, float(np.mean(pas))/200)})
        home, away = summaries
        output.append([home["weighted"]-away["weighted"], home["top"]-away["top"], home["depth"]-away["depth"], min(home["reliability"],away["reliability"])])
    return np.asarray(output, dtype=float), len(contexts)


def bullpen_matrix():
    """Quality and recent workload for the submitted, pregame-available relievers."""
    from datetime import date
    games = sorted(read_jsonl(DATA), key=lambda row: (row["date"], row["game_id"]))
    contexts = {str(row["game_id"]): row for row in read_jsonl(CONTEXTS_V3)}
    raw = {str(row["game_id"]): row for row in read_jsonl(RAW)}
    histories = defaultdict(lambda: deque(maxlen=15)); output = []

    def pitcher_summary(history, game_date):
        rows = list(history); pa=sum(finite(row.get("plate_appearances")) or 0 for row in rows);pitches=sum(finite(row.get("pitches")) or 0 for row in rows);bip=sum(finite(row.get("balls_in_play")) or 0 for row in rows)
        strikeouts=sum(finite(row.get("strikeouts")) or 0 for row in rows);walks=sum(finite(row.get("walks")) or 0 for row in rows)
        def shrink(value,prior,sample,stabilization):
            weight=sample/(sample+stabilization);return prior+weight*(value-prior)
        target=date.fromisoformat(game_date);workload=sum(finite(row.get("pitches")) or 0 for row in rows if 0<(target-date.fromisoformat(row["date"])).days<=3)
        return {"xwoba":shrink(weighted(rows,"xwoba","plate_appearances",.320),.320,pa,100),"hard":shrink(weighted(rows,"hard_hit_rate","balls_in_play",.385),.385,bip,80),"barrel":shrink(weighted(rows,"barrel_rate","balls_in_play",.075),.075,bip,80),"whiff":shrink(weighted(rows,"whiff_rate","pitches",.105),.105,pitches,400),"kbb":shrink((strikeouts-walks)/pa if pa else .12,.12,pa,100),"velocity":shrink(weighted(rows,"avg_velocity","pitches",92.5),92.5,pitches,200),"workload":workload,"reliability":pitches/(pitches+500)}

    def roster_summary(ids, game_date):
        values=[pitcher_summary(histories[str(player_id)],game_date) for player_id in ids]
        if not values: values=[pitcher_summary((),game_date)]
        return {name:float(np.mean([value[name] for value in values])) for name in ("xwoba","hard","barrel","whiff","kbb","velocity","workload","reliability")}

    for game in games:
        context,current=contexts.get(str(game["game_id"]),{}),raw.get(str(game["game_id"]),{})
        def full_pregame_pool(side):
            # In a final MLB boxscore `bullpen` contains pitchers who did not
            # enter, while pitcher_lines contains those who did.  Their disjoint
            # union reconstructs the submitted pregame pitcher pool.  Current
            # game performance is still appended only after feature creation.
            starter_id=str((current.get(f"{side}_starter") or {}).get("pitcher_id"))
            unused=set((context.get(side) or {}).get("bullpen_ids") or [])
            appeared={line.get("pitcher_id") for line in current.get(f"{side}_pitcher_lines") or [] if line.get("pitcher_id") and str(line.get("pitcher_id"))!=starter_id}
            return sorted({int(player_id) for player_id in unused|appeared})
        home=roster_summary(full_pregame_pool("home"),game["date"]);away=roster_summary(full_pregame_pool("away"),game["date"])
        output.append([away["xwoba"]-home["xwoba"],away["hard"]-home["hard"],away["barrel"]-home["barrel"],home["whiff"]-away["whiff"],home["kbb"]-away["kbb"],home["velocity"]-away["velocity"],away["workload"]-home["workload"],min(home["reliability"],away["reliability"])])
        for side in ("home","away"):
            starter_id=(current.get(f"{side}_starter") or {}).get("pitcher_id")
            for pitcher in current.get(f"{side}_pitcher_lines") or []:
                if pitcher.get("pitcher_id") and str(pitcher.get("pitcher_id"))!=str(starter_id):histories[str(pitcher["pitcher_id"])].append({**pitcher,"date":game["date"]})
    return np.asarray(output,dtype=float)


def main():
    base, v2, _, y, years, context_count, _ = matrix()
    starter, starter_coverage = starter_matrix()
    hitters, hitter_coverage = hitter_matrix()
    if hitter_coverage["raw_games"] < 13000 or (hitter_coverage.get("last_raw_date") or "") < "2026-07-12":
        raise SystemExit(f"hitter Statcast backfill incomplete: {hitter_coverage['raw_games']} games")
    lean = np.delete(v2, [1, 3], axis=1)
    ordered, v3_count = ordered_lineup_matrix(); bullpen = bullpen_matrix()
    if v3_count < 13000: raise SystemExit(f"contexts_v3 backfill incomplete: {v3_count} games")
    common = np.column_stack([base, lean])
    sets = {
        "lean_hitter": np.column_stack([common, hitters]),
        "recent_starter": np.column_stack([common, starter[:, :6], starter[:, 12:]]),
        "recent_starter_hitter": np.column_stack([common, starter[:, :6], starter[:, 12:], hitters]),
        "long_starter_hitter": np.column_stack([common, starter[:, 6:], hitters]),
        "recent_starter_personnel": np.column_stack([common, starter[:, :6], starter[:, 12:], hitters, ordered, bullpen]),
        "long_starter_personnel": np.column_stack([common, starter[:, 6:], hitters, ordered, bullpen]),
    }
    games = sorted(read_jsonl(DATA), key=lambda row: (row["date"], row["game_id"]))
    margins = np.asarray([float(game["home_score"] - game["away_score"]) for game in games])
    results = {}
    for name, X in sets.items():
        probability, actual, per_year = rolling_margin_predictions(X, y, years, margins)
        results[f"{name}_margin"] = {"aggregate": score(actual, probability), "per_year": per_year}
        print(name, results[f"{name}_margin"], flush=True)
    report = {
        "status": "shadow_only",
        "policy": "Confirmed batting order is known pregame; every hitter rate uses only earlier games.",
        "context_games": context_count,
        "starter_coverage": starter_coverage,
        "hitter_coverage": hitter_coverage,
        "hitter_features": FEATURE_NAMES,
        "ordered_lineup_features": ORDERED_LINEUP_FEATURE_NAMES,
        "bullpen_features": BULLPEN_FEATURE_NAMES,
        "results": results,
    }
    OUTPUT.write_text(json.dumps(report, indent=2), encoding="utf8")


if __name__ == "__main__":
    main()
