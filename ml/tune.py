"""Leakage-resistant shadow tuning for the NINTH moneyline model.

Candidates are selected on inner, earlier-season folds and scored once on the
next untouched outer season. This script never overwrites the production model.
"""
import json
import sys
from pathlib import Path

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, brier_score_loss, log_loss, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ml.features import FEATURE_NAMES, apply_result, fresh_state, matchup_features, reset_season_records

DATA = ROOT / 'ml' / 'data' / 'games.jsonl'
CONTEXTS = ROOT / 'ml' / 'data' / 'contexts.jsonl'
OUTPUT = ROOT / 'ml' / 'artifacts' / 'tuning_report.json'
SUBSETS = {
    'full': list(range(len(FEATURE_NAMES))),
    'no_weather': [i for i in range(len(FEATURE_NAMES)) if i not in (18, 19)],
    'legacy': [0, 1, 2, 4, 8, 11, 14, 15, 16, 17, 18, 19, 20],
}
CANDIDATES = [
    {'name': f'{subset}_c{c:g}', 'subset': subset, 'c': c}
    for subset in ('full', 'no_weather', 'legacy') for c in (.1, .35, 1.0)
]
INCUMBENT = {'name': 'full_c0.35', 'subset': 'full', 'c': .35}


def model(candidate):
    return Pipeline([
        ('scale', StandardScaler()),
        ('model', LogisticRegression(C=candidate['c'], max_iter=3000)),
    ])


def score(y, probability):
    return {
        'games': int(len(y)),
        'accuracy': round(float(accuracy_score(y, probability >= .5)), 5),
        'log_loss': round(float(log_loss(y, probability)), 5),
        'brier_score': round(float(brier_score_loss(y, probability)), 5),
        'roc_auc': round(float(roc_auc_score(y, probability)), 5),
    }


def load_matrix():
    games = sorted((json.loads(line) for line in DATA.read_text(encoding='utf-8').splitlines() if line.strip()), key=lambda row: (row['date'], row['game_id']))
    contexts = {str(row['game_id']): row for row in (json.loads(line) for line in CONTEXTS.read_text(encoding='utf-8-sig').splitlines() if line.strip())}
    state, rows, labels, seasons, current = fresh_state(), [], [], [], None
    for game in games:
        if game['season'] != current:
            if current is not None:
                reset_season_records(state)
            current = game['season']
        context = contexts.get(str(game['game_id']))
        rows.append(matchup_features(state, game['home_id'], game['away_id'], game['date'], {**context, 'context_available': 1} if context else None))
        labels.append(int(game['home_score'] > game['away_score']))
        seasons.append(game['season'])
        apply_result(state, game, context)
    return np.asarray(rows, float), np.asarray(labels), np.asarray(seasons)


def probability(candidate, X, y, train, test):
    indices = SUBSETS[candidate['subset']]
    return model(candidate).fit(X[train][:, indices], y[train]).predict_proba(X[test][:, indices])[:, 1]


def inner_results(candidate, outer_year, X, y, years):
    validation_years = [int(year) for year in sorted(set(years)) if year < outer_year and year >= 2021 and np.sum(years < year) >= 4000]
    fold_scores = []
    for year in validation_years:
        train, test = years < year, years == year
        fold_scores.append(score(y[test], probability(candidate, X, y, train, test)))
    losses = np.asarray([item['log_loss'] for item in fold_scores])
    return {
        'folds': validation_years,
        'mean_log_loss': float(losses.mean()),
        'standard_error': float(losses.std(ddof=1) / np.sqrt(len(losses))) if len(losses) > 1 else 0.0,
        'mean_accuracy': float(np.mean([item['accuracy'] for item in fold_scores])),
    }


def choose_candidate(inner):
    best_name = min(inner, key=lambda name: inner[name]['mean_log_loss'])
    cutoff = inner[best_name]['mean_log_loss'] + inner[best_name]['standard_error']
    eligible = [candidate for candidate in CANDIDATES if inner[candidate['name']]['mean_log_loss'] <= cutoff]
    # One-standard-error rule: prefer fewer features, then stronger regularization.
    return min(eligible, key=lambda candidate: (len(SUBSETS[candidate['subset']]), candidate['c']))


def main():
    if not DATA.exists() or not CONTEXTS.exists():
        raise SystemExit('Run collect.py and enrich.py first')
    X, y, years = load_matrix()
    outer_years = [year for year in (2024, 2025, 2026) if np.any(years == year)]
    tuned_probabilities, incumbent_probabilities, outer_labels = [], [], []
    folds = {}
    for outer_year in outer_years:
        inner = {candidate['name']: inner_results(candidate, outer_year, X, y, years) for candidate in CANDIDATES}
        selected = choose_candidate(inner)
        train, test = years < outer_year, years == outer_year
        tuned = probability(selected, X, y, train, test)
        incumbent = probability(INCUMBENT, X, y, train, test)
        tuned_probabilities.extend(tuned.tolist())
        incumbent_probabilities.extend(incumbent.tolist())
        outer_labels.extend(y[test].tolist())
        folds[str(outer_year)] = {
            'selected': selected,
            'inner_validation': inner,
            'untouched_outer': score(y[test], tuned),
            'incumbent_outer': score(y[test], incumbent),
        }
    outer_labels = np.asarray(outer_labels)
    tuned_score = score(outer_labels, np.asarray(tuned_probabilities))
    incumbent_score = score(outer_labels, np.asarray(incumbent_probabilities))
    no_bad_season = all(fold['untouched_outer']['log_loss'] <= fold['incumbent_outer']['log_loss'] + .01 for fold in folds.values())
    gate = tuned_score['log_loss'] <= incumbent_score['log_loss'] - .001 and tuned_score['brier_score'] < incumbent_score['brier_score'] and tuned_score['accuracy'] >= incumbent_score['accuracy'] - .002 and no_bad_season
    report = {
        'status': 'eligible_for_production_retrain' if gate else 'shadow_only_no_promotion',
        'production_changed': False,
        'policy': 'Nested rolling-origin validation with a one-standard-error simplicity rule. Promotion requires lower outer log loss and Brier score, no material accuracy loss, and no badly regressing season.',
        'outer_seasons': outer_years,
        'candidate_count': len(CANDIDATES),
        'tuned_outer': tuned_score,
        'incumbent_outer': incumbent_score,
        'promotion_gate_passed': gate,
        'folds': folds,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
