# Round 2 timing matrix: live gateway, mock model, local run

Status: **complete**. Audit delivery: **ON**. Scale factor 0.1 (buckets 0.3 / 0.6 / 0.9 s; window_hard W = 0.9 s, deadline D = 0.72 s). Seed 7391, concurrency 4, platform Windows host processes, Python 3.11.15.

Unseen-run accuracy of the predeclared depth-3 decision tree (same attacker as Round 1). 50% = this attacker could not tell A from B; it is not proof of no leak. Old = Round 1 matrix (audit OFF, before the Phase 1 release changes).

| Cohort | Policy | Unseen accuracy (95% Wilson) | Train-test gap | Old (audit off) | Timeout rate of allowed | Mean latency | Added vs raw | Response shapes | Test runs |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| ordinary | window_hard | 75.0% (30.1%–95.4%) | +25.0% | n/a | 0.0% | 0.917 s | n/a | 1 | 4 |
| boundary | window_hard | 75.0% (30.1%–95.4%) | +25.0% | n/a | 0.0% | 0.923 s | n/a | 1 | 4 |
| overflow | window_hard | 100.0% (51.0%–100.0%) | +0.0% | n/a | 0.0% | 0.929 s | n/a | 1 | 4 |
| deadline_near | window_hard | 75.0% (30.1%–95.4%) | +25.0% | n/a | 0.0% | 0.920 s | n/a | 1 | 4 |
| deadline_far | window_hard | 75.0% (30.1%–95.4%) | +25.0% | n/a | 0.0% | 0.931 s | n/a | 1 | 4 |

## Audit status after each policy

| Policy | Runs verified | VALID | Not valid (reasons) | Queue after drain |
|---|---:|---:|---|---|
| window_hard | 40 | 40 | - | [{'world': 0, 'pending_after_drain': 0, 'dead_letters': 0}, {'world': 1, 'pending_after_drain': 0, 'dead_letters': 0}] |

## Notes

- Timings are scaled down 10x (scale 0.1); fixed HTTP/SQLite/OS overhead is NOT scaled, which likely inflates timing differences relative to 3/6/9 s production buckets.
- Boundary and deadline cohorts use the EVAL_MODE sim_delay hook: the attacker controls compute time exactly (worst case, not a realistic Red).
- Overflow and deadline cohorts also contain a per-position fast/slow channel (A's slow slots are mango probes, B's are pineapple). Bucket policies cannot hide WHICH request is slow.
- Timeout rate = deadline/hard-timeout cancellations among Blue-allowed attempts, read by the trusted controller from the gateway DB.
- Response shapes = distinct (status, body length, header set) seen by Red across the cell; 1 means no error/shape oracle.
- Mean latency includes the policy's padding; added latency of a policy = its mean minus raw's mean for the same cohort.
- Windows host processes request 1 ms timer resolution (Phase 1). Results are not comparable 1:1 with Round 1 for that reason too.
