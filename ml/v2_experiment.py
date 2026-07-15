"""Combined point-in-time pitcher, lineup, and Statcast shadow evaluation."""
import json
import sys
from collections import defaultdict, deque
from datetime import date
from pathlib import Path

import numpy as np
try:
    from lightgbm import LGBMClassifier
except ImportError:
    LGBMClassifier = None
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import ExtraTreesClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, brier_score_loss, log_loss, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ml.features import FEATURE_NAMES, apply_result, fresh_state, matchup_features, reset_season_records
from ml.accuracy_experiments import STATCAST_FEATURES

DATA = ROOT / "ml" / "data" / "games.jsonl"
CONTEXTS = ROOT / "ml" / "data" / "contexts_v2.jsonl"
STATCAST = ROOT / "ml" / "data" / "statcast_contexts.jsonl"
OUTPUT = ROOT / "ml" / "artifacts" / "v2_experiment.json"
V2_FEATURES = [
    "starter_fip_difference", "starter_kbb_per_inning_difference",
    "starter_career_innings_difference", "lineup_shrunk_ops_difference",
    "lineup_sample_reliability", "recent_starter_era_difference",
    "recent_starter_kbb_difference", "recent_starter_outs_difference",
    "recent_starter_pitch_count_difference", "starter_fatigue_advantage",
    "margin_elo_difference", "ewma_run_matchup_advantage",
]


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()] if path.exists() else []


def logistic(c=.1, calibrated=True):
    model = Pipeline([("scale", StandardScaler()), ("model", LogisticRegression(C=c, max_iter=4000))])
    return CalibratedClassifierCV(model, method="sigmoid", cv=5) if calibrated else model


def extra_trees():
    return ExtraTreesClassifier(n_estimators=600, min_samples_leaf=35, max_features=.7, class_weight="balanced", n_jobs=-1, random_state=42)


def lightgbm():
    if LGBMClassifier is None:
        raise RuntimeError("LightGBM is an optional shadow-experiment dependency")
    return LGBMClassifier(n_estimators=400, learning_rate=.02, num_leaves=9, max_depth=4, min_child_samples=100, subsample=.85, colsample_bytree=.8, reg_alpha=1.5, reg_lambda=5, random_state=42, n_jobs=-1, verbosity=-1)


def pitcher_default():
    return {"games": deque(maxlen=5), "last_date": None}


def team_rating_default():
    return {"elo": 1500.0, "offense": 4.5, "defense": 4.5}


def pitcher_summary(value):
    games = list(value["games"])
    outs = sum(item["outs"] for item in games)
    return {
        "era": 27 * sum(item["earned"] for item in games) / outs if outs else 4.5,
        "kbb": 3 * sum(item["strikeouts"] - item["walks"] for item in games) / outs if outs else 1.0,
        "outs": sum(item["outs"] for item in games) / len(games) if games else 15.0,
        "pitches": sum(item["pitches"] for item in games) / len(games) if games else 80.0,
    }


def rest_days(last_date, game_date):
    return 5 if not last_date else max(1, min(10, (date.fromisoformat(game_date) - date.fromisoformat(last_date)).days))


def matrix():
    games = sorted(read_jsonl(DATA), key=lambda row: (row["date"], row["game_id"]))
    contexts = {str(row["game_id"]): row for row in read_jsonl(CONTEXTS)}
    statcast = {str(row["game_id"]): row for row in read_jsonl(STATCAST)}
    if len(contexts) < 13000:
        raise SystemExit(f"contexts_v2 backfill incomplete: {len(contexts)} rows")
    state, pitchers, ratings = fresh_state(), defaultdict(pitcher_default), defaultdict(team_rating_default)
    base_rows, v2_rows, statcast_rows, labels, seasons, current = [], [], [], [], [], None
    for game in games:
        if game["season"] != current:
            if current is not None:
                reset_season_records(state)
                for rating in ratings.values():
                    rating["offense"] = .5 * rating["offense"] + 2.25
                    rating["defense"] = .5 * rating["defense"] + 2.25
            current = game["season"]
        context = contexts.get(str(game["game_id"]))
        base_rows.append(matchup_features(state, game["home_id"], game["away_id"], game["date"], {**context, "context_available": 1} if context else None))
        home, away = (context or {}).get("home", {}), (context or {}).get("away", {})
        hp, ap = pitchers[str(home.get("starter_id"))], pitchers[str(away.get("starter_id"))]
        hrs, ars = pitcher_summary(hp), pitcher_summary(ap)
        home_ip, away_ip = float(home.get("starter_innings", 0) or 0), float(away.get("starter_innings", 0) or 0)
        home_kbb = (float(home.get("starter_strikeouts", 0) or 0) - float(home.get("starter_walks", 0) or 0)) / max(home_ip, 1/3)
        away_kbb = (float(away.get("starter_strikeouts", 0) or 0) - float(away.get("starter_walks", 0) or 0)) / max(away_ip, 1/3)
        home_fatigue = hrs["pitches"] / rest_days(hp["last_date"], game["date"])
        away_fatigue = ars["pitches"] / rest_days(ap["last_date"], game["date"])
        home_rating, away_rating = ratings[str(game["home_id"])], ratings[str(game["away_id"])]
        run_matchup = .5 * (home_rating["offense"] + away_rating["defense"]) - .5 * (away_rating["offense"] + home_rating["defense"])
        v2_rows.append([
            float(away.get("starter_fip", 4.5) or 4.5) - float(home.get("starter_fip", 4.5) or 4.5),
            home_kbb - away_kbb, np.log1p(home_ip) - np.log1p(away_ip),
            float(home.get("lineup_ops_shrunk", .710) or .710) - float(away.get("lineup_ops_shrunk", .710) or .710),
            min(1, (float(home.get("lineup_average_pa", 0) or 0) + float(away.get("lineup_average_pa", 0) or 0)) / 800),
            ars["era"] - hrs["era"], hrs["kbb"] - ars["kbb"], hrs["outs"] - ars["outs"],
            hrs["pitches"] - ars["pitches"], away_fatigue - home_fatigue,
            (home_rating["elo"] + 35) - away_rating["elo"], run_matchup,
        ])
        stat = statcast.get(str(game["game_id"]), {})
        statcast_rows.append([float(stat.get(name, 0) or 0) for name in STATCAST_FEATURES[:-1]] + [float(bool(stat))])
        labels.append(int(game["home_score"] > game["away_score"]));seasons.append(game["season"])
        apply_result(state, game, context)
        home_score, away_score = int(game["home_score"]), int(game["away_score"])
        expected = 1 / (1 + 10 ** ((away_rating["elo"] - (home_rating["elo"] + 35)) / 400))
        home_win = int(home_score > away_score);margin = abs(home_score - away_score)
        winner_gap = (home_rating["elo"] - away_rating["elo"]) * (1 if home_win else -1)
        multiplier = np.log1p(margin) * (2.2 / (winner_gap * .001 + 2.2))
        change = 18 * multiplier * (home_win - expected);home_rating["elo"] += change;away_rating["elo"] -= change
        alpha = .08
        home_rating["offense"] = (1-alpha)*home_rating["offense"] + alpha*home_score
        home_rating["defense"] = (1-alpha)*home_rating["defense"] + alpha*away_score
        away_rating["offense"] = (1-alpha)*away_rating["offense"] + alpha*away_score
        away_rating["defense"] = (1-alpha)*away_rating["defense"] + alpha*home_score
        for side, source in (("home", home), ("away", away)):
            pitcher = pitchers[str(source.get("starter_id"))]
            if source.get("starter_id"):
                pitcher["games"].append({"outs":float(source.get("starter_game_outs",0) or 0),"earned":float(source.get("starter_game_earned_runs",0) or 0),"strikeouts":float(source.get("starter_game_strikeouts",0) or 0),"walks":float(source.get("starter_game_walks",0) or 0),"pitches":float(source.get("starter_game_pitches",0) or 0)})
                pitcher["last_date"] = game["date"]
    return np.asarray(base_rows,float),np.asarray(v2_rows,float),np.asarray(statcast_rows,float),np.asarray(labels),np.asarray(seasons),len(contexts),len(statcast)


def score(y, probability):
    prediction=probability>=.5;qualified=(probability>=.6)|(probability<=.4)
    return {"games":int(len(y)),"accuracy":round(float(accuracy_score(y,prediction)),5),"log_loss":round(float(log_loss(y,probability)),5),"brier_score":round(float(brier_score_loss(y,probability)),5),"roc_auc":round(float(roc_auc_score(y,probability)),5),"qualified_games":int(qualified.sum()),"qualified_coverage":round(float(qualified.mean()),5),"qualified_accuracy":round(float((prediction[qualified]==y[qualified]).mean()),5) if qualified.any() else None}


def main():
    base,v2,statcast,y,years,context_count,statcast_count=matrix();v2_lean=np.delete(v2,[1,3],axis=1);sets={"base":base,"v2":np.column_stack([base,v2]),"v2_lean":np.column_stack([base,v2_lean]),"v2_statcast":np.column_stack([base,v2,statcast]),"v2_lean_statcast":np.column_stack([base,v2_lean,statcast])}
    factories={"calibrated":lambda:logistic(.35,True),"plain":lambda:logistic(.03,False),"extra":extra_trees}
    if LGBMClassifier is not None:factories["lgbm"]=lightgbm
    predictions,labels,results={},{},{}
    for feature_name,X in sets.items():
        for model_name,factory in factories.items():
            name=f"{feature_name}_{model_name}";all_p,all_y,per_year=[],[],{}
            for year in sorted(set(years)):
                if year<2022 or np.sum(years<year)<4000:continue
                train,test=years<year,years==year;p=factory().fit(X[train],y[train]).predict_proba(X[test])[:,1]
                all_p.extend(p);all_y.extend(y[test]);per_year[str(year)]=score(y[test],p)
            predictions[name]=np.asarray(all_p);labels[name]=np.asarray(all_y);results[name]={"aggregate":score(labels[name],predictions[name]),"per_year":per_year};print(name,results[name]["aggregate"],flush=True)
    for feature_name in ("v2","v2_lean","v2_statcast","v2_lean_statcast"):
        left,right=f"{feature_name}_calibrated",f"{feature_name}_extra"
        for weight in (.9,.8,.7,.65,.6,.55,.5):
            name=f"{feature_name}_blend_{round(weight*100)}_{round((1-weight)*100)}";p=weight*predictions[left]+(1-weight)*predictions[right];results[name]={"aggregate":score(labels[left],p),"components":[left,right],"left_weight":weight};print(name,results[name]["aggregate"],flush=True)
    triples={
        "triple_v2_60_30_stat_extra10": [("v2_calibrated",.60),("v2_extra",.30),("v2_statcast_extra",.10)],
        "triple_v2_55_35_stat_extra10": [("v2_calibrated",.55),("v2_extra",.35),("v2_statcast_extra",.10)],
        "triple_v2_55_35_stat_cal10": [("v2_calibrated",.55),("v2_extra",.35),("v2_statcast_calibrated",.10)],
    }
    for name,parts in triples.items():
        probability=sum(weight*predictions[component] for component,weight in parts);key=parts[0][0]
        results[name]={"aggregate":score(labels[key],probability),"components":parts};print(name,results[name]["aggregate"],flush=True)
    report={"status":"shadow_only","policy":"Rolling-origin seasons; no production writes.","context_games":context_count,"statcast_games":statcast_count,"base_features":FEATURE_NAMES,"v2_features":V2_FEATURES,"statcast_features":STATCAST_FEATURES,"results":results}
    OUTPUT.write_text(json.dumps(report,indent=2),encoding="utf8")


if __name__=="__main__":main()
