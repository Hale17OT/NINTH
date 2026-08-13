# Multi-sport research and implementation decision

Research date: 2026-08-12

NINTH is one analytics platform with separate sport workspaces and separate
model contracts. Shared infrastructure covers point-in-time storage,
calibration, evaluation, shadow ledgers and promotion. Features, targets,
simulators, baselines and promotion decisions remain sport-and-market specific.

## Data-source decisions

| Sport | Primary data | Fallback / enrichment | Decision |
| --- | --- | --- | --- |
| Football | Keyless [Football-Data.co.uk](https://www.football-data.co.uk/data.php) CSV archives plus the read-only Fantasy Premier League fixture/club/player feed | [StatsBomb Open Data](https://github.com/statsbomb/open-data) for selected events/lineups, public TheSportsDB cup/UEFA schedules and optional free football-data.org token | Six-season leak-safe ledgers and current shadow forecasts run without a paid subscription. FPL supplies the complete current Premier League directory; other league rosters are explicitly labelled as thinner. |
| American Football | [nflverse](https://github.com/nflverse) schedules, rosters and play-by-play | [NFL Next Gen Stats](https://operations.nfl.com/gameday/technology/nfl-next-gen-stats), point-in-time injuries and weather | Keyless schedules and rosters now drive a current moneyline shadow board. Forecasts remain uncertainty-shrunk until participant availability is captured. |
| Basketball | Keyless [llimllib/nba_data](https://github.com/llimllib/nba_data) NBA Stats mirror | Official NBA Stats and open SportsDataverse releases | Current team-market training runs from open efficiency/game data; player props remain a later, separately gated market. |
| Valorant | [Liquipedia MediaWiki API](https://liquipedia.net/valorant/api.php) | Optional official Riot/GRID access | Keyless API snapshots supply current schedules/results/directories; the series model remains shadow-gated. |
| Counter-Strike 2 | [Liquipedia MediaWiki API](https://liquipedia.net/counterstrike/api.php) | Keyless [CS API](https://www.csapi.de/) rankings, results and player statistics | The chronological series model has a deeper result audit while map-level models remain shadow-gated. |
| League of Legends | [Liquipedia MediaWiki API](https://liquipedia.net/leagueoflegends/api.php) | Future Riot/Oracle's Elixir point-in-time enrichment | Current schedules/results/directories and a series baseline are operational; patch and objective features remain shadow research. |

All three Esports disciplines use the keyless Liquipedia MediaWiki API under its
published caching, attribution and rate-limit contract. Generated HTML pages are
not scraped. CS API supplies an explicitly labelled CS2 statistical supplement.

## Model research translated into the build

### Football

- A time-decayed Dixon-Coles/bivariate-Poisson score model supplies a coherent
  score matrix for 1X2, totals, both-teams-to-score and exact-score markets.
- xG, shot quality, lineup strength, rest, home advantage and league-season
  effects feed residual candidates.
- A result is invalid if separately trained market heads materially contradict
  the score distribution without measured evidence.

### American Football

- Dynamic team and quarterback priors feed opponent-adjusted EPA/play,
  success rate, explosive rate and drive efficiency.
- Offense, defense and special teams are modeled separately; quarterback and
  availability uncertainty are simulated.
- Joint score simulations derive spread, moneyline and total probabilities
  from one internally consistent distribution.

### Basketball

- Forecast possessions first, then offense and defense efficiency per
  possession. Pace and scoring variance are separate uncertainty sources.
- Regularized adjusted plus-minus supplies shrinkage-heavy player impact;
  lineup minutes and availability are distributions, not fixed inputs.
- Game and player markets share the same simulated possession/lineup states.

### Valorant and Counter-Strike 2

- Team and player ratings are map-specific and decay through inactivity.
- Roster continuity, substitutions, event tier, LAN/online context, side
  strength and recent opponent quality are timestamped features.
- A veto tree produces likely map paths; best-of-series probabilities are
  composed from conditional map probabilities rather than a generic team Elo.

## Evaluation and release standard

Research on sports wagering calibration supports optimizing probability quality
rather than classification accuracy alone. Every candidate therefore reports
Brier score, log loss, expected calibration error, AUC, coverage and confidence
bounds. Data is split chronologically, calibration uses only the validation
window, and the newest test block stays untouched until final evaluation.

Training artifacts always start `shadow_only`. Promotion is market-specific and
requires superiority to simple and market baselines plus at least 100 immutable
live resolutions. This is an evidence gate, not a claim that any sport model is
"sure-fire" before it has earned that status.

Relevant methodology references include the sports-calibration study
[Machine learning for sports betting: should forecasting models be optimised
for accuracy or calibration?](https://arxiv.org/abs/2303.06021), recent
[lineup regularized adjusted plus-minus research](https://arxiv.org/abs/2601.15000),
[possession-weighted basketball expected points](https://arxiv.org/abs/2406.09895),
[Counter-Strike map selection modeling](https://arxiv.org/pdf/2106.08888), and
[Counter-Strike player plus-minus](https://arxiv.org/abs/2409.05052).
