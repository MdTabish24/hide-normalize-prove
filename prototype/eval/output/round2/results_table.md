# Round 2 timing matrix: live gateway, mock model, local run

Status: **complete**. Audit delivery: **ON**. Scale factor 0.1 (buckets 0.3 / 0.6 / 0.9 s; window_hard W = 0.9 s, deadline D = 0.72 s). Seed 7391, concurrency 8, platform Windows host processes, Python 3.11.15.

Unseen-run accuracy of the predeclared depth-3 decision tree (same attacker as Round 1). 50% = this attacker could not tell A from B; it is not proof of no leak. Old = Round 1 matrix (audit OFF, before the Phase 1 release changes).

| Cohort | Policy | Unseen accuracy (95% Wilson) | Train-test gap | Old (audit off) | Timeout rate of allowed | Mean latency | Added vs raw | Response shapes | Test runs |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| ordinary | raw | 98.5% (95.7%–99.5%) | +0.0% | 98.0% | 0.0% | 0.160 s | +0.000 s | 1 | 200 |
| boundary | raw | 100.0% (98.1%–100.0%) | +0.0% | 99.5% | 0.0% | 0.220 s | +0.000 s | 1 | 200 |
| overflow | raw | 99.0% (96.4%–99.7%) | +1.0% | 100.0% | 0.0% | 0.502 s | +0.000 s | 1 | 200 |
| ordinary | bucket | 56.5% (49.6%–63.2%) | +9.5% | 68.5% | 0.0% | 0.358 s | +0.198 s | 1 | 200 |
| boundary | bucket | 100.0% (98.1%–100.0%) | +0.0% | 98.5% | 0.0% | 0.442 s | +0.223 s | 1 | 200 |
| overflow | bucket | 100.0% (98.1%–100.0%) | +0.0% | 100.0% | 0.0% | 0.649 s | +0.147 s | 1 | 200 |
| ordinary | bucket_hard | 58.5% (51.6%–65.1%) | +12.5% | 59.5% | 0.3% | 0.387 s | +0.227 s | 1 | 200 |
| boundary | bucket_hard | 98.5% (95.7%–99.5%) | +1.5% | 100.0% | 0.4% | 0.499 s | +0.280 s | 1 | 200 |
| overflow | bucket_hard | 99.5% (97.2%–99.9%) | +0.5% | 100.0% | 72.1% | 0.654 s | +0.152 s | 1 | 200 |
| deadline_near | bucket_hard | 100.0% (98.1%–100.0%) | +0.0% | n/a | 1.9% | 0.621 s | n/a | 1 | 200 |
| deadline_far | bucket_hard | 98.5% (95.7%–99.5%) | +1.5% | n/a | 55.6% | 0.649 s | n/a | 1 | 200 |
| ordinary | window_hard | 52.0% (45.1%–58.8%) | +5.5% | n/a | 0.0% | 0.930 s | +0.770 s | 1 | 200 |
| boundary | window_hard | 58.0% (51.1%–64.6%) | +10.5% | n/a | 0.2% | 0.935 s | +0.715 s | 1 | 200 |
| overflow | window_hard | 54.5% (47.6%–61.3%) | +17.0% | n/a | 100.0% | 0.928 s | +0.426 s | 1 | 200 |
| deadline_near | window_hard | 49.0% (42.2%–55.9%) | +16.5% | n/a | 100.0% | 0.929 s | n/a | 1 | 200 |
| deadline_far | window_hard | 51.0% (44.1%–57.8%) | +17.5% | n/a | 100.1% | 0.923 s | n/a | 1 | 200 |

## Audit status after each policy

| Policy | Runs verified | VALID | Not valid (reasons) | Queue after drain |
|---|---:|---:|---|---|
| raw | 1200 | 1200 | - | [{'world': 0, 'pending_after_drain': 0, 'dead_letters': 0}, {'world': 1, 'pending_after_drain': 0, 'dead_letters': 0}] |
| bucket_hard | 2000 | 2000 | - | [{'world': 0, 'pending_after_drain': 0, 'dead_letters': 0}, {'world': 1, 'pending_after_drain': 0, 'dead_letters': 0}] |
| window_hard | 2000 | 2000 | - | [{'world': 0, 'pending_after_drain': 0, 'dead_letters': 0}, {'world': 1, 'pending_after_drain': 0, 'dead_letters': 0}] |

## Notes

- Timings are scaled down 10x (scale 0.1); fixed HTTP/SQLite/OS overhead is NOT scaled, which likely inflates timing differences relative to 3/6/9 s production buckets.
- Boundary and deadline cohorts use the EVAL_MODE sim_delay hook: the attacker controls compute time exactly (worst case, not a realistic Red).
- Overflow and deadline cohorts also contain a per-position fast/slow channel (A's slow slots are mango probes, B's are pineapple). Bucket policies cannot hide WHICH request is slow.
- Timeout rate = deadline/hard-timeout cancellations among Blue-allowed attempts, read by the trusted controller from the gateway DB.
- Response shapes = distinct (status, body length, header set) seen by Red across the cell; 1 means no error/shape oracle.
- Mean latency includes the policy's padding; added latency of a policy = its mean minus raw's mean for the same cohort.
- Windows host processes request 1 ms timer resolution (Phase 1). Results are not comparable 1:1 with Round 1 for that reason too.
- Merged: raw and bucket cells from the first run; bucket_hard and window_hard cells from a second run with identical seed/scale/audit settings (eval/output/round2b). Timeout rate above 100% in some window_hard cells indicates a counting quirk, not a real rate.
