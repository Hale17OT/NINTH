"""Nested rolling-origin promotion gate for the v2 model family."""
import json
from pathlib import Path
import numpy as np

from ml.v2_experiment import extra_trees, logistic, matrix, score

ROOT=Path(__file__).resolve().parents[1]
OUTPUT=ROOT/'ml'/'artifacts'/'v2_tuning_report.json'
CANDIDATES={
    'lean_calibrated':('lean',1.0),
    'lean_blend_70_30':('lean',.70),
    'lean_blend_60_40':('lean',.60),
    'lean_blend_55_45':('lean',.55),
    'lean_blend_50_50':('lean',.50),
    'full_blend_60_40':('full',.60),
}

def json_default(value):
    if isinstance(value,np.integer):return int(value)
    if isinstance(value,np.floating):return float(value)
    if isinstance(value,np.bool_):return bool(value)
    raise TypeError(f'Object of type {type(value).__name__} is not JSON serializable')

def probability(candidate,sets,y,train,test):
    feature_set,weight=CANDIDATES[candidate];X=sets[feature_set]
    calibrated=logistic(.35,True).fit(X[train],y[train]);left=calibrated.predict_proba(X[test])[:,1]
    if weight==1:return left
    right=extra_trees().fit(X[train],y[train]).predict_proba(X[test])[:,1]
    return weight*left+(1-weight)*right

def inner(candidate,outer,sets,y,years):
    fold_scores=[]
    for year in sorted(set(years)):
        if year<2022 or year>=outer or np.sum(years<year)<4000:continue
        train,test=years<year,years==year;fold_scores.append(score(y[test],probability(candidate,sets,y,train,test)))
    losses=np.asarray([item['log_loss'] for item in fold_scores])
    return {'folds':[year for year in sorted(set(years)) if 2022<=year<outer and np.sum(years<year)>=4000],'mean_accuracy':round(float(np.mean([x['accuracy'] for x in fold_scores])),5),'mean_log_loss':round(float(losses.mean()),5),'standard_error':round(float(losses.std(ddof=1)/np.sqrt(len(losses))),5) if len(losses)>1 else 0,'mean_qualified_accuracy':round(float(np.mean([x['qualified_accuracy'] for x in fold_scores])),5)}

def main():
    base,v2,_,y,years,context_count,statcast_count=matrix();lean=np.delete(v2,[1,3],axis=1);sets={'lean':np.column_stack([base,lean]),'full':np.column_stack([base,v2])}
    outer_years=[year for year in (2024,2025,2026) if np.any(years==year)];outer_p,outer_y,incumbent_p,folds=[],[],[],{}
    for outer in outer_years:
        diagnostics={name:inner(name,outer,sets,y,years) for name in CANDIDATES}
        best_loss=min(value['mean_log_loss'] for value in diagnostics.values());eligible=[name for name,value in diagnostics.items() if value['mean_log_loss']<=best_loss+.001 and value['mean_qualified_accuracy']>=.60]
        selected=max(eligible,key=lambda name:(diagnostics[name]['mean_accuracy'],CANDIDATES[name][1]))
        train,test=years<outer,years==outer;p=probability(selected,sets,y,train,test);inc=logistic(.35,True).fit(base[train],y[train]).predict_proba(base[test])[:,1]
        candidate_score,incumbent_score=score(y[test],p),score(y[test],inc);outer_p.extend(p);incumbent_p.extend(inc);outer_y.extend(y[test]);folds[str(outer)]={'selected':selected,'inner':diagnostics,'untouched_outer':candidate_score,'incumbent_outer':incumbent_score};print(outer,selected,candidate_score,flush=True)
    outer_y=np.asarray(outer_y);candidate=score(outer_y,np.asarray(outer_p));incumbent=score(outer_y,np.asarray(incumbent_p));no_bad_year=all(value['untouched_outer']['accuracy']>=value['incumbent_outer']['accuracy']-.01 and value['untouched_outer']['log_loss']<=value['incumbent_outer']['log_loss']+.005 for value in folds.values())
    gate=candidate['accuracy']>=.57 and candidate['accuracy']>=incumbent['accuracy']+.003 and candidate['log_loss']<incumbent['log_loss'] and candidate['brier_score']<incumbent['brier_score'] and candidate['qualified_accuracy']>=.60 and no_bad_year
    report={'status':'eligible_for_production_integration' if gate else 'shadow_only_no_promotion','production_changed':False,'policy':'Nested rolling-origin selection. Promotion requires >=57% outer accuracy, >=0.3-point accuracy gain, better log loss and Brier, >=60% qualified accuracy, and no badly regressing outer season.','context_games':context_count,'statcast_games':statcast_count,'outer_seasons':outer_years,'candidate_count':len(CANDIDATES),'candidate_outer':candidate,'incumbent_outer':incumbent,'promotion_gate_passed':gate,'folds':folds}
    OUTPUT.write_text(json.dumps(report,indent=2,default=json_default),encoding='utf8');print(json.dumps({key:report[key] for key in ('status','candidate_outer','incumbent_outer','promotion_gate_passed')},indent=2,default=json_default))

if __name__=='__main__':main()
