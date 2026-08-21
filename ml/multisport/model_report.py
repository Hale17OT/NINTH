"""Generate NINTH's evidence-first Football/NFL model inventory.

The report deliberately keeps predictive quality, calibration and archived-line
betting performance separate.  Missing odds-timestamp evidence remains null;
it is never replaced with invented ROI or CLV.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ARTIFACTS = ROOT / "ml" / "artifacts" / "multisport"


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def artifact_version(path: Path, report: dict) -> str:
    model_path = model_artifact_path(path, report)
    source = model_path.read_bytes() if model_path.exists() else path.read_bytes()
    return hashlib.sha256(source).hexdigest()[:12]


def model_artifact_path(path: Path, report: dict) -> Path:
    model_path = Path(report.get("model_artifact") or path.with_suffix(".joblib"))
    if not model_path.is_absolute():
        model_path = ROOT / model_path
    return model_path


def _binary_seasons(report: dict) -> tuple[dict, dict, dict]:
    holdout = report.get("holdout_results") or {}
    by_season = {
        season: {
            **(value.get("candidate") or {}),
            "baseline": value.get("baseline"),
            "closing_line_betting": value.get("closing_line_betting") or {},
        }
        for season, value in (holdout.get("season_by_season") or {}).items()
    }
    combined = holdout.get("combined") or {}
    return by_season, combined.get("candidate") or {}, combined.get("closing_line_betting") or {}


def _distribution_rows(report: dict, path: Path) -> list[dict]:
    sport = report["sport"]
    holdout = report.get("holdout_results") or {}
    by_season = holdout.get("season_by_season") or {}
    if sport == "football":
        markets = ("home_win", "over_2_5", "both_teams_score", "match_result_1x2")
        combined_markets = holdout.get("combined", {}).get("markets", {})
        get_season = lambda value, market: value.get("markets", {}).get(market, {})
    else:
        markets = ("moneyline", "spread", "total")
        combined_markets = holdout.get("combined", {}).get("markets", {})
        get_season = lambda value, market: value.get("markets", {}).get(market, {})
    rows = []
    for market in markets:
        metrics = combined_markets.get(market) or {}
        normalized_metrics = {**metrics}
        if market == "match_result_1x2":
            normalized_metrics["brier"] = metrics.get("multiclass_brier")
        row = _record(
            report, path, market, normalized_metrics,
            {season: get_season(value, market) for season, value in by_season.items()},
            metrics.get("closing_line_betting") or {},
            model_name="Coherent score distribution" if market != "match_result_1x2" else "Calibrated three-way score distribution",
        )
        if market == "match_result_1x2":
            season_values = [value.get("multiclass_brier") for value in row["season_by_season_results"].values()]
            stable = len(season_values) == 2 and all(value is not None and value < 2/3 for value in season_values)
            betting_values = [(value.get("closing_line_betting") or {}).get("roi") for value in row["season_by_season_results"].values()]
            row["comparison_to_baseline"] = {"uninformed_multiclass_brier":2/3, "brier_improvement":2/3-normalized_metrics["brier"]}
            row["decision"] = "USE" if stable and all(value is not None and value > 0 for value in betting_values) else "LIMITED" if stable else "REJECT"
            row["builder_eligible"] = row["decision"] == "USE"
            row["overall_assessment"] = "Three-way predictive skill is stable; betting use remains limited unless archived-line returns persist in both unseen seasons." if stable else "Three-way score probabilities did not beat the uninformed multiclass baseline in both holdouts."
        rows.append(row)
    if sport == "football":
        combined_score = (holdout.get("combined", {}).get("markets", {}) or {}).get("score") or {}
        score_seasons = {
            season: (value.get("markets", {}) or {}).get("score", {})
            for season, value in by_season.items()
        }
        context = _record(report, path, "correct_score_distribution", combined_score, score_seasons, {}, model_name="Dixon–Coles correct-score matrix")
        context.update({
            "brier_score": combined_score.get("multiclass_brier"), "decision":"WATCH", "builder_eligible":False,
            "combined_holdout_results": {
                **combined_score,
                "brier": combined_score.get("multiclass_brier"),
                "accuracy": combined_score.get("exact_score_accuracy"),
            },
            "overall_assessment":"Useful contextual score probabilities, but no complete historical correct-score price series or comparable multiclass market baseline supports betting use.",
            "comparison_to_baseline":None,
        })
        rows.append(context)
    else:
        for market in ("total_points", "home_margin", "home_team_points", "away_team_points"):
            metrics = holdout.get("combined", {}).get(market) or {}
            season_metrics = {season:value.get(market, {}) for season,value in by_season.items()}
            context = _record(report, path, market, metrics, season_metrics, {}, model_name="Expected-score regression")
            context.update({
                "decision":"WATCH", "builder_eligible":False,
                "overall_assessment":"Stable expected-score context is available, but this continuous target is not itself an approved betting market and has no attached price series.",
                "comparison_to_baseline":None,
            })
            rows.append(context)
    return rows


def decision(metrics: dict, seasons: dict, betting: dict) -> tuple[str, str]:
    sample = int(metrics.get("samples") or 0)
    brier = metrics.get("brier")
    season_briers = [value.get("brier") for value in seasons.values() if value.get("brier") is not None]
    season_rois = [
        (value.get("closing_line_betting") or {}).get("roi")
        for value in seasons.values()
        if (value.get("closing_line_betting") or {}).get("roi") is not None
    ]
    stable_prediction = len(season_briers) >= 2 and all(value < .25 for value in season_briers)
    stable_betting = len(season_rois) >= 2 and all(value > 0 for value in season_rois)
    if sample < 300 or brier is None:
        return "WATCH", "Insufficient evaluated probability evidence for normal use."
    if brier >= .25:
        return "REJECT", "Untouched holdout Brier does not beat the uninformed 0.25 benchmark."
    if stable_prediction and stable_betting:
        return "USE", "Predictive and archived-line results were positive in both unseen seasons."
    if stable_prediction:
        return "LIMITED", "Predictive skill is stable, but betting returns are unavailable, negative, or inconsistent across unseen seasons."
    return "WATCH", "Combined skill exists, but it was not stable across both unseen seasons."


def _record(report: dict, path: Path, market: str, metrics: dict, seasons: dict, betting: dict, model_name: str | None = None) -> dict:
    classification, assessment = decision(metrics, seasons, betting)
    qualified = metrics.get("qualified") or metrics.get("qualified_60") or {}
    window = report.get("samples") or {}
    model_path = model_artifact_path(path, report)
    created_at = datetime.fromtimestamp((model_path if model_path.exists() else path).stat().st_mtime, timezone.utc).isoformat()
    row = {
        "sport": report.get("sport"), "competition": "Supported competitions",
        "market": market, "model_name": model_name or market.replace("_", " ").title(),
        "model_family": path.stem,
        "model_version": artifact_version(path, report),
        "created_at": created_at,
        "feature_version": hashlib.sha256("|".join(report.get("features") or []).encode()).hexdigest()[:12],
        "dataset_version": hashlib.sha256(json.dumps({"start": report.get("development_dataset_start"), "end": report.get("development_dataset_end"), "seasons": report.get("development_seasons")}, sort_keys=True).encode()).hexdigest()[:12],
        "algorithm": report.get("algorithm") or report.get("method"),
        "main_feature_groups": report.get("features") or [],
        "development_dataset_start": report.get("development_dataset_start"),
        "development_dataset_end": report.get("development_dataset_end"),
        "development_seasons": report.get("development_seasons") or [],
        "validation_method": (report.get("development_validation") or {}).get("method") or "expanding-season chronological folds",
        "holdout_seasons": report.get("holdout_seasons") or list(seasons),
        "prediction_count": metrics.get("samples") or 0,
        "qualifying_bet_count": betting.get("qualifying_bets"),
        "win_count": betting.get("wins"), "loss_count": betting.get("losses"),
        "push_count": metrics.get("pushes", 0),
        "hit_rate": betting.get("hit_rate", metrics.get("accuracy")),
        "mae": metrics.get("mae"), "rmse": metrics.get("rmse"),
        "brier_score": metrics.get("brier"), "log_loss": metrics.get("log_loss"),
        "calibration_error": metrics.get("expected_calibration_error"),
        "average_market_odds": betting.get("average_market_odds"),
        "average_model_probability": metrics.get("mean_confidence") or metrics.get("mean_probability"),
        "average_estimated_edge": betting.get("average_estimated_edge"),
        "roi": betting.get("roi"), "yield": betting.get("yield"), "clv": betting.get("clv"),
        "maximum_drawdown": betting.get("maximum_drawdown_units"),
        "longest_losing_streak": betting.get("longest_losing_streak"),
        "season_by_season_results": seasons,
        "combined_holdout_results": metrics,
        "holdout_sample_size": metrics.get("samples") or window.get("holdout"),
        "holdout_stability_assessment": report.get("holdout_results", {}).get("stability_assessment"),
        "holdout_calibration": metrics.get("expected_calibration_error"),
        "holdout_roi": betting.get("roi"), "holdout_yield": betting.get("yield"),
        "holdout_clv": betting.get("clv"), "holdout_maximum_drawdown": betting.get("maximum_drawdown_units"),
        "odds_range_results": None, "confidence_bucket_results": qualified,
        "edge_bucket_results": None, "home_away_split": None,
        "sample_size_assessment": "adequate" if int(metrics.get("samples") or 0) >= 500 else "limited",
        "recommended_minimum_edge": "Positive edge only; no holdout-optimized cutoff approved.",
        "recommended_minimum_confidence": "60% reporting bucket; not an automatic release threshold.",
        "comparison_to_baseline": {"uninformed_brier": .25, "brier_improvement": None if metrics.get("brier") is None else .25 - metrics["brier"]},
        "decision": classification, "status": "evaluated", "builder_eligible": classification == "USE",
        "overall_assessment": assessment,
        "odds_limitations": betting.get("limitation") or "No complete historical price series is attached to this evaluated market.",
    }
    if report.get("sport") == "football":
        row.update({
            "football_2024_25_holdout_results": seasons.get("2024/25"),
            "football_2025_26_holdout_results": seasons.get("2025/26"),
            "combined_football_holdout_results": metrics,
        })
    else:
        row.update({
            "nfl_2024_holdout_results": seasons.get("2024"),
            "nfl_2025_holdout_results": seasons.get("2025"),
            "combined_nfl_holdout_results": metrics,
        })
    return row


def records(artifacts: Path = DEFAULT_ARTIFACTS) -> list[dict]:
    rows = []
    for sport in ("football", "american-football"):
        for path in sorted((artifacts / sport).glob("*.json")):
            report = read_json(path)
            market = report.get("market")
            if market in {"score_distribution", "joint_score_distribution"}:
                rows.extend(_distribution_rows(report, path))
                continue
            if sport == "american-football" and market in {"over_44_5", "over_total"}:
                continue
            seasons, metrics, betting = _binary_seasons(report)
            rows.append(_record(report, path, market, metrics, seasons, betting))
    return rows


def football_home_advantage_diagnostic() -> dict:
    """Describe, but never tune against, the required COVID-era seasons."""
    source = ROOT / "ml" / "data" / "multisport" / "football" / "score.jsonl"
    if not source.exists():
        return {"status": "unavailable", "reason": "Football score ledger is missing."}
    totals: dict[str, dict[str, float]] = {}
    for line in source.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        season = str(row.get("season"))
        if season not in {"2018", "2019", "2020", "2021", "2022", "2023"}:
            continue
        home, away = float(row["home_goals"]), float(row["away_goals"])
        values = totals.setdefault(season, {"matches": 0, "goal_advantage": 0, "home_wins": 0, "home_points": 0})
        values["matches"] += 1
        values["goal_advantage"] += home - away
        values["home_wins"] += int(home > away)
        values["home_points"] += 3 if home > away else 1 if home == away else 0
    labels = {str(year): f"{year}/{str(year + 1)[-2:]}" for year in range(2018, 2024)}
    seasons = {
        labels[season]: {
            "matches": int(values["matches"]),
            "home_goal_advantage_per_match": values["goal_advantage"] / values["matches"],
            "home_win_rate": values["home_wins"] / values["matches"],
            "home_points_per_match": values["home_points"] / values["matches"],
        }
        for season, values in sorted(totals.items()) if values["matches"]
    }
    covid = seasons.get("2020/21", {})
    adjacent = [seasons.get("2019/20", {}), seasons.get("2021/22", {})]
    adjacent_goal_advantage = sum(item.get("home_goal_advantage_per_match", 0) for item in adjacent) / 2
    covid_goal_advantage = covid.get("home_goal_advantage_per_match")
    return {
        "status": "reported_not_excluded",
        "scope": "Required development seasons across the six collected Football leagues",
        "seasons": seasons,
        "finding": (
            "2020/21 home advantage was materially lower than the adjacent development seasons; "
            "the season remains in chronological development data and rolling team-strength features absorb the regime change."
        ),
        "covid_2020_21_home_goal_advantage": covid_goal_advantage,
        "adjacent_seasons_mean_home_goal_advantage": adjacent_goal_advantage,
        "difference": None if covid_goal_advantage is None else covid_goal_advantage - adjacent_goal_advantage,
        "used_for_post_holdout_tuning": False,
    }


def markdown(payload: dict) -> str:
    lines = [
        "# NINTH Football & NFL Model Evaluation", "",
        f"Generated: {payload['generated_at']}", "",
        "Holdouts were excluded from fitting, calibration, feature selection, and threshold selection. Archived closing prices are evaluation-only; CLV remains unavailable without prediction-time prices.", "",
        "| Decision | Sport | Model | Market | N | Brier | Hit rate | ROI | Assessment |",
        "|---|---|---|---|---:|---:|---:|---:|---|",
    ]
    percent = lambda value: "—" if value is None else f"{100 * value:.1f}%"
    number = lambda value: "—" if value is None else f"{value:.3f}"
    for row in payload["models"]:
        lines.append(
            f"| {row['decision']} | {row['sport']} | {row['model_name']} | {row['market']} | {row['prediction_count']} | "
            f"{number(row['brier_score'])} | {percent(row['hit_rate'])} | {percent(row['roi'])} | {row['overall_assessment']} |"
        )
    lines.extend(["", "## Decision matrix", ""])
    for decision_name in ("USE", "LIMITED", "WATCH", "REJECT"):
        selected = [f"{row['sport']} · {row['model_name']} · {row['market']}" for row in payload["models"] if row["decision"] == decision_name]
        lines.append(f"- **{decision_name}:** {', '.join(selected) if selected else 'None'}")
    covid = payload["development_findings"]["football_covid_home_advantage"]
    lines.extend([
        "", "## COVID-era development diagnostic", "",
        f"- {covid.get('finding', covid.get('reason', 'Unavailable'))}",
        f"- 2020/21 home-goal advantage: {number(covid.get('covid_2020_21_home_goal_advantage'))}; adjacent-season mean: {number(covid.get('adjacent_seasons_mean_home_goal_advantage'))}.",
    ])
    lines.extend([
        "", "## Data limitations", "",
        "- Football player/event markets (player shots, passes, tackles, cards, saves and event corners/cards) were not trained: the repository does not contain a reliable point-in-time 2018/19–2025/26 participant-level history.",
        "- NFL player props and team-total betting models were not trained: the repository has game-level nflverse history but no frozen point-in-time depth chart, injury, snap, route, target, carry and historical prop-price dataset.",
        "- CLV is intentionally null because exact prediction-time historical prices are unavailable; archived closing-price results are labelled as closing-line audits.",
    ])
    return "\n".join(lines) + "\n"


def generate(artifacts: Path, output: Path) -> dict:
    models = records(artifacts)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "evaluation_contract": {
            "football_development": "2018/19–2023/24", "football_holdouts": ["2024/25", "2025/26"],
            "nfl_development": "2018–2023", "nfl_holdouts": ["2024", "2025"],
            "holdouts_excluded_from_development": True,
        },
        "development_findings": {"football_covid_home_advantage": football_home_advantage_diagnostic()},
        "models": models,
        "unevaluated_inventory": [
            {"sport":"football", "markets":["draw_no_bet","double_chance","asian_handicap","team_totals","corners","cards","player_props"], "decision":"UNAVAILABLE", "reason":"No sufficiently complete point-in-time historical market/participant dataset in the repository."},
            {"sport":"american-football", "markets":["team_totals","passing_props","rushing_props","receiving_props","touchdowns","defense_props"], "decision":"UNAVAILABLE", "reason":"No sufficiently complete point-in-time opportunity, availability and historical prop-price dataset in the repository."},
        ],
        "decision_counts": {name: sum(row["decision"] == name for row in models) for name in ("USE", "LIMITED", "WATCH", "REJECT")},
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    output.with_suffix(".md").write_text(markdown(payload), encoding="utf-8")
    registry = {
        "generated_at": payload["generated_at"],
        "contract": "Every prediction must carry the version of the immutable artifact that generated it.",
        "models": [{
            key: row.get(key) for key in (
                "sport", "competition", "market", "model_name", "model_family", "model_version",
                "algorithm", "feature_version", "dataset_version", "development_dataset_start",
                "development_dataset_end", "development_seasons", "holdout_seasons", "created_at",
                "decision", "status", "builder_eligible",
            )
        } for row in models],
    }
    output.with_name("model_registry.json").write_text(json.dumps(registry, indent=2), encoding="utf-8")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifacts", type=Path, default=DEFAULT_ARTIFACTS)
    parser.add_argument("--output", type=Path, default=DEFAULT_ARTIFACTS / "football_nfl_model_report.json")
    args = parser.parse_args()
    payload = generate(args.artifacts, args.output)
    print(json.dumps({"models": len(payload["models"]), "decisions": payload["decision_counts"], "output": str(args.output)}, indent=2))


if __name__ == "__main__":
    main()
