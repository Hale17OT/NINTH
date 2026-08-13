# Batter-vs-pitcher Monte Carlo shadow model

`research_bvp_monte_carlo.py` estimates one coherent plate-appearance
distribution for a starting batter in the announced-starter context. It uses
the existing leakage-safe replay features, including starter history,
handedness/platoon Statcast, xwOBA, hard-hit, barrel, whiff, velocity,
opportunity, and lineup position.

The model has two categorical heads:

- plate appearances: 1 through 7;
- outcome per plate appearance: other out, strikeout, walk, HBP, single,
  double, triple, or home run;
- context-dependent whole-game count heads for runs, RBIs, and stolen bases.

The reusable `simulate_matchup` function samples both heads and returns
full-game hit, total-base, home-run, and strikeout counts. The historical audit
uses the mathematically equivalent exact finite distribution so model
comparisons do not contain random Monte Carlo error. A held-out Monte Carlo
check in the report verifies that both engines agree.

Run:

```powershell
python -m ml.research_bvp_monte_carlo
python -m unittest ml.test_bvp_monte_carlo
```

Outputs:

- `ml/artifacts/bvp_monte_carlo_shadow.joblib`
- `ml/artifacts/bvp_monte_carlo_shadow.json`

This is research-only. It trains through 2023, calibrates on 2024, and reports
2025 and 2026 separately. It does not overwrite or alter the production
player-prop artifact.

The expanded full audit retained the model in shadow status. Broad held-out
Brier improved for eight of nine batter markets, with stolen bases the
exception. Exact listed-line evidence remained mixed or underpowered:
home-run and doubles Brier regressed, total bases and doubles had only 14 rows
from one game, and the remaining markets either lacked exact lines or had
confidence intervals crossing zero. See `SIMULATION_FULL_AUDIT.md` for every
market and the production decision.
