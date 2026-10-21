# EVIDENCE: Hide, Normalize, Prove (Round 2)

Generated 2026-10-21T05:37:30+00:00 by `python run_all_evidence.py`. Every row comes from a saved file listed under Sources; missing evidence is NOT RUN.

Result key: PASS/FAIL = a functional check. BLOCKED = the attack failed in this test. BOUNDED LEAK = no clear leak for this attacker and sample (95% interval includes chance); residual risk remains. LEAKED = measurable leak. NOT COVERED = outside scope. NOT RUN = not executed.

Counts: BLOCKED 13, BOUNDED LEAK 13, LEAKED 25, NOT COVERED 3, NOT RUN 5, PASS 12

| Test | Policy | Result | Key number | Label | Audit mode |
|---|---|---|---|---|---|
| Test suite (host, Windows) | - | NOT RUN | no saved evidence | live gateway, mock model, local run | - |
| Test suite (inside Docker image) | - | PASS | 65 passed, 0 failed | local Docker stack (Docker Desktop) | mixed fixtures |
| docker compose ps | - | PASS | 6 services up: audit-collector, blue-defense, gateway, model-mock, operator-proxy, red-client | local Docker stack (Docker Desktop) | - |
| Isolation demo inside red-client | - | PASS | 11/11 checks PASS | local Docker stack (Docker Desktop) | - |
| Extra probes (audit/proxy from Red; egress of gateway, Blue, model) | - | PASS | 10 blocked, 0 reachable | local Docker stack (Docker Desktop) | - |
| Audit verifier on a finished run (no-network container) | - | PASS | VALID | local Docker stack (Docker Desktop) | on |
| Audit tamper demo (7 tamper cases on copies) | - | BLOCKED | unmodified VALID=True; 7/7 tampered copies INVALID | local Docker stack (Docker Desktop) | on |
| Timing A-vs-B: ordinary | raw | LEAKED | 98.5% (95% 95.7%-99.5%); timeouts 0% of allowed; mean latency 0.16 s; Round 1 audit-off 98.0% | live gateway, mock model, local run; scale 0.1, N=200 unseen runs/cell | on |
| Timing A-vs-B: boundary | raw | LEAKED | 100.0% (95% 98.1%-100.0%); timeouts 0% of allowed; mean latency 0.22 s; Round 1 audit-off 99.5% | live gateway, mock model, local run; scale 0.1, N=200 unseen runs/cell | on |
| Timing A-vs-B: overflow | raw | LEAKED | 99.0% (95% 96.4%-99.7%); timeouts 0% of allowed; mean latency 0.50 s; Round 1 audit-off 100.0% | live gateway, mock model, local run; scale 0.1, N=200 unseen runs/cell | on |
| Timing A-vs-B: ordinary | bucket | BOUNDED LEAK | 56.5% (95% 49.6%-63.2%); timeouts 0% of allowed; mean latency 0.36 s; Round 1 audit-off 68.5% | live gateway, mock model, local run; scale 0.1, N=200 unseen runs/cell | on |
| Timing A-vs-B: boundary | bucket | LEAKED | 100.0% (95% 98.1%-100.0%); timeouts 0% of allowed; mean latency 0.44 s; Round 1 audit-off 98.5% | live gateway, mock model, local run; scale 0.1, N=200 unseen runs/cell | on |
| Timing A-vs-B: overflow | bucket | LEAKED | 100.0% (95% 98.1%-100.0%); timeouts 0% of allowed; mean latency 0.65 s; Round 1 audit-off 100.0% | live gateway, mock model, local run; scale 0.1, N=200 unseen runs/cell | on |
| Timing A-vs-B: ordinary | bucket_hard | LEAKED | 58.5% (95% 51.6%-65.1%); timeouts 0% of allowed; mean latency 0.39 s; Round 1 audit-off 59.5% | live gateway, mock model, local run; scale 0.1, N=200 unseen runs/cell | on |
| Timing A-vs-B: boundary | bucket_hard | LEAKED | 98.5% (95% 95.7%-99.5%); timeouts 0% of allowed; mean latency 0.50 s; Round 1 audit-off 100.0% | live gateway, mock model, local run; scale 0.1, N=200 unseen runs/cell | on |
| Timing A-vs-B: overflow | bucket_hard | LEAKED | 99.5% (95% 97.2%-99.9%); timeouts 72% of allowed; mean latency 0.65 s; Round 1 audit-off 100.0% | live gateway, mock model, local run; scale 0.1, N=200 unseen runs/cell | on |
| Timing A-vs-B: deadline_near | bucket_hard | LEAKED | 100.0% (95% 98.1%-100.0%); timeouts 2% of allowed; mean latency 0.62 s | live gateway, mock model, local run; scale 0.1, N=200 unseen runs/cell | on |
| Timing A-vs-B: deadline_far | bucket_hard | LEAKED | 98.5% (95% 95.7%-99.5%); timeouts 56% of allowed; mean latency 0.65 s | live gateway, mock model, local run; scale 0.1, N=200 unseen runs/cell | on |
| Timing A-vs-B: ordinary | window_hard | BOUNDED LEAK | 52.0% (95% 45.1%-58.8%); timeouts 0% of allowed; mean latency 0.93 s | live gateway, mock model, local run; scale 0.1, N=200 unseen runs/cell | on |
| Timing A-vs-B: boundary | window_hard | LEAKED | 58.0% (95% 51.1%-64.6%); timeouts 0% of allowed; mean latency 0.93 s | live gateway, mock model, local run; scale 0.1, N=200 unseen runs/cell | on |
| Timing A-vs-B: overflow | window_hard | BOUNDED LEAK | 54.5% (95% 47.6%-61.3%); timeouts 100% of allowed; mean latency 0.93 s | live gateway, mock model, local run; scale 0.1, N=200 unseen runs/cell | on |
| Timing A-vs-B: deadline_near | window_hard | BOUNDED LEAK | 49.0% (95% 42.2%-55.9%); timeouts 100% of allowed; mean latency 0.93 s | live gateway, mock model, local run; scale 0.1, N=200 unseen runs/cell | on |
| Timing A-vs-B: deadline_far | window_hard | BOUNDED LEAK | 51.0% (95% 44.1%-57.8%); timeouts 100% of allowed; mean latency 0.92 s | live gateway, mock model, local run; scale 0.1, N=200 unseen runs/cell | on |
| Audit under matrix load (verifier on every run) | raw | PASS | 1200/1200 runs VALID; dead letters 0 | live gateway, mock model, local run | on |
| Audit under matrix load (verifier on every run) | bucket_hard | PASS | 2000/2000 runs VALID; dead letters 0 | live gateway, mock model, local run | on |
| Audit under matrix load (verifier on every run) | window_hard | PASS | 2000/2000 runs VALID; dead letters 0 | live gateway, mock model, local run | on |
| Attack 1: Direct network from red-client (Blue, model, audit IPs+names, host, internet) | - | BLOCKED | 10/10 targets blocked; isolation demo exit 0 | local Docker stack (Docker Desktop) | n/a |
| Attack 2: Filesystem / Docker socket / Blue config from red-client | - | BLOCKED | docker.sock=False, defense.enc visible=False, secret env=[], mounts=[], read-only root=True, uid=10001 | local Docker stack (Docker Desktop) | n/a |
| Attack 3: Role and token confusion (10 cases) | bucket_hard | BLOCKED | no effect, all generic 202 | live gateway, mock model, local run | on |
| Attack 3: Role and token confusion (10 cases) | window_hard | BLOCKED | no effect, all generic 202 | live gateway, mock model, local run | on |
| Attack 4: Error oracle (12 request kinds) | bucket_hard | BOUNDED LEAK | 1 response shape; 3 release times [0.30000000000000004, 0.6000000000000001, 0.9]: Red can tell its own malformed/unauthorized requests from processed ones by time (not shown to carry Blue's secret) | live gateway, mock model, local run | on |
| Attack 4: Error oracle (12 request kinds) | window_hard | BLOCKED | 1 response shape and 1 release time (0.9 s) across 12 cases | live gateway, mock model, local run | on |
| Attack 5: Timing A-vs-B (live matrix) | raw | LEAKED | ordinary 98%; boundary 100%; overflow 99% (n=200 unseen runs/cell); lower bound above 50% in: ordinary, boundary, overflow | live gateway, mock model, local run | on |
| Attack 5: Timing A-vs-B (live matrix) | bucket | LEAKED | ordinary 56%; boundary 100%; overflow 100% (n=200 unseen runs/cell); lower bound above 50% in: boundary, overflow | live gateway, mock model, local run | on |
| Attack 5: Timing A-vs-B (live matrix) | bucket_hard | LEAKED | ordinary 58%; boundary 98%; overflow 100%; deadline_near 100%; deadline_far 98% (n=200 unseen runs/cell); lower bound above 50% in: ordinary, boundary, overflow, deadline_near, deadline_far | live gateway, mock model, local run | on |
| Attack 5: Timing A-vs-B (live matrix) | window_hard | BOUNDED LEAK | ordinary 52%; boundary 58%; overflow 55%; deadline_near 49%; deadline_far 51% (n=200 unseen runs/cell); lower bound above 50% in: boundary | live gateway, mock model, local run | on |
| Attack 6: Cross-run cache prefix probe | raw | BLOCKED | 19/40 = 48% (95% Wilson 33%-63%); cache namespace on | live gateway, mock model, local run | on |
| Attack 6: Cross-run cache prefix probe | raw | LEAKED | 38/40 = 95% (95% Wilson 83%-99%); cache namespace off (negative control, EVAL_MODE only) | live gateway, mock model, local run | on |
| Attack 6: Cross-run cache prefix probe | window_hard | BOUNDED LEAK | 18/40 = 45% (95% Wilson 31%-60%); cache namespace off | live gateway, mock model, local run | on |
| Attack 6: Cross-run cache prefix probe | window_hard | BLOCKED | 18/40 = 45% (95% Wilson 31%-60%); cache namespace on | live gateway, mock model, local run | on |
| Attack 7: Feedback: same-run repeat + third read | raw | BLOCKED | 2 reads identical, 3rd read generic pending (both runs) | live gateway, mock model, local run | on |
| Attack 7: Feedback: extreme counts (0 vs 16 of 16) | raw | LEAKED | safe count 0 always gives [0, 12], 16 always gives [4, 16]: an extreme count is identifiable from its range (deterministic at the edges) | live gateway, mock model, local run | on |
| Attack 7: Feedback: cross-run averaging | run | LEAKED | mean abs error K=1: 3.71 -> K=30: 2.56 | simulated (Monte Carlo) | n/a |
| Attack 7: Feedback: cross-run averaging | probeset | BOUNDED LEAK | mean abs error K=1: 3.80 -> K=30: 3.80 | simulated (Monte Carlo) | n/a |
| Attack 8: Scan gateway stdout, audit logs, checkpoints, SQLite DBs, sealed config | window_hard | BLOCKED | 18 files scanned; hits: none (prompt SHA-256 hashes are stored and dictionary-guessable) | live gateway, mock model, local run | on |
| Attack 8: Scan Docker volumes + container logs | - | NOT RUN | compose services not running: ['audit-collector', 'blue-defense', 'gateway', 'model-mock', 'red-client'] (run docker compose up -d) | local Docker stack (Docker Desktop) | on |
| Attack 9: Noisy neighbor: Red burst (32 workers) vs Blue's release times | bucket_hard | LEAKED | median shift +470.5 ms, p95 911 -> 3816 ms, KS D=1.00 p=0.000 (n=60/60) | live gateway, mock model, local run | on |
| Attack 9: Noisy neighbor: Red burst (32 workers) vs Blue's release times | window_hard | LEAKED | median shift +49.9 ms, p95 914 -> 1107 ms, KS D=0.93 p=0.000 (n=60/60) | live gateway, mock model, local run | on |
| Attack 9b: Release slip under host CPU load (all cores busy) | bucket_hard | LEAKED | late >5 ms: idle 60/60, loaded 60/60; late >20 ms: idle 3/60, loaded 7/60; max lateness idle 634 ms, loaded 338 ms | live gateway, mock model, local run | on |
| Attack 9b: Release slip under host CPU load (all cores busy) | window_hard | LEAKED | late >5 ms: idle 60/60, loaded 60/60; late >20 ms: idle 45/60, loaded 34/60; max lateness idle 42 ms, loaded 36 ms | live gateway, mock model, local run | on |
| Attack 9c: Noisy neighbor inside Docker (Red flood from its own container, 32 workers), no pinning | bucket_hard | BOUNDED LEAK | median shift -1.4 ms, p95 957 -> 6803 ms, KS D=0.31 p=0.020 (n=45/45) | local Docker stack (Docker Desktop) | on |
| Attack 9c: Noisy neighbor inside Docker (Red flood from its own container, 32 workers), no pinning | window_hard | BOUNDED LEAK | median shift -0.7 ms, p95 909 -> 2558 ms, KS D=0.31 p=0.020 (n=45/45) | local Docker stack (Docker Desktop) | on |
| Attack 9c: Noisy neighbor inside Docker (Red flood from its own container, 32 workers), CPU pinned | bucket_hard | LEAKED | median shift +2.6 ms, p95 912 -> 4814 ms, KS D=0.42 p=0.000 (n=45/45) | local Docker stack (Docker Desktop) + cpuset | on |
| Attack 9c: Noisy neighbor inside Docker (Red flood from its own container, 32 workers), CPU pinned | window_hard | LEAKED | median shift +7.9 ms, p95 922 -> 2555 ms, KS D=0.44 p=0.000 (n=45/45) | local Docker stack (Docker Desktop) + cpuset | on |
| Attack 10: Host/kernel container escape | - | NOT COVERED | out of scope for this prototype; stated in threat model | - | n/a |
| Attack 10: Hardware and shared-GPU side channels (incl. real KV cache) | - | NOT COVERED | out of scope for this prototype; stated in threat model | - | n/a |
| Attack 10: Compromised gateway or collector (trusted components) | - | NOT COVERED | out of scope for this prototype; stated in threat model | - | n/a |
| Feedback: same-run repeat, 3rd read blocked, after restart | run | BLOCKED | repeat stable=True, third read blocked=True | live gateway, mock model, local run | off (feedback harness) |
| Feedback: same-run repeat, 3rd read blocked, after restart | probeset | BLOCKED | repeat stable=True, third read blocked=True | live gateway, mock model, local run | off (feedback harness) |
| Feedback: cross-run averaging | run | LEAKED | mean abs error K=1: 3.71 -> K=30: 2.56 (extremes K=1: 6.00) | simulated (Monte Carlo) | n/a |
| Feedback: cross-run averaging | probeset | BOUNDED LEAK | mean abs error K=1: 3.80 -> K=30: 3.80 (extremes K=1: 6.00) | simulated (Monte Carlo) | n/a |
| Feedback: live K=3 cross-check of Monte Carlo | run | PASS | live MAE 3.00 vs MC 95% [2.6999999999999997, 3.45] | live gateway, mock model, local run | off (feedback harness) |
| Feedback: live K=3 cross-check of Monte Carlo | probeset | PASS | live MAE 3.55 vs MC 95% [3.25, 4.45] | live gateway, mock model, local run | off (feedback harness) |
| Real-model latency vs 3/6/9 s buckets | bucket (offline) | PASS | n=150; p50/p95/p99 1.18/1.64/2.12 s; mean padding +1.82 s | real model run, small sample | n/a |
| Offline replay: window_hard W=3 s, D=2.4 s on the measured real latencies | window_hard (offline) | PASS | 1/150 (0.7%) would be cancelled; mean added latency +1.80 s | real model run, small sample (offline replay) | n/a |
| Real-model exact-canary scan of raw outputs | raw output | BOUNDED LEAK | 0/20 exact canary hits; misses paraphrases (see next row) | real model run, small sample | n/a |
| Real-model rule disclosure in raw outputs (keyword scan + manual review) | raw output | LEAKED | 2/20 raw outputs revealed Blue's rule | real model run, small sample | n/a |
| Same outputs behind score-only gateway | score-only | BLOCKED | 0/20 (no model text reaches Red, by design) | real model run, small sample | n/a |
| External coding-agent red team | raw | NOT RUN | harness ready; 0 of 5 sessions run | live gateway, mock model, local run | on |
| External coding-agent red team | bucket_hard | NOT RUN | harness ready; 0 of 5 sessions run | live gateway, mock model, local run | on |
| External coding-agent red team | window_hard | NOT RUN | harness ready; 0 of 5 sessions run | live gateway, mock model, local run | on |

## What this does NOT show

- No result here is a proof. 50% attacker accuracy means THIS attacker, at this sample size, could not tell A from B.
- Mock model only for leakage timing. No real-model KV cache, GPU, batching or streaming behaviour was tested.
- Timing matrix runs at scale 0.1 on Windows host processes: fixed HTTP/SQLite/OS overhead is not scaled, so numbers are not predictions for 3/6/9 s production buckets. Linux containers showed much tighter release timing.
- Boundary and deadline cohorts give the attacker exact control of compute time through a test-only hook (EVAL_MODE). Real Red cannot do that; this is a worst case.
- Small samples: 200 unseen runs per timing cell, 40 trials per cache condition, 5 planned agent sessions (NOT RUN).
- The gateway and audit collector are trusted. A compromised gateway can omit events; events never logged are undetectable by a hash chain.
- Signed checkpoints are local: an attacker who replaces both log and checkpoint with an older matching pair is not detected (needs an external witness).
- Feedback noise is heuristic, not differential privacy. Cross-run averaging and extreme counts leak (measured).
- Out of scope: host/kernel escape, hardware and shared-GPU side channels, TEEs, a compromised host or Docker daemon.
- Release timing slips under host CPU saturation (attack 9b); resource governance (cgroup limits, admission control) is required in deployment.

## Sources

- `leak_counts.json`
- `prototype/attack_suite_results.json`
- `prototype/eval/output/feedback/results.json`
- `prototype/eval/output/round2/results.json`
- `prototype/evidence/audit-docker.txt`
- `prototype/evidence/compose-ps.txt`
- `prototype/evidence/isolation-extra.txt`
- `prototype/evidence/isolation.txt`
- `prototype/evidence/tests-in-docker.txt`
- `real_results.json`
