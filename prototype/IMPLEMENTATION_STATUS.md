# Hide, Normalize, Prove — actual implementation status

The goal is a valid adversarial evaluation: Red cannot learn Blue's private
defense, Blue's author cannot learn Red's private attacks, and shared observations
cannot reveal the secret. Change secret A to B and measure what Red can distinguish.
Separate, Mediate, Normalize, Measure are controls; a pretty UI is not evidence.

| Proposed control | Current code | Remaining gap |
|---|---|---|
| Encrypted Red/Blue vault | AES-GCM for Blue config, Red prompts and model outputs; role/run/identity-bound records (`vault.py`, `storage.py`) | At-rest encryption does not hide plaintext from trusted execution components or a compromised gateway. |
| Fixed-size payloads + dummy reads | Every encrypted payload record is 32 KiB; one authenticated cover read per record read/write | Not ORAM: filenames, counts, timestamps and host access patterns remain observable. |
| Role + workload identity | Distinct role tokens; role derived from token | No SPIRE/SPIFFE or workload attestation. |
| Stateless 3/6/9s release | Four timing policies; default `bucket_hard` | Buckets expose boundaries; actual overflow is an evaluation-only option. |
| Generic failure response | Same HTTP 202, headers and body | Default errors use the last bucket; this can differ from successful first-bucket replies. |
| Cache/session isolation | Mock namespaces; real DeepSeek adapter sends fresh salted messages, no history/tools/shared conversation | Hosted provider KV/cache deletion is not controlled or proved. |
| Real model backend | `provider.py`, fixed DeepSeek endpoint, environment key, token cap, bounded timeout/retry; opt-in Docker CONNECT broker | Contract tests passed; actual provider completion awaits a key. Docker Engine/service unavailable in this session. No mock fallback. |
| No immediate output feedback | Raw model text withheld; pending during run | Separately saved real-model score-only comparison is offline; live gateway final report is a range. |
| Noisy final range + limits | Stable per-run range, SQLite 2-read budget, 100 submissions/run | Not DP; fresh-run averaging and extreme counts remain risks. |
| Automatic leakage measurement | HTTP A/B harness, train/test split by run, Wilson intervals | Matrix has 6/16 saved cells; attack suite/external agent sessions incomplete. |
| Audit counts + bytes + signature | Separate Ed25519 collector, hash chain, signed checkpoints, verifier | Local checkpoint is not an independent witness; pre-collection omission undetectable. |
| Isolation of channels | Docker network/hardening code and historical isolation checks | No current full-deployment certificate; CPU/GPU/kernel escape and bidirectional confidentiality unproved. |

## What the two panels actually compare

`python -m dashboard.compare_run` makes eight measured HTTP **submissions** to
fresh localhost gateway/model/Blue/collector subprocesses, without reading `.env`
or using a real model API. Same fictional Blue rule and same probes in both arms:
blocked keyword, allowed neutral, repeated neutral, and simulated slow backend.

- Left: `raw` timing. Auth, encryption, Blue filter, output shaping and audit are
  still on. This is **not** an entirely unprotected deployment.
- Right: default `bucket_hard`, scaled to 0.3/0.6/0.9 seconds.
- Separately: a saved real DeepSeek extraction output is replayed as raw text vs
  its saved score-only payload. It is not a fresh API request or the live mock.

The walkthrough is not an A/B accuracy experiment. This recorded run still had
different protected release times: blocked 0.342s vs allowed 0.630s. Both exact
pending envelopes passed; that does not establish timing secrecy. Both paired
audit chains verified VALID (11 and 12 events). Temporary log/checkpoint files
are removed with the lab; the exported presentation JSON is not itself signed.

## Why a request passed or failed

With **both** `EVAL_MODE=1` and `DEMO_TRACE=1`, the gateway writes private demo
telemetry to its temporary data directory **after response release**: actual Blue
allowed boolean, model call/completion, observed deadline cancellation, gateway
compute time and planned/actual release. Only the exact known mock answer
`Dummy answer.` can be captured, never arbitrary model text, prompts or rules.
No telemetry file is produced by default. No reason is sent to Red.

Blue approval, model completion, output containment, timing leakage, and whole-run
validity are separate results. A gateway timeout does not prove that the remote
backend physically stopped computing. No cache-hit telemetry is currently captured.

Current checks: 41 selected non-timing Python tests, four existing gateway timing
tests, and eight JavaScript tests passed. The earlier collector timing-isolation
test failure remains unresolved and is not included in those passing checks.

## Real-model path and vault update

`python -m dashboard.real_demo` asks for the DeepSeek key privately in the terminal
unless already present in its environment. It serves port 8091 with a separate
worker queue. Select **Live DeepSeek**, then **Run test now**. This sends two
benign probes through real localhost gateway/filter/adapter/collector processes;
normally only the allowed probe calls the provider. Across both probes the strict
maximum is four calls including retries; unexpected filter decisions fail. Without
a key, the action stays unavailable. No successful model call is claimed yet.

With `--docker`, the same action uses the Docker gateway instead. The real overlay
retains all internal service networks. Only an authenticated CONNECT broker joins
an external network, and accepts only `api.deepseek.com:443` at public IPs. The API
key is present in the model adapter container only, not gateway/Red/Blue/broker.
Real buckets default to 3/6/9 seconds, independently of a fast mock `.env`.
The default offline/mock Compose file remains unchanged.

The private `/v1/run/{id}/artifacts` endpoint requires the evaluator token and a
finished run. It is the only new variable-size operator response; Red/Blue always
get the generic envelope there. The gateway decrypts the bound records; the host
operator keeps actual demo answer text in memory, persisting only its hash and
metadata. Blue decision is explicit: an internal error is not called a block.

Current work still does not supply workload attestation, formal access-pattern
hiding, provider KV reset, an independent audit witness, a completed timing matrix,
or protection against a compromised host/gateway. Earlier saved measurements
predate the new vault I/O and are historical evidence, not fresh benchmarks.
