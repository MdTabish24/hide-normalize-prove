# Likely judge questions and honest answers (every number is in FINDINGS.md, PROGRESS.md or eval/output/)

Labels: **L** = live gateway, mock model, local run (timings x0.1); **R** = real model run, small sample. "50% = could not tell rule A from B".

**1. What is new compared with PyRIT, Garak, promptfoo, Inspect?**
Those tools run attacks; none of the ones we know isolates the Red, Blue and model sides from each other or measures leakage between them. Fixed-window response timing is a known idea, so we do not claim it as new. What we built is the combination: a mediating gateway, normalized replies, a signed audit chain, and a harness that runs the same test with Blue's rule A and rule B and reports what a tested attacker can tell. A systematic prior-art search has NOT been completed; we do not claim "first".

**2. Is it secure?**
No claim of that kind. We say "the tested attacker could not reliably distinguish". Where we measured a leak we show it.

**3. Why a mock model?**
It makes timing and caching controllable and repeatable. We also ran a real DeepSeek model (R): 60 requests, replies released at 3.007-3.131 s, one reply shape, Blue's rule in 0 of 36 outputs, audit 6 of 6 valid. That is a small sample and not a timing proof.

**4. What exactly leaked without your defense?**
Response time. Blocked prompts never reach the model so they return fast (about 0.05 s), allowed ones wait (about 0.27 s). Red's accuracy at telling A from B was 98.5-100% (L).

**5. What does your fix achieve?**
With window_hard + continue (opt-in) Red's accuracy over five cohorts was 46-56% in two repeats (L), with 0% cancelled. Plain window_hard hid the signal only by cancelling all long requests, so we do not count that as a win.

**6. What does it cost?**
Every reply waits for the full window (W). In the real run the model needed about 1-2 s and the reply came at about 3 s. Long requests are not cancelled but continue in the background (hard maximum 4W), which spends resources and, with a real model, tokens.

**7. What if Red floods the system?**
We tested a worst-case flood (L, N=100): the old default `bucket_hard` leaked (76-78% with or without audit). `window_hard + continue` gave 55% with audit off (bounded) and 47% with our batched audit delivery. One run per cell; this is not a proof. CPU contention (noisy neighbour) itself is NOT solved: Blue's reply tail grows under a Red burst, and CPU pinning did not help.

**8. Can Blue see Red's payloads?**
The Blue filter service receives each prompt in plaintext together with the rule, because it has to match it. The Blue team (people) is not given access, but we did not test whether the service leaks anything. A keyed-hash design for keyword filters is a proposal, not built. Real classifiers need plaintext, so this is a limit.

**9. Is the audit really tamper-evident?**
Hash chain with signed checkpoints: 7 of 7 tampered copies were detected, the untouched copy was valid. Limits: the checkpoint is local (no independent witness) and events dropped before collection cannot be detected.

**10. You had 247 invalid audit runs. Why?**
They were delivery failures, not tampering. Cause (measured): the shipper sent one event per HTTP round trip, which cannot keep up with a flood, so the outbox filled to its cap and entries expired. Opt-in `AUDIT_BATCH` removed it in the flood test (outbox never above 24 events, 0 dead letters). A 2000-run revalidation has NOT been run yet.

**11. What about the shared model cache?**
Mock model: a shared cache let Red guess Blue's prompt prefix 95% of the time; our per-run cache namespace brought it to 45-48%. The real provider's cache is outside our control; we only send a fresh random prefix and measure our own observables.

**12. What about many Red identities (Sybil)?**
The system has three role tokens, so multi-tenant Red is not modelled. Per-identity read budgets would not stop an attacker who mints identities: a documented limit.

**13. What is the feedback meter for, and does it leak?**
It gives Red a coarse hint (LOW, STABLE, IMPROVING) after batches of ten. Against a targeted attacker it still reveals which rule is active (100% at no noise) but needs about 8-9 times more probes than exact per-prompt feedback; noise (q=0.15) lowers both leak (89%) and utility (68.7%). It is a trade-off, off by default.

**14. Why are the timings divided by ten, and does that matter?**
Fixed overheads (HTTP, SQLite) are not scaled, which likely inflates differences compared with production windows. The real-model run used the real 3 s window but is small.

**15. Why not gVisor, Falco, Cilium or SPIRE?**
Out of scope for a 24-36 hour prototype on standard Docker with no special hardware. They are future work, not claimed.

**16. What is still open?**
CPU/noisy neighbour, averaging and extreme counts of the noisy report, hosted KV cache, Blue seeing payloads, a larger real-model test, and the default policy is still `bucket_hard` (the better profile is opt-in: `docker-compose.recommended.yml`).

**17. How do I reproduce it?**
`pytest tests eval/tests` (some timing tests need an idle machine); `python -m eval.matrix ...` (timing matrix); `python attack_suite.py`; `python -m dashboard.duel_run` then `uvicorn dashboard.app:app` and open `/duel`; `python -m dashboard.real_batch` with a DeepSeek key. Details in README and PROGRESS.md.
