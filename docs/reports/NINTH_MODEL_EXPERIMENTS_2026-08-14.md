# NINTH model experiment report — 2026-08-14

## Status and release decision

This is a research-only audit. It did not overwrite a production artifact, change a builder eligibility flag, or promote a model. The versioned machine-readable result is `ml/artifacts/experiments/multisport_feature_audit_20260814.json` and the repeatable runner is `ml/experiments/multisport_feature_audit.py`.

## Existing baseline

The live MLB model report currently identifies the moneyline model as `v6_multiseason_lineup_talent`: 11,442 walk-forward games, 57.534% accuracy, 0.24134 Brier, and 63.593% qualified accuracy. The deployed totals model is `market_free_pitching_availability_distribution_v5` with a 0.22186 mean unseen Brier. Player props are version 3.

The independent MLB research artifact remains `shadow_only`. Its calibrated-logistic reference covered 11,141 rolling-origin predictions with 56.323% accuracy and 0.24445 Brier. Its 2026 slice fell to 54.816% accuracy, 0.24941 Brier, and 54.986% qualified accuracy. That recent degradation is a reason to continue testing, not a basis for promotion.

## Candidate features investigated

- MLB: team Elo and form, starter form and availability, lineup quality, bullpen workload, weather, Statcast expected contact/whiff/velocity fields, and season-progress interactions.
- NBA: Elo/rating context; rolling points, offensive and defensive rating, assists, rebounding, turnovers, shooting and win rate; rest and availability context.
- NFL: Elo; opponent-adjusted recent scoring and prevention; rolling win rate; rest, venue/weather and divisional context. The player intelligence layer separately exposes position-aware weekly passing, rushing and receiving evidence, but those player fields were not silently inserted into the audited game model.
- Football: Elo; rolling goals, shots, shots on target, shot share, shot-quality proxies, recent form and availability/context fields.

Sportsbook odds, price, spread line, total line and any field prefixed as market information were excluded from training features.

## Data sources and permitted use

- MLB: NINTH's existing point-in-time official MLB/Statcast-derived ledgers.
- NBA: the open `llimllib/nba_data` season/game release already used by the NINTH multisport collector.
- NFL: open nflverse schedules, rosters, weekly player statistics and historical ledgers.
- Football: keyless Football-Data.co.uk match archives, Fantasy Premier League's read-only feed, and the existing open ledger; optional football-data.org access remains a free-account supplement rather than a requirement.

Baseball-Reference, Basketball-Reference, Pro-Football-Reference and FBref were used only to research metric definitions and information hierarchy. No Sports Reference HTML scraping or predictive-model training ingestion was added. Their published data-use terms require permission for automated/predictive ML uses, so they are deliberately not a production dependency.

## Leakage controls

- Every record must contain `knowledge_time <= event_time`.
- Rows are ordered by event time and split chronologically 60% train / 20% validation / 20% untouched test.
- Model-family selection happens only on the validation block.
- Isotonic calibration is fit only on validation predictions.
- The final 20% is evaluated once after family selection and calibration.
- Feature ablations use the same untouched period.
- Market prices and lines are rejected by feature name before matrix construction.

## Untouched experiment results

| Sport | Samples | Selected family | Test N | Accuracy | Brier | Climatology Brier | Log loss | AUC | ECE | 60%+ coverage / accuracy |
| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| NBA | 9,667 | Regularized logistic | 1,934 | 67.43% | 0.20980 | 0.24753 | 0.62022 | 0.72174 | 0.02722 | 51.09% / 76.52% |
| NFL | 4,363 | Regularized logistic | 873 | 64.83% | 0.21943 | 0.24757 | 0.62870 | 0.69527 | 0.03487 | 70.10% / 69.77% |
| Football | 10,734 | Histogram gradient boosting | 2,147 | 64.60% | 0.22145 | 0.24566 | 0.63871 | 0.68772 | 0.02996 | 71.73% / 68.57% |

These are odds-independent classification/calibration results, not profitability claims.

## Calibration: before and after

Negative deltas mean calibration improved the metric.

| Sport | Uncalibrated Brier → calibrated | Uncalibrated log loss → calibrated | Uncalibrated ECE → calibrated | Decision |
| --- | --- | --- | --- | --- |
| NBA | 0.20928 → 0.20980 (+0.00052) | 0.60609 → 0.62022 (+0.01413) | 0.02209 → 0.02722 (+0.00513) | Reject this isotonic mapping; keep the feature candidate in shadow and test a simpler or cross-fitted calibrator. |
| NFL | 0.22013 → 0.21943 (-0.00070) | 0.63148 → 0.62870 (-0.00278) | 0.04546 → 0.03487 (-0.01059) | Calibration helped all three measures; continue the live shadow gate. |
| Football | 0.22088 → 0.22145 (+0.00057) | 0.63222 → 0.63871 (+0.00650) | 0.04091 → 0.02996 (-0.01095) | ECE improved but proper-score quality worsened; do not promote this mapping. |

## Feature-group ablations

- NBA: removing ratings worsened Brier by 0.011319. Removing availability context worsened it by 0.001223. Removing the large recent-form group worsened Brier by only 0.000505 while improving log loss by 0.009284, so that group needs a smaller locked follow-up rather than an automatic expansion.
- NFL: removing recent form worsened Brier by 0.007595 and ratings by 0.001407. Availability/context was essentially neutral in Brier (+0.000001) but improved log loss when retained (+0.012232 degradation when removed). The full set is retained for shadow observation.
- Football: removing ratings worsened Brier by 0.002745. Removing availability/context improved Brier by 0.001396 and log loss by 0.003956. That group is a pruning candidate, but must be re-selected on a new validation block before another untouched audit.

Coefficient-derived feature influence and standardized train/test drift are recorded together in the JSON artifact. They are model diagnostics, not causal claims.

## Final decision by sport

- **MLB — Continue testing.** Preserve production v6. Do not promote the shadow candidate while the 2026 slice is degraded.
- **NBA — Continue testing the feature set; reject the current calibrator.** The full candidate beats climatology but isotonic calibration made the untouched proper scores worse.
- **NFL — Continue testing.** This is the cleanest result: the model beats climatology and calibration improved Brier, log loss and ECE. Live immutable observations are still required before promotion.
- **Football — Reject direct promotion.** Re-run a pruned availability/context candidate and a different calibrator through a fresh locked audit.

No sport received a production promotion in this pass.
