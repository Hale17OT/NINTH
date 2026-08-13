# Simulation research basis

This note records the primary research used to design the shadow simulation
experiments. External results are hypotheses and architecture guidance only;
NINTH's chronological audits remain the promotion authority.

## Matchup probability and shrinkage

- Doo and Kim, *Modeling the probability of a batter/pitcher matchup event: A
  Bayesian approach* (2018), DOI
  [10.1371/journal.pone.0204874](https://doi.org/10.1371/journal.pone.0204874).
  A hierarchical Log5 formulation improved matchup-event prediction when
  direct batter/pitcher samples were sparse. This supports partial pooling and
  argues against using raw BvP averages.
- Wapner, Dalpiaz, and Eck, *SEAM methodology for context-rich player matchup
  evaluations* (2022),
  [arXiv:2005.07742](https://arxiv.org/abs/2005.07742). The method constructs
  synthetic comparable batters and pitchers because most direct matchups are
  too small to estimate reliably.
- Brown, *In-season prediction of batting averages* (2008),
  [arXiv:0803.3697](https://arxiv.org/abs/0803.3697). Empirical/hierarchical
  Bayes estimators beat the naive observed batting average, supporting NINTH's
  existing prior-season and league shrinkage.

## Plate appearances and pitcher workload

- Brill, *A Bayesian analysis of the time through the order* (2023),
  [paper](https://wsb.wharton.upenn.edu/wp-content/uploads/2023/08/Ryan-Brill_Research-Paper.pdf).
  The paper models categorical PA outcomes using batter quality, pitcher
  quality, handedness, home field, batter sequence, and second/third
  times-through-order effects. It reports roughly a 13-point average wOBA
  decline each time through the order. This supports a separate batters-faced
  head and a per-batter terminal-outcome head.
- Douglas et al., *Computing an Optimal Pitching Strategy in a Baseball
  At-Bat* (2021), [arXiv:2110.04321](https://arxiv.org/abs/2110.04321).
  Pitch selection/location, swing outcome, and patience are distinct
  stochastic components. NINTH does not claim pitch-sequence realism until
  those inputs are retained and validated.
- Yee and Deshpande, *Evaluating plate discipline in Major League Baseball
  with Bayesian Additive Regression Trees* (2023),
  [arXiv:2305.05752](https://arxiv.org/abs/2305.05752). Their separation of
  called-strike, contact, and downstream run-expectancy uncertainty supports
  keeping discipline and contact-quality signals explicit.

## Full-game and baserunning simulation

- Tallavarjula, *A Monte Carlo simulation of baseball offense with
  speed-stratified baserunning and distributional validation* (2026), DOI
  [10.1177/22150218251410737](https://doi.org/10.1177/22150218251410737).
  The architecture separates player initialization, categorical PA sampling,
  base/out transitions, full-game simulation, and distributional validation.
  Runs, RBIs, and steals therefore should not be treated as ordinary terminal
  PA categories.
- Ursin, *A Markov Model for Baseball with Applications* (2014),
  [repository record](https://minds.wisc.edu/items/53b95b6c-c7a7-4f2f-8eb6-7e0df42534c8).
  Player transition matrices can produce single-inning and nine-inning run
  distributions for a fixed lineup.
- Mott et al., *The Impacts of Increasingly Complex Matchup Models on Baseball
  Win Probability* (2025),
  [arXiv:2511.17733](https://arxiv.org/abs/2511.17733). Their hierarchical
  batter/pitcher, handedness, recency, and baserunning models reinforce the
  need to validate the matchup layer before expecting downstream win gains.

## Official data definitions

- [Statcast CSV documentation](https://baseballsavant.mlb.com/csv-docs)
  defines pitch type, pitcher/batter identifiers, handedness, velocity,
  location, spin, extension, expected outcomes, and play state.
- [Statcast pitch-arsenal leaderboard](https://baseballsavant.mlb.com/leaderboard/pitch-arsenal-stats)
  exposes pitch-type outcomes for pitchers and hitters. Run Value and whiff
  rate are per pitch; most outcome rates are per PA.

The current compact collector retains handedness and aggregate Statcast
quality but discards pitch rows. Arsenal/location simulation remains a future
candidate rather than an asserted capability.
