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

---

# PARAMS (version 7: LOOP_OFFLOAD flood test, fixed BEFORE the cells are added or run; versions 1-6 are unchanged)

Question: does moving the gateway's SQLite store and audit-enqueue work off the event-loop thread (opt-in `LOOP_OFFLOAD=1`: worker threads, WAL, `synchronous=NORMAL`) lower the load-observer accuracy of the version-2 flood (mock model, scale 0.1, W = 0.9 s, audit ON with `AUDIT_BATCH=50`)?
Label: live gateway, mock model, local run. Everything else is exactly version 2/3: 12 flood workers, 6 observer probes, 100 train + 100 unseen test runs, depth-3 tree on `eval.run.features`, 95% Wilson, README thresholds.

| Cell | Policy | Extra environment | Seed |
|---|---|---|---|
| C1 `window_continue_batch50_s2` | window_hard + continue | `AUDIT_BATCH=50` | 20261101 (repeat of the version-3 cell with a new seed: shows run-to-run spread) |
| C2 `window_continue_offload` | window_hard + continue | `AUDIT_BATCH=50`, `LOOP_OFFLOAD=1` | 20261101 |
| C3 `bucket_hard_offload` | bucket_hard | `AUDIT_BATCH=50`, `LOOP_OFFLOAD=1` | 20261101 |

Decision rules (written before any run): C2 upper bound <= 60% -> "no leak found (descriptive)" for the flood with the flag on; C2 lower bound > 55% and accuracy >= 60% -> LEAKED, the flag did not remove the channel; otherwise BOUNDED.
"The flag helped" is claimed only if C2's interval lies entirely below C1's point estimate or C1 is LEAKED/BOUNDED and C2 is not worse; with overlapping intervals the result is reported as "no proven difference". C3 is reported on the same rules (the version-2 bucket_hard flood was 78% LEAKED, 76% with audit off).
Also reported per cell: audit outbox maximum, dead letters, throughput check (version-3 rule). One run per cell; no parameter is changed after seeing a result. Not covered: real model, Docker, the noisy-neighbour attacks 9/9b/9c.

---

# PARAMS (version 8: `RANGE_SEED_MODE=coarse`, fixed BEFORE it is measured; versions 1-7 are unchanged)

Question: does the opt-in `coarse` report range (same width 12, NOT clamped to [0, total], offset keyed by the probe set) stop Red from recovering the exact safe count, in particular at the extreme counts 0 and 16 of 16?
Simulation with production `generate_range` (`eval/coarse_report.py`), label "simulated (Monte Carlo)": total 16, 4000 draws per count for training and 4000 for testing, 17 counts, seed 20261102, uniform prior over counts, maximum-a-posteriori attacker that learns P(range | count) from the training draws.
Compared against the current `run` mode. Decision rule (written before running): the extreme-count leak is "closed" only if exact recovery at BOTH count 0 and count 16 is <= 25% in coarse mode and the true count is inside the range in 100% of draws (utility kept);
otherwise it is reported as reduced (lower than `run`) or not reduced. Also reported: overall exact recovery, and that repeating one probe set gives one output (no averaging). Not covered: a smarter attacker (several probe sets, rewording), total other than 16, real model.
The Red-visible report shape stays `{"status","safe_range"}` in a 64-byte envelope; ranges may contain values outside [0, total] by design (documented in FINAL_REPORT.md).

---

# PARAMS (version 9: attacks 9 and 9b with the version-7 flags, fixed BEFORE they are re-run; versions 1-8 are unchanged)

Question: do `LOOP_OFFLOAD=1`, `WINDOW_CONTINUE=1` and `AUDIT_BATCH=50` change the two shared-load measurements of the attack suite? Attack 9 = Blue's `/v1/defense` release times, 60 quiet vs 60 under a 32-worker Red burst; attack 9b = release slip with all host cores busy (60 requests idle, 60 loaded).
Run twice with the unchanged measurement code of `attack_suite.py`: (a) baseline flags, (b) `ATTACK_EXTRA_ENV={"LOOP_OFFLOAD":"1","WINDOW_CONTINUE":"1","AUDIT_BATCH":"50"}`, each policy of the attack (`bucket_hard`, `window_hard`); results in `eval/output/loop_offload/attack9_baseline.json` and `attack9_offload.json`. Label: live gateway, mock model, local run; the laptop must be idle.
Decision rule (before running): an attack counts as "no shift found" only if the KS test gives p >= 0.05 AND the under-load p95 is at most 1.5 times the quiet p95 (attack 9), or the share of requests released more than 20 ms late under load is at most 1.5 times the idle share (attack 9b); otherwise it stays as measured (LEAKED / BOUNDED LEAK). A lower number with the flags on that does not meet this rule is reported as "reduced", not as closed. One run per cell; no parameter is changed after seeing a result. Not covered: Docker (attack 9c), real model.

---

# PARAMS (version 10: final profile vs old default, with leave-one-out cells; fixed BEFORE the cells are added or run; versions 1-9 are unchanged)

Forensic finding that precedes it (PARAMS v7 forensic dumps, `eval/output/loop_offload/audit_forensic*.json`): in the flood cell the audit outbox of one world fills because, after one delivery timeout, every later attempt of the shipper's HTTP client fails with `PoolTimeout` for minutes while the collector answers a direct request in 8-54 ms. Fix added before this version: a fresh HTTP client after any failed delivery (`audit_forwarder.py`). Not yet shown to remove the backlog; the cells below measure it.
Final profile (all opt-in flags together): `window_hard` + `WINDOW_CONTINUE=1` + `AUDIT_BATCH=50` + `LOOP_OFFLOAD=1` + `BLUE_INLINE=1` + `RANGE_SEED_MODE=coarse`.
Label: live gateway, mock model, local run (scale 0.1, W = 0.9 s, audit ON); load observer of version 2 (12 flood workers, 6 observer probes, 100 train + 100 unseen test runs, depth-3 tree, 95% Wilson), seed 20261201 in every cell, one run per cell.

| Cell | Policy | Flags |
|---|---|---|
| F1 `final_profile` | window_hard + continue | AUDIT_BATCH=50, LOOP_OFFLOAD=1, BLUE_INLINE=1, RANGE_SEED_MODE=coarse |
| F2 `bucket_hard_old` | bucket_hard | none (the old default) |
| F3 `final_no_offload` | window_hard + continue | F1 without LOOP_OFFLOAD |
| F4 `final_no_batch` | window_hard + continue | F1 without AUDIT_BATCH |
| F5 `final_no_inline` | window_hard + continue | F1 without BLUE_INLINE |
| R1 `real_final` (needs the user's key; run separately) | window_hard + continue, real DeepSeek, W = 3 s | same flags as F1; 60 + 60 runs as in version 6 |

Also: attacks 4, 9 and 9b of `attack_suite.py` with `ATTACK_EXTRA_ENV` = the F1 flags and once without flags (output `attack_final_*.json`), one run each. Attack 7 is covered by the version-8 simulation, not re-run.
Decision rules (before any run): (1) "final profile is better than the old default" only if the F1 interval lies entirely below the F2 interval (upper bound of F1 < lower bound of F2) AND F1's audit throughput check passes (max sampled outbox < 10000, 0 pending after the 20 s drain, dead servers none); otherwise "no proven difference" or, if F1 is worse, "worse".
(2) A leave-one-out cell shows that a flag "contributes" only if removing it makes accuracy higher with non-overlapping intervals (lower bound of the cell > upper bound of F1) or makes the throughput check fail while F1 passes; otherwise "no proven contribution". Flags that do not act in the flood (`RANGE_SEED_MODE`) are judged by their own measurements (version 8); `BLUE_INLINE` also by its unit test.
(3) Attack 9/9b rules are those of version 9. Report every number, including audit outbox maximum and dead letters. No parameter is changed after seeing a result. Not covered: Docker, other seeds, more than one run per cell.

---

# PARAMS (version 11: Docker noisy neighbour (9c) and a container hardening check, fixed BEFORE they are run; versions 1-10 are unchanged)

Why: attack 9c was not re-run in version 10 and the "out of scope" row (attack 10) had no measured part at all. Both are tested as far as this prototype controls them. Label: local Docker stack (Docker Desktop), mock model.
(a) Attack 9c (`attack_suite.py --only 9c`, unchanged measurement code): Red floods from inside its own container (32 workers) while Blue's `/v1/defense` release times are measured from outside, 45 quiet vs 45 flooded, for `bucket_hard` and `window_hard`, with and without the CPU-pinned overlay (`docker-compose.pinned.yml`).
Run twice: flags OFF (`LOOP_OFFLOAD=0`, `BLUE_INLINE=0`; the compose default already has `WINDOW_CONTINUE=1` and `AUDIT_BATCH=50`) and flags ON (`LOOP_OFFLOAD=1`, `BLUE_INLINE=1`, exported in the launching environment); images rebuilt from the current code first. Output `eval/output/final_run/attack9c_flags_off.json` and `attack9c_flags_on.json`.
Rule: as in version 9: "no shift found" only if the KS test gives p >= 0.05 AND the flooded p95 is at most 1.5 times the quiet p95; otherwise it stays as measured (LEAKED / BOUNDED LEAK); a lower number that misses the rule is "reduced", not closed. One run per condition.
(b) `eval/hardening_check.py`: reads `docker inspect` of every running container and checks: not privileged, `cap_drop ALL`, `no-new-privileges`, read-only root filesystem, non-root user, no docker socket mount, no host PID/network mode, memory / PID / CPU limits, published ports only on 127.0.0.1; plus that the four service networks are `internal`. Reported as counts per check and the failing containers; nothing is changed by it.
Not tested and stated as residual risk: kernel and container-runtime exploits (escape), hypervisor or hardware side channels, shared-GPU or real KV-cache channels, a compromised gateway or collector. These need an environment and exploits this prototype does not have; the hardening check only shows how little the Red container is allowed to do.

---

# PARAMS (version 12: attack 9b repeated three times with the final flags, fixed BEFORE it is run; versions 1-11 are unchanged)

Why: in version 10 attack 9b under `window_hard` gave 32/60 late-over-20-ms requests under load without the final flags and 1/60 with them, but the version-9 ratio rule ("loaded share <= 1.5 x idle share") cannot be met when the idle share is 0, so the result could only be called "strongly reduced". That rule is degenerate for this attack; it is replaced here by the rule below, stated before any new run.
Run: `attack_suite.py --only 9b` three times in a row (separate processes, same machine, nothing else running) with `ATTACK_EXTRA_ENV` = `{"LOOP_OFFLOAD":"1","WINDOW_CONTINUE":"1","AUDIT_BATCH":"50","BLUE_INLINE":"1"}`, and once without flags for comparison; outputs `eval/output/final_run/attack9b_flags_r1..r3.json` and `attack9b_noflags.json`. All four runs are reported whatever they show; no run is dropped or repeated because of its result.
New rule (per run, policy `window_hard`): the share of requests released more than 20 ms late under load minus the same share when idle is at most 10 percentage points AND a two-sided Fisher exact test of loaded vs idle late counts (60 vs 60) gives p >= 0.05. "No shift found" only if ALL THREE flagged runs meet it; two of three = "reduced, not stable"; fewer = unchanged finding (LEAKED). The no-flags run is expected not to meet it (version 10: 0/60 idle vs 32/60 loaded).
Mock model, live gateway as local processes, one machine. Not covered: Docker, real model, other core counts. This changes the definition of "closed" for 9b only; the version-9 rule for attacks 9 and 9c is untouched.
Container pinning (`docker-compose.pinned.yml`) stays an opt-in overlay: it assumes at least 8 CPUs visible to Docker and would stop containers from starting on smaller hosts, so it is NOT made the default.

---

# PARAMS (version 13: attack 9c with a portable CPU plan for a 4-CPU host, fixed BEFORE it is run; versions 1-12 are unchanged)

Question: does the CPU plan of `pin_cpus.py` for a SMALL host (4 CPUs: Red alone on core 0, gateway alone on core 1, everything else on cores 2-3) keep the Docker noisy-neighbour shift of attack 9c away, so that the opt-in pinning does not need an 8-CPU host?
Run on this 12-CPU laptop with `ATTACK_PIN_NCPU=4` (the plan only uses cores 0-3; the other cores stay idle, so this is a layout test, not a test on a real 4-CPU machine). `attack_suite.py --only 9c`, unchanged measurement code of version 11 (45 quiet vs 45 flooded requests; both policies; unpinned and pinned conditions), twice: flags OFF (`LOOP_OFFLOAD=0`, `BLUE_INLINE=0`) and flags ON (`LOOP_OFFLOAD=1`, `BLUE_INLINE=1`).
Outputs `eval/output/final_run/attack9c_ncpu4_flags_off.json` and `attack9c_ncpu4_flags_on.json`. Rule: that of version 9 for the PINNED `window_hard` row of the flags-ON run: "no shift found" only if the KS test gives p >= 0.05 AND the flooded p95 is at most 1.5 times the quiet p95; otherwise the pinning plan is reported as not sufficient on a 4-CPU layout. The other three rows are reported as measured. One run per condition.
Not covered: a real small machine, other CPU counts, the real model. The plan is opt-in (`python pin_cpus.py --up`); the default compose file is unchanged.
