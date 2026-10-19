# EVIDENCE: Hide, Normalize, Prove (Round 2)

Generated 2026-10-19T03:52:37+00:00 by `python run_all_evidence.py`. Every row comes from a saved file listed under Sources; missing evidence is NOT RUN.

Result key: PASS/FAIL = a functional check. BLOCKED = the attack failed in this test. BOUNDED LEAK = no clear leak for this attacker and sample (95% interval includes chance); residual risk remains. LEAKED = measurable leak. NOT COVERED = outside scope. NOT RUN = not executed.

Counts: BLOCKED 2, BOUNDED LEAK 1, LEAKED 4, NOT RUN 7, PASS 8

| Test | Policy | Result | Key number | Label | Audit mode |
|---|---|---|---|---|---|
| Test suite (host, Windows) | - | NOT RUN | no saved evidence | live gateway, mock model, local run | - |
| Test suite (inside Docker image) | - | PASS | 39 passed, 0 failed | local Docker stack (Docker Desktop) | mixed fixtures |
| docker compose ps | - | PASS | 6 services up: audit-collector, blue-defense, gateway, model-mock, operator-proxy, red-client | local Docker stack (Docker Desktop) | - |
| Isolation demo inside red-client | - | PASS | 11/11 checks PASS | local Docker stack (Docker Desktop) | - |
| Extra probes (audit/proxy from Red; egress of gateway, Blue, model) | - | PASS | 10 blocked, 0 reachable | local Docker stack (Docker Desktop) | - |
| Audit verifier on a finished run (no-network container) | - | PASS | VALID | local Docker stack (Docker Desktop) | on |
| Audit tamper demo (7 tamper cases on copies) | - | BLOCKED | unmodified VALID=True; 7/7 tampered copies INVALID | local Docker stack (Docker Desktop) | on |
| Timing A-vs-B: ordinary | raw | LEAKED | 98.5% (95% 95.7%-99.5%); timeouts 0% of allowed; mean latency 0.16 s; Round 1 audit-off 98.0% | live gateway, mock model, local run; scale 0.1, N=200 unseen runs/cell | on |
| Timing A-vs-B: boundary | raw | LEAKED | 100.0% (95% 98.1%-100.0%); timeouts 0% of allowed; mean latency 0.22 s; Round 1 audit-off 99.5% | live gateway, mock model, local run; scale 0.1, N=200 unseen runs/cell | on |
| Timing A-vs-B: overflow | raw | LEAKED | 99.0% (95% 96.4%-99.7%); timeouts 0% of allowed; mean latency 0.50 s; Round 1 audit-off 100.0% | live gateway, mock model, local run; scale 0.1, N=200 unseen runs/cell | on |
| Audit under matrix load (verifier on every run) | raw | PASS | 1200/1200 runs VALID; dead letters 0 | live gateway, mock model, local run | on |
| Timing matrix status | - | NOT RUN | artifact status: in_progress | live gateway, mock model, local run | - |
| Attack suite | - | NOT RUN | no saved evidence | live gateway, mock model, local run | - |
| Feedback analysis (Phase 5) | - | NOT RUN | no complete saved result | simulated (Monte Carlo) | - |
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
- `prototype/eval/output/round2/results.json`
- `prototype/evidence/audit-docker.txt`
- `prototype/evidence/compose-ps.txt`
- `prototype/evidence/isolation-extra.txt`
- `prototype/evidence/isolation.txt`
- `prototype/evidence/tests-in-docker.txt`
- `real_results.json`
