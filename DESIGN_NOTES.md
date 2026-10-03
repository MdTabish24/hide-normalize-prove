# Hide, Normalize, Prove — current decisions and evidence

Updated 2026-10-04. These are local PoC controls and explicit limitations,
not a claim that the Bayora sandbox is already isolated or proven secure.

## Run locally

```powershell
cd "C:\Users\Mohammad Tabish\Downloads\hackatrhon-hackskills"
python -m pip install matplotlib scikit-learn cryptography
python experiment.py
python -m unittest test_experiment.py
```

`experiment.py` performs no API calls. It writes `simulated_results.json`,
`simulated_leakage.png`, and `demo_audit/`. All new evidence is labeled
**simulated, local PoC**. Existing DeepSeek files stay unchanged.

## 1. End-of-test range feedback

During a test, Red gets only a constant pending acknowledgement, never raw
model text, per-prompt safety scores, or reasons. After completion, Red gets
an integer range, not the exact safe count. The true count is not forced to
the midpoint: for count 13, a width-12 range could be 1–13, 7–19, or 13–25.
No exact count is included in the Red-facing result.

The random range is generated once and stored in a trusted SQLite ledger.
Repeated identical prompt multisets reuse the result, even after a service
object restart. Reordering does not obtain fresh noise; duplicate multiplicity
still matters. Two unique batches of at most 100 prompts are allowed per
trusted principal and defense version. Session/run IDs cannot reset this budget.
The demo uses temporary SQLite storage; production requires a durable ledger,
stable protected key, authenticated identities, and atomic budget operations.
Principal/defense version are trusted inputs, never Red-selected identifiers.

Important: this is heuristic obfuscation, NOT differential privacy or a
confidence interval. A narrow range containing the true count can reveal
coarse outcomes: 0/100 yields 0–12; 100/100 yields 88–100. Those distinguish
the hypotheses perfectly. Sticky reports prevent fresh samples for the exact
same batch, but related/adaptive batches and colluding identities can still
leak. A changed batch spends the shared budget. Freeze one report rather than
rerun a stochastic model and repeatedly change the count. Formal privacy would
need a defined secret/adjacency model, sensitivity, and composition accounting.

## 2. Timing: preserve the user's chosen overflow policy

For measured/simulated time t, release at the smallest eligible bucket in
3/6/9 seconds. For t > 9 seconds, release at actual time t. This reuses the
stateless `release_time` function from `experiment_real.py`.

9 seconds is the **last padding bucket**, not a hard maximum response time.
The API client timeout is a separate operational timeout. The existing policy is unchanged. A separate simulated hard-timeout comparison
arm caps observations at 9s using the same generic response envelope. Above 9s, fine-grained timing remains exposed and has no
established leakage bound. Rare benign overruns do not establish rarity for
attacker-chosen workloads. Safety labels do not make latency secret-independent.

The simulation includes ordinary times, secret-dependent times around 3s,
and secret-dependent >9s times. 2.9s versus 3.1s becomes 3s versus 6s: the same
rule can still reveal the secret. The current tests intentionally report this.
Release schedules are numerical observations, not a live sleep/network gateway.

## 3. Personal pending response system

The local response envelope is always status 202, a 64-byte ASCII body, fixed
Content-Type/Content-Length headers, and streaming disabled. Pass/fail/denial
does not appear in the envelope. Only the final range is published after the
trusted completion condition. The pending control message contains no safety
feedback, although scheduled response timing may still disclose information.

This is a local interface model, not an HTTP server. Fixed first-byte timing,
TLS/proxy headers, error paths, acceptance delays, polling schedules and actual
network behavior still need live verification. Run completion must itself be
scheduled independently of secret-dependent work; hiding the result body alone
does not hide when computation finished. Console/debug files are operator-only
and must never be mounted into Red's sandbox.

## 4. Session cache reset

The mock cache retires a principal/role's old session entries on session start
and separates entries by principal, role, run, and session. It leaves concurrent
other roles untouched. Reset plus role/run namespaces avoids modeling a
single shared cache that concurrent Red/Blue users could reuse.

Hosted DeepSeek cache cannot be reset or inspected from this client. Fresh
message lists do not establish a backend KV reset. Real vLLM deployment would
need server-side cache disabling or protected role/run salts, plus appropriate
reset controls for dedicated instances. Do not expose admin reset routes to Red.

## 5. Audit log event/byte length (user clarified)

Store audit event count, serialized byte length, character length, run ID,
sequence numbers, and final hash. Each event links to the previous hash.
A final completion event records the preceding event count. An Ed25519 signature
covers the checkpoint's run ID, counts, lengths and final hash.

Verification requires a trusted public key and the expected run/checkpoint.
The demo detects edit, tail deletion, reorder, replay under a different run ID,
and tampering with the checkpoint count/length. Length alone misses same-size
edits, so hash/signature validation remains necessary.

The local checkpoint/public-key files simulate an independent witness; they
are not independently protected by ACLs or separate infrastructure. A real
verifier must pin its key and checkpoint outside attacker-controlled storage.
Replay of an old valid checkpoint for the same run still needs freshness/version
protection. Events never recorded cannot be recovered/proven by a hash chain.
This proves integrity of the recorded sequence, not truth or completeness of
every real action. API/encryption key length is unrelated to log integrity.

## 6. Separate training/testing, plus overall diagnostic

Generate disjoint train and unseen test runs, 200 each per cohort. Every request
from one run belongs to one split. Train a limited decision-tree attacker on
Red-observable timing features only; evaluate on unseen runs without fitting.
Report train accuracy, unseen accuracy, gap, sample size, and Wilson 95%
intervals. Runs are balanced between two synthetic secrets.

Also report the requested combined train + unseen accuracy, explicitly labeled
**diagnostic only**. It is not the headline because it includes fitted examples.
These synthetic samples can reveal weaknesses in the specified toy latency
model, not prove performance on real caches/production secrets. No A/B labels
are invented for the existing DeepSeek measurements. Near-chance performance
means this attacker did not distinguish the tested secrets, not zero leakage.

## Audit integrity and leakage validity are separate

`audit_demo.intact=true` means recorded-log integrity verifies. It is not a
universal VALID safety verdict. Boundary/overflow leakage experiments may fail
even with a valid audit chain. Do not select a security pass threshold after
seeing results; define attacker scope, tolerable advantage, uncertainty, and
an independent final holdout before assigning a run-level security verdict.

## Existing real evidence

**Real model run (DeepSeek), small sample, n=150 latency / n=20 extraction.**
149 releases at 3s, one at 6s; p50/p95/p99 1.18/1.64/2.12s;
>3s 0.7%; average offline padding +1.82s. No hit/miss or secret A/B labels.
Canary disclosure raw/gateway: 0/20 versus 0/20. Rule keyword disclosure:
2/20 versus 0/20 by design. Request #2 reveals trigger and response; #59
reveals the trigger. Historical gateway payloads are exact-scan 0/1 placeholders,
not actual safety verdicts or the new range-feedback protocol.

## Still outside the implemented PoC

Encrypted vault, real workload authentication, container/network/log isolation,
live gateway scheduling, real KV cache reset, independent audit witness, and
hardware/host isolation remain deployment work. New helper classes demonstrate
controls locally; they do not enforce a boundary against a hostile OS user.

## Executed simulation results

200 train and 200 unseen runs per cohort, fixed seed 7391; six observations per
run. These synthetic distributions were chosen to exercise the policy, not
estimated from real production traffic.

| Cohort | Raw unseen accuracy | Bucketed unseen accuracy | Mean bucket padding |
|---|---:|---:|---:|
| Ordinary | 100% | 50% | +1.65s |
| Around 3s boundary | 93% | 95% | +1.49s |
| Above 9s | 100% | 100% | +0s |

Additional simulated overflow comparison on the same unseen runs: actual-time
after 9s gives 100% attacker accuracy; a fixed 9s hard timeout gives 50%. All
observations in this overflow cohort time out (100% timeout rate), losing useful
responses. The 256 output-token cap is metadata in this local deadline model,
not a wall-clock bound or implemented cancellation. Mixed completion/timeout
signals and boundary probes remain risks. No real-model requests were made.

Ordinary bucketed accuracy has a Wilson 95% interval of about 43.1–56.9%.
The 93% vs 95% values are empirical performance of one limited classifier;
do not conclude quantization universally increases leakage. Both detect strong
boundary information in this toy model. Zero observed >9s rate in the previous
real sample cannot invalidate this synthetic counterexample.

Audit: intact=true; edit, tail-delete, reorder, wrong-run replay and altered
checkpoint count all false. Feedback: identical repeat reuses one range;
third unique batch is unavailable. Cache reset/role isolation tests pass locally.
Eleven automated tests passed, plus complete artifact generation. No API calls;
all four original real-model artifacts were verified unchanged.

References:
- vLLM prefix cache salt: https://docs.vllm.ai/en/latest/design/prefix_caching/
- vLLM admin/reset security: https://docs.vllm.ai/en/latest/usage/security/
- NIST differential privacy evaluation: https://csrc.nist.gov/pubs/sp/800/226/final
