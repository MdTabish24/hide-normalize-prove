# Final report: what is measured, and the open PROBLEMS (no solutions on purpose)

> **STATUS:** P1, P4, P5, P6, P11 and section 4 reflect the real-model runs of 2026-10-21/22 (PARAMS v4, v5 and v6, incl. the overnight suite). The other problems are unchanged.
> Every real-model cell is one run (the ordinary window cell has four); see the limits in P5 and P11. Full generated tables: `REAL_MODEL_REPORT.md`.

Snapshot 2026-10-21. Purpose: give a solver (Opus) the exact problems, their mechanisms, the evidence and the constraints. Labels: **L** = live gateway, mock model, local run (timings x0.1);
**R** = real model run, small sample, local; **S** = simulated with production code. "50% = the tested attacker could not tell Blue's rule A from B" (not proof of no leak).
Sources: `FINDINGS.md`, `PROGRESS.md`, `PARAMS.md`, `eval/output/`, `attack_suite_results.json`, `OPUS_BRIEF.md` (how the code works).

## 0. The system in four lines
A gateway mediates Red, Blue and the model. Red always gets HTTP 202 + `{"status":"pending"}` (64 bytes) at a policy-fixed release time. Blue's keyword rule is sealed in the gateway and checked by a separate
blue-defense service. Every event goes to a signed hash-chain audit. A harness measures leakage by running the same test with rule A and rule B and training an attacker on what Red can observe.

## 1. What is established (summary)
Network/file/token isolation (10/10, 11/11 checks); error and shape oracle closed; time leak: raw 98.5-100% vs window_hard + continue 46-56% (L, N=200 per cell, two repeats, 0% cancelled);
cache guess 95% -> 45-48% with a per-run namespace (L); model-text rule disclosure behind the gateway 0/20 (offline) and 0/36 (R); audit tamper 7/7 detected; real 60-request run: release 3.007-3.131 s, 6/6 audit valid (R).

## 2. Open problems

### P1. Shared load can still carry the secret (worst case flood)
- Observation: an observer (Red itself; the system has only three role tokens) floods with prompts that world 0 blocks and world 1 allows and measures its own six probes. N=100 unseen runs per cell (L):
  `bucket_hard` 78.0% audit on / 76.0% audit off (LEAKED); `window_hard + continue` 73.0% audit on (LEAKED), 55.0% (45.2-64.4%) audit off (bounded), 47.0% (37.5-56.7%) with `AUDIT_BATCH=50`. One run per cell.
- Known mechanism of the confound: the audit shipper sent one event per HTTP round trip; under the flood the outbox hit its 10000 cap (829-888 dead letters) in ONE world per cell, so the classifier partly read audit trouble.
- Hypothesis (untested): every request does several synchronous SQLite commits, a vault file write and an audit enqueue on the single event-loop thread. A blocked request skips only one HTTP call to the model; the vault and store work is the same.
- Separate measurement: a Red burst (32 workers) raises Blue's reply tail. In Docker (Red container capped at 1 CPU) the median does not move but p95 goes from about 0.9 s to 2.5-6.8 s; with local processes the median shifts +470 ms (bucket_hard) and +50 ms (window_hard); per-service CPU pinning did not reduce it. This measured Red's VOLUME, not a secret.
- Unknown: whether blocked and allowed work differ enough to matter, whether 55% vs 47% is noise (single runs, wide intervals), behaviour with a real model, a no-flood control.
- Real-model flood (R, PARAMS v6, W = 3 s, audit ON with `AUDIT_BATCH=50`, 60 + 60 runs, about 84 flood requests per run, about 10,800 requests per cell, ~5,600 provider answers each):
  `window_hard + continue` 48.3% (36.2-60.7%) BOUNDED LEAK, train 83%; default `bucket_hard` 66.7% (54.1-77.3%) BOUNDED LEAK, train 78%. The two intervals overlap, so "continue is better" is NOT established; one run per cell; permutation p 0.351 and 0.134.
- Under the real flood the audit outbox of one world in the `bucket_hard` cell grew to 4146 and ended with 4090 events pending and 1305 dead letters (throughput check FAILED); the `window_continue` cell stayed at 25 with 0 dead (check passed). Both used `AUDIT_BATCH=50`, so batching alone did not prevent this in `bucket_hard`. Cause not tested.
- Constraints: Red-visible replies stay byte-identical; opt-in; no special hardware.

### P2. The noisy final report leaks structure
- The report range has width 12 around the Blue-allowed count and is clamped to [0, total]: a count of 0 always gives [0,12] and 16 always gives [4,16] (extreme counts identifiable).
- Averaging over fresh runs lowers Red's error (mean absolute error 3.71 at K=1 to 2.56 at K=30, run mode, S); probe-set-keyed mode does not improve with K (3.80). Not formal differential privacy.
- Unknown: the effect with up to 100 attempts per run (the evaluation used 16), and with an attacker who rewords probes.

### P3. Blue's service sees every Red prompt in plaintext (not tested)
- The gateway sends the Blue service the prompt AND the decrypted rule on every request; the rule is a casefolded substring match. The Blue team (people) is not given access, but no test shows what the Blue side can observe or retain.
- The problem statement requires that Red's payloads are not observable by Blue until the test ends.
- Read-only code check (2026-10-22): `blue.py` has no logging, no storage and no outbound call; it returns only `{allowed: bool}` (blue.py:21-25); uvicorn runs with `--no-access-log --log-level critical`; the container is read-only with `blue-net` (internal) as its only network (docker-compose.yml:119-124, 183-185); the Blue token is accepted only by `POST /v1/defense` (gateway.py:401), so it cannot read Red data. Residual risk that remains by design: the Blue SERVICE code receives the plaintext prompt in memory on every request, and the gateway audit chain carries a SHA-256 of each prompt. Not tested: what a malicious Blue service could retain or send (blue-net is internal, but no test tries it).

### P4. The default policy still leaks under load
`bucket_hard` is the default and fails boundary/overflow/deadline cohorts (98-100%) and the flood (76%, L; 66.7% bounded leak with the real model, R). The better profile (`window_hard + continue + AUDIT_BATCH=50`, `docker-compose.recommended.yml`) is opt-in.
Costs of continue: background compute is bounded by a hard maximum of 4W; with a real model it spends tokens.

### P5. Real-model evidence: now several small tests; remaining gaps
All R, DeepSeek `deepseek-flash`, localhost processes, audit ON with `AUDIT_BATCH=50`, 95% Wilson, README thresholds; files in `eval/output/real_timing/` and `eval/output/real_suite/`.
- Ordinary cohort (60 train + 60 unseen test runs per cell): `raw` 100.0% (94.0-100%) in both seeds (LEAKED); `window_hard + continue` (W = 3 s) 33.3% (22.7-45.9%) and 43.3% (31.6-55.9%) in v4/v5 and 41.7% (30.1-54.3%) and 46.7% (34.6-59.1%) in v6, all four "no leak found", 0 late, 0 cancelled, 0 of 720 requests slipped in each v6 cell.
- Long-answer cohort `real_long` (40 + 40 runs; the real-model analogue of the attacker controlling compute time, `max_tokens` 512): `raw` 95.0% (83.5-98.6%) LEAKED; `window_hard + continue` 45.0% (30.7-60.2%) BOUNDED LEAK in v5 and 57.5% (42.2-71.5%) BOUNDED LEAK in v6 (upper bound above 60% both times; the point estimate rose by 12.5 points between repeats, so one run of this cell is not stable). 105 of 240 allowed attempts finished after the 2.4 s deadline (late) and 1 was cancelled; so continue kept long answers alive, and the signal dropped from 95% to 45%.
- Anomaly, partly checked: the ordinary `window_continue` cells are at or BELOW chance on the unseen runs (33.3%, 43.3%, 41.7%, 46.7%) while train accuracy was 73-80% (gaps +30 to +45 points; mock window cells had gaps of +5 to +17).
  The tree learns a pattern in the train runs that does not transfer. v6 saved the samples and ran a label-permutation check (500 shuffles): p 0.23 and 0.673 (ordinary), 0.389 (real_long), 0.351 and 0.134 (floods) - none distinguishable from chance, but with 60 test runs this check has little power. The cause of the train/test gap is still unknown.
- Hosted cache: our own latency observable only. Ordinary `raw`: allowed-probe latencies show no sign of bimodality (bimodality coefficient 0.378, median 1.036 s) and the median latency of the 1st, 2nd and 3rd repetition of the same prompt was 1.05, 1.025 and 1.023 s
  (no sign of a hosted-cache speed-up on repeats; we send a fresh random 64-hex system prefix). The `real_long` coefficient (0.898, "possibly bimodal") comes from mixing short and long answers in the probe design, not from a cache. This says nothing about the provider's internals.
- Docker with the real model (30 requests through the operator proxy, W = 3 s): isolation 11 of 11 from inside `red-client`; reply identical in 30 of 30 requests (one status/body); release 3.002-3.511 s (median 3.008); 20 outputs from the DeepSeek backend; 0 cancelled; audit VALID.
- Audit in every non-flood real cell: all runs valid, no dead server. The two flood cells are listed in P1 (one of them failed the throughput check).
- Still open: one run per cell for the floods and for `bucket_hard`; no boundary/deadline cohorts as such; N = 40-60 test runs; the hosted cache is not under our control; the real runs used a laptop that went to sleep once mid-suite (see P8).

### P6. Audit limits
- 247 of 2000 runs were INVALID in one `window_continue` repeat (delivery failure, no integrity failure); batching removed the backlog in the mock flood test (L) and in the real `window_continue` flood (R), but NOT in the real `bucket_hard` flood (4090 pending, 1305 dead letters, one world); the 2000-run matrix has not been re-run with batching.
- In the real flood cells 16-17 of 1560 runs per cell had no evaluator record available and 1 run had a count mismatch; the per-request joins therefore cover 10,641 of 10,758 and 10,794 of 10,913 requests.
- The checkpoint is local (no independent witness) and events dropped before collection are undetectable.

### P7. The feedback meter is a structural trade-off (S)
With no noise a targeted attacker tells rule A from B perfectly (100%) and finds a planted bypass in 100% of trials, needing a median of 60 probes vs 7 with exact feedback. Noise q=0.15 gives 89% leak and 68.7% success. Off by default.

### P8. Evaluation limits
Mock model; timings scaled by 0.1 (fixed overheads not scaled, which likely inflates differences); one laptop (Windows host processes); most cells are one run; intervals are wide; "late/timeout rate" printed values slightly above 100% in some cells
(counting quirk, unverified); timing tests fail under a loaded machine (Chrome, Defender) and pass when idle; nothing was weakened.
The overnight suite took 597 minutes; the traffic itself was about 45 minutes per flood cell. The laptop slept after the first flood's traffic ended, which stretched that step to 482 minutes; the Windows keep-awake call did not prevent it. Sleep suspends only the test runner, but it was not independently verified that the first flood's results are unaffected beyond the saved timestamps.

### P9. Identities
Exactly three role tokens exist (red, blue, evaluator); multiple Red identities and Sybil behaviour are not modelled.

### P10. Out of scope
Kernel/container escape, hardware and shared-GPU side channels, a compromised gateway or collector.

### P11. The fixed release time can slip under real long outputs and under real floods
- `window_hard + continue`, `real_long` cohort (W = 3 s): release time median 3.017 s and p95 3.139 s, but p99 5.719 s and maximum 6.020 s (about 2 x W) over 480 requests; 1 attempt cancelled. Ordinary cells: maximum 3.517 s (p99 3.319 s) and 3.511 s in the Docker check.
- The design promises one fixed release time for every request. These slips exceed it; per-request release data for the window cells was not saved, so which requests slipped and why is unknown. The late long answers (105 of 240 allowed) were NOT cancelled, as intended.
- Diagnosis from v6 (per-request server-side lateness and an event-loop lag monitor were recorded):
  real flood `window_continue`: 21 of 720 observer requests slipped (more than W + 0.5 s); release median 3.066 s, p95 3.407 s, max 3.703 s; server-side lateness max 1.629 s (31 requests over 0.25 s, 5 over 1 s); 391 loop-lag events (max 3.151 s); ALL 21 slipped requests overlapped a loop-lag event.
  real flood default `bucket_hard`: 44 of 720 slipped; release median 3.12 s, p95 3.623 s, p99 8.572 s, max 9.909 s; server lateness max 1.801 s (83 over 0.25 s, 10 over 1 s); 639 loop-lag events (max 1.339 s); 35 of the 44 overlapped a loop-lag event (9 did not, cause not found).
  Non-flood v6 cells (A1-A3): 0 of 720, 0 of 720 and 0 of 480 slipped, so the `real_long` slip of v5 (max 6.020 s) did not repeat in v6 (max 3.077 s).
- This supports the event-loop hypothesis (stalls coincide with slips) but is correlation from one run per cell, not proof of cause; the stalls' source (store/vault/audit work on the loop thread, the provider path, or the laptop) was not isolated.

## 3. Claims allowed and not allowed
Allowed: "the tested attacker could not reliably distinguish" with the label, N and interval; the list of open problems above. Not allowed: "secure", "zero leakage", "formally private", "proves", or any claim about a hosted provider's internals.

## 4. Real-model results (RUN 2026-10-21; PARAMS v4 and v5; label "real model run, small sample, local")
| Cell | Cohort / seed | Red's A-vs-B accuracy (95% Wilson) | Train | Verdict | Release median / p95 / max | Late / cancelled | Audit |
|---|---|---:|---:|---|---|---|---|
| raw | ordinary, v4 seed | 100.0% (94.0-100%) | 100% | LEAKED | 0.957 / 1.433 / 1.841 s | n/a / 0 | 120/120 |
| window_hard + continue | ordinary, v4 seed | 33.3% (22.7-45.9%) | 78% | no leak found (below chance) | 3.033 / 3.082 / 3.297 s | 0 / 0 | 120/120 |
| raw | ordinary, 20261025 | 100.0% (94.0-100%) | 100% | LEAKED | 0.943 / 1.500 / 2.342 s | n/a / 0 | 120/120 |
| window_hard + continue | ordinary, 20261025 | 43.3% (31.6-55.9%) | 73% | no leak found (below chance) | 3.023 / 3.124 / 3.517 s | 0 / 0 | 120/120 |
| raw | real_long, 20261026 | 95.0% (83.5-98.6%) | 100% | LEAKED | 0.497 / 4.746 / 5.220 s | n/a / 0 | 80/80 |
| window_hard + continue | real_long, 20261026 | 45.0% (30.7-60.2%) | 93% | BOUNDED LEAK | 3.017 / 3.139 / 6.020 s | 105 / 1 | 80/80 |
| Docker real check | 30 requests | n/a | n/a | isolation 11/11, 30/30 identical replies | 3.008 median, 3.002-3.511 s | 0 cancelled | VALID |
Total v4/v5 suite time 28.2 minutes; about 1300 provider calls.

Overnight suite (PARAMS v6, 2026-10-21/22, `eval/output/real_overnight/`; window W = 3 s; floods use 60 + 60 runs):
| Step | Cohort | Red's A-vs-B accuracy (95% Wilson) | Train | Verdict | Release median / p95 / max | Slipped (> W + 0.5 s) | Audit |
|---|---|---:|---:|---|---|---|---|
| A1 window_hard + continue, seed 20261027 | ordinary | 41.7% (30.1-54.3%) | 80% | no leak found | 3.012 / n.a. / 3.225 s | 0 / 720 | 120/120 |
| A2 window_hard + continue, seed 20261028 | ordinary | 46.7% (34.6-59.1%) | 80% | no leak found | 3.044 / n.a. / 3.167 s | 0 / 720 | 120/120 |
| A3 window_hard + continue, seed 20261029 | real_long | 57.5% (42.2-71.5%) | 80% | BOUNDED LEAK | 3.025 / 3.049 / 3.077 s | 0 / 480 | 80/80 |
| B1 flood, window_hard + continue | flood observer | 48.3% (36.2-60.7%) | 83% | BOUNDED LEAK | 3.066 / 3.407 / 3.703 s | 21 / 720 | outbox max 25, 0 dead |
| B2 flood, bucket_hard (default) | flood observer | 66.7% (54.1-77.3%) | 78% | BOUNDED LEAK | 3.12 / 3.623 / 9.909 s | 44 / 720 | outbox max 4146, 1305 dead, 4090 pending (check failed) |
Suite time 597 minutes (see P8 for why). About 21,700 requests and about 11,300 provider answers were recorded in the two floods; every request is in `eval/output/real_overnight/requests/` (public) and the answers are in a git-ignored private folder.

## 5. Changes made after the overnight run (2026-10-22/23; all opt-in unless stated; measured parts are labelled)
- `BLUE_INLINE=1`: the keyword rule runs inside the gateway; the Blue service never receives Red's prompt (P3). Decisions identical to the service (unit test). Not default.
- Docker compose DEFAULT changed to `window_hard` + `WINDOW_CONTINUE=1` + `AUDIT_BATCH=50` (the code default and any local `.env` that sets `POLICY_MODE` are unchanged). The error-oracle attack 4 is BLOCKED under `window_hard` (L).
- `LOOP_OFFLOAD=1`: store and audit-queue SQLite work in worker threads, WAL and `synchronous=NORMAL` (durability trade-off: a crash can lose the last commits). 168 tests pass. Effect on the flood: see the PARAMS v7 cells below; not yet concluded when this section was written.
- `RANGE_SEED_MODE=coarse` (branch `report-coarse`, not merged): unclamped, probe-set-keyed range. Simulation (S, PARAMS v8): exact recovery at count 0 100% -> 24%, at count 16 100% -> 46.8% (rule needed <= 25% at both: NOT closed, reduced), overall 19.6% -> 13.3%, truth always inside the range. Ranges can lie outside [0, total]; the dashboard display was not checked.
- Gateway-internal time (L, mock, `eval/gateway_internal_time.py`, one idle run): blocked 62.1 ms vs allowed 78.1 ms median (audit off), 76.5 vs 97.4 ms (audit on): about 16-21 ms (+26%) more work for allowed requests. The about 1 s gap of the raw policy is the provider wait, which the fixed window hides.
- New problem (L, PARAMS v7 cell C1, `window_continue` + `AUDIT_BATCH=50`, seed 20261101): 57.0% (47.2-66.3%) BOUNDED LEAK and the audit outbox of one world reached its 10000 cap (throughput check FAILED), although the version-3 run of the same setting stayed at 24 and gave 47%. So `AUDIT_BATCH=50` does not reliably prevent the backlog; the earlier result was one run.
- Attack-suite tally (12 groups, mostly L): 5 fully stopped (network, files/socket, token confusion, cache with namespace, log scan); error oracle stopped only under `window_hard` (now the compose default); timing bounded; report extremes/averaging, noisy neighbour (9), CPU-load slip (9b) and Docker noisy neighbour (9c) still open; kernel/hardware/compromised-gateway out of scope. Not allowed to say "9 of 12 stopped".
- Timeline note: the deadline stated by the user (28 Oct) differs from another source (24 Oct 23:59 IST); to be checked on the Unstop page.
- PARAMS v7 result (L, mock, one run each, `eval/output/loop_offload/`): C1 `window_continue`+batch50 57.0% (47.2-66.3%) BOUNDED LEAK; C2 same + `LOOP_OFFLOAD=1` 45.0% (35.6-54.8%) NO LEAK FOUND. Intervals overlap: by the pre-registered rule "no proven difference". In BOTH cells one world's audit outbox reached its 10000 cap (963-1224 dead letters, throughput check FAILED), so `LOOP_OFFLOAD` did not remove the audit backlog. C3 (`bucket_hard`+offload) not run.
- PARAMS v9 result (L, mock, one run each): attack 9 (Red burst vs Blue release times): `bucket_hard` baseline LEAKED (median +649 ms, p95 928 -> 2278 ms); with `LOOP_OFFLOAD`+batch50 median -2.4 ms, p95 930 -> 955 ms, KS p 0.477 = "no shift found" by the rule. `window_hard` with the flags: still LEAKED (median +24.8 ms, p95 928 -> 1059 ms, KS p < 0.001); its baseline run crashed (ReadError), so no same-run comparison (an older run: +49.9 ms, p95 914 -> 1107 ms). Attack 9b (CPU load slip): not informative in this form: the idle run is already late by more than 5 ms for 60/60 requests, and with the flags the loaded run was LESS late than idle (4/60 vs 19/60 over 20 ms), which points to machine noise, not a fix. The laptop may not have been idle. The default policy (`window_hard`) still leaks under shared load.
- PARAMS v10 result so far (L, mock, one run per cell, `eval/output/final_run/`; the leave-one-out cells and the real-model cell were still running when this was written): ROOT CAUSE of the audit backlog found by forensic dumps: after one delivery timeout every later attempt of the shipper's single-connection HTTP client failed with `PoolTimeout` for minutes while the collector answered a direct request in 8-54 ms (exact cause inside httpx not reproduced in isolation). Fix: a fresh client after any failed delivery.
  Flood, final profile (`window_hard`+continue, `AUDIT_BATCH=50`, `LOOP_OFFLOAD=1`, `BLUE_INLINE=1`, coarse): 52.0% (42.3-61.5%) BOUNDED LEAK, audit outbox max 35/26, 0 dead letters, throughput check PASSED, release median 0.917 s, max 1.053 s. Old default `bucket_hard`: 85.0% (76.7-90.7%) LEAKED, outbox 1029, throughput check FAILED. By the pre-registered rule (interval below, throughput passed) the final profile IS better than the old default in this flood.
  Attack 9 with the final flags: `window_hard` median -0.0 ms, p95 909 -> 910 ms, KS p = 0.629 (rule: "no shift found"); the same attack without flags: median +84 ms, p95 911 -> 1811 ms, KS p < 0.001 (LEAKED). `bucket_hard` with flags: p95 unchanged but KS p < 0.001, still LEAKED by the test. Attack 9b `window_hard`: share of requests more than 20 ms late under load 32/60 without flags vs 1/60 with flags (idle 0/60 in both; the pre-registered ratio rule cannot be met when the idle share is 0, so this is reported as strongly reduced, not closed). Attack 4: `window_hard` BLOCKED, `bucket_hard` BOUNDED LEAK, same with and without flags. One run each, mock model, local; Docker (attack 9c) and the real model were not re-run at this point.
- PARAMS v10 leave-one-out cells (L, mock, flood, seed 20261201, one run each; the chain finished 2026-10-24 01:08): final profile 52.0% (42.3-61.5%), release max 1.053 s; without `LOOP_OFFLOAD` 60.0% (50.2-69.1%), release max 2.754 s; without `AUDIT_BATCH` 60.0% (50.2-69.1%), release max 11.286 s, audit outbox 287/453 (throughput check still passed); without `BLUE_INLINE` 58.0% (48.2-67.2%), release max 1.639 s; old default `bucket_hard` 85.0% (76.7-90.7%), release max 3.449 s.
  By the pre-registered rule NO single flag is shown to contribute (every leave-one-out interval overlaps the final profile's), so no flag can be ranked from this run. Descriptively all three removals have a higher point estimate (+6 to +8 points) and a longer worst-case release; the longest slip (11.3 s against a 0.9 s window) occurred without `AUDIT_BATCH`. One run per cell, mock model: this is not proof of any single flag's effect.
  Attack tally after PARAMS v10 (12 groups, mostly L, one run): 7 stopped or shown with no shift (network, files/socket, token confusion, cache, log scan, error oracle under `window_hard`, noisy neighbour 9 under `window_hard` with the final flags); timing (5) bounded; CPU-load slip (9b) strongly reduced, not closed; report extremes (7) reduced in simulation only; Docker noisy neighbour (9c) not re-run; 1 out of scope. The final-profile flood stays BOUNDED (upper bound 61.5%). (Superseded: the real-model run and PARAMS v11 are below.)
- PARAMS v10 real-model result (R, DeepSeek `deepseek-flash`, localhost, W = 3 s, flood with the final profile `window_hard`+continue, `AUDIT_BATCH=50`, `LOOP_OFFLOAD=1`, `BLUE_INLINE=1`, coarse; 60 + 60 runs, 83.5 flood requests per run, 10,741 requests recorded, 2026-10-24, 53.6 minutes, one run):
  Red's A-vs-B accuracy 58.3% (45.7-69.9%) BOUNDED LEAK (train 75%, permutation p 0.214); release median 3.008 s, p95 3.096 s, max 3.920 s; 3 of 720 observer requests slipped (more than W + 0.5 s), all 3 overlapped a loop-lag event; server-side lateness max 0.908 s; audit outbox max 42/36, 0 pending and 0 dead letters after the drain, throughput check PASSED, 0 cancelled.
  Compared with the earlier real floods (same method, one run each): `window_continue` without the final flags 48.3% (36.2-60.7%), 21/720 slipped, release max 3.703 s; default `bucket_hard` 66.7% (54.1-77.3%), 44/720 slipped, release max 9.909 s, audit check FAILED. The accuracy intervals all overlap, so the real model does NOT show that the final profile lowers Red's accuracy (58.3% is above 48.3% and below 66.7% with overlapping intervals). What is clearly better is the delivery side: fewer slipped requests (3/720 against 21 and 44), a shorter worst release (3.92 s against 9.91 s for the default) and an audit queue that stayed healthy in a real flood. The mock flood (52.0% against 85.0%) did show separated intervals; the real flood did not.
- PARAMS v11 result (local Docker stack, mock model, one run per condition, 45 quiet vs 45 flooded requests): attack 9c, Red flooding from inside its own container (`eval/output/final_run/attack9c_flags_off.json` and `attack9c_flags_on.json`).
  Default policy `window_hard`, no CPU pinning: flags OFF LEAKED (median +38.0 ms, p95 915 -> 2519 ms, KS p < 0.001); flags ON (`LOOP_OFFLOAD=1`, `BLUE_INLINE=1`) still LEAKED but reduced (median +1.1 ms, p95 912 -> 1697 ms = 1.86x, KS p = 0.005): the pre-registered rule for "no shift found" (KS p >= 0.05 AND p95 ratio <= 1.5) is NOT met.
  `window_hard` with the CPU-pinned overlay (`docker-compose.pinned.yml`): flags OFF LEAKED (median +111.6 ms, KS p < 0.001); flags ON median +0.5 ms, p95 911 -> 914 ms, KS p = 0.189: rule met, "no shift found". `bucket_hard` flags ON: no pinning KS p = 0.002 (LEAKED), pinned KS p = 0.790 with p95 unchanged (no shift found; flags OFF pinned had p95 912 -> 7308 ms).
  So the Docker noisy-neighbour channel is reduced by the final flags and closed in this run only when the Red container's CPU is pinned; it is NOT closed in the default (unpinned) configuration.
- PARAMS v11 hardening check (`eval/hardening_check.py`, `eval/output/hardening/results.json`, 5 running containers: gateway, blue-defense, model-mock, red-client, audit-collector; `operator-proxy` was not running because host port 8000 was busy): all 5 pass every check (not privileged, cap_drop ALL, no-new-privileges, read-only root filesystem, non-root user, no docker socket, no host PID/network, memory / PID / CPU limits, published ports only on 127.0.0.1) and the four service networks are `internal`. This shows how little the Red container may do; it does NOT test kernel or runtime exploits, hardware or shared-GPU side channels or a compromised gateway (stated as residual risk, not tested).
- Tally after PARAMS v11 (how to say it): of 11 tested attack groups, 7 stopped (network, files/socket, token confusion, cache, log scan, error oracle under `window_hard`, noisy neighbour 9 in the local-process test with the final flags) and 4 reduced or bounded (timing 5, CPU-load slip 9b, report extremes 7 in simulation only, Docker noisy neighbour 9c unless CPU-pinned); plus 1 group declared out of scope (kernel/runtime escape, hardware and GPU side channels, compromised gateway) with the hardening check above. Single runs, mock model, local.
