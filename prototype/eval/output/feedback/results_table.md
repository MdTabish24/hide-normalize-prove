# Feedback analysis (Round 2, Phase 5)

True safe counts span 0..32; production range width 12; per-run budget 2 reads. Red's estimate = mean of range midpoints over K fresh runs of the same probe set. Heuristic noise, not formal differential privacy.

## simulated feedback analysis (production range logic, Monte Carlo)

200 probe sets per K and mode, seed 7391.

| Mode | K | Mean abs error (all counts) | Intersection MAE | Truth inside intersection | Mean intersection width | Extremes (0 and 32) MAE | Interior (12..20) MAE |
|---|---:|---:|---:|---:|---:|---:|---:|
| run | 1 | 3.71 | 3.71 | 100% | 12.0 | 6.00 | 3.35 |
| run | 3 | 3.09 | 2.99 | 100% | 7.9 | 6.00 | 1.60 |
| run | 10 | 2.75 | 2.57 | 100% | 5.5 | 6.00 | 0.75 |
| run | 30 | 2.56 | 2.40 | 100% | 4.8 | 6.00 | 0.51 |
| probeset | 1 | 3.80 | 3.80 | 100% | 12.0 | 6.00 | 3.56 |
| probeset | 3 | 3.80 | 3.80 | 100% | 12.0 | 6.00 | 3.56 |
| probeset | 10 | 3.80 | 3.80 | 100% | 12.0 | 6.00 | 3.56 |
| probeset | 30 | 3.80 | 3.80 | 100% | 12.0 | 6.00 | 3.56 |

Extremes, separately: a true count of 0 always yields [0,12] and 32 always yields [20,32], so the extreme outcome itself is identifiable from ONE report even though midpoints are biased by 6.

## live gateway with mock model, local run; feedback small subset

| Mode | Repeat stable after restart | Third same-run read blocked | Same probes, 3 fresh runs identical | Changed probe sets: distinct ranges | Live K=3 MAE | MC 95% predictive interval | Agreement |
|---|---|---|---|---|---:|---|---|
| run | True | True | False | 8/8 | 3.00 | 2.70-3.45 | True |
| probeset | True | True | True | 7/8 | 3.55 | 3.25-4.45 | True |

## What this shows / does not show

- The per-run budget blocks a third read of the SAME run, including after a gateway restart.
- It does NOT stop cross-run averaging: fresh run IDs each get their own budget (residual risk).
- `probeset` mode returns the same range for the same probe set, so repeating it adds nothing; any change to the set gets fresh noise.
- Monte Carlo uses synthetic counts with the production generator and Store.report; live noise uses secrets.randbelow.
