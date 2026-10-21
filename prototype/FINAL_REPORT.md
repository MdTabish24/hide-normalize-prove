# Final report: what is measured, and the open PROBLEMS (no solutions on purpose)

> **STATUS:** P5 and section 4 were rewritten after the real-model timing test (PARAMS v4) was RUN on 2026-10-21. The other problems are unchanged.
> One run per cell; see the limits listed in P5.

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

### P5. Real-model evidence: one small A-vs-B test exists; gaps remain
- RUN (PARAMS v4, R: DeepSeek `deepseek-flash`, localhost, ordinary cohort, 60 train + 60 unseen test runs per cell, seed 20261024, audit ON with `AUDIT_BATCH=50`):
  `raw` 100.0% (94.0-100%) LEAKED; `window_hard + continue` (W = 3 s) 33.3% (22.7-45.9%), verdict "no leak found" (README thresholds).
- Real latency: raw release times ran from 0.049 s (blocked) to 1.841 s (median 0.957, p95 1.433, p99 1.661 over all probes). Over 540 allowed attempts per cell none exceeded the 2.4 s deadline
  (0 late, 0 cancelled). The window cell released at 3.008-3.297 s (p99 3.126 s) with one reply shape; audit was 120 of 120 valid in both cells.
- Anomaly, not resolved: the window cell's test accuracy is BELOW chance (33.3%, the interval excludes 50%) while its train accuracy was 78.3% (gap +45 points; the mock window cells had gaps of +5 to +17).
  The tree learned a pattern in train noise that did not transfer. It is not evidence of a leak (nothing was distinguished above chance), but it shows overfitting at N=60 and that a verdict on the upper bound alone
  ignores a two-sided deviation. Not investigated (per-run samples were not saved).
- Still open: a single run per cell; ordinary cohort only (no boundary, overflow, deadline or flood cohort with the real model); localhost processes, not Docker isolation; N=60 test runs;
  the hosted prefix cache is not under our control (we send a fresh random 64-hex system prefix) and the modality of the latency distribution was NOT analysed.

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

## 3. Claims allowed and not allowed
Allowed: "the tested attacker could not reliably distinguish" with the label, N and interval; the list of open problems above. Not allowed: "secure", "zero leakage", "formally private", "proves", or any claim about a hosted provider's internals.

## 4. Real-model timing test (RUN 2026-10-21)
Parameters fixed in `PARAMS.md` v4 before the run; results in `eval/output/real_timing/{raw,window_continue}.json` (label "real model run, small sample, local"). About 1080 DeepSeek calls in total.
| Cell | Red's A-vs-B accuracy (95% Wilson) | Train accuracy | Verdict | Release time median / p95 / p99 / max | Late / cancelled | Audit |
|---|---:|---:|---|---|---|---|
| raw | 100.0% (94.0-100%) | 100% | LEAKED | 0.957 / 1.433 / 1.661 / 1.841 s | n/a / 0 | 120/120 valid |
| window_hard + continue, W = 3 s | 33.3% (22.7-45.9%) | 78.3% | no leak found (below chance, see P5) | 3.033 / 3.082 / 3.126 / 3.297 s | 0 / 0 | 120/120 valid |
