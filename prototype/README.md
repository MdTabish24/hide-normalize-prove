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
| Gateway | `gateway.py` | The only mediator. Role comes from the token, never from JSON. Every response to Red is the same 202 envelope (same status, header set, 64-byte body). Release time follows the policy below. |
| Blue filter | `blue.py` | Private keyword filter, reachable only from the gateway. |
| Mock model | `model.py` | Simulated prefix cache, namespaced per (role, run). No real model or API key. |
| Sealed config | `storage.py` | Blue's rule is AES-256-GCM encrypted at rest; only the gateway holds the key. Per-run report budget (2 reads). |
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
| `bucket_hard` | smallest of 3/6/9 s; compute stopped at 9 s | **default** (unchanged from Round 1) |
| `window_hard` | **always exactly W** (default 9 s); compute cancelled at D = 0.8 W | Round 2 proposal; select explicitly |

`window_hard` removes the bucket boundary: a request that finishes at 0.1 s,
one that is blocked, one that errors and one cancelled at D are all released
at W. Cancellations are recorded only for the evaluator (DB column, audit
event, evaluator-only `/v1/run/{id}/evaluation`). Per-identity in-flight limit
(default 16) with no queue: excess requests are rejected at once and still
released at W, so waiting can never shift compute. Cost: every response waits
W, and compute longer than D is cancelled. It is not the default because three
existing tests assert first-bucket timing.

## Run it (Windows PowerShell)

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
- Every response: status 202, `content-type: application/json`,
  `content-length: 64`, body `{"status":"pending"}` padded to 64 bytes. Only an
  authorized final report body differs (its range), with the same length.
- Release is scheduled from ASGI dispatch on a monotonic clock. The gateway
  sleeps to 3 ms before the deadline and then yields until it, so lateness does
  not depend on unrelated event-loop work; on Windows hosts it requests 1 ms
  timer resolution. Docker/Linux timers were already precise.
- Errors (auth, schema, route, downstream failure) use the last bucket under
  bucket policies and W under `window_hard`.

### Audit pipeline
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

## Dashboard story view

`http://127.0.0.1:8090/story` is a NEW presentation page. `/`, its HTML/CSS/JS,
and existing dashboard observations are unchanged. Use the same dashboard and
worker commands above. New read-only endpoints: `/api/story`, `/api/story/events`.
The existing allowlisted job queue accepts the additional `story` action.

Or start the local UI + worker together in ONE terminal (do not also start the
separate worker/preview on the same port):

```powershell
cd "C:\Users\Mohammad Tabish\Downloads\hackatrhon-hackskills\prototype"
.\.venv\Scripts\python.exe -m dashboard.story_demo
```

Open **http://127.0.0.1:8090/story**. Ctrl+C stops both. The launcher refuses to
start if a timing matrix is active. Stop it before starting any timing matrix.

The page has one main **Demo dekho** button. It explains one saved request in
eight short phases; the active character stays bright and the others dim.
The same button pauses, resumes or replays. Technical controls and evidence are
collapsed under **Asli numbers aur proof**. Playback is a simplified explanation
of recorded facts, not an actual inner-service timing trace or a fresh attack.

The optional **Naya 4-request test record karo** action inside details starts a separate local mock Lab,
with the same two fictional benign probes in each A/B world. All evaluator
file writes happen AFTER response release. It reads actual gateway outcomes,
finished evaluator counts, three actual report responses (stable repeat and
pending third read), persistent report-budget usage, then verifies each run's
signed audit checkpoint and reads its event count. Only allowlisted metadata
is written to `dashboard/runtime/observations/story.json` (UI read-only mount).
This evaluator-only artifact is protected by the operator boundary, not a new
encryption/signature format; audit integrity comes from the existing verifier.
The 4-request story is not a leakage accuracy experiment or Docker isolation test.

No gateway, Blue, model or existing test changes. The gateway discards model
text and records no compute duration: the story explicitly states **Mock model:
fixed dummy answer (not a real model)** as configuration, NOT as a captured
per-request output. Actual generated text, rule-firing trace and compute time
stay NOT RUN in details. A `safe=0` DB outcome is “not allowed”, not proof of a
logged block reason. No real provider/API calls or keys are used.

Presentation verdict rules (fixed now, before running this story demo; existing
matrix results have already been seen, so this is NOT a preregistration claim):

- Timing needs at least 40 unseen test groups and a recorded 95% interval.
  Otherwise timing is NOT RUN / insufficient evidence.
- LEAKED: accuracy >=60% and interval lower endpoint >55%.
- NO LEAK FOUND: interval upper endpoint <=60%. Wording: “the tested attacker
  could not reliably distinguish”, never “no leak”.
- Otherwise BOUNDED LEAK: an uncertain presentation category, **not a formal
  information-theoretic or differential-privacy bound**.
- Overall VALID requires isolation PASS, timing NO LEAK FOUND or BOUNDED LEAK,
  and audit VALID, all for the same deployment/run scope. A failure is INVALID;
  missing inputs are INCOMPLETE. Historical Docker isolation or an unrelated
  timing demo cannot certify a new localhost story run.

Below the animation, **Saare tests. Saaf hisaab.** exposes all saved evidence in
five visible tables (no extra mode buttons): all 16 expected timing cells across
four policies, real DeepSeek output/latency comparisons, the complete evidence
register including unresolved failures, 11 individual isolation + 8 audit cases,
and every current-story request/report/budget/audit check. Missing cells remain
NOT RUN; unplanned timing arms are shown as a dash. Raw/bucket ordinary accuracy
is 98.5%/56.5%; boundary and overflow bucket accuracy is 100%. Intervals, sample
sizes, training accuracy and gaps are visible in the timing table. Historical
checks are labelled separately from this tiny mock story. Real-model projections
expose only allowlisted numeric metrics/provider, never raw prompts or outputs.
Exact pending envelope verification does not establish equal timing.

### Robot stage: who is doing what?

`/story` now shows a red robot (Red/scripted tester), a blue robot
(Blue/private guard), a central gateway shield (trusted mediator), and a
neutral face (client model, explicitly MOCK). Red is outside the environment;
only the gateway connects to Blue, the model and audit. The diagram is a flow
map, not proof of Docker isolation for a localhost demo.

The optional recording action executes real HTTP submissions. Attempt events
are written BEFORE the HTTP measurement clock starts; evaluator reads/writes
remain after release. No new work is added inside the gateway request path.
SSE polls every 0.4 seconds during a job, every 2 seconds idle.

**Demo dekho** preferentially explains a saved not-allowed request with a verified
pending envelope, otherwise the first saved request. Red shakes when that attempt
stops. Flowers celebrate only a verified exact output envelope. Failed or missing
evidence never produces flowers. With reduced-motion enabled, these effects are
disabled. Playback makes no API/model calls; its pace is not original compute
time. The model branch follows recorded allow status and known gateway flow;
actual model output and compute timing remain uncaptured.

Green PASS means only that the exact generic output envelope matched. An
allowed request can still have its raw model output withheld. This does not
certify timing isolation or the whole run. Environment lifecycle is recorded
as starting/running/stopped/unknown; completed temporary services are not
presented as still online.

34 story/dashboard tests and six JavaScript playback/report checks pass. Browser QA
checks active/inactive opacity, playback completion and flower elements. New
evidence: `evidence/simple-story.png`, `evidence/simple-ui-tests.txt`,
`evidence/simple-playback-tests.txt`. The previous collector timing-test failure
remains unresolved; this UI work does not change its assertions.
