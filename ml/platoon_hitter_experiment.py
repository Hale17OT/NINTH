"""Individual confirmed-lineup performance versus the confirmed starter hand."""
import json
from collections import defaultdict, deque
from pathlib import Path

import numpy as np

from ml.hitter_statcast_experiment import ORDER_WEIGHTS, finite, weighted
from ml.starter_statcast_experiment import rolling_margin_predictions, starter_matrix
from ml.v2_experiment import CONTEXTS, DATA, matrix, read_jsonl, score

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "ml" / "data" / "statcast_matchup_games.jsonl"
OUTPUT = ROOT / "ml" / "artifacts" / "platoon_hitter_experiment.json"
RATE_NAMES = ("xwoba", "woba", "hard_hit_rate", "barrel_rate", "discipline")
FEATURE_NAMES = [f"confirmed_platoon_recent_{name}_advantage" for name in RATE_NAMES] + [f"confirmed_platoon_long_{name}_advantage" for name in RATE_NAMES] + ["confirmed_platoon_joint_reliability"]


def player_summary(history, limit):
    rows=list(history)[-limit:];pa=sum(finite(row.get("plate_appearances")) or 0 for row in rows);bip=sum(finite(row.get("balls_in_play")) or 0 for row in rows);strikeouts=sum(finite(row.get("strikeouts")) or 0 for row in rows);walks=sum(finite(row.get("walks")) or 0 for row in rows)
    def shrink(value,prior,sample,stabilization):
        weight=sample/(sample+stabilization);return prior+weight*(value-prior)
    return {"xwoba":shrink(weighted(rows,"xwoba","plate_appearances",.320),.320,pa,150),"woba":shrink(weighted(rows,"woba","plate_appearances",.315),.315,pa,150),"hard_hit_rate":shrink(weighted(rows,"hard_hit_rate","balls_in_play",.385),.385,bip,120),"barrel_rate":shrink(weighted(rows,"barrel_rate","balls_in_play",.075),.075,bip,120),"discipline":shrink((walks-strikeouts)/pa if pa else -.12,-.12,pa,150),"reliability":pa/(pa+150)}


def lineup(ids, hand, histories, limit):
    values=[player_summary(histories[(str(player_id),hand)],limit) for player_id in ids[:9]]
    while len(values)<9:values.append(player_summary((),limit))
    weights=ORDER_WEIGHTS/ORDER_WEIGHTS.sum()
    return {name:float(sum(weight*value[name] for weight,value in zip(weights,values))) for name in (*RATE_NAMES,"reliability")}


def platoon_matrix():
    games=sorted(read_jsonl(DATA),key=lambda row:(row["date"],row["game_id"]));contexts={str(row["game_id"]):row for row in read_jsonl(CONTEXTS)};raw={str(row["game_id"]):row for row in read_jsonl(RAW)}
    histories=defaultdict(lambda:deque(maxlen=30));pitcher_hands={};output=[]
    for game in games:
        context,current=contexts.get(str(game["game_id"]),{}),raw.get(str(game["game_id"]),{});home_ids=(context.get("home") or {}).get("lineup_ids") or [];away_ids=(context.get("away") or {}).get("lineup_ids") or []
        home_starter_id=(context.get("home") or {}).get("starter_id");away_starter_id=(context.get("away") or {}).get("starter_id")
        def hand(side,official_id):
            observed=current.get(f"{side}_starter") or {}
            if official_id and str(observed.get("pitcher_id"))==str(official_id):return observed.get("pitcher_hand") or pitcher_hands.get(str(official_id),"R")
            return pitcher_hands.get(str(official_id),"R")
        home_pitcher_hand,away_pitcher_hand=hand("home",home_starter_id),hand("away",away_starter_id)
        hr,ar=lineup(home_ids,away_pitcher_hand,histories,10),lineup(away_ids,home_pitcher_hand,histories,10);hl,al=lineup(home_ids,away_pitcher_hand,histories,30),lineup(away_ids,home_pitcher_hand,histories,30)
        output.append([hr[name]-ar[name] for name in RATE_NAMES]+[hl[name]-al[name] for name in RATE_NAMES]+[min(hl["reliability"],al["reliability"])])
        for side in ("home","away"):
            observed=current.get(f"{side}_starter") or {}
            if observed.get("pitcher_id") and observed.get("pitcher_hand"):pitcher_hands[str(observed["pitcher_id"])]=observed["pitcher_hand"]
            for throwing_hand,suffix in (("L","left"),("R","right")):
                for batter in current.get(f"{side}_batters_vs_{suffix}") or []:
                    if batter.get("batter_id"):histories[(str(batter["batter_id"]),throwing_hand)].append(batter)
    return np.asarray(output,dtype=float),{"raw_games":len(raw),"first_raw_date":min((row.get("date") for row in raw.values()),default=None),"last_raw_date":max((row.get("date") for row in raw.values()),default=None)}


def main():
    base,v2,_,y,years,context_count,_=matrix();starter,starter_coverage=starter_matrix();platoon,coverage=platoon_matrix()
    if coverage["raw_games"]<13000 or (coverage.get("last_raw_date") or "")<"2026-07-12":raise SystemExit(f"platoon backfill incomplete: {coverage['raw_games']}")
    common=np.column_stack([base,np.delete(v2,[1,3],axis=1)]);sets={"recent_starter":np.column_stack([common,starter[:,:6],starter[:,12:]]),"recent_starter_platoon":np.column_stack([common,starter[:,:6],starter[:,12:],platoon]),"long_starter_platoon":np.column_stack([common,starter[:,6:],platoon])}
    games=sorted(read_jsonl(DATA),key=lambda row:(row["date"],row["game_id"]));margins=np.asarray([float(game["home_score"]-game["away_score"]) for game in games]);results={}
    for name,X in sets.items():
        probability,actual,per_year=rolling_margin_predictions(X,y,years,margins);results[name]={"aggregate":score(actual,probability),"per_year":per_year};print(name,results[name],flush=True)
    OUTPUT.write_text(json.dumps({"status":"shadow_only","policy":"Confirmed lineup and starter hand are current-game identities; every performance rate is from prior games only.","context_games":context_count,"starter_coverage":starter_coverage,"platoon_coverage":coverage,"features":FEATURE_NAMES,"results":results},indent=2),encoding="utf8")


if __name__=="__main__":main()
