# Hide, Normalize, Prove: live skeleton

Live FastAPI gateway, private filter service, mock prefix cache,
isolated Red client, encrypted defense storage and persistent feedback budget.
No real model, API key or dashboard. A separate signed audit collector (Task 2)
and live HTTP leakage evaluation harness (Task 3) are included below. Original experiment files are untouched.
Constants mirror the earlier experiment
without importing its API/ML dependencies.

## Run (PowerShell)

Requires Python 3.11 for host commands and a running Docker Engine 28+ using
Linux containers, with Docker Compose v2. The image itself uses Python 3.11.
Image building needs internet for dependencies; runtime service networks are
internal. Keep the generated local credentials and encryption key private.

```powershell
cd "C:\Users\Mohammad Tabish\Downloads\hackatrhon-hackskills\prototype"
python -m pip install -r requirements.txt
python init_env.py --fast
docker compose up --build -d
python manage.py configure
docker compose exec -T red-client python demo_isolation.py
docker compose exec -T gateway python -m pytest tests -q -s -p no:cacheprovider
```

`init_env.py` creates `.env` once, using generated LOCAL demo credentials, and
refuses to overwrite it. `.env.example` contains placeholders only; do not use
its key literally. Never commit `.env`. `--fast` sets buckets 0.3/0.6/0.9s,
miss 0.08s and hit 0.01s. Omit `--fast` for buckets 3/6/9s, miss ~2s, hit ~0.3s.
To change settings after creating `.env`, edit it locally and run
`docker compose up -d --force-recreate`. Do not rotate GATEWAY_KEY while keeping
its encrypted volume: startup fails closed if the persisted data cannot decrypt.

The configure acknowledgement is generic, as requested, and cannot certify that
an operation succeeded. Configure before submissions; a filter is frozen while
unfinished runs exist. The isolation demo prints its run ID; finish it before
changing the defense, or deliberately reset the demo volume.

Only gateway publishes a port, `127.0.0.1:8000`. Red gets ONLY RED_TOKEN and only
red-net. Blue and model get distinct internal service tokens, not role tokens
or GATEWAY_KEY. All containers are non-root, read-only except gateway's `/data`
volume and temporary `/tmp`, drop all capabilities, set no-new-privileges, and
have resource limits. No host directories or Docker socket are mounted.

Red, Blue, model and audit networks are user-defined internal bridges. Red additionally uses
`gateway_mode_ipv4: isolated` (Engine 28+) and no upstream DNS. Ordinary
`internal: true` alone does not prevent access to host services on a bridge
address; see [Docker gateway modes](https://docs.docker.com/engine/network/port-publishing/#gateway-modes).
The gateway's blue-net attachment provides the host demo binding. This design
still requires the runtime isolation checks on the target Docker installation.

### Probe private IPs too

The default demo tests service DNS, host aliases/bridge candidates, external DNS,
internet IPs, Docker socket absence, denied defense access and mediated submit.
It prints FAIL and exits nonzero if a forbidden target is reachable. To check
cross-network packet isolation independently of private DNS visibility:

```powershell
$blueContainer = docker compose ps -q blue-defense
$modelContainer = docker compose ps -q model-mock
$blueIp = docker inspect --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' $blueContainer
$modelIp = docker inspect --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' $modelContainer
docker compose exec -T red-client python demo_isolation.py --blue-ip $blueIp --model-ip $modelIp
```

An optional `--host-ip YOUR_HOST_IP` tests a known host address too. TCP probes
cover ports 80/443/8000; closed ports and a few unreachable IPs are observations,
not proof that every host service or escape route is unreachable. Host alias
resolution itself counts as a failed DNS isolation check.

### Finish and persistent reports

Use the run ID printed by the isolation demo, replacing `YOUR_RUN_ID`:

```powershell
python manage.py report --run-id YOUR_RUN_ID
python manage.py finish --run-id YOUR_RUN_ID
python manage.py report --run-id YOUR_RUN_ID
docker compose restart gateway
python manage.py report --run-id YOUR_RUN_ID
python manage.py report --run-id YOUR_RUN_ID
```

Before finish: 202 pending. After evaluator finish: two reports with the same
stored range, including across gateway restart. Third report: generic pending.
Pre-finish polls do not consume the budget. All final report reads, including
repeats, consume the two-report allowance per token identity per run.
Red cannot finish a run or choose a role in JSON. At most 100 attempts per run.
Completion while requests are in flight is ignored; evaluator must retry after
they settle. New runs do not inherit another run's counters or reports.

## Timing and output contract

- No streaming. Every response uses 202, application/json and 64 bytes. For
  submission, denial and error the body is `{"status":"pending"}` plus spaces.
  Uvicorn Date/Server headers and access logging are disabled by Compose.
- For successful submit processing, choose the smallest configured bucket at
  least as large as elapsed compute time, measured with `perf_counter()`.
  Same stateless rule for allowed, blocked, hit and miss.
- Request-wide timeout is the last bucket, including request-body processing.
  Above it, stop waiting for downstream HTTP and send the SAME pending envelope.
  Errors (auth, schema, route, downstream failure) all use that fixed LAST bucket.
  Their body/status/header set is identical; error timing is not claimed equal
  to every successful request's timing.
- Network deadlines are approximate wall-clock targets: scheduling, socket
  delivery and overload can exceed them. They are measured from ASGI dispatch,
  after HTTP headers. No production claim of "exactly 9s" under arbitrary load.
- Model namespaces are (authenticated role, run_id). Prefixes are SHA-256 of
  the first 32 characters. The answer is fixed; the cache has real sleep/jitter,
  no real inference. Gateway never returns model answers or filter reasons.
- Blue's keyword config is AES-256-GCM encrypted in `defense.enc`; only gateway
  has the env key. Blue receives the decrypted config over its private check
  request and holds it only in memory while evaluating it. No plaintext rules
  are put in SQLite. There is no default implicit filter: configure first.
- Metadata stdout contains event type, run ID, role, chosen bucket, timestamp
  and prompt hash only. Raw prompts, rules, tokens and stack traces are excluded.

## Tests without Docker

```powershell
python -m pytest tests -q -s -p no:cacheprovider
```

Tests use fast buckets, ASGI HTTP requests with real sleeps, SQLite, AES, and a
real localhost Uvicorn subprocess test. They check envelope/header equality,
hit/miss and blocked/allowed timing, generic errors, hard timeout, role-derived
authorization, cache namespaces, encrypted storage and budget after a real
gateway process restart. `test-output.txt` records the executed local test run.
These tests DO NOT establish Docker network isolation; run demo_isolation.py
inside red-client for that.

Execution on 2026-10-18: **9 tests passed on Python 3.11.15**, including the real
localhost HTTP process/restart test. Compose topology and hardening checks passed
statically. Container build/isolation execution was blocked by a Docker Desktop
startup failure; details are in [demo-output.txt](demo-output.txt). No container
isolation PASS is claimed for this machine.

## Honest limitations

Local prototype; gateway is a trusted single point. One Uvicorn worker only.
TLS, external identity management, independent audit witnesses, real vault payload
padding, real-model leakage evaluation and production sandbox hardening are later tasks.
The host/Docker administrator is trusted. Do not expose the host demo port.

Bucketing leaks at boundaries; a mixed completed/timed-out workload can also
leak. An HTTP cancellation stops waiting, not necessarily remote backend compute:
the separate model service can finish a cancelled request and warm its namespace.
No claim of model compute cancellation or constant runtime under resource exhaustion.

Safe count means Blue explicitly allowed the attempt. No decision due to a crash
or filter timeout counts as zero; model timeout after an allow still counts as
allowed. Interrupted attempts are marked settled on one-worker startup and are
not replayed. This is conservative bookkeeping, not a scored real-model verdict.

The random interval is stored and need not center the true count. It is heuristic
protection, not formal differential privacy. Extreme counts, related batches,
new run IDs and repeated identities can still reveal information; the requested
per-run report budget does not solve global adaptive probing. Prompt hashes can
be dictionary-guessed and should remain operator-only. Plain private-bridge HTTP
depends on Docker/host trust, not encryption on the wire.

Stop with `docker compose down` (keeps persisted state). For a deliberate fresh
demo, `docker compose down -v` deletes its gateway data and budgets.

## Audit

The `audit-collector` service attaches ONLY to `audit-net` (internal bridge),
shared only with gateway. Red, Blue and model have no audit-net attachment or
collector credential. Nothing publishes the collector's port. `/append` and
`/finish` require a separate local AUDIT_TOKEN; there is no HTTP read/key/export
endpoint. Append-only here describes the gateway API's permissions, not a WORM
filesystem against the collector or host administrator.

The collector generates its Ed25519 signing key on first startup inside its
own `audit-keys` volume. No other service mounts that volume. Gateway has no
private signing key. Raw logs go to `audit-logs`; signed checkpoints and the
public key go to separate `checkpoints`. The optional verifier container has
no network and mounts logs, checkpoints and gateway data READ-ONLY. Only the
collector mounts checkpoints writable. All service hardening still applies.

### Start or upgrade an existing Task 1 setup

For an existing local `.env`, add ONLY a missing demo audit token:

```powershell
python init_env.py --add-audit
docker compose up --build -d
```

For a new setup, `python init_env.py --fast` already includes AUDIT_TOKEN.
The upgrade helper never replaces existing role tokens or GATEWAY_KEY. Back up
the collector's key/checkpoint volumes appropriately: deleting the key while
keeping signed logs is not a recoverable key rotation. Startup refuses a key
that disagrees with the existing public key.

Configure Blue before starting a new run, run the isolation/submit demo, and
finish the run as evaluator. Use the run ID printed by the demo:

```powershell
python manage.py configure
docker compose exec -T red-client python demo_isolation.py
python manage.py finish --run-id YOUR_RUN_ID
docker compose run --rm verifier --run-id YOUR_RUN_ID
docker compose run --rm --entrypoint python verifier demo_audit_tamper.py --run-id YOUR_RUN_ID
```

Audit delivery is asynchronous. Let its outbox drain before verifying; a pending
outbox gives INVALID rather than a premature publication decision. Retry the
verifier after a moment if collection is still in progress. A run is publishable
only when the verifier prints VALID. This checks audit integrity/availability,
not whether the run passed a leakage/security evaluation.

### Metadata and completion format

Gateway queues `submit_received`, `bucket_released`, `defense_stored`,
`report_served`, and `run_finished`. Events contain only type, run_id, role,
bucket, timestamp and SHA-256 of the prompt (or null). No raw prompt, filter,
model answer, token, exception detail or private key enters the log.
Configuration events use the reserved stream ID `@gateway`, which Red's run ID
schema cannot choose. It is checkpointed too. Ordinary run IDs retain the Task 1
schema and behavior.

Each per-run record has seq starting at 1, prev_hash (initially 64 zeroes),
and current_hash. Hash the canonical JSON of ALL record fields except
current_hash, including prev_hash and seq. Canonical JSON means sorted keys,
compact separators, UTF-8, no NaN/Infinity. Store exactly one canonical JSON
record plus `\n` per line. Sequence and chain continuation survive collector
restart; one collector worker serializes file operations.

`/finish` appends a complete record. Its count and bytes INCLUDE that record
and its newline; decimal byte length stabilizes before the hash is calculated.
It also seals an `audit_unavailable` flag. The checkpoint is
`{run_id,count,bytes,head_hash,signature}`, signed over the canonical object
without signature. The signature is hex-encoded Ed25519. The verifier checks
all complete-record prefix lengths, sequence continuity/replay, each hash,
terminal completion, checkpoint signature, count, byte length and chain head.
Failure output names the first detected reason and 1-based record index;
index 0 identifies a file/checkpoint/gateway-status failure.

Reports and bucket releases can occur after a run finishes. The collector
appends them without changing old lines and writes another complete record and
signed checkpoint. Thus verification targets the LATEST completed snapshot;
it is not an immutable one-time checkpoint. Verify after activity settles.
Duplicate `/finish` without a new event/status change is idempotent.

### Outages and publication

A durable SQLite FIFO outbox separates audit HTTP/fsync work from response
release. Submission metadata is enqueued on receipt; bucket/report/finish
metadata is enqueued after sending the existing response. Collector requests
have a bounded timeout and do not alter the 202/body/header contract. Existing
final report behavior and budget also stay unchanged.

If delivery fails, gateway persists a sticky `audit_unavailable` flag. If it
later reaches `/finish`, the collector seals the flag into the complete record.
The publication verifier ALSO reads the gateway's read-only `audit_state` and
outbox, so failure AFTER an earlier valid checkpoint still yields INVALID.
Queued, undelivered events also prevent publication. Restart resumes the FIFO;
unacknowledged pre-crash deliveries are conservatively marked unavailable
because delivery/replay is ambiguous. Flags are not cleared by restart or
later successful events. Start a fresh evaluated run after resolving an outage.

Standalone Task 1 tests omit AUDIT_URL/AUDIT_TOKEN and keep their existing API
behavior; such runs are marked unavailable, not advertised as audited.

### Host verification and tests

To verify exported local copies on a trusted host (no network or signing key):

```powershell
python verify_audit.py --run-id YOUR_RUN_ID --logs PATH_TO_LOGS --checkpoints PATH_TO_CHECKPOINTS --gateway-db PATH_TO_GATEWAY_DATA/runs.sqlite
python demo_audit_tamper.py --run-id YOUR_RUN_ID --logs PATH_TO_LOGS --checkpoints PATH_TO_CHECKPOINTS
python -m pytest tests -q -s -p no:cacheprovider
```

The full suite can also run in the isolated tools container (the higher memory
limit accommodates its localhost process tests):

```powershell
docker compose run --rm --no-deps --entrypoint python verifier -m pytest tests -q -s -p no:cacheprovider
```

Export/copy data only after the outbox drains. `--public-key PATH` optionally
pins a separately trusted public key; otherwise verification trusts the public
key in the local checkpoint volume. CLI publication verification requires
gateway availability state. The tamper demo intentionally checks COPIES of
the collected integrity artifacts and never reads or generates a signing key;
it does not itself certify gateway availability or publish a run.

The demo needs a completed log with at least five records and prints eight
cases: original VALID; edit, middle deletion, tail-three deletion, reorder,
duplicate/replay, full rehash without signing key, and log+count edit INVALID.
In the full-rehash case the attacker also updates the claimed checkpoint
head/count/bytes but retains the old signature: signature verification fails.
No source log, checkpoint or key changes.

Executed on Python 3.11.15: **27 tests passed**, including all 9 unchanged Task 1
tests, the eight tamper cases, restart persistence, outage flags and separate
collector/gateway HTTP processes. See [audit-test-output.txt](audit-test-output.txt)
and the actual [tamper table](audit-demo-output.txt). Compose audit network,
credential and read-only/key-volume checks passed statically. Docker Engine is
still unavailable on this machine, so container network/isolation execution
remains unverified; the real HTTP tests ran as local OS processes.

### Audit limitations

Collector and host administrator are trusted. These are LOCAL signed checkpoints,
not an independent witness. An attacker who can replace both the local checkpoint
and log can replay an older matching signed snapshot without detection here;
replacement of the locally trusted public key adds another trust failure.
An arbitrary forged checkpoint still fails against a pinned genuine public key.
Events never logged before collection cannot be detected by a hash chain.
Durable unavailable/pending flags cover detected delivery failures, not a malicious
gateway that omits an event and its flag. Prompt hashes remain dictionary-guessable.

The log append and checkpoint replace are not a cross-volume atomic transaction.
A crash during sealing may leave a temporarily unverifiable snapshot; verification
fails closed rather than inventing a valid history. Filesystem/fsync latency,
SQLite contention and overload still affect wall-clock deadlines. No container
isolation claim replaces the runtime network tests from Task 1.

## Leakage evaluation

Run from this folder with Python 3.11. The operator harness starts actual Uvicorn
gateway/Blue/mock-model/collector processes on temporary localhost ports, attacks
the gateways over TCP/HTTP, then stops them and removes their temporary data/keys.
It does not contact a real API, read `.env`, or change your Compose volumes.
Keep the result files operator-only: they contain ground truth for scoring,
which never enters the attacker feature function or a gateway response.

```powershell
cd "C:\Users\Mohammad Tabish\Downloads\hackatrhon-hackskills\prototype"
uv pip install --python .venv/Scripts/python.exe -r eval/requirements.txt
.\.venv\Scripts\python.exe -m eval.run --n 200 --train-n 200 --scale 0.1 --concurrency 8 --mc-sets 200 --live-sets 20 --seed 7391 --no-audit --output eval/output
```

Alternatively install `eval/requirements.txt` using pip in an activated Python
3.11 environment and use `python -m eval.run` with the same arguments. This is
a substantial local run (21,600 measured submission requests plus controls and
feedback checks), not a quick smoke test. Progress prints every 100 runs.

The harness defaults to disabled collector delivery in its temporary timing gateways;
SQLite bookkeeping and the response policies still run. Outputs record this
condition explicitly. `--audit` additionally starts the existing collector;
the normal Compose gateway's audit configuration is unchanged.
Collector-disabled timing runs have `audit_unavailable` and are not
audit-certified publishable runs; this experiment evaluates their HTTP leakage.
An audit-enabled full run on this machine completed only two cells before
collector connections accumulated and model requests stalled (consistent with
shared backend-client pool starvation). Its incomplete observations are retained
in `eval/output/audit_enabled_partial.json`; they are not the completed matrix.
Audit-enabled performance under load remains unresolved.

Tiny smoke command and tests:

```powershell
.\.venv\Scripts\python.exe -m eval.run --n 2 --train-n 2 --scale 0.02 --concurrency 1 --mc-sets 2 --live-sets 2 --no-audit --output eval/smoke
.\.venv\Scripts\python.exe -m pytest tests eval/tests -q -p no:cacheprovider
```

Tiny runs are plumbing checks; they cannot support security conclusions or the
full feedback cross-check. Evaluation-only dependencies stay in
`eval/requirements.txt`; normal gateway images do not require scikit-learn.

### Policies and test-only hook

**Default stays `POLICY_MODE=bucket_hard`**, preserving the existing Tasks 1–2
behavior and tests. The Task 3 text also calls for default `bucket`; that conflicts
with preserving the existing hard-timeout default. The harness avoids this
ambiguity by explicitly selecting each evaluation policy:

- `raw`: no release padding for successful processing, actual elapsed compute.
- `bucket`: ceiling bucket; above the last bucket return at actual elapsed time.
- `bucket_hard`: ceiling bucket and last-bucket hard timeout with the same 202
  envelope. Raw/bucket use a separate 60-second operational timeout.

Errors keep the original generic envelope/fixed error bucket. Raw is a TIMING
baseline, not a removal of authorization, filtering or output restrictions.
`BUCKETS` remains configurable; `--scale 0.1` uses 0.3/0.6/0.9s and scales normal
mock cache sleeps/jitter and synthetic delay hints by the same factor.

**EVAL_MODE is off by default.** Only with `EVAL_MODE=1` at BOTH gateway and
model may a submit body include `sim_delay` (finite 0..30 seconds). Disabled
gateway drops it and disabled mock ignores it. Never enable it on a shared or
production deployment: it is an attacker-controlled test latency hook. Compose
defaults keep it off. The harness enables it only in its private test processes.

### Timing matrix: live gateway with mock model, local run

Each cohort/policy has 200 unseen runs (100/secret) AND 200 distinct training
runs (100/secret), six sequential requests per run. Jobs are shuffled with
seed 7391 and may overlap up to the stated concurrency, while cache namespaces
use unique run IDs. Train/test membership is assigned by RUN, never request.

Secret A blocks pineapple; B blocks mango. Both worlds receive identical probe
plans. Ordinary probes have randomized benign wording and repeated pineapple
and neutral prefixes, using normal cache hit/miss sleeps. Boundary plans send
three mango probes at 2.65×scale and three pineapple probes at 3.25×scale.
A's allowed probes therefore target just below the first bucket; B's allowed
probes target just above it. The other probes block quickly. Overflow plans
similarly use 8.2×scale and 9.8×scale. Hints are model sleeps, not claimed exact
end-to-end compute times: real filter/HTTP/SQLite overhead and jitter remain.

Overflow also contains a per-probe fast/slow channel: A's mango requests are
allowed and slow while its pineapple requests block quickly; B reverses those
positions. Hard timeout may give both worlds the same sorted timing histogram
while Red still identifies the filter from which probe occupies which bucket.
This cohort therefore does not isolate only the over-9s tail. Do not assume its
hard-timeout arm should reach 50%, or attribute all residual leakage to the tail.

Attacker input includes sorted/summary total times and first-body-chunk TTFB,
status, body length, header name/value fingerprint and per-request timing bins
inferred ONLY from observed time/public buckets. No label, run ID, URL, Blue
configuration, exact body content or server-computed bucket enters the features.
The predeclared attacker is a depth-3 decision tree with a fixed seed; no tuning
or held-out model selection. Headline accuracy uses unseen runs, with training
accuracy, gap and Wilson 95% interval reported separately. Chance performance
only limits this tested attacker; it does not prove noninterference.

`results.json`, `results_table.md` and `leakage_matrix.png` label this matrix
**live gateway with mock model, local run**. These localhost process measurements
do not establish Docker isolation or production behavior. Local CPU/I/O load,
world-specific processes and overlapping runs can produce additional confounds.

### Recorded timing results

The completed matrix used 200 held-out runs plus 200 separate training runs per
cell (100 per secret in each split): 3,600 distinct run IDs and 21,600 measured
submissions, scale 0.1, concurrency 8, seed 7391, collector delivery disabled.
Ordinary accuracy was raw 98%, bucket 68.5%, hard timeout 59.5%; boundary accuracy
was 99.5%, 98.5%, 100%; overflow accuracy was 100% in all three arms.
All submission observations had the same status/header fingerprint/body length.
These results show residual timing signals, including under ordinary traffic;
they do not support a claim that bucketing or hard timeout eliminates leakage.
See [the full table and intervals](eval/output/results_table.md),
[observations and scoring data](eval/output/results.json), and
[the matrix chart](eval/output/leakage_matrix.png).

### Feedback: separate live checks and simulated analysis

Per-run two-report budget stays unchanged. Live checks for BOTH seed modes
repeat a report across gateway restart and confirm the third read is pending.
With `probeset`, three independent runs of the same canonical set return the
same range; with default `run` seeding, fresh runs receive fresh noise. Eight
changed sets check variation in both modes. Range outputs are finite: different
probe sets can collide. We check nonconstant variation, not an impossible
guarantee that all different sets have distinct ranges.

Optional `RANGE_SEED_MODE=probeset` uses a keyed HMAC of identity, a canonical
sorted multiset of prompt hashes (duplicates preserved), and Blue config-version
hash. The gateway key never enters logs/responses. Only hashes are stored; no
plaintext probes/rules enter SQLite. Default `run` retains fresh uniform noise
on first report and persistent per-run memoization. Switching to probeset does
not rewrite already memoized reports; use fresh evaluated runs.

The statistical arm is explicitly **simulated feedback analysis (production
range logic, Monte Carlo)**: 200 synthetic probe sets with fixed true counts
spanning 0..32, K=1/3/10/30, both modes, seed 7391. It imports the SAME generator
function passed by the gateway to `Store`, and calls production `Store.report`,
including memoization and the two-read budget. Tests assert function identity
and actual calls. Only synthetic input counts/attempts are seeded directly into
temporary simulation databases. Default/live noise uses `secrets.randbelow`;
simulation injects a fixed-seed uniform source for reproducibility. Probeset
HMAC/rejection sampling uses exactly the same production path in both cases.
K curves use prefixes of each set's fixed 30-run sample bank.

Red's averaging estimate is the mean interval midpoint. We also report the
midpoint of the intersection, its coverage/width, exact-estimate share, the
fraction where TRUTH lies at a returned interval's center, and whether the
averaging estimate equals the INTERSECTION center. These last two are different
metrics: an estimator can choose a midpoint even when truth is not centered.
Counts 0 and 32 are reported separately from the full distribution; the fixed
unclipped interior 12..20 is also shown. Extreme intervals are disjoint ([0,12]
vs [20,32]) and disclose coarse outcomes despite biased midpoint estimates.

The **live gateway with mock model, local run; feedback small subset** cross-check uses 20 sets spanning the full
count range, K=3, both modes, over real HTTP. Feedback-only submissions use a
zero model-delay hint and batches of four; timing cohorts retain their normal
settings and six sequential requests. Live errors are compared to a predeclared
95% count-stratified Monte Carlo predictive interval (2,000 fixed-seed resamples).
Agreement is not proof. A disagreement is flagged prominently; the simulated
results must then NOT be claimed as validated live-feedback behavior.

`feedback_error.png` and every Monte Carlo table carry the simulated-feedback
label. Live checks carry their own small-subset label. Probeset mode is heuristic
protection, not formal differential privacy: slightly changed probes get fresh
noise, and shared seeds reduce independence between legitimate repeated tests.
