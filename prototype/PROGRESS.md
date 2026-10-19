# Round 2 progress log (branch `round2-fixes`)

Resume rule: read this file top to bottom, then `git log --oneline`. Each phase
ends with a commit. Labels: "live gateway, mock model, local run",
"simulated (Monte Carlo)", "real model run, small sample". Missing = NOT RUN.

Machine notes: Windows 11, Python 3.11.15 in `prototype/.venv` (no pip; use
`uv pip install --python .venv/Scripts/python.exe ...`), Docker Desktop 29.6.2,
Compose v5.3.1, 12 CPUs. Host port 8000 is taken by an unrelated local tool
(openagent MCP server), so this machine runs the stack with `GATEWAY_PORT=8088`.

## Baseline (before any change), 2026-10-19

- Host test suite `pytest tests eval/tests`: **32 passed, 2 failed** while Docker
  Desktop was booting. Failures: `test_live_http` (a 0.3 s bucket released at
  0.61 s) and `test_audit_gateway::test_all_required_events...`. Both passed when
  re-run alone (12 s). They are timing-sensitive under CPU load; not weakened.
- Checkpoint commit on `main`: `ca984e3`.

## Phase 0: Docker stack actually run (first time)

What changed
- `docker-compose.yml`: the gateway's host port never worked. Docker publishes
  no ports for a container whose networks are all `internal: true`, so the
  `127.0.0.1:8000` binding was silently inactive. Tried a non-internal network
  with masquerade disabled: Docker Desktop ignored that and the gateway could
  reach 1.1.1.1. Final fix: new secret-free `operator-proxy` (`tcp_proxy.py`,
  plain TCP forwarder) owns the host binding on `operator-net`; the gateway stays
  on internal networks only (`ops-net`, red/blue/model/audit).
- Host port configurable: `GATEWAY_PORT` (default 8000) in compose and `manage.py`.

Results (saved in `evidence/`)
- `compose-ps.txt`: 6 services up, only operator-proxy publishes 127.0.0.1:8088.
- `isolation.txt`: demo inside red-client, **11/11 PASS** (incl. Blue/model IPs).
- `isolation-extra.txt`: from red-client, audit-collector and operator-proxy are
  unreachable (IP and name); gateway, blue-defense and model-mock have no
  internet egress (1.1.1.1:443, 8.8.8.8:53 blocked).
- `audit-docker.txt`: finished run verified **VALID** in the network-less
  verifier; tamper demo: unmodified VALID, 7/7 tamper cases INVALID.
- `tests-in-docker.txt`: **27 passed** inside the verifier container (pre-Phase-1 code).

Next: Phase 1 (audit off the request path).

## Phase 1: audit off the critical path (DONE)

What changed
- `audit_queue.py` (new): durable queue in its own SQLite file
  (`DATA_DIR/audit_queue.sqlite`), per-run `gw_seq` assigned at enqueue, bounded
  (`AUDIT_QUEUE_MAX`, default 10000; overflow flags the run `queue full`, never
  waits), dead-letter table instead of deletion. One process lock around queue
  transactions: without it the event loop and the shipper thread collided in
  SQLite busy-wait (measured a 2.5 s release stall).
- `audit_forwarder.py`: background shipper with its OWN HTTP pool (audit can no
  longer starve Blue/model calls), FIFO retry with exponential backoff
  (0.05 s to 0.5 s), per-attempt timeout `AUDIT_TIMEOUT_SECONDS` (0.3 s; 1 s in
  compose); only the attempted head entry can expire after `AUDIT_GIVE_UP_SECONDS`
  (2 s code default, 30 s in compose, 1 s in audit test fixtures), counted from
  when this process first saw it (restart = fresh window). Expired entries go to
  `audit_dead` and the run is flagged audit_incomplete.
- Collector (`audit_store.py`): full chain + checkpoint check once per stream per
  process, then incremental appends from the cached verified head (no re-read,
  no re-hash, no full verify on every event). Drops duplicate `gw_seq` (lost ack),
  seals a gap as `audit_unavailable`. Format: records carry `gw_seq`; old logs
  without it still verify.
- Verifier reads gateway status from `audit_queue.sqlite` next to `runs.sqlite`.
  Old conservative rule "restart with queued entries => unavailable" removed,
  because replay is now deduplicated.
- Gateway release: `release_at()` sleeps to 3 ms before the deadline, then yields
  until it; Windows host processes request 1 ms timer resolution (`fine_timer`).
  Before this, Windows' 15.6 ms timer tick made release lateness (~28 ms median
  over a 150 ms bucket) depend on event-loop activity. Linux containers: no-op.
- `stats.py` (new): Wilson, two-sample KS (checked against scipy), percentiles.
- `pytest.ini`: `timing` marker; 8 timing-sensitive tests tagged (logic unchanged).

Tests: host `pytest tests eval/tests` = **41 passed** (34 old + 7 new in
`tests/test_audit_queue.py`). Existing-test change: audit fixture sets
`AUDIT_GIVE_UP_SECONDS=1` (outage window) and gained a `lose_ack_once` mode;
no assertion was weakened.

Key result (in-process ASGI, Windows host, 0.15 s bucket, 45 submits per
collector condition, interleaved blocks, 4 runs): medians within ~2 ms, p95
within ~2 ms, KS p between 0.01 and 0.61. No consistent health signal, but a
shift of 2 ms or less is NOT excluded. Live separate-process measurement: Phase 4.

NOT RUN yet: Docker image rebuild with Phase 1 code (do with Phase 2).
Next: Phase 2 (window_hard).

## Phase 2: window_hard (DONE)

What changed
- `POLICY_MODE=window_hard`: one window W (`WINDOW_SECONDS`, default = last
  bucket), compute deadline D = `DEADLINE_FRACTION` x W (default 0.8, so a
  20% margin for cancellation and release overhead). EVERY request (done,
  blocked, error, report, cancelled) is released at exactly W after ASGI
  dispatch (perf_counter, monotonic), same generic 202 envelope.
- Cancelled at D: attempt is marked done; `attempts.cancelled=1`; stdout
  metadata `deadline_cancelled`; audit event `deadline_cancelled`; new
  evaluator-only `GET /v1/run/{id}/evaluation` (after finish) returns
  `{"attempts","safe","cancelled"}`. Red's report is unchanged.
- Queue rule: NO queue. Fixed per-identity in-flight limit
  (`MAX_INFLIGHT_PER_IDENTITY`, default 16). Over it: immediate reject, still
  released at W. Applied only under window_hard, so old baselines stay identical.
- EVAL_MODE gating: `raw`/`bucket` fall back to `bucket_hard` unless
  `EVAL_MODE=1` (stdout `policy_ignored_without_eval_mode`); explicit
  `AUDIT_MODE=off` is honored only with `EVAL_MODE=1`.
- Default stays `bucket_hard`: trial with window_hard as default made 3 existing
  tests fail (they assert first-bucket timing). Reverted, as the brief requires.
- Compose: `WINDOW_SECONDS`, `DEADLINE_FRACTION`, `MAX_INFLIGHT_PER_IDENTITY`.

Utility cost (documented; measured in Phase 3): every response waits the full W
(added latency = W - compute), and any compute longer than D is cancelled
(timeout rate). With the real-model small sample (p99 2.12 s) and W = 3 s,
D = 2.4 s, about 1% of requests would be cancelled (estimate from that sample,
not measured with window_hard).

Tests: host `pytest tests eval/tests` = **46 passed** (+5 in
`tests/test_window_hard.py`). Docker rebuilt: isolation 11/11 PASS, audit VALID,
tamper 7/7 INVALID (`evidence/isolation.txt`, `evidence/audit-docker.txt`).
Inside Docker (Linux): `pytest tests` = **39 passed** (`evidence/tests-in-docker.txt`);
there the collector-health release test shows medians 0.1520/0.1521/0.1523 s
and p95 within ~1 ms (KS p 0.44, 0.12): Linux timers are far tighter than the
Windows host.
Phase 3 harness prepared: `eval/matrix.py` (smoke N=4: audit ON, 128/128 runs VALID).

Next: Phase 3 (live matrix with audit ON, 4 policies + deadline probes).

## Phase 3: live matrix with audit ON (RUNNING at time of writing)

- Command: `.venv/Scripts/python.exe -m eval.matrix --n 200 --train-n 200 --scale 0.1
  --concurrency 8 --seed 7391 --audit --max-minutes 120 --output eval/output/round2`
- Log: `eval/output/round2/run-output.txt`; partial results are saved after every
  cell in `eval/output/round2/results.json` (status field says in_progress/complete).
- If cut off: re-run the same command (it restarts from scratch), or keep the
  saved partial and label it partial. `python -m eval.matrix --render-only` rebuilds tables.
- Early cells: raw 98.5/100/99.0 % (ordinary/boundary/overflow); raw audit check
  1200/1200 runs VALID, 0 dead letters; ordinary/bucket 56.5 % (Round 1: 68.5 %).

## Code written while Phase 3 runs (NOT yet run; tests NOT yet re-run)

- `attack_suite.py` (Phase 4), `tests/test_attack_controls.py`, model
  `CACHE_NAMESPACE=off` control (EVAL_MODE only).
- `eval/feedback_run.py` (Phase 5 runner; saves `eval/output/feedback/`).
- `run_all_evidence.py` rewritten (Phase 6); `--cached` already builds a partial EVIDENCE.md.
- `agent_redteam/`: policies read from `gateway.POLICIES`, override now targets
  operator-proxy, raw sessions set gateway EVAL_MODE=1 (model stays 0), audit on
  by default, new `agent_redteam/README.md` protocol. Sessions NOT RUN.
- DESIGN_NOTES.md: softened one affirmative "proves" sentence.

Next after the matrix: run full tests, commit Phase 3, run attack suite (needs
idle machine; attack 9b loads all CPU cores), then feedback, evidence, README.

## Dashboard handoff — 2026-10-19 (supersedes the RUNNING note above)

- Branch remains `round2-fixes`; no new commit, push or branch created.
- Phase 0 isolation and Phase 1/2 implementations have saved evidence. Phase 3
  matrix STOPPED before completion: **6/16 saved cells**, no active matrix process
  found at this handoff. The file's `in_progress` marker is stale. No long matrix
  rerun was started and no partial results were overwritten.
- Saved raw accuracy ordinary/boundary/overflow: 98.5/100/99%; saved bucket:
  56.5/100/100%. Raw audit checks alone: 1200/1200 VALID. All 10 missing cells,
  including every `window_hard` cell, remain **NOT RUN**.
- Phases 4/5 attack suite, full feedback analysis and external coding-agent
  sessions remain NOT RUN. Encrypted vault/dummy-file layer remains designed.
- Added optional `dashboard/`: local HTML/CSS/JS + FastAPI + SSE, strict metadata
  projections, split Red/evaluator panels, actual release histogram, tiny
  held-out accuracy, isolation/audit buttons, saved matrix/evidence and presenter.
  No gateway/default/existing-test changes. UI uses only internal dash-net; no
  tokens, signing-key mount or Docker socket. Secret-free proxy binds localhost.
- Host operator worker consumes allowlisted file jobs. It refuses demos during
  an active eval.matrix/eval.run; no .env reading. Traffic starts a SEPARATE
  temporary local mock Lab, not the running Compose deployment. Isolation alone
  executes inside the existing Red container when Docker is available.
- Actual tiny window_hard demo: 16 HTTP submissions, scale .1, audit enabled;
  4 training and 4 unseen test groups, 2 requests/group. Test 2/4 = 50%, Wilson
  95% 15.0–85.0%; train 100%, gap 50 points. **Not a completed matrix or proof of
  non-leakage.** All 16 audit runs verified VALID. Histogram includes padding.
- Copy-only audit demo was executed against a newly collected gateway log:
  unmodified VALID, seven tamper cases INVALID. Also verified UI queue → worker
  → result using the audit button. Original logs/checkpoints unchanged.
- New backend tests: 10 passed. Selected backend/audit/queue checks:
  **29 passed, 1 timing test deselected**, recorded in dashboard-tests.txt.
- IMPORTANT: the existing collector timing test FAILED, first during concurrent
  demo activity, then again with dashboard stopped in a standalone rerun:
  healthy median .16315s vs slow .17892s, gap .01577s exceeds .010s. Do not claim
  all tests pass or blame only concurrent load. Cause unresolved; no assertion
  weakening or gateway edits. See evidence/dashboard-timing-check.txt.
- Compose configuration validates with explicit empty env file / no interpolation.
  Docker Engine unavailable now: new dashboard container runtime and network
  enforcement **NOT RUN**; topology test is static. Historical 11/11 Docker
  isolation / 39 tests remain historical, not fresh dashboard verification.
- Compute duration and per-request model completion were never logged and show
  NOT RUN. No fake lane animation or model score. Final-report fields are only
  filled after actual report reads; the saved first demo did not run report reads.
- README includes exact standalone / Compose / worker / shutdown commands.
  Screenshots and dashboard-specific checks are under evidence/dashboard-*.

## Separate /story page — 2026-10-19

- User explicitly requested keeping the old dashboard. Its index.html, app.js
  and style.css are untouched; `/` still serves that original operator view.
  Added `/story`, `/api/story` and `/api/story/events` plus separate assets.
- New story has four presentation screens, previous/next request selection,
  five-step request narrative, matched Red envelopes, evaluator-vs-Red reports,
  report budget, audit count/status, and explicitly scoped validity.
- Policy/audit columns and raw-baseline wording exist only in the new story
  evidence view; external-agent rows aggregate once. Missing comparison bars
  are hatched NOT RUN. Matrix still **6/16**, no long rerun started.
- Added a four-submission `story` worker action. It uses the existing real HTTP
  local mock Lab and only reads/writes evaluator records AFTER response release.
  No gateway, Blue, model or existing test changes. No real model API calls.
- Actual CLI demo and UI-button end-to-end demo both completed. Each: four exact
  202/64-byte pending envelopes; A allowed 1/2, B allowed 2/2; both Red ranges
  [0,2], repeats unchanged, third report read pending, budget 0/2. Both audit
  chains VALID with 19 events each. This small range demo is not formal privacy.
- Model output and compute duration are not captured, not fabricated. The
  model card labels the fixed dummy backend as configuration; not-allowed
  requests skip the model by gateway control flow. Exact rule-firing trace
  is also absent. These gaps stay visible in technical details.
- Run validity remains INCOMPLETE: the localhost story is not a Docker
  isolation test and has no sufficiently powered matched timing evaluation.
  Historical isolation / a different demo's accuracy cannot certify it.
- Fixed a reproduced Windows PermissionError when a reader briefly locked
  state.json during atomic replacement. Six bounded retries keep the worker
  alive; a permanent lock retains the last valid file. The one-command launcher
  supervises the worker so it cannot silently die behind an apparently live UI.
- `python -m dashboard.story_demo` runs UI + worker together, localhost only;
  refuses active matrix. README has exact commands. Ctrl+C stops both.
- **29 story/dashboard tests passed** (19 new story cases + original 10).
  Includes secret filtering, verdict rules, incomplete handling, old-route
  preservation, report correlation and Windows lock regression. The earlier
  collector timing failure is unresolved and was not rerun for this UI work.
- Evidence: story-results.json, story-tests.txt, story-request.png,
  story-comparison.png. Audit results were verified on temporary Lab artifacts
  during the demo; the exported story JSON is not independently signed, and
  the temporary signing-key/log directories are not retained or served.
- Docker runtime for the new UI remains NOT RUN; no commit/push/branch created.

## Robot actor stage — 2026-10-19

- `/story` now leads with an SVG actor map: Red attacker robot, Blue guard robot,
  neutral mock-model face, gateway shield and audit. Original `/` is unchanged.
- Small runner now records controller events and environment lifecycle. Attempt
  writes happen before the measurement clock; result reads/writes after release.
  Gateway, Blue, model and existing tests remain unchanged. No real API calls.
- UI job completed with bucket_hard: 4 requests, 20 real controller events,
  all exact pending envelopes, both audit chains VALID with 19 events each.
- Live pulses require recorded events; slow playback is labelled REPLAY and
  has pause/resume. Model path is an inference, not an invented output trace.
  Browser checked that environment-ready replay does not show a future result.
- PASS is scoped to the output envelope. Isolation/timing validity remains
  incomplete; matrix still 6/16. No long rerun or claim of complete security.
- 31 story/dashboard tests pass. Browser verified real execution and replay.
  Evidence under robot-stage* and stage-tests.txt. Local server kept available
  for the user's requested demonstration.

## One-button story — 2026-10-19

- Simplified `/story` to one main play/pause/replay button, one active character,
  short Hinglish narration and a visible final result. Other actors dim.
- Stopped Red attempts shake; verified generic output envelopes get flower/leaf
  celebration. Missing/failed evidence never celebrates. Reduced motion supported.
- Comparison uses saved ordinary raw vs original-bucket timing cells (98.5% vs
  56.5%, 200 unseen runs each). Separate mock experiment, not whole-system proof.
- Detailed controls/evidence collapsed. Original `/` and gateway behavior unchanged.
- Playback is a simplified reconstruction from one recorded HTTP request; no
  invented LLM answer/compute trace, no fresh API calls or long matrix rerun.
- 32 Python story/dashboard tests and four JS playback tests pass. Browser checked
  actor opacity and completion/flower elements; screenshot `evidence/simple-story.png`.
- Local UI kept running for the requested demo. Earlier collector timing failure
  remains unresolved; Docker runtime verification for this UI remains NOT RUN.

## Complete story report tables — 2026-10-19

- Replaced the bucket-only comparison with five visible evidence tables: all 16
  planned timing arms; real DeepSeek raw vs gateway output and latency cost; all
  saved check summaries; 11 isolation and 8 audit cases; every saved story request,
  report-repeat, third-read-budget and audit result. No extra main buttons.
- Missing arms remain NOT RUN; unplanned cells are distinct. Boundary/overflow
  leakage and the unresolved collector timing FAIL stay visible. Historical Docker
  PASS does not certify this story deployment. No full matrix/API rerun started.
- Story-only backend extracts known case names/statuses from bounded saved logs
  and numeric/provider fields from real artifacts. No raw prompts, outputs or keys
  are exposed; original dashboard and gateway behavior unchanged.
- 34 Python and six JavaScript checks pass, including failure/missing-data handling
  and retention of all planned arms. Local server remains available on :8090.
