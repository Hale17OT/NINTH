"""Leave-one-feature-out rolling-origin diagnostics for the linear model."""
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
from ml.accuracy_experiments import matrix
from ml.features import FEATURE_NAMES

OUTPUT = ROOT / "ml" / "artifacts" / "feature_ablation.json"


def model():
    return Pipeline([("scale", StandardScaler()), ("model", LogisticRegression(C=.03, max_iter=4000))])


def evaluate(X, y, years, indices):
    labels, probabilities, per_year = [], [], {}
    for year in sorted(set(years)):
        if year < 2022 or np.sum(years < year) < 4000:
            continue
        train, test = years < year, years == year
        probability = model().fit(X[train][:, indices], y[train]).predict_proba(X[test][:, indices])[:, 1]
        labels.extend(y[test]);probabilities.extend(probability)
        per_year[str(year)] = float(accuracy_score(y[test], probability >= .5))
    labels, probabilities = np.asarray(labels), np.asarray(probabilities)
    return {
        "accuracy": round(float(accuracy_score(labels, probabilities >= .5)), 5),
        "log_loss": round(float(log_loss(labels, probabilities)), 5),
        "brier_score": round(float(brier_score_loss(labels, probabilities)), 5),
        "roc_auc": round(float(roc_auc_score(labels, probabilities)), 5),
        "per_year_accuracy": {key: round(value, 5) for key, value in per_year.items()},
    }


def main():
    X, _, _, y, years, _ = matrix()
    all_indices = list(range(len(FEATURE_NAMES)))
    baseline = evaluate(X, y, years, all_indices)
    removals = {}
    for index, name in enumerate(FEATURE_NAMES):
        result = evaluate(X, y, years, [item for item in all_indices if item != index])
        result["accuracy_change"] = round(result["accuracy"] - baseline["accuracy"], 5)
        result["log_loss_change"] = round(result["log_loss"] - baseline["log_loss"], 5)
        removals[name] = result
        print(name, result, flush=True)
    OUTPUT.write_text(json.dumps({"status":"diagnostic_only","baseline":baseline,"removals":removals},indent=2),encoding="utf-8")


if __name__ == "__main__":
    main()
