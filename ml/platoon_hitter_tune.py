"""Nested rolling-origin gate for individual confirmed-lineup platoon form."""
import json
from pathlib import Path
import numpy as np

from ml.platoon_hitter_experiment import platoon_matrix
from ml.starter_statcast_experiment import margin_probability, starter_matrix
from ml.v2_experiment import DATA, logistic, matrix, read_jsonl, score

ROOT=Path(__file__).resolve().parents[1];OUTPUT=ROOT/'ml'/'artifacts'/'platoon_hitter_tuning_report.json'
CANDIDATES={
    'recent_raw':('recent',None),'recent_cap8':('recent',8),
    'recent_platoon_raw':('recent_platoon',None),'recent_platoon_cap8':('recent_platoon',8),
    'long_platoon_raw':('long_platoon',None),'long_platoon_cap8':('long_platoon',8),
}

def default(value):
    if isinstance(value,np.integer):return int(value)
    if isinstance(value,np.floating):return float(value)
    if isinstance(value,np.bool_):return bool(value)
    raise TypeError(type(value).__name__)

def build():
    base,v2,_,y,years,context_count,_=matrix();starter,starter_coverage=starter_matrix();platoon,coverage=platoon_matrix()
    if coverage['raw_games']<13000 or (coverage.get('last_raw_date') or '')<'2026-07-12':raise SystemExit(f"platoon backfill incomplete: {coverage['raw_games']}")
    common=np.column_stack([base,np.delete(v2,[1,3],axis=1)]);sets={'recent':np.column_stack([common,starter[:,:6],starter[:,12:]]),'recent_platoon':np.column_stack([common,starter[:,:6],starter[:,12:],platoon]),'long_platoon':np.column_stack([common,starter[:,6:],platoon])}
    games=sorted(read_jsonl(DATA),key=lambda row:(row['date'],row['game_id']));margins=np.asarray([float(game['home_score']-game['away_score']) for game in games])
    return sets,base,y,years,margins,context_count,starter_coverage,coverage

def probability(name,sets,y,margins,train,test):
    feature_set,cap=CANDIDATES[name];return margin_probability(sets[feature_set],y,margins,train,test,cap)

def inner(name,outer,sets,y,years,margins):
    values=[];folds=[]
    for year in sorted(set(years)):
        if year<2022 or year>=outer or np.sum(years<year)<4000:continue
        train,test=years<year,years==year;values.append(score(y[test],probability(name,sets,y,margins,train,test)));folds.append(int(year))
    return {'folds':folds,'mean_accuracy':round(float(np.mean([v['accuracy'] for v in values])),5),'mean_log_loss':round(float(np.mean([v['log_loss'] for v in values])),5),'mean_qualified_accuracy':round(float(np.mean([v['qualified_accuracy'] for v in values])),5)}

def main():
    sets,base,y,years,margins,context_count,starter_coverage,coverage=build();candidate_p=[];incumbent_p=[];actual=[];folds={}
    for outer in (2024,2025,2026):
        diagnostics={name:inner(name,outer,sets,y,years,margins) for name in CANDIDATES};best_loss=min(value['mean_log_loss'] for value in diagnostics.values());eligible=[name for name,value in diagnostics.items() if value['mean_log_loss']<=best_loss+.001 and value['mean_qualified_accuracy']>=.60]
        if not eligible:eligible=[min(diagnostics,key=lambda name:diagnostics[name]['mean_log_loss'])]
        selected=max(eligible,key=lambda name:(diagnostics[name]['mean_accuracy'],-sets[CANDIDATES[name][0]].shape[1],CANDIDATES[name][1] is None));train,test=years<outer,years==outer;candidate=probability(selected,sets,y,margins,train,test);incumbent=logistic(.35,True).fit(base[train],y[train]).predict_proba(base[test])[:,1]
        candidate_p.extend(candidate);incumbent_p.extend(incumbent);actual.extend(y[test]);folds[str(outer)]={'selected':selected,'inner':diagnostics,'untouched_outer':score(y[test],candidate),'incumbent_outer':score(y[test],incumbent)};print(outer,selected,folds[str(outer)]['untouched_outer'],flush=True)
    actual=np.asarray(actual);candidate_score=score(actual,np.asarray(candidate_p));incumbent_score=score(actual,np.asarray(incumbent_p));no_bad_year=all(v['untouched_outer']['accuracy']>=v['incumbent_outer']['accuracy']-.01 and v['untouched_outer']['log_loss']<=v['incumbent_outer']['log_loss']+.005 for v in folds.values());gate=candidate_score['accuracy']>=.57 and candidate_score['accuracy']>=incumbent_score['accuracy']+.003 and candidate_score['log_loss']<incumbent_score['log_loss'] and candidate_score['brier_score']<incumbent_score['brier_score'] and candidate_score['qualified_accuracy']>=.60 and no_bad_year
    report={'status':'eligible_for_production_integration' if gate else 'shadow_only_no_promotion','production_changed':False,'policy':'Six candidate families fixed before platoon results; nested rolling selection with the same strict 57% promotion gate.','context_games':context_count,'starter_coverage':starter_coverage,'platoon_coverage':coverage,'candidate_count':len(CANDIDATES),'candidate_outer':candidate_score,'incumbent_outer':incumbent_score,'promotion_gate_passed':gate,'folds':folds};OUTPUT.write_text(json.dumps(report,indent=2,default=default),encoding='utf8');print(json.dumps({k:report[k] for k in ('status','candidate_outer','incumbent_outer','promotion_gate_passed')},indent=2,default=default))

if __name__=='__main__':main()
