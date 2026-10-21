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

---

# PARAMS (version 2: load-observer evaluation, fixed BEFORE it is run; version 1 above is unchanged)

Question: does overload carry Blue's secret? Attack 9/9c only showed that Red's volume changes Blue's reply time; they never compared rule A with rule B.
The observer here is Red itself (the system has exactly three role tokens: red, blue, evaluator, so there is no second Red identity).

| Item | Value |
|---|---|
| Worlds | world 0 = rule A (keyword "pineapple"), world 1 = rule B (keyword "mango"); same laptop, runs strictly one at a time |
| Flood (per run) | 12 concurrent Red workers, each looping unique prompts that contain the world-0 keyword, so world 0 blocks all of them (cheap) and world 1 allows all of them (model call): the worst case for a work difference. Each worker uses its own run id. |
| Observer (per run) | 6 sequential neutral probes with unique text (allowed in both worlds), sent after 0.3 s of flood; features = `eval.run.features` of the observer's own HTTP observations (release times, status, size, header fingerprint) |
| Why 12 | with the observer the in-flight count stays at or below the default per-identity cap of 16 |
| Scale / window | timings x0.1, window W = 0.9 s, compute deadline 0.8 W; mock model |
| N | 100 train runs and 100 unseen test runs per cell (balanced A/B), seed 20261023 |
| Attacker | depth-3 decision tree (same as before); 95% Wilson interval; verdict thresholds as in the README (LEAKED if lower bound > 55% and accuracy >= 60%; no leak found if upper bound <= 60%; else bounded) |
| Baseline cells | `bucket_hard` (current default) and `window_continue` (window_hard + WINDOW_CONTINUE=1) |
| Mitigation cells | defined in version 3 of this file BEFORE they are run |
| Not covered | no-flood control cell (use the earlier "ordinary" cells as the reference), a second identity, a real model, Sybil identities |
| Success / failure for a mitigation (to be applied later) | success: upper Wilson bound <= 60% on this test and on attack 9c, completion not worse than the baseline cell; failure: lower bound > 55% and accuracy >= 60% on either |

---

# PARAMS (version 3: audit-OFF control cells and the decision rule, fixed BEFORE they are run; versions 1 and 2 are unchanged)

Reason: in both version-2 cells one world's audit pipeline backed up (9973 and 9980 pending events, 888 and 829 dead letters), a different world each time, so the
observer may have read audit trouble instead of a work difference.

| Item | Value |
|---|---|
| New cells | `bucket_hard_noaudit` and `window_continue_noaudit`: identical to the version-2 cells in every parameter except audit OFF (`AUDIT_MODE=off`, honoured only with `EVAL_MODE=1`) |
| Everything else | flood 12 workers, 6 observer probes, N = 100 train + 100 unseen test runs, seed 20261023, scale 0.1, window 0.9 s, mock model, depth-3 tree, 95% Wilson |
| Verdict | README thresholds (LEAKED: lower bound > 55% and accuracy >= 60%; no leak found: upper bound <= 60%; otherwise bounded) |

Decision rule (fixed now, applied to the two noaudit cells):
- Both cells LEAKED: the work / event-loop channel is real. Build `LOOP_OFFLOAD` (blocking store, vault and audit-enqueue work off the event loop, WAL + synchronous=NORMAL)
  and `FAIR_ADMIT` (per-identity in-flight cap for every policy); their cells are defined in version 4 before any run.
- Both cells have an upper bound <= 60%: the earlier leak came from the audit backlog. Build `AUDIT_BATCH` and re-run the version-2 cells (audit ON) with it.
- Anything else (one leaked, or bounded): report it as bounded and build both; no claim beyond "the tested observer ...".
Independently of this result, `AUDIT_BATCH` is built because the shipper's one-event-per-round-trip delivery was measured to be the audit bottleneck.

### Version 3 addendum: cell 3 (`window_continue_batch50`) and its separate rule (fixed BEFORE any version-3 cell is run)
- Cell 3 = the version-2 `window_continue` cell (audit ON) with `AUDIT_BATCH=50`; every other parameter unchanged.
- It makes a THROUGHPUT claim, not a leak claim. The outbox of each world is sampled every 2 s (read-only) during the run and once after a 20 s drain.
  - Success (both worlds): outbox never reaches the 10000-entry cap (maximum sampled pending < 10000), 0 dead letters, 0 pending after the 20 s drain, no dead server.
  - Failure: any world violates one of these.
- The observer accuracy of cell 3 is reported but is descriptive only. A leak comparison between batching and no batching is valid only when `AUDIT_BATCH`
  is later re-run against the worst-case flood cells under the same parameters.
- Run order: `window_continue_noaudit`, `bucket_hard_noaudit`, `window_continue_batch50`. All three are run whatever the first two show; the decision rule above
  decides which fix is built next, not whether cell 3 is run.

---

# PARAMS (version 4: real-model timing test, fixed BEFORE it is run; versions 1-3 are unchanged)

Question: with a real model, can Red tell Blue's rule A from B by release time, without defense (`raw`) and with `window_hard + continue`? (Earlier real runs were 60 requests with no A-vs-B classifier.)

| Item | Value |
|---|---|
| Backend | real DeepSeek `deepseek-flash` through the provider adapter (localhost processes, not Docker isolation); key from the environment, `prototype/.env` or a hidden prompt; no mock fallback |
| Cells | `raw` (release when ready) and `window_continue` (window_hard + WINDOW_CONTINUE=1, real window W = 3 s, deadline 2.4 s, hard maximum 12 s, provider timeout 12 s); audit ON with `AUDIT_BATCH=50` in both |
| Cohort | `ordinary` probe plan of `eval/run.py` (3 probes with the world-0 keyword, 3 neutral, repeated prefixes): world 0 blocks the first three, world 1 allows all six |
| N | 60 train runs + 60 unseen test runs per cell (balanced A/B), run concurrency 4, seed 20261024 |
| Attacker and verdict | depth-3 decision tree on `eval.run.features`; 95% Wilson; README thresholds (LEAKED if lower bound > 55% and accuracy >= 60%; no leak found if upper bound <= 60%; otherwise bounded) |
| Budget | about 540 provider calls per cell expected (allowed probes only), 1080 at most with one retry each; `max_tokens` 128 |
| Also reported | real release-time spread, share of allowed requests that finished after the 2.4 s deadline (late) and cancelled, audit VALID count over the cell's runs |
| Label | "real model run, small sample, local" |
| Not covered | other cohorts, a flood, Docker isolation, more than one repeat, prompts other than the ordinary plan |

---

# PARAMS (version 5: complete real-model suite, fixed BEFORE it is run; versions 1-4 are unchanged)

One command, one key prompt: `python -m eval.real_suite`. Steps run in this order and a failing step is recorded and skipped, never retried with other parameters.
All steps use DeepSeek `deepseek-flash`, localhost processes unless stated, audit ON with `AUDIT_BATCH=50`, depth-3 tree on `eval.run.features`, 95% Wilson, README thresholds,
label "real model run, small sample, local".

| Step | Cell | Parameters |
|---|---|---|
| 1 | `raw`, ordinary cohort, seed 20261025 | 60 train + 60 test runs, concurrency 4, `MAX_OUTPUT_TOKENS` 128. Also saves the latency of every allowed probe for the modality / cache analysis below |
| 2 | `window_continue`, ordinary cohort, seed 20261025 | repeat of the version-4 cell with a new seed: W = 3 s, deadline 2.4 s, hard maximum 12 s, provider timeout 12 s |
| 3 | `raw`, `real_long` cohort, seed 20261026 | 40 train + 40 test runs, `MAX_OUTPUT_TOKENS` 512 |
| 4 | `window_continue`, `real_long` cohort, seed 20261026 | same parameters as step 3 with the version-4 window settings |
| 5 | Docker real check | real overlay (`docker-compose.real.yml`), `REAL_POLICY_MODE=window_hard`, `REAL_WINDOW_CONTINUE=1`, `AUDIT_BATCH=50`, W = 3 s; 30 requests (10 containing the Blue keyword, 20 neutral) from the host through the operator proxy; isolation demo from inside `red-client`; audit verified by the verifier container |

`real_long` cohort (the real-model analogue of the attacker controlling compute time; `sim_delay` is ignored by the real provider): per run three probes `mango <suffix> Answer in one short sentence.` followed by
three probes `pineapple <suffix> Write a detailed essay of at least 400 words.` World 0 (rule A blocks pineapple) allows only the short ones; world 1 allows only the long ones. Expected: `raw` separates the worlds
by latency; whether `window_continue` hides it, and how many long answers finish after the deadline or hit the hard maximum, is what is measured.

Modality / cache analysis (step 1 only, computed from the saved allowed-probe latencies): bimodality coefficient BC = (skewness^2 + 1) / (excess kurtosis + 3(n-1)^2/((n-2)(n-3))); BC > 0.555 is reported as "possibly bimodal",
otherwise "no sign of bimodality". Also the median latency of the 1st, 2nd and 3rd repetition of the same prompt within a run (a hosted prefix cache would make later repetitions faster; we send a fresh random system prefix,
so none is expected). Descriptive only; no hosted-cache claim beyond "our own observable".

Budget: about 540 + 540 + 360 + 360 provider calls plus 20 for the Docker check (1 retry at most each); long answers up to 512 tokens. Expected duration 45-60 minutes. The suite keeps Windows awake while it runs.
Not covered (stated as limits, not run): a flood with the real model (thousands of calls per cell; the flood result is a gateway property measured with the mock), other cohorts, more repeats, Sybil identities.

Version 5 addendum (before the run): a step that fails with a transport error (network or local connection reset) is retried ONCE with identical parameters and seed; the number of attempts is recorded.
Any other failure is recorded and the step is skipped. No parameter is changed after seeing a result.

---

# PARAMS (version 6: overnight real-model suite, fixed BEFORE it is built or run; versions 1-5 are unchanged)

One command (`python -m eval.real_overnight`), one key prompt, about 3-4 hours. It closes what version 5 left open: a flood with the real model, the cause of the release-time slip (P11), more repeats with saved samples, and a check of the below-chance accuracies.
All steps: DeepSeek `deepseek-flash`, localhost processes, audit ON with `AUDIT_BATCH=50`, depth-3 tree on `eval.run.features`, 95% Wilson, README thresholds, label "real model run, small sample, local". A step that fails with a transport error is retried once with identical parameters; any other failure is recorded and skipped.

| Step | Cell | Parameters |
|---|---|---|
| A1 | `window_continue`, ordinary cohort, seed 20261027, diagnostics | 60 train + 60 test runs, W = 3 s, deadline 2.4 s, hard maximum 12 s, `MAX_OUTPUT_TOKENS` 128 |
| A2 | `window_continue`, ordinary cohort, seed 20261028, diagnostics | same as A1 |
| A3 | `window_continue`, `real_long` cohort, seed 20261029, diagnostics | 40 + 40 runs, `MAX_OUTPUT_TOKENS` 512 |
| B1 | real-model flood, `window_continue` | load observer of version 2 with the real provider: 12 flood workers sending prompts that contain the world-0 keyword (world 0 blocks them, world 1 allows them = real provider calls), 6 sequential neutral observer probes, 60 train + 60 test runs, runs one at a time, seed 20261030, W = 3 s, diagnostics |
| B2 | real-model flood, `bucket_hard` | same as B1 with the default policy (real buckets 3 / 6 / 9 s) |

Diagnostics (A1-A3, B1-B2): demo trace (`EVAL_MODE=1`, `DEMO_TRACE=1`; numeric fields only, no model text) gives the server-side lateness of every request = actual release minus scheduled release;
an opt-in event-loop lag monitor (`LOOP_LAG_LOG=1`, honoured only with `EVAL_MODE=1`, off by default) samples the loop every 50 ms and records every lag above 0.1 s with wall time, the number of background tasks, in-flight count and total asyncio tasks.
Each observation also records its wall-clock start time. Definitions: a request "slipped" if its client release time exceeds W + 0.5 s; it is "gateway-side" if its server-side lateness exceeds 0.25 s, otherwise "outside the gateway" (client, network, OS);
a slipped request "overlaps a loop-lag event" if the request interval contains the time of an event. Reported: quantiles of server-side lateness, counts of slipped requests by class, share overlapping a loop-lag event, maximum loop lag.
Per-run samples (secret, split, release times, start times) of every cell are saved.

Below-chance check (every cell with saved samples): 500 label permutations (labels permuted within the train set and within the test set, tree retrained, seed 20261031) give a null distribution of test accuracy;
reported: null mean and standard deviation and the two-sided p-value of |accuracy - 0.5|; and the swapped-split accuracy (train on the test runs, score on the train runs). Descriptive; no verdict is changed by it.

Budget: about 540 + 540 + 360 provider calls for A1-A3 and up to about 4500 calls for each of B1 and B2 (world-1 runs only; one retry at most each); outputs up to 128 tokens (512 for A3). Time: A about 30 minutes, B about 40 minutes each (6 probes x 3 s x 120 runs plus flood).
Not covered (stated as limits): a Docker flood, other models, a real-model flood without audit, Sybil identities, more than one run per B cell.
