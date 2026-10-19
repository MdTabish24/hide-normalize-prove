# live gateway with mock model, local run

Artifact status: partial. All nine timing cells are saved. The process was interrupted before feedback results were persisted; those sections are unavailable, not zero.

Held-out RUN accuracy. Fixed depth-3 decision tree; all response features are observed over HTTP.

Seed: 7391; buckets: 0.3 / 0.6 / 0.9 seconds; concurrent runs: 8; audit collector delivery: disabled (--no-audit). 

| Cohort | Policy | Train accuracy (n) | Unseen test (95% Wilson) | Gap | Test runs |
|---|---|---:|---:|---:|---:|
| ordinary | raw | 100.0% (n=200) | 98.0% (95.0%–99.2%) | +2.0% | 200 |
| boundary | raw | 100.0% (n=200) | 99.5% (97.2%–99.9%) | +0.5% | 200 |
| overflow | raw | 100.0% (n=200) | 100.0% (98.1%–100.0%) | +0.0% | 200 |
| ordinary | bucket | 76.0% (n=200) | 68.5% (61.8%–74.5%) | +7.5% | 200 |
| boundary | bucket | 99.5% (n=200) | 98.5% (95.7%–99.5%) | +1.0% | 200 |
| overflow | bucket | 100.0% (n=200) | 100.0% (98.1%–100.0%) | +0.0% | 200 |
| ordinary | bucket_hard | 72.0% (n=200) | 59.5% (52.6%–66.1%) | +12.5% | 200 |
| boundary | bucket_hard | 100.0% (n=200) | 100.0% (98.1%–100.0%) | +0.0% | 200 |
| overflow | bucket_hard | 100.0% (n=200) | 100.0% (98.1%–100.0%) | +0.0% | 200 |

Feedback artifacts: **NOT RUN / unavailable in this saved artifact**. Do not infer feedback results from timing measurements.

## simulated feedback analysis (production range logic, Monte Carlo)

Synthetic counts span 0..32; production width=12 and two-read per-run budget are unchanged.
Estimate = mean of reported interval midpoints. Intersection estimate = midpoint of the intersection.

| Mode | K | Sets | Mean absolute error | Intersection MAE | Truth in intersection | Truth at range center | Exact estimate | Estimate at intersection center |
|---|---:|---:|---:|---:|---:|---:|---:|---:|

### Extremes, separately — simulated feedback analysis (production range logic, Monte Carlo)

| Mode | K | Extreme sets | Mean absolute error | Intersection MAE | Coverage |
|---|---:|---:|---:|---:|---:|

For true count 0 the interval is [0,12]; for 32 it is [20,32]. These disjoint ranges disclose the extreme hypothesis even though their midpoint estimates remain biased by 6. Per-extreme metrics are also in JSON.

### Unclipped interior (counts 12..20), predeclared — simulated feedback analysis (production range logic, Monte Carlo)

| Mode | K | Sets | Averaging MAE | Intersection MAE | Mean intersection width |
|---|---:|---:|---:|---:|---:|

## live gateway with mock model, local run; feedback small subset

The budget blocks the third read of the SAME run, including after restart. Three fresh run IDs each have their own allowance; this does not prevent cross-run averaging.

| Mode | Live sets (K=3) | Live MAE | True count at range center | Inside, off-center | Monte Carlo 95% predictive interval | Agreement |
|---|---:|---:|---:|---:|---|---|

## LIMITATIONS

- Mock model, localhost scheduling jitter, fixed HTTP/SQLite overhead does not scale with sleeps.
- Audit delivery disabled; these runs are not audit-certified publishable runs.
- Overflow probes retain per-request fast/slow bucket differences even with a hard cap; this does not isolate only the over-9s tail channel.
- Decision tree only; one seed; no claim of absence of leakage.
- Feedback results were not persisted before interruption. No counts or midpoint statistics have been invented.
- Earlier audit-enabled full run stalled and remains incomplete; see audit_enabled_partial.json.
