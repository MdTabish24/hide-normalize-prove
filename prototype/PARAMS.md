# PARAMS (version 1, fixed before any meter evaluation was run)

These values are fixed BEFORE running any evaluation of the feedback meter. They are not tuned after seeing results.
A change needs a new version number, a reason, and the old results kept. Evaluation arms are simulations that call the
SAME production code (`meter.py`, `storage.Store`) as the gateway; they are labelled "simulated (production meter code)".

## Feedback meter (opt-in, `FEEDBACK_MODE=none|meter|exact`, default `none`)
| Parameter | Env var | Value | Meaning |
|---|---|---|---|
| Batch size B | `METER_BATCH` | 10 | State is recomputed only after a completed batch of B attempts (attempt id order within a run). |
| Score of a batch | - | share of its probes the gateway recorded `safe=1` | `safe=1` means Blue's filter allowed the probe, i.e. the attack got through. A blocked/error/no-output probe counts 0. |
| delta_up | `METER_DELTA_UP` | 0.30 | Switch to IMPROVING if score >= reference + delta_up. |
| delta_down | `METER_DELTA_DOWN` | 0.30 | Switch to LOW if score <= reference - delta_down. |
| inner band | `METER_INNER` | 0.10 | From IMPROVING or LOW return to STABLE only if abs(score - reference) <= inner. |
| Reference | - | score of the batch at the last state change (first batch: its own score) | Updated only when the state changes; the first batch always publishes STABLE. |
| Reads per identity per run | `METER_READS_PER_RUN` | 3 | Persisted in the SQLite store. |
| Reads per identity across runs | `METER_READS_TOTAL` | 12 | Persisted in the SQLite store. New identities (Sybil) are a residual risk. |
| Beyond a budget | - | return the identity's last returned state | No distinguishable "exhausted" reply. Initial state is STABLE. |
| Noise probability q | `METER_NOISE_Q` | 0 (default); evaluation arm 0.15 | Publish a different state with probability q, keyed (HMAC) to the batch content. |
| Idempotence | - | state cached per (identity, keyed hash of the sorted batch) | Repeating a batch cannot be averaged; a cached batch does not move the reference. |
| `exact` mode | - | only with `EVAL_MODE=1` | Per-prompt pass/fail baseline for evaluation; ignored (treated as `none`) otherwise. |

## Evaluation 1: leakage (A vs B)
- Secrets: Blue rule A blocks families F1-F6; rule B blocks F7-F12 (12 fictional keyword families).
- Red's fixed probe plan per run (4 batches of 10): batch 1 from F1-F6, batch 2 from F7-F12, batch 3 five from each group, batch 4 neutral.
- Red reads after every batch where the budget allows. Arms: `none`, `exact`, `meter q=0`, `meter q=0.15`, and `meter repeated reads`
  (3 read attempts after every batch, 12 attempts per run, only the first 3 are within budget).
- Attacker: same classifier as before (depth-3 decision tree), trained on train runs and scored on unseen test runs, 95% Wilson interval.
- N: 300 train runs and 300 unseen test runs per arm (balanced between A and B); seed 20261021. Each simulated run uses a fresh identity
  (so budgets measure within-run leakage; Sybil is not modelled).
- Reported as "simulated (production meter code)"; 50% means this attacker could not tell A from B.

## Evaluation 2: utility (planted bypass)
- 12 candidate families F1-F12; Blue blocks all of them except one planted bypass family P (uniform at random per trial). Red also knows one
  family K that Blue blocks (calibration).
- Scripted adaptive Red (Kerckhoffs: knows B, thresholds, budgets): per run, a calibration batch of 10 K probes (no read), then group tests
  (3 candidate families x 3 probes + 1 K probe per batch), decode each state by simulating the meter for the hypotheses {hit=0.3, miss=0.0},
  then single-family tests inside a hit group. Inconsistent states (noise) are re-tested with new probe text. Rolls to a new run after 3 reads.
- Exact arm: one probe per family in a fixed order until one passes. None arm: random guess.
- Query limit 150 probes per trial; read budgets as above; 300 trials per arm; seed 20261022. Success = declared P equals planted P.
- Reported per arm: success rate within the limit, median and mean queries (successes), median reads.

## Not covered by these evaluations
Mock backend only, no real model, no timing channel, no Sybil identities, no attacker who changes probe content adaptively beyond the scripted Red.
