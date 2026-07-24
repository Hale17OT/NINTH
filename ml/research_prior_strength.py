"""Fast shadow audit of explicit previous-season strength priors."""
import json
from collections import defaultdict
from pathlib import Path
import numpy as np
from sklearn.linear_model import LogisticRegression,Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from ml.starter_statcast_experiment import starter_matrix
from ml.v2_experiment import DATA,matrix,read_jsonl,score
from ml.train_v3 import fit as production_fit

ROOT=Path(__file__).resolve().parents[1];OUTPUT=ROOT/"ml"/"artifacts"/"prior_strength_research.json"

def prior_matrix(games):
    current=defaultdict(lambda:{"g":0,"w":0,"rf":0.,"ra":0.});previous={};season=None;rows=[]
    def strength(value):
        g=value.get("g",0);w=value.get("w",0);rf=value.get("rf",0.);ra=value.get("ra",0.)
        win=(w+10)/(g+20);py=(rf+90)**1.83/((rf+90)**1.83+(ra+90)**1.83);margin=(rf-ra)/(g+20)
        return win,py,margin
    for game in games:
        if game["season"]!=season:
            if season is not None:previous={key:dict(value) for key,value in current.items()}
            current=defaultdict(lambda:{"g":0,"w":0,"rf":0.,"ra":0.});season=game["season"]
        home,away=str(game["home_id"]),str(game["away_id"]);hp=strength(previous.get(home,{}));ap=strength(previous.get(away,{}));hc=strength(current[home]);ac=strength(current[away])
        games_played=min(current[home]["g"],current[away]["g"]);progress=min(1,games_played/80)
        rows.append([hp[0]-ap[0],hp[1]-ap[1],hp[2]-ap[2],hc[0]-ac[0],hc[1]-ac[1],hc[2]-ac[2],progress,(1-progress)*(hp[1]-ap[1]),progress*(hc[1]-ac[1])])
        hs,as_=int(game["home_score"]),int(game["away_score"])
        for key,scored,allowed,won in ((home,hs,as_,hs>as_),(away,as_,hs,as_>hs)):
            v=current[key];v["g"]+=1;v["w"]+=int(won);v["rf"]+=scored;v["ra"]+=allowed
    return np.asarray(rows,float)

def main():
    base,_,_,y,years,_,_=matrix();starter,_=starter_matrix();games=sorted(read_jsonl(DATA),key=lambda x:(x["date"],x["game_id"]));prior=prior_matrix(games);margins=np.asarray([g["home_score"]-g["away_score"] for g in games],float)
    sets={"incumbent_features":np.column_stack([base,starter[:,6:]]),"prior_strength":np.column_stack([base,starter[:,6:],prior])};report={}
    for name,X in sets.items():
        probabilities=[];labels=[];fold_years=[]
        for year in sorted(set(years)):
            if year<2022 or np.sum(years<year)<4000:continue
            train,test=years<year,years==year;reg=Pipeline([("scale",StandardScaler()),("ridge",Ridge(alpha=100))]).fit(X[train],np.clip(margins[train],-8,8));cal=LogisticRegression(C=.1,max_iter=2000).fit(reg.predict(X[train]).reshape(-1,1),y[train]);probabilities.extend(cal.predict_proba(reg.predict(X[test]).reshape(-1,1))[:,1]);labels.extend(y[test]);fold_years.extend(years[test])
        p=np.asarray(probabilities);labels=np.asarray(labels);fold_years=np.asarray(fold_years);report[name]={"development":score(labels[fold_years<=2024],p[fold_years<=2024]),"audit_2025_2026":score(labels[fold_years>=2025],p[fold_years>=2025])}
    X=sets["prior_strength"];probabilities=[];labels=[];fold_years=[]
    for year in sorted(set(years)):
        if year<2022 or np.sum(years<year)<4000:continue
        train,test=years<year,years==year;p=production_fit(X[train],y[train],margins[train]).predict_proba(X[test])[:,1];probabilities.extend(p);labels.extend(y[test]);fold_years.extend(years[test])
    p=np.asarray(probabilities);labels=np.asarray(labels);fold_years=np.asarray(fold_years);report["prior_strength_v4"]={"development":score(labels[fold_years<=2024],p[fold_years<=2024]),"audit_2025_2026":score(labels[fold_years>=2025],p[fold_years>=2025])}
    OUTPUT.write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))
if __name__=="__main__":main()
