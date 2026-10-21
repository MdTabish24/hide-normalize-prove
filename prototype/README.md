# Hide, Normalize, Prove: Round 2 prototype

A working proof of concept for Bayora problem 04, *Securing Adversarial AI
Safety Testing Infrastructure*. Red (attacker), Blue (defender) and a client
model share one Docker sandbox. A finding is only valid if Red cannot learn
Blue's secret logic and Blue cannot see Red's payloads, including through side
channels.

**One principle.** A leak exists when something *shared* changes with Blue's
*secret* and Red can *observe* it. Test: swap Blue's secret A vs B; if anything
Red sees changes, that is a leak. Per channel we either **Separate** it
(networks, cache namespaces), **Mediate** it (one gateway), **Normalize** it
(identical responses at identical times), or **Measure** what is left.

Our differentiator is the last step: we measure leakage with an A-vs-B
attacker and publish what still leaks, instead of claiming it is gone.

## What is in the box

| Component | File | Role |
|---|---|---|
| Gateway | `gateway.py` | The only mediator. Role comes from the token, never from JSON. Red submit/denial replies are 202 pending with fixed headers/64-byte body; delayed final reports keep the size but contain a noisy range. |
| Blue filter | `blue.py` | Private keyword filter, reachable only from the gateway. |
| Mock model | `model.py` | Simulated prefix cache, namespaced per (role, run). No real model or API key. |
| Payload vault | `vault.py`, `storage.py` | Blue config, Red prompts and model outputs: AES-256-GCM, fixed 32 KiB records, role/run/identity binding, cover reads. Per-run report budget (2 reads). Not ORAM. |
| Real model (opt-in) | `provider.py`, `provider_proxy.py`, `docker-compose.real.yml` | Stateless DeepSeek calls, environment key, capped output, timeout and retry. Authenticated egress broker; default mock stack stays offline. |
| Feedback | `range_feedback.py` | After a run: a noisy 12-wide range for the safe count, not the exact count. |
| Audit queue + shipper | `audit_queue.py`, `audit_forwarder.py` | Durable local queue with per-run sequence numbers, retry with backoff, never on the request path. |
| Audit collector | `audit_collector.py`, `audit_store.py` | Separate container, Ed25519 key only here, canonical hash chain, signed checkpoints. |
| Verifier, tamper demo | `verify_audit.py`, `demo_audit_tamper.py` | Read-only check; tampers with copies only. |
| Operator proxy | `tcp_proxy.py` | Secret-free TCP forwarder that owns the host port, so the gateway keeps zero internet egress. |
| Evidence | `eval/`, `attack_suite.py`, `run_all_evidence.py` | Live leakage matrix, attack suite, feedback analysis, evidence table. |

### Release policies (`POLICY_MODE`)

| Policy | Release time seen by Red | Status |
|---|---|---|
| `raw` | actual compute time | evaluation baseline only, honored only with `EVAL_MODE=1` |
| `bucket` | smallest of 3/6/9 s that fits; late = actual time | evaluation baseline only (`EVAL_MODE=1`) |
| `bucket_hard` | smallest of 3/6/9 s; gateway wait cancelled at 9 s | **default**; remote provider termination is unverified |
| `window_hard` | target W (default 9 s); gateway wait cancelled at D = 0.8 W | Round 2 proposal; select explicitly; OS scheduling jitter remains |

`window_hard` removes the bucket boundary: a request that finishes at 0.1 s,
one that is blocked, one that errors and one cancelled at D are all released
at W. Cancellations are recorded only for the evaluator (DB column, audit
event, evaluator-only `/v1/run/{id}/evaluation`). Per-identity in-flight limit
(default 16) with no queue: excess requests are rejected at once and still
released at W, so waiting can never shift compute. Cost: every response waits
W, and compute longer than D is cancelled. It is not the default because three
existing tests assert first-bucket timing.

## Run it (Windows PowerShell)

### Real DeepSeek demo

Use Python 3.11. On a fresh checkout, create `.venv` and install
`requirements.txt` there before running the command below.

```powershell
cd "C:\Users\Mohammad Tabish\Downloads\hackatrhon-hackskills\prototype"
.\.venv\Scripts\python.exe -m dashboard.real_demo
```

Enter the key at the hidden terminal prompt, then open
`http://127.0.0.1:8091/story`. Select **Live DeepSeek → Run test now**. This starts
real localhost gateway/filter/DeepSeek-adapter/audit processes. Two benign probes:
one expected to be blocked, one allowed to call DeepSeek. Normally one provider
request, at most four calls including retries if both probes reach the provider;
an unexpected filter decision fails the demo. Missing/invalid keys never fall back to a mock.
The UI compares the private operator execution with Red's view of the **same
request**, not a fabricated unprotected deployment. Actual model text is kept in
operator memory; only hash/metadata persist. This mode does not test Docker
network isolation. The worker queue is separate from the existing 8090 demo.

For the real **Docker** stack, first start Docker Desktop's Linux Engine, then:

```powershell
.\.venv\Scripts\python.exe -m dashboard.real_demo --docker
```

This builds/starts the real-provider overlay and uses its gateway for the real
test. Local role credentials are initialized without replacing existing keys.
The existing `model-mock` service slot runs `provider:factory` in this overlay;
it is not the mock implementation. Its only network remains internal model-net.
An authenticated CONNECT broker alone joins provider-wan and allows only
`api.deepseek.com:443` with public DNS answers. No extra published ports. Only the
adapter container gets the provider key. This is an explicit internet exception
for a hosted API; the default Compose stack is still offline. The real overlay
uses `REAL_BUCKETS` (default 3,6,9), not scaled mock buckets from `.env`.
Stop the 8091 real-demo server with Ctrl+C before switching between local/Docker modes.

Current contract: fixed `https://api.deepseek.com/chat/completions`, default
`DEEPSEEK_MODEL=deepseek-flash`, non-thinking, 128 output tokens (configurable up
to 512), six-second provider deadline, at most one 429/503 retry. Checked against
[DeepSeek's API reference](https://api-docs.deepseek.com/api/create-chat-completion/).
Fresh random prefixes/no history reduce reuse but cannot enforce hosted KV
deletion; [DeepSeek caching is automatic](https://api-docs.deepseek.com/guides/kv_cache/).

### Offline/mock stack

Requirements: Python 3.11, Docker Desktop (Linux containers, Compose v2).

```powershell
cd "C:\Users\Mohammad Tabish\Downloads\hackatrhon-hackskills\prototype"
python -m pip install -r requirements.txt   # or: uv pip install --python .venv\Scripts\python.exe -r requirements.txt
python init_env.py --fast                   # creates .env once (never commit it); fast = 0.3/0.6/0.9 s buckets
$env:GATEWAY_PORT = "8088"                  # only if host port 8000 is busy (it is on our dev machine)
docker compose up --build -d
docker compose ps
python manage.py configure                  # Blue sets its rule (default trigger: pineapple)
```

To run the Round 2 policy instead of the default: `$env:POLICY_MODE = "window_hard"; docker compose up -d`.

### Demo in 4 steps (what the video shows)

```powershell
# 1. Red is blocked from Blue, the model, audit, host and internet (run INSIDE red-client)
$ip = { param($s) docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}' (docker compose ps -q $s) }
docker compose exec -T red-client python demo_isolation.py --blue-ip (& $ip blue-defense).Trim() --model-ip (& $ip model-mock).Trim()

# 2. Finish that run (use the run ID printed by step 1), then verify its signed audit
python manage.py finish --run-id YOUR_RUN_ID
docker compose run --rm verifier --run-id YOUR_RUN_ID

# 3. Tamper detection: 7 tampered copies must all be INVALID
docker compose run --rm --entrypoint python verifier demo_audit_tamper.py --run-id YOUR_RUN_ID

# 4. Before/after leakage numbers and residual risk: open EVIDENCE.md
```

Stop with `docker compose down` (keeps data) or `docker compose down -v` (fresh demo).

## Reproduce the evidence

Keep the machine idle while running timing tests and measurements: CPU load
delays releases (we measured this, attack 9b) and makes timing tests flaky.

```powershell
.venv\Scripts\python.exe -m pytest tests eval/tests -q -p no:cacheprovider          # host
docker compose run --rm --no-deps --entrypoint python verifier -m pytest tests -q -p no:cacheprovider   # inside the image
.venv\Scripts\python.exe -m pytest tests -m timing -q -p no:cacheprovider           # timing-sensitive tests only, serially

uv pip install --python .venv\Scripts\python.exe -r eval\requirements.txt           # scikit-learn, matplotlib
.venv\Scripts\python.exe -m eval.matrix --n 200 --train-n 200 --scale 0.1 --concurrency 8 --seed 7391 --audit   # ~1 h
.venv\Scripts\python.exe attack_suite.py                                            # ~20 min; 9b loads all CPU cores
.venv\Scripts\python.exe -m eval.feedback_run                                       # feedback analysis
.venv\Scripts\python.exe run_all_evidence.py --cached                               # rebuild EVIDENCE.md from saved files
```

External coding-agent sessions: see `agent_redteam/README.md` (harness ready, sessions NOT RUN).

<!-- RESULTS -->

## Threat model and limitations

**Protected (and measured):** direct network paths from Red to Blue, model,
audit, host and internet; Red reading Blue's rule from disk, env or Docker;
role/token confusion; error-shape oracles; timing differences under the
measured policies; cross-run cache probing; log/audit/DB leakage of the rule,
raw prompts and tokens; same-run feedback re-reads; audit tampering after
collection.

**Not protected / out of scope:** host or kernel container escape; hardware
and shared-GPU side channels (including a real KV cache); a compromised
gateway or collector (both are trusted); a compromised Docker daemon or host
administrator; TEEs (not required, not used).

**When the guarantees fail (measured or known):**

- Timing normalization slips when the host CPU is saturated (attack 9b). A
  deployment needs resource governance: cgroup CPU limits, admission control.
- Bucket policies leak at bucket boundaries and through which request is slow;
  `window_hard` removes the boundary but costs latency and cancels long compute.
- Feedback: the per-run budget stops re-reading the same run, not averaging
  over fresh runs; extreme counts are identifiable from one range. The noise
  is heuristic, not formal differential privacy.
- Audit: signed checkpoints are local, not an independent witness (an old
  matching log + checkpoint pair can be replayed); events never logged before
  collection cannot be detected; the gateway can omit events it never enqueues.
- Measurements: mock model, Windows localhost jitter, timings scaled down 10x
  (fixed overhead not scaled), one predeclared attacker, small samples. 50%
  attacker accuracy means *this* attacker failed, not that no leak exists.
  The boundary and deadline cohorts use a test-only hook that gives Red exact
  control over compute time (worst case).

## Design details

### Timing contract
- Red submit/error replies: status 202, `content-type: application/json`,
  `content-length: 64`, body `{"status":"pending"}` padded to 64 bytes. An
  authorized final report body differs (its range), with the same length.
- The evaluator-only `/v1/run/{id}/artifacts` response is variable-size after
  completion. It decrypts stored prompts/results for the trusted operator;
  Red/Blue, bad tokens and unfinished runs receive the generic 64-byte envelope.
- Release is scheduled from ASGI dispatch on a monotonic clock. The gateway
  sleeps to 3 ms before the deadline and then yields until it, so lateness does
  not depend on unrelated event-loop work; on Windows hosts it requests 1 ms
  timer resolution. Docker/Linux timers were already precise.
- Errors (auth, schema, route, downstream failure) use the last bucket under
  bucket policies and W under `window_hard`.
- Startup warms the local executor and internal HTTP pools with root GETs;
  these do not submit prompts, touch the prefix cache, or call a model API.
  Prompt file I/O runs off the event loop; SQLite commits are serialized in the
  gateway process. Result references and completion flags publish atomically.

### Audit pipeline

Checkpoint publication retries short Windows reader locks using the same signed
head. A repeated gateway sequence republishes a pending checkpoint without
duplicating events. Restart recovery accepts an already-signed temporary
checkpoint only when it authenticates the entire current log; unsigned/forged
tails are never re-signed automatically. This is still a local checkpoint, not
an independent witness.
- The gateway enqueues metadata (event type, run ID, role, release time,
  timestamp, SHA-256 of the prompt, per-run `gw_seq`) into
  `audit_queue.sqlite`. No raw prompt, rule, token or exception text.
- A background shipper with its own HTTP pool delivers FIFO with retry and
  exponential backoff. Undeliverable entries move to a dead-letter table after
  `AUDIT_GIVE_UP_SECONDS` (30 s in compose) and the run is flagged
  audit_incomplete. A full queue (`AUDIT_QUEUE_MAX`) flags the run; it never
  blocks a response.
- The collector verifies a stream once, then extends it from the cached
  verified head; it drops duplicate `gw_seq` (lost acknowledgements) and seals
  a sequence gap as unavailable. Each finish/report writes a `complete`
  record and an Ed25519-signed checkpoint `{run_id,count,bytes,head_hash}`.
- `verify_audit.py` checks every hash, sequence, byte count, signature and the
  gateway's queue state (pending or flagged runs are INVALID).

### Network topology
All service networks are internal bridges (no egress). Red joins only
`red-net` (gateway reachable, nothing else; no upstream DNS, isolated gateway
mode). Blue, model and audit each have their own network shared only with the
gateway. Docker publishes no ports on internal-only networks, so
`operator-proxy` (no secrets) bridges the host port to the gateway over an
internal `ops-net`. Containers run as non-root, read-only, all capabilities
dropped, no-new-privileges, with memory/PID/CPU limits; no Docker socket.

### Configuration
`BUCKETS` (3,6,9), `POLICY_MODE`, `WINDOW_SECONDS` (default last bucket),
`DEADLINE_FRACTION` (0.8), `MAX_INFLIGHT_PER_IDENTITY` (16), `RANGE_SEED_MODE`
(`run` or `probeset`), `AUDIT_GIVE_UP_SECONDS`, `AUDIT_TIMEOUT_SECONDS`,
`AUDIT_QUEUE_MAX`, `GATEWAY_PORT`. `EVAL_MODE=1` (never in service) enables the
`raw`/`bucket` baselines, `AUDIT_MODE=off`, the mock's `CACHE_NAMESPACE=off`
control and the `sim_delay` test hook.

## Dashboard

The local operator UI is in `dashboard/`. It reads saved evidence and collector
metadata; it does not call the production gateway or add work to its request
path. **Stop the dashboard and its worker before starting any timing matrix.**
The worker refuses demo actions while a Python `eval.matrix` / `eval.run` process
is active; this guard is not a replacement for keeping timing runs exclusive.

From PowerShell, terminal 1 (no API keys needed, no `.env` loading):

```powershell
cd "C:\Users\Mohammad Tabish\Downloads\hackatrhon-hackskills\prototype"
.\.venv\Scripts\python.exe -m dashboard.worker
```

Terminal 2, with Docker Desktop running (the existing stack setup is unchanged):

```powershell
cd "C:\Users\Mohammad Tabish\Downloads\hackatrhon-hackskills\prototype"
$env:DASHBOARD_PORT = "8090"
docker compose --profile dashboard up --build -d dashboard dashboard-proxy
```

Open **http://127.0.0.1:8090**. The worker creates the two bind directories before
Compose starts. On Linux, give container UID 10001 write permission to
`dashboard/runtime/requests` and read/traverse permission to `observations`.
The optional dashboard profile does not change the default services.

Without Docker, the same UI can preview saved evidence and run local mock demos:

```powershell
.\.venv\Scripts\python.exe -m uvicorn dashboard.app:app --host 127.0.0.1 --port 8090 --no-access-log
```

The dashboard service joins **only `dash-net` (internal)**, reads audit/results
mounts read-only, and has no credentials, signing-key volume, Docker socket or
Red network route. A separate credential-free `dashboard-proxy` publishes only
localhost, using the same Desktop internal-network port workaround as the
existing operator proxy. The host worker consumes three allowlisted filesystem
jobs; it is deliberately outside the UI container. Never expose this trusted
operator UI or its bind directories to Red. The evaluator toggle is presentation,
not an authentication boundary. The worker is trusted and its control directory
is operator-only. No browser assets require internet access.

Buttons:

- **Traffic:** a separate temporary local Lab with actual gateway, Blue, model-mock
  and collectors over HTTP. Sixteen submissions, 4 train and 4 unseen test groups
  (2 requests/group), fixed seed/tree, scale 0.1, audit enabled. A/B use identical
  probes; selector changes order/highlight. This tiny illustrative demo does not
  complete or replace the 16-cell matrix. Time-to-first-byte means first body
  chunk, as in the existing harness. Histograms use measured total response time.
- **Isolation:** runs the existing 11-check script inside the existing Red
  container, including direct Blue/model IP probes. It does not start the stack;
  unavailable Docker is **NOT RUN**. It needs the base services already running
  (see the earlier stack commands; use `GATEWAY_PORT=8088` if 8000 is occupied).
- **Audit:** collects a small real gateway run in a temporary local mock Lab,
  verifies it, then runs the existing seven tamper cases on copies only. Neither
  the original log nor checkpoint is edited. The UI never receives a signing key.
- **Saved matrix / evidence:** read-only historical results, with missing cells
  explicitly **NOT RUN**. A stale on-disk `in_progress` is not live process status.

Only `EVAL_MODE=1` enables the worker's raw baseline. For a test-only raw demo,
set `$env:EVAL_MODE="1"` in terminal 1 before starting the worker and set
`$env:DASHBOARD_EVAL_MODE="1"` in terminal 2 before creating the dashboard service.
For a standalone preview set `EVAL_MODE=1` in its terminal too. The warning remains
visible; these UI flags do not change the main gateway's policy configuration.

Metadata panels use allowlisted fields. Request numbers correlate actual Red
HTTP observations with later operator reads of gateway outcomes. No prompts,
filter keywords, credentials or arbitrary error messages are served. “Not allowed”
can also mean a failed decision. Per-request compute duration and model completion
events are **NOT RUN** because the current gateway does not record them. Collector
events are displayed only if present; no model-scoring animation is fabricated.
SSE heartbeats are transport keepalives, not synthetic activity.

Checks (small backend tests, not a timing matrix):

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_dashboard.py -q
```

Shutdown: Ctrl+C in the worker/standalone preview terminals, then
`docker compose --profile dashboard stop dashboard dashboard-proxy`.
Dashboard screenshots and verification notes are under `evidence/dashboard-*`.
Limitations: local trusted operator, shared host resources, mock model,
localhost jitter, very small demo sample, no host/kernel/hardware isolation proof,
and no independent checkpoint witness or detection of pre-collection omission.

Latest dashboard verification (2026-10-19): 10 new backend tests pass; the
selected non-timing backend/audit/queue checks report 29 passed. The existing
collector timing test **fails even in a separate rerun with the dashboard
stopped** (.01577 s median gap vs .010 s limit); its cause is unresolved. No
existing assertions were changed. Docker runtime verification of the new
services is NOT RUN because the Engine is unavailable; Compose config and
static network checks pass. See `evidence/dashboard-verification.json` and
`evidence/dashboard-timing-check.txt`. The saved matrix remains 6/16, incomplete.

## Dashboard story view: paired before / after

`http://127.0.0.1:8090/story` is the trusted operator view. The original `/`
dashboard remains separate. Start UI and worker together (do not run another
preview/worker on the same port):

```powershell
cd "C:\Users\Mohammad Tabish\Downloads\hackatrhon-hackskills\prototype"
.\.venv\Scripts\python.exe -m dashboard.story_demo
```

The two synchronized panels play a measured paired mock run at four seconds per
step. **Slow demo** plays/pauses; **Agla step** advances manually. Inactive actors
dim. Blue's decision, model call/completion, Red's actual envelope and timing are
separate fields. Rejection explains the actual keyword decision; allowance is
never presented as an attack win. A gateway timeout does not prove backend compute
physically stopped. Actor icons are a cast/status view, not network routes.

Left is raw **timing**, not a completely unprotected deployment: authentication,
Blue, sealed config, output shaping and audit stay on. Right is the unchanged
default `bucket_hard`, with 0.3/0.6/0.9s demo buckets. Real-model output disclosure
is a separate chapter using an existing DeepSeek response and saved score payload,
labelled offline, small sample. Playback itself makes no model calls.

Record a fresh eight-submission pair (or use the optional control in details):

```powershell
.\.venv\Scripts\python.exe -m dashboard.compare_run
```

The controller launches temporary localhost gateway/Blue/mock/collector processes,
never reads `.env`, and uses no real API keys. It enables private telemetry with
BOTH `EVAL_MODE=1` and `DEMO_TRACE=1`. The gateway writes decision, known mock
answer and compute/release metadata only after sending Red's response. Normal
service and ordinary evaluations create no trace. Arbitrary model output, prompt
text, filter text and credentials are never persisted in that trace.

The paired artifact is `dashboard/runtime/observations/comparison.json` (ignored).
The checked-in sanitized `evidence/paired-comparison.json` is the fallback when
no runtime recording exists. Audit chains were verified inside the temporary lab;
its temporary keys/logs are removed. The exported UI JSON is not independently
signed. Fresh tests are instrumented examples, not a powered leakage experiment.
The recorded protected blocked/allowed totals were 0.342s/0.630s: equal envelopes
still did not produce equal times. The UI explicitly shows this limitation.

The implementation coverage table lists the original controls and gaps. See
[IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md): workload attestation,
formal access-pattern hiding and real hosted KV reset are not
implemented. The complete evidence tables remain visible, including all 16 timing
arms (6 saved), historical isolation/audit cases, real-model statistics, earlier
report-budget checks and the unresolved collector timing failure.

Read-only `/api/story` and `/api/story/events` expose allowlisted operator
projections. `/api/red` continues to exclude private reasons and telemetry.
The job queue accepts only fixed scenarios; the browser gets no API keys or
Docker socket. Only the trusted host operator may read the provider environment
and execute demos. The separate Docker dashboard image still gets no credentials.

Selected validation: 41 non-timing Python checks, four existing gateway timing
checks, eight JavaScript checks passed. Earlier collector timing isolation failure
remains unresolved; this is not a full-suite PASS. Evidence: `paired-story-tests.txt`,
`paired-gateway-timing-tests.txt`, `paired-story-js-tests.txt`, `paired-story.png`.

Timing presentation rules remain: at least 40 unseen test groups and a valid 95%
interval; LEAKED if accuracy >=60% and lower bound >55%; NO LEAK FOUND if upper
bound <=60%; otherwise uncertain BOUNDED LEAK (not a formal bound). Whole-run
VALID still needs matching isolation, timing and audit; the tiny story is not a
certificate. Stop this UI/worker before a full timing matrix; Ctrl+C stops both.

### Current presentation: visual demo vs evidence

`/story` is now an English-only visual surface, with one Scenario selector and
Play/Pause + Next Step. The eight scenes cover live DeepSeek, output disclosure, response timing,
network isolation, vault/identity, delayed reports/budgets, audit tampering and
A/B leakage evaluation. It contains no evidence tables or implementation matrix.
Figures use the same saved observations: network boundary, sealed-config drawing,
latency/accuracy bars, score gate, report budget and hash-chain changes. They are
explanatory replays, not additional sensor telemetry or newly run attacks.

`/story/evidence` preserves all detailed tables and implementation coverage in
English. Fresh recording is also available directly on `/story`. The original `/` operator
page is unchanged. Unmeasured baselines remain grey; missing controls are not
animated as implemented. Historical Docker results, code inspection, local mock
measurements and saved real DeepSeek outputs remain labelled separately.

Current UI checks: 36 Python story/dashboard checks and nine JavaScript checks
passed. These do not rerun the full gateway/matrix or resolve the existing
collector timing failure. Evidence: `evidence/visual-demo-tests.txt`,
`evidence/visual-demo-js-tests.txt`, and `evidence/visual-demo-audit.png`.

### Run from the visual demo

Start `python -m dashboard.story_demo` and open `http://127.0.0.1:8090/story`.
Select a scenario and click **Run test now**. This submits an allowlisted job to
the host worker, starts actual local subprocess services (or probes the existing
Docker stack for isolation), and plays the measured results after completion.
The fresh job ID must match before a result is presented as completed. A failed
fresh isolation/audit attempt replaces old passes with no result; it cannot fall
back to historical evidence. Other queued actions are disabled during execution.

Live actions: paired HTTP timing (eight submissions; only timing differs), measured
controls (vault, role access, reports/restart, eight audit copies; two submissions),
existing Docker isolation probes, and tiny A/B smoke evaluation (16 submissions;
four train/four unseen groups, not the full matrix). Each is mock-model/local.
Playback remains a separate action and never starts tests. The output-disclosure
scene is saved real DeepSeek evidence, not a live API call. Choose Vault & identity,
Audit tampering, or Final report & budget to rerun the measured controls together.
Only the saved output-disclosure scene has no live action. Full implementation gaps and failed timing checks remain in
the evidence view. This UI wiring does not resolve those security gaps.

### Measured control comparisons

Run `python -m dashboard.control_run` without a provider key or Docker. It writes
`dashboard/runtime/observations/controls.json` and `/story` replays its measured
comparisons; Run test now performs the same test. A saved result is available in
`evidence/controls-comparison.json`, explicitly labelled saved when used.

- Vault: scan temporary plaintext and AES-GCM files for the same random dummy
  marker, decrypt round-trip, compare short/long file sizes, reject a changed owner.
- Role access: actual local HTTP to finished-run private artifacts as evaluator,
  Red, Blue and invalid token. Only the evaluator receives the records.
- Feedback: private evaluator exact count vs Red range; pending before finish,
  identical repeated range, third read withheld, budget still exhausted after an
  actual gateway process restart. This is two views of one protected deployment,
  not a measured insecure exact-count deployment.
- Audit: the same eight log copies are read as JSON and passed through the signed
  verifier. JSON reading deliberately has no integrity check; it is a diagnostic
  baseline, not an unsigned gateway mode. Seven altered copies remain readable
  JSON but fail signed verification; the original passes.

Dummy payloads, keys and log copies are temporary; artifacts contain counts and
booleans only. These tests do not prove ORAM, workload attestation, hosted KV reset,
Docker isolation, formal privacy or security against a compromised collector/host.
Fresh failed control jobs never fall back to saved successful control results.
For a real provider run use `python -m dashboard.real_demo` and enter the key at
the hidden terminal prompt; never paste it into chat or commit it.
