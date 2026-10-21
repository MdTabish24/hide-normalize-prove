# Final report: what is measured, and the open PROBLEMS (no solutions on purpose)

> **STATUS:** P5, P11 and section 4 reflect the real-model runs of 2026-10-21 (PARAMS v4 and v5). The other problems are unchanged.
> Every real-model cell is one run; see the limits in P5 and P11.

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
- Constraints: Red-visible replies stay byte-identical; opt-in; no special hardware.

### P2. The noisy final report leaks structure
- The report range has width 12 around the Blue-allowed count and is clamped to [0, total]: a count of 0 always gives [0,12] and 16 always gives [4,16] (extreme counts identifiable).
- Averaging over fresh runs lowers Red's error (mean absolute error 3.71 at K=1 to 2.56 at K=30, run mode, S); probe-set-keyed mode does not improve with K (3.80). Not formal differential privacy.
- Unknown: the effect with up to 100 attempts per run (the evaluation used 16), and with an attacker who rewords probes.

### P3. Blue's service sees every Red prompt in plaintext (not tested)
- The gateway sends the Blue service the prompt AND the decrypted rule on every request; the rule is a casefolded substring match. The Blue team (people) is not given access, but no test shows what the Blue side can observe or retain.
- The problem statement requires that Red's payloads are not observable by Blue until the test ends.

### P4. The default policy still leaks under load
`bucket_hard` is the default and fails boundary/overflow/deadline cohorts (98-100%) and the flood (76%). The better profile (`window_hard + continue + AUDIT_BATCH=50`, `docker-compose.recommended.yml`) is opt-in.
Costs of continue: background compute is bounded by a hard maximum of 4W; with a real model it spends tokens.

### P5. Real-model evidence: now several small tests; remaining gaps
All R, DeepSeek `deepseek-flash`, localhost processes, audit ON with `AUDIT_BATCH=50`, 95% Wilson, README thresholds; files in `eval/output/real_timing/` and `eval/output/real_suite/`.
- Ordinary cohort (60 train + 60 unseen test runs per cell): `raw` 100.0% (94.0-100%) in both seeds (LEAKED); `window_hard + continue` (W = 3 s) 33.3% (22.7-45.9%) and 43.3% (31.6-55.9%), both "no leak found", 0 late, 0 cancelled.
- Long-answer cohort `real_long` (40 + 40 runs; the real-model analogue of the attacker controlling compute time, `max_tokens` 512): `raw` 95.0% (83.5-98.6%) LEAKED; `window_hard + continue` 45.0% (30.7-60.2%) BOUNDED LEAK
  (upper bound above 60%). 105 of 240 allowed attempts finished after the 2.4 s deadline (late) and 1 was cancelled; so continue kept long answers alive, and the signal dropped from 95% to 45%.
- Anomaly, not resolved: both ordinary `window_continue` cells are BELOW chance on the unseen runs (33.3% and 43.3%) while their train accuracy was 78% and 73% (gaps +45 and +30 points; mock window cells had gaps of +5 to +17).
  The tree learns a pattern in the train runs that does not transfer. This is not evidence of a leak, but a verdict from the upper bound alone ignores a two-sided deviation, and the cause was not investigated (per-run samples of the window cells were not saved).
- Hosted cache: our own latency observable only. Ordinary `raw`: allowed-probe latencies show no sign of bimodality (bimodality coefficient 0.378, median 1.036 s) and the median latency of the 1st, 2nd and 3rd repetition of the same prompt was 1.05, 1.025 and 1.023 s
  (no sign of a hosted-cache speed-up on repeats; we send a fresh random 64-hex system prefix). The `real_long` coefficient (0.898, "possibly bimodal") comes from mixing short and long answers in the probe design, not from a cache. This says nothing about the provider's internals.
- Docker with the real model (30 requests through the operator proxy, W = 3 s): isolation 11 of 11 from inside `red-client`; reply identical in 30 of 30 requests (one status/body); release 3.002-3.511 s (median 3.008); 20 outputs from the DeepSeek backend; 0 cancelled; audit VALID.
- Audit in every real cell: all runs valid (120/120, 120/120, 80/80, 80/80), no dead server.
- Still open: one run per cell; no flood with the real model (thousands of provider calls per cell; the flood is a gateway property measured with the mock); no boundary/deadline cohorts as such; N = 40-60 test runs; the hosted cache is not under our control.

### P6. Audit limits
- 247 of 2000 runs were INVALID in one `window_continue` repeat (delivery failure, no integrity failure); batching removed the backlog in the flood test, but the 2000-run matrix has not been re-run with batching.
- The checkpoint is local (no independent witness) and events dropped before collection are undetectable.

### P7. The feedback meter is a structural trade-off (S)
With no noise a targeted attacker tells rule A from B perfectly (100%) and finds a planted bypass in 100% of trials, needing a median of 60 probes vs 7 with exact feedback. Noise q=0.15 gives 89% leak and 68.7% success. Off by default.

### P8. Evaluation limits
Mock model; timings scaled by 0.1 (fixed overheads not scaled, which likely inflates differences); one laptop (Windows host processes); most cells are one run; intervals are wide; "late/timeout rate" printed values slightly above 100% in some cells
(counting quirk, unverified); timing tests fail under a loaded machine (Chrome, Defender) and pass when idle; nothing was weakened.

### P9. Identities
Exactly three role tokens exist (red, blue, evaluator); multiple Red identities and Sybil behaviour are not modelled.

### P10. Out of scope
Kernel/container escape, hardware and shared-GPU side channels, a compromised gateway or collector.

### P11. The fixed release time can slip under real long outputs (new)
- `window_hard + continue`, `real_long` cohort (W = 3 s): release time median 3.017 s and p95 3.139 s, but p99 5.719 s and maximum 6.020 s (about 2 x W) over 480 requests; 1 attempt cancelled. Ordinary cells: maximum 3.517 s (p99 3.319 s) and 3.511 s in the Docker check.
- The design promises one fixed release time for every request. These slips exceed it; per-request release data for the window cells was not saved, so which requests slipped and why is unknown. The late long answers (105 of 240 allowed) were NOT cancelled, as intended.
- Unknown: whether the slip comes from the event loop being blocked (several synchronous store/vault/audit operations run on the loop thread), from in-flight accounting of continuing background tasks, from the laptop, or from the real provider path.

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
Total suite time 28.2 minutes; about 1300 provider calls.
