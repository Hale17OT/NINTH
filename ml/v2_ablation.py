"""Leave-one-v2-feature-out rolling diagnostic; never promotes a model."""
import json
from pathlib import Path
import numpy as np

from ml.v2_experiment import V2_FEATURES, logistic, matrix, score

ROOT=Path(__file__).resolve().parents[1]
OUTPUT=ROOT/'ml'/'artifacts'/'v2_ablation.json'

def evaluate(X,y,years):
    labels,probabilities,per_year=[],[],{}
    for year in sorted(set(years)):
        if year<2022 or np.sum(years<year)<4000:continue
        train,test=years<year,years==year;p=logistic(.35,True).fit(X[train],y[train]).predict_proba(X[test])[:,1]
        labels.extend(y[test]);probabilities.extend(p);per_year[str(year)]=score(y[test],p)
    return score(np.asarray(labels),np.asarray(probabilities)),per_year

def main():
    base,v2,_,y,years,_,_=matrix();baseline,base_year=evaluate(np.column_stack([base,v2]),y,years);removals={}
    for index,name in enumerate(V2_FEATURES):
        result,per_year=evaluate(np.column_stack([base,np.delete(v2,index,axis=1)]),y,years);removals[name]={"aggregate":result,"per_year":per_year,"accuracy_change":round(result['accuracy']-baseline['accuracy'],5),"log_loss_change":round(result['log_loss']-baseline['log_loss'],5)};print(name,removals[name],flush=True)
    OUTPUT.write_text(json.dumps({"status":"diagnostic_only","baseline":baseline,"baseline_per_year":base_year,"removals":removals},indent=2),encoding='utf8')

if __name__=='__main__':main()
