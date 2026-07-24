"""Leakage-safe research cycle for NINTH moneyline and totals v6 candidates.

This script never writes production artifacts. Hyperparameters and ensemble weights
are selected on rolling-origin 2022-2024 predictions; 2025-2026 is reported once as
the temporal audit.
"""
from __future__ import annotations

import json
from collections import defaultdict, deque
from pathlib import Path

import numpy as np
from scipy.optimize import minimize
from scipy.sparse import csr_matrix, hstack
from scipy.stats import nbinom, skellam
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression, PoissonRegressor, Ridge
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import SplineTransformer, StandardScaler

from ml.starter_statcast_experiment import starter_matrix
from ml.hitter_statcast_experiment import bullpen_matrix as personnel_bullpen_matrix, hitter_matrix, ordered_lineup_matrix
from ml.totals_features import TOTAL_FEATURE_NAMES
from ml.train_totals import LINES, matrix as totals_matrix
from ml.train_v3 import fit as production_moneyline_fit
from ml.v2_experiment import DATA, matrix as moneyline_matrix, read_jsonl


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "ml" / "artifacts" / "v6_research.json"
CONTEXTS_V3 = ROOT / "ml" / "data" / "contexts_v3.jsonl"


def metrics(y, p):
    y, p = np.asarray(y, int), np.clip(np.asarray(p, float), 1e-6, 1-1e-6)
    return {
        "games": int(len(y)),
        "brier_score": round(float(brier_score_loss(y, p)), 6),
        "log_loss": round(float(log_loss(y, p)), 6),
        "accuracy": round(float(np.mean((p >= .5) == y)), 6),
        "roc_auc": round(float(roc_auc_score(y, p)), 6),
    }


def beta_columns(p):
    p = np.clip(np.asarray(p, float), 1e-5, 1-1e-5)
    return np.column_stack([np.log(p), -np.log1p(-p)])


def fit_beta(p, y, c=.03):
    return LogisticRegression(C=c, max_iter=3000).fit(beta_columns(p), y)


def apply_beta(model, p):
    return model.predict_proba(beta_columns(p))[:, 1]


def team_design(games, numeric):
    team_ids = sorted({str(g[side]) for g in games for side in ("home_id", "away_id")})
    lookup = {team_id: i for i, team_id in enumerate(team_ids)}
    rows, cols, values = [], [], []
    for row, game in enumerate(games):
        rows.extend((row, row)); cols.extend((lookup[str(game["home_id"])], lookup[str(game["away_id"])])); values.extend((1., -1.))
    teams = csr_matrix((values, (rows, cols)), shape=(len(games), len(team_ids)))
    scale = StandardScaler().fit_transform(numeric)
    return hstack([csr_matrix(scale), teams], format="csr")


def personnel_design(games, numeric):
    """Signed team, confirmed-starter and submitted-lineup identity effects."""
    contexts = {str(row["game_id"]): row for row in read_jsonl(CONTEXTS_V3)}
    teams = sorted({f"t:{g[side]}" for g in games for side in ("home_id", "away_id")})
    players = set()
    for context in contexts.values():
        for side in ("home", "away"):
            value = context.get(side) or {}
            if value.get("starter_id"): players.add(f"p:{value['starter_id']}")
            players.update(f"b:{player_id}" for player_id in (value.get("lineup_ids") or [])[:9])
    columns = {value: index for index, value in enumerate(teams + sorted(players))}
    rows, cols, values = [], [], []
    def add(row, key, value):
        if key in columns: rows.append(row); cols.append(columns[key]); values.append(value)
    for row, game in enumerate(games):
        add(row, f"t:{game['home_id']}", 1.); add(row, f"t:{game['away_id']}", -1.)
        context = contexts.get(str(game["game_id"]), {})
        for side, sign in (("home", 1.), ("away", -1.)):
            value = context.get(side) or {}
            if value.get("starter_id"): add(row, f"p:{value['starter_id']}", sign)
            for player_id in (value.get("lineup_ids") or [])[:9]: add(row, f"b:{player_id}", sign/9)
    identities = csr_matrix((values, (rows, cols)), shape=(len(games), len(columns)))
    scale = StandardScaler().fit_transform(numeric)
    return hstack([csr_matrix(scale), identities], format="csr")


def moneyline_research():
    base, v2, _, y, years, _, _ = moneyline_matrix()
    starters, _ = starter_matrix()
    games = sorted(read_jsonl(DATA), key=lambda row: (row["date"], row["game_id"]))
    X = np.column_stack([base, starters[:, 6:]])
    sparse = team_design(games, X)
    personnel = personnel_design(games, X)
    totals_games, totals_X, _, totals_years, _, _, _ = totals_matrix()
    if [g["game_id"] for g in totals_games] != [g["game_id"] for g in games]:
        raise RuntimeError("moneyline/totals game matrices are not aligned")
    home_runs=np.asarray([g["home_score"] for g in games],float);away_runs=np.asarray([g["away_score"] for g in games],float)
    hitters,_=hitter_matrix();ordered,_=ordered_lineup_matrix();bullpen=personnel_bullpen_matrix()
    lean=np.delete(v2,[1,3],axis=1)
    personnel_numeric=np.column_stack([base,lean,starters[:,6:],hitters,ordered,bullpen])
    model_specs = []
    for c in (.001, .003, .01, .03, .1):
        for half_life in (0, 365, 730, 1460):
            model_specs.append((c, half_life))
    predictions = defaultdict(list); labels = []; fold_years = []
    for year in sorted(set(years)):
        if year < 2022 or np.sum(years < year) < 4000:
            continue
        train, test = years < year, years == year
        labels.extend(y[test]); fold_years.extend(years[test])
        dates = np.asarray([np.datetime64(g["date"]) for g in games])
        age = (np.datetime64(f"{year}-01-01") - dates[train]).astype("timedelta64[D]").astype(float)
        for c, half_life in model_specs:
            weight = None if half_life == 0 else np.exp2(-np.maximum(age, 0) / half_life)
            model = LogisticRegression(C=c, max_iter=2500, solver="liblinear")
            model.fit(sparse[train], y[train], sample_weight=weight)
            predictions[f"team_logistic_c{c}_h{half_life}"].extend(model.predict_proba(sparse[test])[:, 1])
        for c in (.0003, .001, .003, .01, .03):
            for half_life in (0, 730, 1460):
                weight = None if half_life == 0 else np.exp2(-np.maximum(age, 0) / half_life)
                model = LogisticRegression(C=c, max_iter=2500, solver="liblinear")
                model.fit(personnel[train], y[train], sample_weight=weight)
                predictions[f"personnel_logistic_c{c}_h{half_life}"].extend(model.predict_proba(personnel[test])[:, 1])
        # Generative score forecasts supply a signal with different inductive
        # bias from direct win classification. The Skellam tie mass is split
        # evenly here and can be calibrated/blended on development OOF data.
        for width in (21, len(TOTAL_FEATURE_NAMES)):
            for alpha in (.2, 1., 3., 10.):
                def run_model(target):
                    return Pipeline([("scale",StandardScaler()),("poisson",PoissonRegressor(alpha=alpha,max_iter=1500))]).fit(totals_X[train,:width],target[train])
                hm,am=run_model(home_runs),run_model(away_runs)
                home_mu=np.clip(hm.predict(totals_X[test,:width]),.1,20);away_mu=np.clip(am.predict(totals_X[test,:width]),.1,20)
                p=skellam.sf(0,home_mu,away_mu)+.5*skellam.pmf(0,home_mu,away_mu)
                predictions[f"skellam_w{width}_a{alpha}"].extend(p)
        for alpha in (.2,1.,3.,10.):
            def money_run_model(target):
                return Pipeline([("scale",StandardScaler()),("poisson",PoissonRegressor(alpha=alpha,max_iter=1500))]).fit(X[train],target[train])
            hm,am=money_run_model(home_runs),money_run_model(away_runs)
            home_mu=np.clip(hm.predict(X[test]),.1,20);away_mu=np.clip(am.predict(X[test]),.1,20)
            predictions[f"live_skellam_a{alpha}"].extend(skellam.sf(0,home_mu,away_mu)+.5*skellam.pmf(0,home_mu,away_mu))
        # A stable linear margin model gives an independent score-shaped signal.
        target = np.clip(np.asarray([g["home_score"]-g["away_score"] for g in games], float), -8, 8)
        margin = Pipeline([("scale", StandardScaler()), ("ridge", Ridge(alpha=100))]).fit(X[train], target[train])
        score_train, score_test = margin.predict(X[train]), margin.predict(X[test])
        cal = LogisticRegression(C=.1, max_iter=2000).fit(score_train.reshape(-1, 1), y[train])
        predictions["margin"].extend(cal.predict_proba(score_test.reshape(-1, 1))[:, 1])
        predictions["production_v4"].extend(production_moneyline_fit(X[train],y[train],target[train]).predict_proba(X[test])[:,1])
        p_margin=Pipeline([("scale",StandardScaler()),("ridge",Ridge(alpha=100))]).fit(personnel_numeric[train],target[train])
        p_cal=LogisticRegression(C=.1,max_iter=2000).fit(p_margin.predict(personnel_numeric[train]).reshape(-1,1),y[train])
        predictions["personnel_margin"].extend(p_cal.predict_proba(p_margin.predict(personnel_numeric[test]).reshape(-1,1))[:,1])
    labels, fold_years = np.asarray(labels), np.asarray(fold_years)
    predictions = {k: np.asarray(v) for k, v in predictions.items()}
    dev, audit = fold_years <= 2024, fold_years >= 2025
    bad = {key: len(value) for key, value in predictions.items() if len(value) != len(labels)}
    if bad:
        raise RuntimeError(f"incomplete moneyline prediction streams: labels={len(labels)} streams={bad}")
    ranked = sorted(predictions, key=lambda k: brier_score_loss(labels[dev], predictions[k][dev]))
    # Constrained stacking cannot create extreme probabilities: all weights are
    # non-negative and sum to one. Components are chosen by architecture on dev.
    best_team=next(k for k in ranked if k.startswith("team_"))
    best_skellam=next(k for k in ranked if k.startswith("skellam_"))
    component_names=["production_v4","personnel_margin",best_team,best_skellam]
    matrix=np.column_stack([predictions[k] for k in component_names])
    objective=lambda w:float(np.mean((matrix[dev]@w-labels[dev])**2)+1e-5*np.sum((w-.25)**2))
    solution=minimize(objective,np.full(4,.25),method="SLSQP",bounds=[(0,1)]*4,constraints={"type":"eq","fun":lambda w:np.sum(w)-1},options={"ftol":1e-12,"maxiter":500})
    weights=np.clip(solution.x,0,1);weights/=weights.sum();raw=matrix@weights
    # Cross-era beta calibration is fit on development OOF predictions only.
    calibrators = [(c, fit_beta(raw[dev], labels[dev], c)) for c in (.003, .01, .03, .1, .3)]
    calibrated = [(brier_score_loss(labels[dev], apply_beta(m, raw[dev])), c, m) for c, m in calibrators]
    _, beta_c, beta = min(calibrated, key=lambda row: row[0])
    final = apply_beta(beta, raw)
    live_skellam=next(k for k in ranked if k.startswith("live_skellam"))
    live_matrix=np.column_stack([predictions["production_v4"],predictions[live_skellam]])
    live_objective=lambda w:float(np.mean((live_matrix[dev]@w-labels[dev])**2))
    live_solution=minimize(live_objective,np.full(2,.5),method="SLSQP",bounds=[(0,1)]*2,constraints={"type":"eq","fun":lambda w:np.sum(w)-1},options={"ftol":1e-12,"maxiter":500})
    live_weights=np.clip(live_solution.x,0,1);live_weights/=live_weights.sum();live_probability=live_matrix@live_weights
    return {
        "selection_policy": "Team/logistic hyperparameters, blend, and beta calibration selected on 2022-2024 rolling-origin OOF predictions.",
        "ensemble_components": component_names, "ensemble_weights": [round(float(v),6) for v in weights], "beta_c": beta_c,
        "development": metrics(labels[dev], final[dev]), "audit_2025_2026": metrics(labels[audit], final[audit]),
        "uncalibrated_audit": metrics(labels[audit], raw[audit]),
        "live_reproducible_ensemble":{"components":["production_v4",live_skellam],"weights":[round(float(v),6) for v in live_weights],"development":metrics(labels[dev],live_probability[dev]),"audit_2025_2026":metrics(labels[audit],live_probability[audit])},
        "candidate_development": {k: metrics(labels[dev], predictions[k][dev]) for k in ranked[:8]},
        "candidate_audit": {k: metrics(labels[audit], predictions[k][audit]) for k in ranked[:8]},
    }


def varying_dispersion_probability(mu, alpha, lines):
    mu = np.clip(np.asarray(mu, float), .1, 30)
    alpha = np.clip(np.asarray(alpha, float), .005, 1.5)
    size = 1/alpha
    return np.column_stack([nbinom.sf(int(line), size, size/(size+mu)) for line in lines])


def totals_statcast_matrix(games):
    """Pregame contact-quality sums at recent and long horizons."""
    raw={str(row["game_id"]):row for row in read_jsonl(ROOT/"ml"/"data"/"statcast_rich_games.jsonl")}
    keys=("off_xwoba","off_hard","off_barrel","pit_xwoba","pit_whiff")
    histories=defaultdict(lambda:{key:deque(maxlen=60) for key in keys});output=[]
    def avg(values,n,default):
        rows=list(values)[-n:];return float(np.mean(rows)) if rows else default
    for game in games:
        current=raw.get(str(game["game_id"]),{});abbrs=(current.get("home_abbr"),current.get("away_abbr"))
        sides=[]
        for abbr in abbrs:
            h=histories[str(abbr)]
            sides.append([[avg(h[k],n,d) for k,d in zip(keys,(.320,.385,.075,.320,.105))] for n in (10,40)])
        # Totals depend on combined quality/exposure, so sums (plus absolute
        # mismatch gaps) are retained rather than moneyline-style differences.
        features=[]
        for horizon in range(2):
            home,away=sides[0][horizon],sides[1][horizon]
            features.extend([home[i]+away[i] for i in range(len(keys))])
            features.extend([abs(home[i]-away[i]) for i in range(len(keys))])
        features.append(float(bool(current)))
        output.append(features)
        if current:
            for side,abbr in (("home",current.get("home_abbr")),("away",current.get("away_abbr"))):
                offense=current.get(side) or {};pitching=current.get(f"{side}_pitching") or {};h=histories[str(abbr)]
                values={"off_xwoba":offense.get("xwoba"),"off_hard":offense.get("hard_hit_rate"),"off_barrel":offense.get("barrel_rate"),"pit_xwoba":pitching.get("xwoba"),"pit_whiff":pitching.get("whiff_rate")}
                for key,value in values.items():
                    if value is not None:h[key].append(float(value))
    return np.asarray(output,float)


def totals_research():
    games, X, total, years, _, _, _ = totals_matrix()
    statcast_rows={str(row["game_id"]):row for row in read_jsonl(ROOT/"ml"/"data"/"statcast_contexts.jsonl")}
    stat_names=["statcast_xwoba_difference","statcast_xwoba_allowed_advantage","statcast_hard_hit_difference","statcast_barrel_difference","statcast_pitching_whiff_difference","statcast_velocity_difference"]
    stat=np.asarray([[float(statcast_rows.get(str(g["game_id"]),{}).get(name,0) or 0) for name in stat_names]+[float(str(g["game_id"]) in statcast_rows)] for g in games])
    totals_stat=totals_statcast_matrix(games)
    X_aug=np.column_stack([X,stat,totals_stat])
    actual = np.column_stack([total > line for line in LINES]).astype(int)
    fold_y, fold_year, fixed_parts, varying_parts, isotonic_parts, spline_parts, statcast_parts, direct_parts, prior_direct_parts = [], [], [], [], [], [], [], [], []
    for year in sorted(set(years)):
        if year < 2022 or np.sum(years < year) < 4000:
            continue
        train, test = years < year, years == year
        mean_model = Pipeline([("scale", StandardScaler()), ("poisson", PoissonRegressor(alpha=2, max_iter=1500))]).fit(X[train, :21], total[train])
        mu_train = np.clip(mean_model.predict(X[train, :21]), .1, 30)
        mu_test = np.clip(mean_model.predict(X[test, :21]), .1, 30)
        pearson = np.maximum(((total[train]-mu_train)**2-mu_train)/np.maximum(mu_train**2, 1e-6), .005)
        alpha_fixed = float(np.clip(np.mean(pearson), .005, 1.5))
        fixed_parts.append(varying_dispersion_probability(mu_test, np.full(np.sum(test), alpha_fixed), LINES))
        # Predict log dispersion from strictly prior residuals. Strong regularity
        # constraints keep this variance model from chasing individual outliers.
        variance_model = HistGradientBoostingRegressor(
            loss="squared_error", learning_rate=.025, max_iter=120,
            max_leaf_nodes=7, min_samples_leaf=250, l2_regularization=30,
            random_state=42,
        ).fit(X[train], np.log(np.clip(pearson, .01, 1.5)))
        alpha_test = np.exp(variance_model.predict(X[test]))
        varying_parts.append(varying_dispersion_probability(mu_test, alpha_test, LINES))
        iso_probability=[];spline_probability=[]
        for line in LINES:
            line_y=(total[train]>line).astype(int)
            iso=IsotonicRegression(increasing=True,out_of_bounds="clip",y_min=.01,y_max=.99).fit(mu_train,line_y)
            iso_probability.append(iso.predict(mu_test))
            spline=Pipeline([("spline",SplineTransformer(n_knots=5,degree=2,include_bias=False)),("logistic",LogisticRegression(C=.03,max_iter=2000))]).fit(mu_train.reshape(-1,1),line_y)
            spline_probability.append(spline.predict_proba(mu_test.reshape(-1,1))[:,1])
        isotonic_parts.append(np.minimum.accumulate(np.column_stack(iso_probability),axis=1))
        spline_parts.append(np.minimum.accumulate(np.column_stack(spline_probability),axis=1))
        stat_mean_model=Pipeline([("scale",StandardScaler()),("poisson",PoissonRegressor(alpha=1,max_iter=1500))]).fit(X_aug[train],total[train])
        stat_mu_train=np.clip(stat_mean_model.predict(X_aug[train]),.1,30);stat_mu_test=np.clip(stat_mean_model.predict(X_aug[test]),.1,30)
        stat_alpha=float(np.clip(np.mean(((total[train]-stat_mu_train)**2-stat_mu_train)/np.maximum(stat_mu_train**2,1e-6)),.005,1.5))
        statcast_parts.append(varying_dispersion_probability(stat_mu_test,np.full(np.sum(test),stat_alpha),LINES))
        direct=[]
        for line in LINES:
            model=Pipeline([("scale",StandardScaler()),("logistic",LogisticRegression(C=.03,max_iter=2500))]).fit(X_aug[train],(total[train]>line).astype(int))
            direct.append(model.predict_proba(X_aug[test])[:,1])
        direct_parts.append(np.minimum.accumulate(np.column_stack(direct),axis=1))
        prior_direct=[]
        for line in LINES:
            model=Pipeline([("scale",StandardScaler()),("logistic",LogisticRegression(C=.03,max_iter=2500))]).fit(X[train],(total[train]>line).astype(int))
            prior_direct.append(model.predict_proba(X[test])[:,1])
        prior_direct_parts.append(np.minimum.accumulate(np.column_stack(prior_direct),axis=1))
        fold_y.append(actual[test]); fold_year.extend(years[test])
    y = np.vstack(fold_y); fold_year = np.asarray(fold_year)
    fixed, varying = np.vstack(fixed_parts), np.vstack(varying_parts)
    isotonic,spline=np.vstack(isotonic_parts),np.vstack(spline_parts)
    statcast,direct=np.vstack(statcast_parts),np.vstack(direct_parts)
    prior_direct=np.vstack(prior_direct_parts)
    dev, audit = fold_year <= 2024, fold_year >= 2025
    # Convex stacking preserves coherent ranges and prevents extrapolation.
    stack=np.stack([fixed,varying,isotonic,spline,statcast,direct,prior_direct],axis=2)
    objective=lambda w:float(np.mean((np.tensordot(stack[dev],w,axes=([2],[0]))-y[dev])**2)+1e-5*np.sum((w-1/7)**2))
    solution=minimize(objective,np.full(7,1/7),method="SLSQP",bounds=[(0,1)]*7,constraints={"type":"eq","fun":lambda w:np.sum(w)-1},options={"ftol":1e-12,"maxiter":500})
    weights=np.clip(solution.x,0,1);weights/=weights.sum();raw=np.tensordot(stack,weights,axes=([2],[0]))
    calibrated = np.zeros_like(raw)
    beta_cs = []
    for index in range(len(LINES)):
        options=[]
        for c in (.003, .01, .03, .1, .3):
            model=fit_beta(raw[dev,index], y[dev,index], c)
            options.append((brier_score_loss(y[dev,index], apply_beta(model, raw[dev,index])), c, model))
        _, c, model=min(options, key=lambda row:row[0]); beta_cs.append(c)
        calibrated[:,index]=apply_beta(model, raw[:,index])
    def summary(mask, probability):
        per={str(line):round(float(brier_score_loss(y[mask,i], probability[mask,i])),6) for i,line in enumerate(LINES)}
        return {"mean_brier":round(float(np.mean(list(per.values()))),6),"per_line":per}
    decision_indices=[LINES.index(line) for line in (7.5,8.5,9.5,10.5)]
    def selected_rows(probability):
        over=probability[:,decision_indices];confidence=np.maximum(over,1-over);choice=np.argmax(confidence,axis=1)
        rows=np.arange(len(probability));indices=np.asarray(decision_indices)[choice];is_over=over[rows,choice]>=.5
        outcome=np.where(is_over,y[rows,indices],1-y[rows,indices]);return confidence[rows,choice],outcome
    selected_probability,selected_outcome=selected_rows(raw)
    selected_calibrator=fit_beta(selected_probability[dev],selected_outcome[dev],.1)
    selected_adjusted=apply_beta(selected_calibrator,selected_probability)
    return {
        "selection_policy":"Dispersion blend and beta maps selected on 2022-2024 rolling-origin OOF predictions.",
        "ensemble_components":["fixed_negative_binomial","varying_dispersion","isotonic_mean_distribution","spline_mean_distribution","statcast_negative_binomial","statcast_direct_threshold","prior_direct_threshold"],
        "ensemble_weights":[round(float(v),6) for v in weights],"beta_cs":beta_cs,
        "fixed_development":summary(dev,fixed),"fixed_audit_2025_2026":summary(audit,fixed),
        "isotonic_audit_2025_2026":summary(audit,isotonic),"spline_audit_2025_2026":summary(audit,spline),
        "statcast_audit_2025_2026":summary(audit,statcast),"direct_audit_2025_2026":summary(audit,direct),
        "prior_direct_audit_2025_2026":summary(audit,prior_direct),
        "raw_development":summary(dev,raw),"raw_audit_2025_2026":summary(audit,raw),
        "calibrated_development":summary(dev,calibrated),"calibrated_audit_2025_2026":summary(audit,calibrated),
        "recommended_audit":{"raw":metrics(selected_outcome[audit],selected_probability[audit]),"confidence_calibrated":metrics(selected_outcome[audit],selected_adjusted[audit])},
    }


def main():
    import sys
    prior=json.loads(OUTPUT.read_text()) if OUTPUT.exists() else {}
    if len(sys.argv)>1 and sys.argv[1]=="totals": report={**prior,"totals":totals_research()}
    elif len(sys.argv)>1 and sys.argv[1]=="moneyline": report={**prior,"moneyline":moneyline_research()}
    else: report={"moneyline":moneyline_research(),"totals":totals_research()}
    OUTPUT.write_text(json.dumps(report,indent=2),encoding="utf8")
    print(json.dumps(report,indent=2))


if __name__ == "__main__":
    main()
