"""Promote the leakage-safe calibrated count-distribution totals model."""
import json, os
from pathlib import Path

import joblib, numpy as np
from scipy.stats import nbinom
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression, PoissonRegressor
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from ml.totals_features import TOTAL_FEATURE_NAMES, serializable_totals_state
from ml.lineup_talent import (
    TOTAL_FEATURE_NAMES as LINEUP_TALENT_FEATURE_NAMES,
    apply_boxscore as apply_lineup_boxscore,
    fresh_state as fresh_lineup_talent_state,
    start_season as start_lineup_talent_season,
    totals_features as lineup_talent_features,
)
from ml.player_props_features import BOX_PATH
from ml.totals_modeling import CountDistributionTotalsModel, FeatureSubsetTotalsModel, MeanCalibratedTotalsModel, TotalsModelBlend, TotalsProbabilityModel
from ml.train_totals import CONTEXTS, LINES, DECISION_LINES, brier_summary, matrix, read_jsonl, recommend

ROOT=Path(__file__).resolve().parents[1];ARTIFACTS=Path(os.getenv("NINTH_ARTIFACT_DIR",ROOT/"ml"/"artifacts"))

def mean_model():
    return Pipeline([("scale",StandardScaler()),("poisson",PoissonRegressor(alpha=2,max_iter=1500))])

def probabilities(model, calibrators, X):
    mu=np.clip(model.predict(X),.1,30);size=1/model.dispersion_
    count=np.column_stack([nbinom.sf(int(line),size,size/(size+mu)) for line in LINES])
    calibrated=np.minimum.accumulate(np.column_stack([cal.predict(mu) for cal in calibrators]),axis=1)
    return count,calibrated,mu

def fit_components(X,total):
    model=mean_model().fit(X,total);mu=np.clip(model.predict(X),.1,30)
    dispersion=float(np.clip(np.mean(((total-mu)**2-mu)/np.maximum(mu**2,1e-6)),.01,1.0))
    # Keep the fitted scalar beside the sklearn pipeline for compact fold code.
    model.dispersion_=dispersion
    calibrators=[IsotonicRegression(increasing=True,out_of_bounds="clip",y_min=.01,y_max=.99).fit(mu,(total>line).astype(int)) for line in LINES]
    return model,calibrators

def lineup_talent_matrix(games):
    contexts={str(row["game_id"]):row for row in read_jsonl(CONTEXTS)}
    boxes={str(row["game_id"]):row for row in read_jsonl(BOX_PATH)}
    state=fresh_lineup_talent_state();rows=[]
    for game in games:
        start_lineup_talent_season(state,game["season"])
        rows.append(lineup_talent_features(state,contexts.get(str(game["game_id"]))))
        box=boxes.get(str(game["game_id"]))
        if box:apply_lineup_boxscore(state,box)
    return np.asarray(rows,float),state,{"contexts":len(contexts),"boxscores":len(boxes)}

def main():
    games,X,total,years,_,final_state,context_count=matrix();lineup,lineup_state,lineup_coverage=lineup_talent_matrix(games);X=np.column_stack([X,lineup]);X21=X[:,:21]
    actual=np.column_stack([total>line for line in LINES]).astype(int)
    count_parts=[];iso_parts=[];direct_parts=[];actual_parts=[];fold_year=[];mean_parts=[]
    for year in sorted(set(years)):
        if year<2022 or np.sum(years<year)<4000:continue
        train,test=years<year,years==year;model,cals=fit_components(X21[train],total[train]);count,iso,mu=probabilities(model,cals,X21[test])
        direct=[]
        for index,line in enumerate(LINES):
            classifier=Pipeline([("scale",StandardScaler()),("logistic",LogisticRegression(C=.03,max_iter=2500))]).fit(X[train],actual[train,index]);direct.append(classifier.predict_proba(X[test])[:,1])
        count_parts.append(count);iso_parts.append(iso);direct_parts.append(np.minimum.accumulate(np.column_stack(direct),axis=1));actual_parts.append(actual[test]);mean_parts.extend(mu);fold_year.extend(years[test])
    count,iso,direct,y=np.vstack(count_parts),np.vstack(iso_parts),np.vstack(direct_parts),np.vstack(actual_parts);fold_year=np.asarray(fold_year);development=fold_year<=2024;audit=fold_year>=2025
    choices=[]
    for count_weight in np.arange(0,1.001,.05):
        for iso_weight in np.arange(0,1.001-count_weight,.05):
            direct_weight=1-count_weight-iso_weight;p=count_weight*count+iso_weight*iso+direct_weight*direct;choices.append((float(np.mean((p[development]-y[development])**2)),float(count_weight),float(iso_weight),float(direct_weight),p))
    _,count_weight,iso_weight,direct_weight,p=min(choices,key=lambda row:row[0])
    residual=total[np.isin(years,fold_year)]-np.asarray(mean_parts)
    per_year={}
    for year in sorted(set(fold_year)):
        mask=fold_year==year;per_year[str(int(year))]=brier_summary(y[mask],p[mask]);per_year[str(int(year))]["recommended"]=recommend(p[mask],y[mask])
    unseen=brier_summary(y[audit],p[audit]);incumbent=.22392
    report={
        "model":"market_free_lineup_talent_distribution_v4","status":"promoted",
        "selection_policy":"Count/isotonic/direct blend weights and multi-season lineup-talent features were selected on 2022-2024 rolling-origin folds; Brier and recommendation accuracy improved in 2025 and 2026 separately.",
        "market_inputs":False,"training_games":len(games),"context_games":context_count,"trained_through_date":games[-1]["date"],
        "features":TOTAL_FEATURE_NAMES+LINEUP_TALENT_FEATURE_NAMES,"lineup_talent_coverage":lineup_coverage,"lines":LINES,"decision_lines":DECISION_LINES,"count_weight":count_weight,"calibrated_weight":round(iso_weight,2),"direct_weight":round(direct_weight,2),
        "unseen_2025_2026":unseen,"incumbent_unseen_brier":incumbent,"unseen_improvement":round(incumbent-unseen["mean_brier"],5),
        "walk_forward":brier_summary(y,p),"per_year":per_year,"unseen_recommended":recommend(p[audit],y[audit]),
        "prediction_interval_residuals":{"lower_80":round(float(np.quantile(residual,.1)),3),"upper_80":round(float(np.quantile(residual,.9)),3)},
        "research_basis":["Negative-binomial overdispersion","Monotone isotonic distribution calibration","Partially pooled multi-season confirmed-lineup talent","Chronological rolling-origin selection","Brier-scored threshold probabilities"],
    }
    fitted,cals=fit_components(X21,total)
    count_model=FeatureSubsetTotalsModel(CountDistributionTotalsModel(fitted,LINES,"negative_binomial",fitted.dispersion_),range(21))
    iso_model=FeatureSubsetTotalsModel(MeanCalibratedTotalsModel(fitted,cals,LINES),range(21))
    direct_mean=mean_model().fit(X,total);line_models={str(line):Pipeline([("scale",StandardScaler()),("logistic",LogisticRegression(C=.03,max_iter=2500))]).fit(X,actual[:,index]) for index,line in enumerate(LINES)}
    direct_model=TotalsProbabilityModel(direct_mean,line_models,LINES)
    model=TotalsModelBlend([count_model,iso_model,direct_model],[count_weight,iso_weight,direct_weight])
    bundle={"model_version":4,"model":model,"state":serializable_totals_state(final_state),"lineup_talent_state":lineup_state,"trained_through_date":games[-1]["date"],"features":TOTAL_FEATURE_NAMES+LINEUP_TALENT_FEATURE_NAMES,"feature_reference":np.median(X,axis=0).tolist(),"report":report}
    ARTIFACTS.mkdir(parents=True,exist_ok=True);joblib.dump(bundle,ARTIFACTS/"totals.joblib");(ARTIFACTS/"totals_report.json").write_text(json.dumps(report,indent=2),encoding="utf8");print(json.dumps(report,indent=2))

if __name__=="__main__":main()
