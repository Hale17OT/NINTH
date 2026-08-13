# Full simulation challenger audit

## Decision

Retain every new simulation component in research/shadow status. Do not replace
any production model from this experiment.

The plate-appearance simulator produces real broad-sample gains, especially for
batter hits, total bases, and strikeouts. The pitcher simulator produces one
statistically credible broad gain for outs. Those results are useful enough to
continue shadow collection, but none passes the full production gate:

1. lower aggregate 2025-2026 Brier score;
2. improvement in both 2025 and 2026;
3. paired game-block bootstrap interval below zero;
4. adequate immutable exact listed-line evidence;
5. no material regression at a commercially important line.

The first three gates use the complete chronological replay. The fourth cannot
be manufactured retrospectively: the archive contains exact player-prop
snapshots for only 59 games.

## Method

- Training: 2018-2023 data, with model fitting restricted through 2023.
- Calibration: 2024 only.
- Untouched audit: 2025 and 2026, reported jointly and separately.
- Batter coverage: 345,490 starting-batter games; 71,906 held-out batter games.
- Pitcher coverage: 35,974 valid starts; only 5 invalid records excluded.
- Comparisons: sample-for-sample against the current production artifacts.
- Uncertainty: paired game-block bootstrap, 2,000 broad-audit resamples and
  5,000 exact-line resamples.
- Scoring: Brier score is primary. In the tables below,
  `delta = challenger - production`, so a negative value is better.
- Serving validation: the batter Monte Carlo engine used 50,000 draws for each
  of 40 held-out matchups and agreed with the exact finite distribution across
  920 probabilities with mean absolute error 0.001066 and maximum error
  0.005323.

## All production-market comparisons

| Market | 2025-26 Brier, new vs production | Delta (relative improvement) | 95% paired CI | Season result | Exact listed-line evidence | Production decision |
|---|---:|---:|---:|---|---|---|
| Moneyline | 0.244729 vs 0.243017 | +0.001712 (-0.705%) | not bootstrapped | worse in 2025 and 2026 | not applicable | Reject |
| Totals | 0.224421 vs 0.221957 | +0.002463 (-1.110%) | not bootstrapped | worse in 2025 and 2026 | not applicable | Reject |
| Batter hits | 0.149167 vs 0.150038 | -0.000871 (+0.580%) | [-0.001031, -0.000708] | better in both | 980 rows / 59 games; delta -0.000289, CI crosses zero | Shadow; strongest batter candidate |
| Batter total bases | 0.186121 vs 0.187121 | -0.001000 (+0.534%) | [-0.001194, -0.000813] | better in both | 14 rows from 1 game; delta -0.000888 | Shadow; exact evidence unusable |
| Batter home runs | 0.054720 vs 0.054778 | -0.000057 (+0.104%) | [-0.000098, -0.000016] | better in both | 783 rows / 53 games; **worse** by +0.001104, CI [0.000285, 0.001947] | Reject current challenger |
| Batter walks | 0.122539 vs 0.122752 | -0.000212 (+0.173%) | [-0.000314, -0.000109] | better in both | no archived exact lines | Shadow only |
| Batter strikeouts | 0.144224 vs 0.144666 | -0.000443 (+0.306%) | [-0.000598, -0.000284] | better in both | no archived exact lines | Shadow only |
| Batter doubles | 0.072204 vs 0.072308 | -0.000104 (+0.144%) | [-0.000154, -0.000054] | better in both | 14 rows from 1 game; **worse** by +0.004557 | Shadow; exact evidence unusable |
| Batter runs | 0.152969 vs 0.153342 | -0.000373 (+0.243%) | [-0.000521, -0.000238] | better in both | 979 rows / 59 games; delta -0.000530, CI crosses zero | Shadow only |
| Batter RBIs | 0.111803 vs 0.111968 | -0.000165 (+0.147%) | [-0.000233, -0.000090] | better in both | no archived exact lines | Shadow only |
| Batter stolen bases | 0.032632 vs 0.032623 | +0.000008 (-0.026%) | [-0.000029, 0.000044] | worse in 2025, better in 2026 | no archived exact lines | Reject |
| Pitcher strikeouts | 0.141580 vs 0.141689 | -0.000110 (+0.077%) | [-0.000626, 0.000390] | slightly better in both | 105 rows / 58 games; **worse** by +0.014949 | Reject current challenger |
| Pitcher outs | 0.157286 vs 0.158056 | -0.000770 (+0.487%) | [-0.001352, -0.000159] | better in both; 2026 nearly flat | 102 rows / 57 games; delta -0.001345, CI crosses zero | Shadow; strongest pitcher candidate |
| Pitcher walks | 0.135692 vs 0.135905 | -0.000213 (+0.157%) | [-0.000720, 0.000160] | better in both | 109 rows / 59 games; delta -0.003141, CI crosses zero | Shadow only |
| Pitcher hits allowed | 0.155821 vs 0.156263 | -0.000442 (+0.283%) | [-0.001023, 0.000025] | better in both | 107 rows / 58 games; **worse** by +0.011301 | Reject current challenger |
| Pitcher earned runs | 0.168711 vs 0.168635 | +0.000076 (-0.045%) | [-0.000367, 0.000441] | better in 2025, worse in 2026 | no archived exact lines | Reject |
| Pitcher home runs allowed | 0.107585 vs 0.107841 | -0.000256 (+0.237%) | [-0.000622, 0.000043] | better in 2025, worse in 2026 | no archived exact lines | Shadow only |
| Pitcher pitches | 0.108717 vs 0.108993 | -0.000276 (+0.253%) | [-0.000811, 0.000208] | better in both | no archived exact lines | Shadow only |

The moneyline and totals figures are sample-weighted across 2,425 games in
2025 and 1,596 games in 2026. Their bivariate run-distribution challenger
selected pooling alpha 0.3 on the earlier 2022-2024 development period before
the untouched audits.

## Separate totals line-grid experiment

The expanded push-aware MelBet-style grid improved simulated held-out selected
Brier from 0.223071 to 0.222194 (delta -0.000877) and selected accuracy by
0.003233. This does not authorize production use because the experiment
reconstructed the offered ranges: `historical_market_data` is false. Archive
the real pregame grids and rerun a later temporal audit.

## Architecture and research conclusions

The batter engine uses separate distributions for plate-appearance exposure
and eight terminal outcomes (out, strikeout, walk, hit by pitch, single,
double, triple, home run). Runs, RBIs, and steals use separate whole-game count
heads because they depend on lineup and base/out context.

The pitcher engine separates batters faced from per-batter terminal outcomes.
Outs are modeled separately because double plays make them impossible to
reconstruct reliably from terminal PA categories. Earned runs and pitches are
also separate overdispersed count heads.

The research supports this structure but does not imply automatic predictive
gain:

- Doo and Kim's hierarchical Log5 work shows why sparse direct matchup rates
  need partial pooling rather than raw BvP averages.
- SEAM constructs comparable-player samples because direct matchup histories
  are usually too small.
- Brown's empirical-Bayes study shows naive observed batting average is a poor
  forecast relative to shrinkage.
- Brill models categorical PA outcomes with batter/pitcher quality,
  handedness, home field, sequence, and times through the order.
- Full-game and Markov research separates PA sampling from base/out state,
  baserunning, and run generation.
- Statcast exposes pitch type, location, velocity, movement, spin, extension,
  and expected outcomes, but the current compact collector does not retain raw
  pitch rows. Pitch-arsenal/location simulation is therefore a future
  experiment, not a capability of this challenger.

Primary sources are recorded in `SIMULATION_RESEARCH.md`.

## Required next gate

Keep the artifacts shadow-only and archive immutable pregame line snapshots
continuously. Reconsider batter hits, batter runs, and pitcher outs first after
the archive reaches multiple independent seasons or at least several hundred
games per market. Require the same line definition and incumbent version,
pre-register the promotion threshold, and rerun the locked chronological
comparison once—without tuning on that new audit window.

