# NINTH analytics implementation report — 2026-08-14

## MLB matchup fixes

- Reproduced the 7,837px final-game evidence wall and reorganized it around a sticky jump rail: starters, moneyline, totals, offense and run prevention.
- Kept the visible final score and verdict while collapsing deep final-game driver/input/audit evidence by default. Representative desktop matchups now measure roughly 6,900–7,500px rather than forcing every audit field into the initial scan.
- Replaced the fixed probability gauge with the shared responsive `ProbabilityRing`. It synchronizes path and number animation, supports fractional inputs, uses container-relative typography, and was visually checked at 1%, 9%, 42%, 50%, 52.4%, 76%, 99% and 100%.
- Consolidated the two conflicting trend implementations behind `AnalyticsChart`, with bounded geometry, finite-value sanitation, correct single/empty/missing-value states, and resize transitions that do not replay the opening animation.
- Added explicit responsive treatment for the jump navigation, evidence panels and charts. Representative matchups had no horizontal overflow at 375px or 1,440px.

## Player and team intelligence

### MLB

- Official player game logs now drive real rolling trend charts.
- Hitters receive AVG, OBP, SLG, OPS, BB rate, strikeout rate and ISO peer context where the official feed supports it.
- Pitchers receive ERA, WHIP, strikeout rate, walk rate and home-run rate with lower-is-better percentile handling where appropriate.
- Trend interpretation is deterministic and derived from the displayed recent/season values. Unsupported WAR, FIP, wRC+, barrel and Statcast fields remain absent instead of being synthesized.

### NBA

- Added season production, per-36 normalization when minutes are available, league peer percentiles, metric definitions and source/sample disclosure.
- The current open player source does not provide a trustworthy per-game log for this route, so the chart intentionally renders an analytical empty state rather than a fake trend.

### NFL

- Added nflverse weekly player-stat ingestion and position-aware profiles.
- QB pages expose passing volume/efficiency, touchdowns, interceptions, sacks and EPA per dropback.
- RB pages expose workload, rushing/receiving production, yards per carry, scrimmage yards and EPA per touch.
- WR/TE pages expose targets, receptions, catch rate, yards per target, target/air-yard share and receiving EPA per target.
- Weekly game logs drive real trend charts, and peer comparisons stay within the player's position group.

### Football

- Premier League player pages now use source-backed goals, assists, minutes, xG and xA, including per-90 normalization and position peer percentiles.
- The keyless Premier League path is complete. Other top-five squad depth remains explicitly dependent on the optional free football-data.org supplement.

### Teams

- Added reusable team percentile profiles and source/sample context instead of only surface-level totals.
- NBA, NFL and Football team pages now share the same honest loading, empty and trend behavior as player pages.

## NFL Builder

- Rebuilt the opportunity rows around team identity, model probability, line/market evidence and builder eligibility.
- Kept only genuinely supported markets—moneyline, spread, totals and mixed. Player props are not displayed as selectable merely because their UI would look complete.
- Added structural selection/tray motion and responsive row layouts.
- Browser interaction produced a five-leg, five-game card with a 15.6% multiplicative joint estimate and 6.42 listed decimal odds in the current shadow board. Switching to production evidence correctly produced zero eligible rows rather than silently using shadow data.
- All seven requested widths (375, 430, 768, 1024, 1280, 1440 and 1728) remained free of horizontal document overflow.

## Canonical identity and logo coverage

- Added one canonical resolver used by `SportIdentity` rather than constructing league URLs in each page.
- Canonical IDs take precedence over unreliable provider abbreviations; NBA historical aliases and special ESPN logo slugs are centralized.
- Fixed an NBA routing bug found during browser QA: a higher-detail provider row could replace the canonical `nba:DEN` record, causing the player-to-team link to return “Team not found.” Team workspaces now resolve canonical ID, provider code or canonical name.
- The diagnostic utility verified:

| Sport | Teams audited | Working remote logos | Intentional fallback | Broken URL |
| --- | ---: | ---: | ---: | ---: |
| MLB | 30 | 30 | 0 | 0 |
| NBA | 30 | 30 | 0 | 0 |
| NFL | 32 | 32 | 0 | 0 |
| Football | 139 | 70 | 69 | 0 |
| Esports | 177 | 0 | 177 | 0 |

Football/esports rows without a stable source logo use an explicit NINTH monogram treatment. They no longer emit broken images or blank identity space.

## Analytics and motion primitives

- `ProbabilityRing` — synchronized number/path animation, viewport-triggered once, live-value interpolation and reduced motion.
- `AnalyticsChart` / `TrendChart` — line/bar interpolation, responsive sizing, readable axes/tooltips, missing/empty/single/long data handling and no resize replay.
- `PlayerPercentileProfile` / `TeamPercentileProfile` — animated measured bars and source/sample context.
- `RollingTrend` — 5/10/all range switching through one analytical workspace.
- `SplitComparison`, `OpponentComparison`, `AdvancedMetricTable`, `ModelDriverPanel` — progressive disclosure and metric definitions without stacking raw tables.
- The unlinked `/experiments/visual-qa` route exercises the probability edge cases and normal, empty, single-point, missing-value and long chart datasets.

Reduced-motion media queries disable path-drawing and large entrance movement while preserving immediate state communication.

## Browser verification

Representative desktop routes inspected in the live app included:

- MLB: `/games/824238`, `/games/823508`, `/games/823913`, `/players/592450`, `/players/543037`, `/teams/147`, `/builder`.
- NBA: `/basketball/players/203932`, `/basketball/teams/nba:DEN`.
- NFL: QB `/american-football/players/00-0023459`, RB `/american-football/players/00-0033293`, WR `/american-football/players/00-0035676`, `/american-football/teams/nfl:PIT`, `/american-football/builder`.
- Football: `/football/players/fpl:561`, `/football/teams/fpl:6`.
- Shared identity: `/esports/teams`.
- Component QA: `/experiments/visual-qa`.

The component QA route was checked at 375, 430, 768, 1024, 1280, 1440 and 1728 pixels. The MLB matchup, MLB/NBA/NFL/Football player pages and NFL Builder were additionally checked at mobile width. Loaded representative pages reported zero horizontal overflow and zero broken images.

## Bugs found through browser testing

- Three-digit/decimal probability text was only 5px in one first-pass implementation because percentage font sizing did not map correctly to container query units; corrected and rechecked across every edge value.
- NBA canonical player-team links could 404 after provider de-duplication preferred a numeric identity; fixed with cross-provider canonical matching.
- A Premier League player page fanned out through unrelated football competitions and took about 12–15 seconds cold. FPL identities now take the direct open-data path; the measured endpoint dropped to 0.711 seconds after a server restart.
- NFL/NBA provider codes could override the canonical suffix (`LAS`, `GRE`, `NEW`) and generate six NFL and two NBA logo failures. The suffix now wins and the audit reports zero failures.
- Final MLB games exposed too much audit evidence at once and pushed relevant totals/offense sections far below the fold; final-only deep evidence is now collapsed with explicit disclosure.
- NBA player pages lacked time-series data. The fix is an honest empty state, not generated numbers.

## Technical verification

- `node --test ...`: 36/36 affected JavaScript tests passed.
- `python -m unittest stats-service/test_projection_integrity.py`: 69/69 passed.
- `python -m unittest ml.multisport...`: 5/5 passed when invoked as package modules. A discovery-mode attempt produced two relative-import loader errors; those are invocation errors, not test failures, and the correct package invocation passed.
- `node --check` passed for the changed server services and identity diagnostic.
- `python -m py_compile` passed for the stats service and research runner.
- `npm run build`: production Vite build passed (2,120 modules transformed).
- This repository defines no lint or static typecheck script, so there was no additional lint/typecheck command to run.
- Ports 3001, 3002 and 5173 are listening, and all processes were launched without a visible terminal window.

## Remaining issues and honest limits

- The NBA source lacks a suitable player game log and several advanced fields (TS%, usage, BPM/VORP) for the current route. They remain unavailable until a permitted point-in-time provider is added.
- NFL profiles correctly label the latest statistics season present in nflverse. A roster can be newer than the latest complete weekly-stat release.
- Complete player directories outside the Premier League require the optional free football-data.org token; no paid subscription was introduced.
- 69 Football and 177 esports teams still use intentional monogram fallback because their current source lacks a stable permitted logo URL.
- Position-specific NFL defensive/OL profiles remain necessarily thinner than QB/RB/WR/TE profiles because the weekly source does not expose equivalent role metrics.
- Browser automation exposed page errors, failed route states, overflow and broken-image checks, but this browser harness did not expose a console-message API. Direct API probes, route alerts and identity URL checks were used instead; automated console-log capture remains a tooling gap.
- No production model was promoted. The experiment identified promising areas, but it also showed that isotonic calibration worsened untouched NBA proper scores and traded Football Brier/log loss for better ECE.
