# NINTH moneyline model

This model estimates straight-up home/away win probability using baseball data only. Bookmaker odds are intentionally excluded from collection, training, inference, and evaluation.

## Workflow

```powershell
python -m pip install -r stats-service/requirements.txt
python ml/collect.py --start-season 2018 --end-season 2026
python ml/enrich.py --start-season 2018 --end-season 2026 --workers 12
python ml/statcast_collect.py --start 2018-03-01 --end 2026-07-14
python -m ml.train_v3
```

The collector stores official completed MLB games in `ml/data/games.jsonl`. The resumable context collector writes point-in-time starting pitchers, submitted lineups, bullpen usage, and weather. Features are built chronologically before each game result is applied.

At inference, matchup pages refresh every 60 seconds before first pitch and every 10 seconds while live. Finals stop polling. A starter is `confirmed` only when the announced pitcher matches the first pitcher on the submitted official game roster; otherwise the announced pitcher is `predicted`. A bullpen becomes `confirmed` after the official pitcher pool is submitted. Lineups require a submitted nine-player batting order. Projection snapshots raise alerts when certainty changes, a starter or lineup changes, bullpen workload moves materially, or weather shifts.

V3 training performs leakage-safe walk-forward evaluation across 2022–2026 and fits a capped run-margin model using market-free team-form features plus each confirmed starter's prior 15-start Statcast history. The production report records all-game and selective results, while the recent 2024–2026 outer audit remains visible as an anti-overfitting check.

The confidence score is not win probability. It is an isotonic estimate of historical straight-up hit rate for similarly decisive walk-forward predictions, reduced when confirmed starter, confirmed lineup, bullpen, or weather inputs are incomplete. `selective_accuracy` in `ml/artifacts/report.json` records accuracy and coverage at each probability threshold.

Generated artifacts are written under `ml/artifacts/`. This is decision-support software, not a guarantee of outcomes. Validate with forward paper tracking before relying on projections.

## Statcast accuracy pipeline

`statcast_collect.py` streams official Baseball Savant pitch data one day at a time, writes compact per-game aggregates, and records completed dates so interrupted backfills resume safely. Raw pitch downloads are discarded.

V3 promotes only the long-history starting-pitcher aggregates that survived the walk-forward ablation. Hitter platoon, bullpen-personnel, short-window starter, and stacked variants remain excluded because they did not improve the unseen folds. The serialized production state is trained through the cutoff recorded in `ml/artifacts/report.json`; inference applies only completed games after that cutoff, preventing current-season games from being replayed twice.
