import json, sys
from pathlib import Path
import joblib, numpy as np
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, brier_score_loss, log_loss, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from ml.features import FEATURE_NAMES,apply_result,fresh_state,matchup_features,reset_season_records,serializable_state
from ml.modeling import FeatureSubsetModel,ProbabilityBlend
DATA=ROOT/'ml'/'data'/'games.jsonl';CONTEXTS=ROOT/'ml'/'data'/'contexts.jsonl';ARTIFACTS=ROOT/'ml'/'artifacts'

SUBSETS={'logistic_full':list(range(len(FEATURE_NAMES))),'logistic_no_weather':[i for i in range(len(FEATURE_NAMES)) if i not in (18,19)],'logistic_no_lineup_weather':[i for i in range(len(FEATURE_NAMES)) if i not in (16,18,19)],'logistic_legacy':[0,1,2,4,8,11,14,15,16,17,18,19,20]}
def logistic_factory():return CalibratedClassifierCV(Pipeline([('scale',StandardScaler()),('model',LogisticRegression(C=.35,max_iter=3000))]),method='sigmoid',cv=5)
def tree_factory():return CalibratedClassifierCV(HistGradientBoostingClassifier(max_iter=220,learning_rate=.04,max_depth=3,min_samples_leaf=55,l2_regularization=1.5,random_state=42),method='sigmoid',cv=5)

def metrics(y,p):
    return {'accuracy':round(float(accuracy_score(y,p>=.5)),4),'log_loss':round(float(log_loss(y,p)),4),'brier_score':round(float(brier_score_loss(y,p)),4),'roc_auc':round(float(roc_auc_score(y,p)),4)}

def candidate_probabilities(X_train,y_train,X_test,train_years):
    probabilities={}
    for name,indices in SUBSETS.items():probabilities[name]=logistic_factory().fit(X_train[:,indices],y_train).predict_proba(X_test[:,indices])[:,1]
    recent_mask=train_years>=max(train_years)-3
    probabilities['logistic_recent_four_seasons']=logistic_factory().fit(X_train[recent_mask],y_train[recent_mask]).predict_proba(X_test)[:,1]
    probabilities['blend_70_full_30_recent']=.70*probabilities['logistic_full']+.30*probabilities['logistic_recent_four_seasons']
    tree=tree_factory().fit(X_train,y_train).predict_proba(X_test)[:,1];probabilities['calibrated_hist_gradient_boosting']=tree
    logistic=probabilities['logistic_full'];probabilities['blend_75_logistic_25_tree']=.75*logistic+.25*tree;probabilities['blend_50_logistic_50_tree']=.5*logistic+.5*tree
    return probabilities

def fit_selected(name,X,y,years):
    if name in SUBSETS:
        indices=SUBSETS[name];return FeatureSubsetModel(logistic_factory().fit(X[:,indices],y),indices)
    if name=='calibrated_hist_gradient_boosting':return tree_factory().fit(X,y)
    if name=='logistic_recent_four_seasons':
        recent=years>=max(years)-3;return logistic_factory().fit(X[recent],y[recent])
    if name=='blend_70_full_30_recent':
        recent=years>=max(years)-3;return ProbabilityBlend([logistic_factory().fit(X,y),logistic_factory().fit(X[recent],y[recent])],[.70,.30])
    logistic=logistic_factory().fit(X,y);tree=tree_factory().fit(X,y)
    weights=[.75,.25] if name.startswith('blend_75') else [.5,.5]
    return ProbabilityBlend([logistic,tree],weights)

def main():
    if not DATA.exists() or not CONTEXTS.exists():raise SystemExit('Run collect.py and enrich.py first')
    games=sorted((json.loads(line) for line in DATA.read_text(encoding='utf-8').splitlines() if line.strip()),key=lambda row:(row['date'],row['game_id']))
    contexts={str(row['game_id']):row for row in (json.loads(line) for line in CONTEXTS.read_text(encoding='utf-8-sig').splitlines() if line.strip())}
    state,rows,labels,seasons,current=fresh_state(),[],[],[],None
    for game in games:
        if game['season']!=current:
            if current is not None:reset_season_records(state)
            current=game['season']
        context=contexts.get(str(game['game_id']));feature_context={**context,'context_available':1} if context else None
        rows.append(matchup_features(state,game['home_id'],game['away_id'],game['date'],feature_context));labels.append(int(game['home_score']>game['away_score']));seasons.append(game['season']);apply_result(state,game,context)
    X,y,years=np.asarray(rows,float),np.asarray(labels),np.asarray(seasons)
    evaluation_years=[int(year) for year in sorted(set(years)) if year>=2022 and np.sum(years<year)>=4000]
    candidate_names=list(SUBSETS)+['logistic_recent_four_seasons','blend_70_full_30_recent','calibrated_hist_gradient_boosting','blend_75_logistic_25_tree','blend_50_logistic_50_tree'];fold_predictions={name:[] for name in candidate_names}
    fold_labels=[];per_year={}
    for year in evaluation_years:
        train,test=years<year,years==year;predictions=candidate_probabilities(X[train],y[train],X[test],years[train]);fold_labels.extend(y[test].tolist());per_year[str(year)]={}
        for name,probabilities in predictions.items():fold_predictions[name].extend(probabilities.tolist());per_year[str(year)][name]=metrics(y[test],probabilities)
    oof_y=np.asarray(fold_labels);aggregate={name:metrics(oof_y,np.asarray(probabilities)) for name,probabilities in fold_predictions.items()}
    best_loss=min(result['log_loss'] for result in aggregate.values())
    competitive=[name for name,result in aggregate.items() if result['log_loss']<=best_loss+.001]
    selected_name=max(competitive,key=lambda name:aggregate[name]['accuracy']);selected_oof=np.asarray(fold_predictions[selected_name]);correct=(selected_oof>=.5)==oof_y
    confidence_model=IsotonicRegression(increasing=True,out_of_bounds='clip',y_min=.5,y_max=.85).fit(np.abs(selected_oof-.5),correct.astype(float))
    final_model=fit_selected(selected_name,X,y,years)
    last_year=max(evaluation_years);last=per_year[str(last_year)][selected_name]
    confidence_points=[]
    for margin in (0,.025,.05,.075,.10,.15,.20,.30,.40):confidence_points.append({'probability_margin':margin,'expected_accuracy':round(float(confidence_model.predict([margin])[0]),4)})
    selective=[];margins=np.abs(selected_oof-.5)
    for threshold in (.05,.10,.15,.20,.25,.30):
        mask=margins>=threshold
        selective.append({'minimum_probability':round(.5+threshold,2),'games':int(mask.sum()),'coverage':round(float(mask.mean()),4),'accuracy':round(float(correct[mask].mean()),4) if mask.any() else None})
    selected_features=[FEATURE_NAMES[i] for i in SUBSETS.get(selected_name,range(len(FEATURE_NAMES)))]
    report={'model':selected_name,'selection_policy':'Highest walk-forward accuracy among candidates within 0.001 log loss of the best candidate.','market_inputs':False,'point_in_time_context':True,'deployment_training_games':len(games),'training_through_season':int(max(years)),'context_games':len(contexts),'context_training_games':sum(str(g['game_id']) in contexts for g in games),'accuracy':last['accuracy'],'log_loss':last['log_loss'],'brier_score':last['brier_score'],'roc_auc':last['roc_auc'],'holdout_season':int(last_year),'holdout_games':int(np.sum(years==last_year)),'walk_forward_seasons':evaluation_years,'walk_forward':aggregate[selected_name],'walk_forward_candidates':aggregate,'per_year':per_year,'features':FEATURE_NAMES,'selected_features':selected_features,'confidence_definition':'Expected straight-up hit rate among similarly decisive walk-forward predictions, adjusted for live input completeness.','confidence_curve':confidence_points,'selective_accuracy':selective}
    ARTIFACTS.mkdir(parents=True,exist_ok=True);joblib.dump({'model':final_model,'confidence_model':confidence_model,'state':serializable_state(state),'features':FEATURE_NAMES,'report':report},ARTIFACTS/'moneyline.joblib');(ARTIFACTS/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report,indent=2))

if __name__=='__main__':main()
