# NINTH multi-sport research foundation

NINTH shares an evidence contract, not one universal model. Each sport owns its
data collector, sport-native features, candidate families and forward ledger.

## Modeling choices

- **Football:** time-decayed Dixon–Coles/bivariate-Poisson score distribution,
  then a residual learner using xG, shot quality, lineup strength, rest and
  league-season effects. One score matrix powers 1X2, totals, BTTS and exact
  scores so the markets cannot contradict one another.
- **American Football:** dynamic team and quarterback priors feeding
  possession/drive efficiency and a joint score simulation. EPA/play, success
  rate and explosive-play rate are separated by phase and adjusted for
  opponent, personnel, weather and game availability.
- **Basketball:** possession-based pace and efficiency distributions with
  shrinkage-heavy lineup/player impact. Minutes and availability uncertainty
  must be simulated rather than treated as fixed inputs.
- **Valorant and CS2:** map-specific team/player ratings, roster continuity,
  side/context splits and an explicit veto tree. Series prices are composed
  from map probabilities only after the likely/known pick-ban state.

## Non-negotiable validation

1. Store event time and knowledge time separately; reject rows whose knowledge
   time is after event start.
2. Select features and models on older expanding windows only.
3. Reserve the newest competition/season block for a single untouched audit.
4. Compare against climatology and dynamic ratings. Odds are excluded from this
   historical-readiness pass and may only be evaluated later in a separate
   price/edge audit.
5. Report Brier, log loss, calibration error, AUC, coverage and Wilson bounds.
6. Require at least 500 three-year walk-forward observations, including 150
   recent-regime observations. After historical readiness, archive at least 30
   live forecasts to verify that the production locking path behaves like the
   tested pipeline.
7. Promote per sport and market. A good NFL moneyline model says nothing about
   NFL totals, and neither says anything about Basketball or Football.

The first research trainer is `python -m ml.multisport.train`. It accepts a
canonical JSONL ledger and produces a shadow-only artifact. No code path can
promote directly from its training result.

## Data-source decision

The registry is in `registry.json`. The Football, NFL and NBA baselines use
keyless open feeds and need no subscription. Premier League fixtures, clubs and
all current players come from the read-only Fantasy Premier League feed; the
other top-five league player directories remain thinner and are labelled as
such in the UI.

Valorant, Counter-Strike 2 and League of Legends use Liquipedia's MediaWiki API
under its published caching, attribution and rate-limit contract. HTML pages
are not scraped. CS API adds keyless CS2 rankings, results and player statistics;
all model outputs remain shadow-locked until their chronological promotion gate
passes.

## Running the historical readiness pipeline

`python -m ml.multisport.backfill --refresh-sources`

The command refreshes the permitted open sources, removes all odds/price/market
features, replays the latest three years in expanding quarterly folds, and
writes a readiness summary to `ml/artifacts/multisport/historical_readiness.json`.
Liquipedia page parses are deliberately slow because its published limit is one
parse every 30 seconds; cached pages make subsequent runs incremental.
