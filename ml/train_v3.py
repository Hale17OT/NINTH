"""Train the practical, live-reproducible NINTH v3 candidate."""
import json,os
from collections import defaultdict,deque
from datetime import date as calendar_date,timedelta
from math import sqrt
from pathlib import Path

import joblib,numpy as np
from sklearn.isotonic import IsotonicRegression
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression,Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from ml.features import FEATURE_NAMES,apply_result,fresh_state,reset_season_records,serializable_state
from ml.modeling import CenteredProbabilityShrink,MarginProbabilityModel,ProbabilityBlend
from ml.starter_statcast_experiment import RAW,STARTER_CONTEXTS,read_jsonl,starter_matrix
from ml.v2_experiment import DATA,matrix,score

ROOT=Path(__file__).resolve().parents[1];ARTIFACTS=Path(os.getenv('NINTH_ARTIFACT_DIR',ROOT/'ml'/'artifacts'))
STARTER_FEATURES=['starter_statcast_long_xwoba_advantage','starter_statcast_long_hard_hit_advantage','starter_statcast_long_barrel_advantage','starter_statcast_long_whiff_advantage','starter_statcast_long_kbb_advantage','starter_statcast_long_velocity_advantage','starter_statcast_joint_reliability','starter_statcast_start_count_difference']

def fit(X,y,margins):
    target=np.clip(margins,-8,8);regressor=Pipeline([('scale',StandardScaler()),('ridge',Ridge(alpha=100))]).fit(X,target);fitted=regressor.predict(X);calibrator=LogisticRegression(C=.1,max_iter=2000).fit(fitted.reshape(-1,1),y);margin=MarginProbabilityModel(regressor,calibrator)
    nonlinear=HistGradientBoostingClassifier(learning_rate=.03,max_iter=180,max_leaf_nodes=11,min_samples_leaf=120,l2_regularization=15,random_state=42).fit(X,y)
    # Fixed from 2022-2024 rolling-origin development only. The nonlinear
    # component adds a little decision diversity; shrinkage corrects the
    # incumbent's measured overconfidence without changing pick direction.
    return CenteredProbabilityShrink(ProbabilityBlend([margin,nonlinear],[.75,.25]),.90)

def histories():
    values=defaultdict(lambda:deque(maxlen=15))
    for game in sorted(read_jsonl(RAW),key=lambda row:(row['date'],row['game_id'])):
        for side in ('home_starter','away_starter'):
            pitcher=game.get(side)
            if pitcher and pitcher.get('pitcher_id'):values[str(pitcher['pitcher_id'])].append(pitcher)
    return {key:list(value) for key,value in values.items()}

def summarize_slip_samples(samples,method,training_windows):
    top_five=[item for item in samples if item['legs']==5]
    train=[item for item in samples if item['year']<=2024];test=[item for item in samples if item['year']>=2025]
    x=lambda rows:np.asarray([[np.log(np.clip(item['raw'],1e-6,1-1e-6)/(1-np.clip(item['raw'],1e-6,1-1e-6)))] for item in rows])
    y=lambda rows:np.asarray([item['won'] for item in rows],dtype=int)
    validation_model=LogisticRegression(C=.1,max_iter=2000).fit(x(train),y(train));validation_probability=validation_model.predict_proba(x(test))[:,1]
    final_model=LogisticRegression(C=.1,max_iter=2000).fit(x(samples),y(samples))
    bounds=[0,.02,.04,.06,.08,.12,.18,.30,1.0];bins=[]
    for lower,upper in zip(bounds,bounds[1:]):
        rows=[item for item in samples if lower<=item['raw']<(upper if upper<1 else upper+1)]
        if not rows:continue
        n=len(rows);wins=sum(item['won'] for item in rows);rate=wins/n;z=1.96;denom=1+z*z/n;center=(rate+z*z/(2*n))/denom;margin=z*sqrt((rate*(1-rate)+z*z/(4*n))/n)/denom
        bins.append({'raw_min':lower,'raw_max':upper,'samples':n,'mean_raw':round(float(np.mean([item['raw'] for item in rows])),4),'observed_all_correct':round(rate,4),'wilson_low':round(max(0,center-margin),4),'wilson_high':round(min(1,center+margin),4)})
    top5_recent=[item for item in top_five if item['year']>=2025]
    per_leg=[]
    for legs in range(2,9):
        rows=[item for item in samples if item['legs']==legs];recent=[item for item in rows if item['year']>=2025]
        wins=sum(item['won'] for item in rows);recent_wins=sum(item['won'] for item in recent)
        n=len(rows);rate=wins/n if n else 0;z=1.96;denom=1+z*z/n if n else 1;center=(rate+z*z/(2*n))/denom if n else 0;margin=z*sqrt((rate*(1-rate)+z*z/(4*n))/n)/denom if n else 0
        per_leg.append({'legs':legs,'samples':n,'hits':wins,'observed_all_correct':round(rate,4) if n else None,'wilson_low':round(max(0,center-margin),4) if n else None,'wilson_high':round(min(1,center+margin),4) if n else None,'mean_raw_probability':round(float(np.mean([item['raw'] for item in rows])),4) if rows else None,'recent_samples':len(recent),'recent_hits':recent_wins,'recent_observed_all_correct':round(recent_wins/len(recent),4) if recent else None})
    raw_brier=float(np.mean([(item['raw']-item['won'])**2 for item in test]));calibrated_brier=float(np.mean((validation_probability-y(test))**2))
    return {'method':method,'promoted':calibrated_brier<raw_brier,'intercept':round(float(final_model.intercept_[0]),6),'logit_slope':round(float(final_model.coef_[0,0]),6),'training_samples':len(samples),'training_days':training_windows,'leg_counts':[2,3,4,5,6,7,8],'per_leg':per_leg,'validation_seasons':[2025,2026],'validation_samples':len(test),'validation_brier_raw':round(raw_brier,5),'validation_brier_calibrated':round(calibrated_brier,5),'top_five':{'samples':len(top_five),'mean_raw':round(float(np.mean([item['raw'] for item in top_five])),4),'observed_all_correct':round(float(np.mean([item['won'] for item in top_five])),4),'recent_samples':len(top5_recent),'recent_observed_all_correct':round(float(np.mean([item['won'] for item in top5_recent])),4) if top5_recent else None},'bins':bins}

def prediction_days(probabilities,actual,dates):
    by_date=defaultdict(list)
    for probability,result,date in zip(probabilities,actual,dates):
        selected=max(float(probability),1-float(probability));correct=bool((probability>=.5)==result)
        by_date[date].append((selected,correct))
    return by_date

def build_slip_calibration(probabilities,actual,dates):
    """Calibrate same-day multi-leg confidence from out-of-fold daily cards."""
    by_date=prediction_days(probabilities,actual,dates);samples=[]
    for date,rows in by_date.items():
        ranked=sorted(rows,reverse=True)
        for legs in range(2,min(8,len(ranked))+1):
            chosen=ranked[:legs];raw=float(np.prod([item[0] for item in chosen]));won=all(item[1] for item in chosen)
            samples.append({'date':date,'year':int(date[:4]),'legs':legs,'raw':raw,'won':won})
    return summarize_slip_samples(samples,'logistic calibration of same-day top-N out-of-fold cards',len(by_date))

def build_multiday_calibrations(probabilities,actual,dates):
    by_date=prediction_days(probabilities,actual,dates);available=sorted(by_date);results={}
    for horizon in (3,5,7):
        samples=[];windows=0
        for start in available:
            first=calendar_date.fromisoformat(start);last=first+timedelta(days=horizon-1)
            rows=[]
            for offset in range(horizon):rows.extend(by_date.get((first+timedelta(days=offset)).isoformat(),[]))
            if len(rows)<2 or last.year!=first.year:continue
            windows+=1;ranked=sorted(rows,reverse=True)
            for legs in range(2,min(8,len(ranked))+1):
                chosen=ranked[:legs];samples.append({'date':start,'year':first.year,'legs':legs,'raw':float(np.prod([item[0] for item in chosen])),'won':all(item[1] for item in chosen)})
        results[str(horizon)]=summarize_slip_samples(samples,f'logistic calibration of {horizon}-day top-N out-of-fold cards',windows)
    return results

def build_multiday_validation_grid(probabilities,actual,dates):
    """Validate every supported range/leg pair without pooling unlike cards."""
    by_date=prediction_days(probabilities,actual,dates);available=sorted(by_date);grid={}
    for horizon in range(2,15):
        by_legs=defaultdict(list)
        for start in available:
            first=calendar_date.fromisoformat(start);last=first+timedelta(days=horizon-1)
            if last.year!=first.year:continue
            rows=[]
            for offset in range(horizon):rows.extend(by_date.get((first+timedelta(days=offset)).isoformat(),[]))
            ranked=sorted(rows,reverse=True)
            for legs in range(2,min(10,len(ranked))+1):
                chosen=ranked[:legs];by_legs[legs].append({'date':start,'year':first.year,'raw':float(np.prod([item[0] for item in chosen])),'won':all(item[1] for item in chosen)})
        grid[str(horizon)]={}
        for legs in range(2,11):
            samples=by_legs.get(legs,[]);train=[item for item in samples if item['year']<=2024];test=[item for item in samples if item['year']>=2025]
            if len(train)<250 or len(test)<100 or len({item['won'] for item in train})<2:
                grid[str(horizon)][str(legs)]={'range_days':horizon,'legs':legs,'status':'insufficient','promoted':False,'training_samples':len(train),'validation_samples':len(test)};continue
            x=lambda rows:np.asarray([[np.log(np.clip(item['raw'],1e-6,1-1e-6)/(1-np.clip(item['raw'],1e-6,1-1e-6)))] for item in rows])
            y=lambda rows:np.asarray([item['won'] for item in rows],dtype=int)
            candidate=LogisticRegression(C=.05,max_iter=2000).fit(x(train),y(train));candidate_p=candidate.predict_proba(x(test))[:,1]
            raw_brier=float(np.mean([(item['raw']-item['won'])**2 for item in test]));cal_brier=float(np.mean((candidate_p-y(test))**2));per_year={};stable=True
            for year in (2025,2026):
                rows=[item for item in test if item['year']==year]
                if len(rows)<50:continue
                predicted=candidate.predict_proba(x(rows))[:,1];raw_year=float(np.mean([(item['raw']-item['won'])**2 for item in rows]));cal_year=float(np.mean((predicted-y(rows))**2));per_year[str(year)]={'samples':len(rows),'raw_brier':round(raw_year,5),'calibrated_brier':round(cal_year,5),'improvement':round(raw_year-cal_year,5)}
                if cal_year-raw_year>.0005:stable=False
            wins=sum(item['won'] for item in test);n=len(test);rate=wins/n;z=1.96;denom=1+z*z/n;center=(rate+z*z/(2*n))/denom;margin=z*sqrt((rate*(1-rate)+z*z/(4*n))/n)/denom
            promoted=raw_brier-cal_brier>=.001 and stable and wins>=5
            final=LogisticRegression(C=.05,max_iter=2000).fit(x(samples),y(samples))
            grid[str(horizon)][str(legs)]={'range_days':horizon,'legs':legs,'status':'promoted' if promoted else 'rejected','promoted':promoted,'method':'exact range-and-leg logistic calibration','intercept':round(float(final.intercept_[0]),6),'logit_slope':round(float(final.coef_[0,0]),6),'training_samples':len(train),'validation_samples':n,'validation_brier_raw':round(raw_brier,5),'validation_brier_calibrated':round(cal_brier,5),'validation_improvement':round(raw_brier-cal_brier,5),'validation_mean_raw':round(float(np.mean([item['raw'] for item in test])),4),'validation_observed_all_correct':round(rate,4),'validation_wilson_low':round(max(0,center-margin),4),'validation_wilson_high':round(min(1,center+margin),4),'validation_wins':wins,'per_year':per_year}
    return grid

def main():
    base,_,_,y,years,context_count,_=matrix();starter,coverage=starter_matrix();X=np.column_stack([base,starter[:,6:]])
    games=sorted(read_jsonl(DATA),key=lambda row:(row['date'],row['game_id']));margins=np.asarray([float(game['home_score']-game['away_score']) for game in games]);probabilities=[];actual=[];oof_dates=[];outer_p=[];outer_y=[];per_year={}
    for year in sorted(set(years)):
        if year<2022 or np.sum(years<year)<4000:continue
        train,test=years<year,years==year;p=fit(X[train],y[train],margins[train]).predict_proba(X[test])[:,1];probabilities.extend(p);actual.extend(y[test]);oof_dates.extend([games[index]['date'] for index in np.flatnonzero(test)]);per_year[str(int(year))]=score(y[test],p)
        if year>=2024:outer_p.extend(p);outer_y.extend(y[test])
    probabilities,actual=np.asarray(probabilities),np.asarray(actual);oof_years=np.asarray([int(value[:4]) for value in oof_dates]);correct=(probabilities>=.5)==actual;confidence=IsotonicRegression(increasing=True,out_of_bounds='clip',y_min=.5,y_max=.85).fit(np.abs(probabilities-.5),correct.astype(float));walk=score(actual,probabilities);outer=score(np.asarray(outer_y),np.asarray(outer_p));development=score(actual[oof_years<=2024],probabilities[oof_years<=2024]);locked=score(actual[oof_years>=2025],probabilities[oof_years>=2025])
    curve=[{'probability_margin':margin,'expected_accuracy':round(float(confidence.predict([margin])[0]),4)} for margin in (0,.025,.05,.075,.10,.15,.20,.30,.40)];selective=[]
    for threshold in (.05,.10,.15,.20,.25,.30):
        mask=np.abs(probabilities-.5)>=threshold;selective.append({'minimum_probability':round(.5+threshold,2),'games':int(mask.sum()),'coverage':round(float(mask.mean()),4),'accuracy':round(float(correct[mask].mean()),4) if mask.any() else None})
    contexts={str(row['game_id']):row for row in read_jsonl(STARTER_CONTEXTS)};state=fresh_state();current=None
    for game in games:
        if game['season']!=current:
            if current is not None:reset_season_records(state)
            current=game['season']
        apply_result(state,game,contexts.get(str(game['game_id'])))
    slip_calibration=build_slip_calibration(probabilities,actual,oof_dates);multiday_calibrations=build_multiday_calibrations(probabilities,actual,oof_dates);multiday_grid=build_multiday_validation_grid(probabilities,actual,oof_dates)
    report={'model':'v5_prior_strength_calibrated_margin_histogram_blend','status':'promoted','market_inputs':False,'point_in_time_context':True,'selection_policy':'Previous-season strength features and the existing 75/25 margin/nonlinear architecture were validated on rolling-origin seasons. The later 2025-2026 audit must improve before promotion.','promotion_note':'Carries full prior-season win and run quality into early-season forecasts, then hands weight to current-season strength as games accumulate.','deployment_training_games':len(games),'training_through_season':int(max(years)),'trained_through_date':games[-1]['date'],'context_games':context_count,'starter_statcast_coverage':coverage,'accuracy':per_year[str(int(max(years)))]['accuracy'],'log_loss':per_year[str(int(max(years)))]['log_loss'],'brier_score':per_year[str(int(max(years)))]['brier_score'],'roc_auc':per_year[str(int(max(years)))]['roc_auc'],'holdout_season':int(max(years)),'holdout_games':int(np.sum(years==max(years))),'walk_forward_seasons':[int(v) for v in sorted(set(years)) if v>=2022],'walk_forward':walk,'development_2022_2024':development,'temporal_audit_2025_2026':locked,'recent_outer':outer,'per_year':per_year,'features':FEATURE_NAMES+STARTER_FEATURES,'selected_features':FEATURE_NAMES+STARTER_FEATURES,'confidence_definition':'Expected straight-up hit rate among similarly decisive walk-forward predictions, adjusted for live input completeness.','confidence_curve':curve,'selective_accuracy':selective,'slip_calibration':slip_calibration,'multiday_slip_calibrations':multiday_calibrations,'multiday_validation_grid':multiday_grid,'qualified_accuracy':walk['qualified_accuracy'],'qualified_coverage':walk['qualified_coverage']}
    model=fit(X,y,margins);bundle={'model_version':5,'model':model,'confidence_model':confidence,'state':serializable_state(state),'starter_statcast_histories':histories(),'trained_through_date':games[-1]['date'],'features':FEATURE_NAMES+STARTER_FEATURES,'report':report}
    ARTIFACTS.mkdir(parents=True,exist_ok=True);joblib.dump(bundle,ARTIFACTS/'moneyline.joblib');(ARTIFACTS/'report.json').write_text(json.dumps(report,indent=2),encoding='utf8');print(json.dumps(report,indent=2))

if __name__=='__main__':main()
