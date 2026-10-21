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

## Paired explanatory story and implementation audit — 2026-10-19

- Two synchronized panels, four seconds/step, play/pause + manual next. Shows
  actual Blue decision/reason, known mock output, observed cancellation, compute
  duration, release schedule and Red response. Inactive actors dim. All evidence
  tables retained; implementation coverage lists 12 controls and honest gaps.
- Added opt-in EVAL_MODE + DEMO_TRACE private telemetry after response release;
  default gateway policy, replies and normal evaluation telemetry unchanged.
  No arbitrary output/prompt/rule recording. Two trace gating/privacy tests pass.
- New controller made eight actual submissions across raw timing / bucket_hard,
  with same rule/prompts. Model remains mock; real DeepSeek output is separately
  saved/offline. Both paired audits VALID (11/12 events). Protected blocked vs
  allowed measured 0.342s/0.630s: timing equality is NOT established.
- 41 selected non-timing Python checks, four existing timing checks and eight JS
  checks pass. Prior collector timing failure unresolved. No new real API calls,
  heavy matrix run, complete-security claim or changes to original dashboard.
- Artifacts under evidence/paired-*. Implementation gaps documented in
  IMPLEMENTATION_STATUS.md. Local server kept available for the requested demo.

## English visual scenes, separate evidence page — 2026-10-19

- Removed all tables/coverage from `/story`; moved them intact to a separate
  English `/story/evidence` route. No changes to original `/` or gateway behavior.
- Added seven selectable visual scene families for output, timing, isolation,
  vault/identity, feedback, audit and A/B evaluation. Saved measurements supply
  outcomes; unmeasured baselines and missing controls remain grey. No invented
  insecure deployment or new API/matrix run.
- Boundary diagram, sealed-config/identity icon, time/accuracy meters, report
  range/budget and broken audit chain now show what the text described. Actor
  emphasis and four-second playback remain; manual next and one scene picker.
- Browser verified all seven scene families, zero tables on main page, English
  rendered text, separate evidence tables (25 checks / 19 cases / 12 controls).
- 36 Python UI checks and nine JS checks pass. Previous collector timing failure
  remains unresolved. User-requested local server kept running.

## Live actions on the visual demo — 2026-10-19

- Connected `/story` to the existing allowlisted host worker: one Run test now
  action for timing, Docker isolation, report budget, signed audit, tiny A/B.
  Playback never executes tests; real DeepSeek replay and vault inspection have
  no live action. No real API call or new gateway policy change.
- Queue IDs correlate completion to the requested job. A failed fresh audit or
  isolation attempt cannot reuse historical PASS. During a run, previous results
  are hidden. Fresh smoke results do not borrow saved matrix numbers; playback
  stays in the selected scenario. The mock backend label is always visible.
- Browser executed paired timing (8 submissions, all exact envelopes, both audit
  chains VALID), fresh audit (original VALID, 7 tampered copies INVALID), report
  checks (stable range, third read pending, both run audits VALID), A/B smoke
  (16 submissions, 4 train / 4 unseen groups, 2/4 correct). No matrix claim.
- Docker isolation attempt failed because the Linux Engine was unavailable.
  `docker desktop start --detach` was attempted; subsequent status/info still
  failed. The UI showed no fresh result instead of the historical PASS.
- 37 selected Python checks, 12 JS checks pass. Existing security gaps and the
  earlier collector timing failure remain unresolved. Proof:
  evidence/live-controls-verification.json, evidence/live-controls-browser.png.
- Local UI/worker kept running at http://127.0.0.1:8090/story. Not committed/pushed.

## Vault and opt-in real backend — 2026-10-20

- Implemented gateway-only padded AES-GCM records for Red prompts, Blue config
  and model outputs. 32 KiB per record, authenticated role/run/identity binding,
  one cover read per operation; legacy Blue config migrates without key rotation.
  Not ORAM: names, counts and host access patterns are not hidden.
- Finished-run artifacts require evaluator authorization; Red/Blue get pending.
  Actual Blue decision is distinct from downstream failure/cancellation.
- Added DeepSeek adapter (official current endpoint, deepseek-flash default,
  environment key, no history/tools, random first-message nonce, 128-token cap,
  six-second deadline, at most one 429/503 retry). No mock fallback.
- Optional real Compose overlay keeps the model on internal model-net; only an
  authenticated, fixed-destination CONNECT broker has external egress. Key only
  in adapter container. Overlay defaults to unscaled 3/6/9 buckets and EVAL_MODE=0.
- `python -m dashboard.real_demo` prompts for the key privately and starts 8091
  with a separate worker queue. Live DeepSeek compares private execution with
  Red's view of the SAME real request. Model text stays in operator memory;
  persisted demo evidence contains hashes/metadata only. `--docker` uses the
  real Docker gateway instead of localhost subprocesses.
- Full tests initially exposed collector checkpoint publication and event-loop
  SQLite contention. Fixed locked-checkpoint retry/restart recovery without
  re-signing unsigned tails; moved prompt I/O off loop, serialized Store commits,
  published output ref + completion in one transaction, warmed startup resources.
- Final full prototype suite: 106 passed, one TestClient deprecation warning.
  Includes actual HTTP subprocess/restart tests and local TLS CONNECT contract.
  JavaScript suite: 13 passed. No real model API request was made.
- External blockers remain: no DEEPSEEK_API_KEY in process/user environment;
  Docker Linux Engine unavailable, and this session cannot start com.docker.service.
  Compose configuration validates; new real Docker image/isolation not run.
- Remaining scope: hosted KV reset, attestation, independent witness, hardware/
  host protection, full timing matrix. Historical measurements stay historical.
- Refreshed mock HTTP comparison after the vault change: four submissions/arm,
  all exact envelopes, both signed audit chains VALID (11/12 events). Browser
  verified the unavailable-key guard, 32 KiB coverage and test evidence. Evidence
  projection replaces the old host-suite NOT RUN with the recorded 106 PASS;
  historical failures remain. Follow-up: 28 story tests and 13 JS checks pass.

### Measured control comparisons
- Added `dashboard.control_run`: actual temporary-file vault comparisons, local
  HTTP role/report checks, persistent budget after process restart, and eight
  copied-log JSON-read vs signed-verifier comparisons. No API key required.
- `/story` now has a live controls action for Vault, Audit and Final report, with
  measured pairs replacing their absent baselines. Exact counts are explicitly
  private evaluator references; JSON-only parsing is a diagnostic baseline.
- First run: encrypted marker absent, 32 KiB records, wrong owner rejected;
  evaluator got two records, all three unauthorized callers got pending;
  stable report, third read and post-restart read withheld; original audit VALID,
  seven altered copies INVALID. Saved counts/booleans contain no dummy payloads.
- Docker Engine and real DeepSeek calls are still unverified; they are not
  relabelled PASS. Remaining matrix arms and missing controls remain visible.
- Validation: 43 Python control/story/dashboard checks, 16 JavaScript checks
  passed. Browser live job completed and displayed the measured audit pair.
  Fixed completion projection for the new controls action (otherwise the UI
  remained queued despite a completed worker). Evidence:
  `evidence/measured-controls-verification.json`, `controls-comparison.json`,
  `measured-controls-audit.png`.

## 2026-10-21 catch-up (matrix, attack suite, continue variant, real batch) and Step 0

What changed since Phase 3 (all committed on `round2-fixes`)
- Timing matrix 16/16 cells (raw, bucket, bucket_hard, window_hard; N=200 unseen runs/cell, seed 7391, scale 0.1).
  bucket_hard leaks on boundary/overflow/deadline (98-100%); window_hard 49-58% but cancelled ~100% of long
  requests in overflow/deadline cohorts (vacuous 50%).
- Opt-in `WINDOW_CONTINUE=1` (window_hard only): same fixed release, compute continues in the background up to
  4x the window, shares the per-identity in-flight limit, late attempts counted. Two repeats (round2c, round2d):
  Red A-vs-B accuracy 46-56%, 0% cancelled; audit 1753/2000 VALID in run 1 (247 INVALID, cause unknown) and
  2000/2000 in run 2.
- Attack suite run (see `attack_suite_results.json`): network, filesystem, roles, error oracle, cache (95% -> 45-48% with
  namespace), scan, repeat reads BLOCKED; noisy neighbour, CPU slip, extreme counts, cross-run averaging LEAKED;
  Docker noisy neighbour (9c): median unchanged, p95 grows, CPU pinning did not help. Verdict rule aligned with README.
- Dashboard: /history (dated, hash-checked saved runs) and /why (per-channel baseline vs solution, usability cost,
  short summary on top, detail collapsed).
- Real model: `dashboard.real_batch` (real 3 s window, window_hard + continue, 60 requests, ~36 provider calls):
  release 3.007-3.131 s, 1 reply shape, 0 rule disclosures in 36 outputs, 0 late/cancelled, audit 6/6 VALID
  (`evidence/real-batch-1792576001.json`). Small sample; no statistical timing claim.
Tests: host suite 129+ passed; one timing test (`test_collector_healthy_slow_down_give_same_release_times`) is load
sensitive and passes on an idle machine.
NOT RUN: CPU quota/fair admission, meter feedback, side-by-side story view, window_continue under noisy neighbour,
real-model timing matrix at scale, attack suite 8b (Docker volume scan).

### Step 0: commit and push
Checked `.env` and `dashboard/runtime/` are git-ignored (`git check-ignore`), scanned the diff for keys/tokens,
committed the real-batch summary (aggregate only, no model text) and pushed `round2-fixes`. Not merged into main.
Next: Step 1 (read-only analysis of the 247 INVALID runs).

### Step 1: why 247 of 2000 runs were INVALID in `window_continue` run 1 (read-only, no code changed)
Data: `eval/output/round2c/results.json` (audit_checks), `matrix_continue_out.txt`, `verify_audit.py`, `eval/run.py`, `gateway.py`.
Counts by verifier reason (2000 runs, 1000 per world): VALID 1753; "missing or unreadable audit/checkpoint/key/status file" 247;
sequence gap 0; event hash mismatch 0; checkpoint signature invalid 0; duplicate/replay 0; "audit_unavailable recorded" 0;
"gateway audit events still pending" 0; "gateway audit status missing" 0. All 247 are in world 0 (world 1: 1000/1000 VALID,
queue empty, 0 dead letters).
Gateway queue after the 120 s drain, world 0: 3164 events pending + 518 dead letters (expired after the 30 s give-up) = 3682
undelivered events. Each matrix run emits 14 gateway events (6 submits x [submit_received + bucket_released] + finish
[bucket_released + run_finished]); 3682 / 14 = 263 runs' worth, close to but not exactly the 247 invalid runs (about 16
runs' worth unexplained).
What this means: the failures are delivery failures (queue not drained), not integrity failures. No hash, signature,
sequence or duplicate problem was found in any run. The reason string is a catch-all (`except OSError, ValueError, TypeError,
KeyError, sqlite3.Error`), so it merges "log missing" and "no checkpoint because the chain never reached `complete`";
the saved data cannot separate those two. The collector's stderr was discarded (`stderr=DEVNULL` in `eval/live.py`
Server.start) and the temporary audit directories were deleted, so the cause (collector hang/crash, or a stalled gateway
shipper behind a FIFO head) is NOT determined. Run 2 (same settings) had 2000/2000 VALID, so it is not deterministic.
FIFO retry in `audit_forwarder.py` means one undeliverable head holds back everything behind it, which matches a large
pending count plus a slowly growing dead-letter count.
Proposed fixes (NOT implemented): (1) keep the collector's stdout/stderr in the matrix harness; (2) poll collector liveness
during a matrix and fail loudly; (3) split the verifier's catch-all into separate reasons (log missing / checkpoint missing /
sqlite error); (4) keep the audit directories of any matrix with INVALID runs; (5) re-run window_continue with (1)-(4) and
report how often it recurs. Until then, the variant's audit is reported as FAIL (1 of 2 repeats).
Tests: none run (read-only). NOT RUN: reproduction of the failure.
Next: Step 2 (feedback meter). First commit PARAMS.md with all new parameters before any evaluation.

### Step 2: feedback meter (opt-in) and its evaluation
What changed
- `PARAMS.md` v1 committed BEFORE any run (`f8da51c`): B=10, delta_up/down 0.30, inner band 0.10, reads 3 per run / 12 across runs,
  noise arm q=0.15, N 300 train + 300 unseen, 300 utility trials, seeds 20261021/22, query limit 150.
- `meter.py` (pure logic), `storage.py` (tables `meter_state/_batches/_log/_reads/_identity` and `meter_update`, `meter_read`,
  `meter_evaluation`, `last_attempt_safe`), `gateway.py` (`FEEDBACK_MODE=none|meter|exact`, default `none`).
  Score of a batch = share of its probes recorded `safe=1` (Blue allowed). State recomputed only after a completed batch, in a worker
  thread after the response (never on Red's submit path). Hysteresis with two thresholds and an inner band; reference moves only on a
  state change; batch content hashed with the gateway key so the same batch always gives the same state (cached per identity, the
  reference chain does not move); optional keyed noise q (default 0); read budgets persisted in SQLite, beyond budget the identity's last
  returned state is repeated (same 64-byte envelope). `exact` is ignored (treated as `none`) unless `EVAL_MODE=1`.
  Red-visible endpoint `GET /v1/run/{id}/feedback` returns the standard envelope in every mode; evaluator-only
  `GET /v1/run/{id}/meter-evaluation` shows true per-batch scores next to what Red saw.
- `eval/meter_eval.py` (simulation with the production `Store` and `meter.py`), results in `eval/output/meter/` (json, table, chart).
Tests: 10 new in `tests/test_meter.py` (hysteresis, batching, idempotence, restart-proof budgets, one probe cannot flip the state,
identical envelopes, exact unreachable without EVAL_MODE, end-to-end through the gateway). Existing gateway/window/audit tests unchanged and passing.
Results (simulated, production meter code; 50% = guessing):
| Arm | Red's A-vs-B accuracy (95% Wilson) | Finds planted bypass within 150 probes | Median probes |
|---|---:|---:|---:|
| none | 50.0% (44.4-55.6) | 10.3% (7.4-14.3) | n/a |
| exact (EVAL only) | 100.0% (98.7-100) | 100.0% (98.7-100) | 7 |
| meter q=0 | 100.0% (98.7-100) | 100.0% (98.7-100) | 60 (4 reads) |
| meter q=0.15 | 89.0% (85.0-92.1) | 68.7% (63.2-73.7) | 60 |
| meter repeated reads | 50.0% (44.4-55.6) | NOT RUN | n/a |
Honest reading: the meter does NOT hide Blue's rule from a targeted attacker. With q=0 Red tells rule A from B perfectly (same as exact)
and still finds the planted bypass every time, but needs about 8-9x more probes (median 60 vs 7) and 4 reads. Noise q=0.15 lowers both
the leak (89%) and the success (68.7%). "Repeated reads" reaches 50% only because that schedule spends the 3-read budget on the
uninformative first batch; it is not the worst case (use the "meter q=0" arm for that). The meter is a utility/leak trade-off, not a fix.
NOT RUN: real model, release-time measurement of the feedback endpoint, Sybil identities (each simulated run uses a fresh identity),
repeated-reads utility arm, an attacker that adapts beyond the scripted Red. The chart script had a plotting bug (error bar of -1e-16);
fixed and the chart re-rendered from the saved results without re-running the evaluation.
Reproduce: `python -m eval.meter_eval` (about 17 min, CPU only); `pytest tests/test_meter.py`.
Next: Step 3 (side-by-side dashboard story view).
Full suite after Step 2: 147 passed, 2 failed (`test_collector_healthy_slow_down_give_same_release_times`, and
`eval/tests/test_eval.py::test_tiny_live_http_full_harness` with an httpx ReadTimeout). The suite took 14 min instead of ~4: Defender, Chrome
(~80% CPU) and WMI were busy. On a re-run the eval test passed; `test_full_queue_flags_run_and_never_delays_release` failed once under load and
passed alone (4 s); `test_collector_healthy_slow_down_give_same_release_times` still failed on the loaded machine (it passed on an idle
machine earlier today). These are the known load-sensitive timing tests; no test was weakened. JS tests 16/16.

### Step 3: side-by-side dashboard view (`/duel`)
What changed
- `dashboard/duel_run.py`: records ONE 20-request sequence under two policies, each on a fresh live gateway with the mock model
  (label "live gateway, mock model, local run", scale 0.1): left `raw` timing, right `window_hard` + continue + feedback meter. Same auth, Blue
  filter, encryption, output shaping and audit in both. Per request it keeps what Red saw (status, size, release time, exact envelope) and, from the
  gateway database, what the evaluator knows (Blue allowed, model called/completed, late, cancelled). `eval/live.py` Lab gained an `extra_env`
  parameter (empty by default) so the meter can be switched on for the right arm only.
- `dashboard/duel.py`: allowlisted projection. No prompt text and no keyword is ever served (only "keyword rule A"); Red-visible text never says
  blocked or allowed; missing or partial recordings show NOT RUN / PARTIAL and never fill the missing arm. Accuracy under each panel is read from the
  saved matrix (raw: 98-100% over 3 cohorts; window_hard + continue: 51-56%, worse of two repeats, 5 cohorts; 200 unseen runs per cohort).
- `/duel` (`static/sbs.html|js|css`, pure logic in `sbs_logic.js`): slow-motion player (Play/Pause/Step/Back/Reset, 0.25x-2x) that reveals 6 steps per
  probe (Red sends, fixed clock, Blue decides [evaluator only], model, what Red sees, report/meter) in plain Hinglish with the reason for every decision;
  per-probe release-time bars (colour = evaluator only); meter state and reads left in the Red panel and the true per-batch score in the evaluator-only
  box; audit status per arm. Presenter mode: 4 screens (side-by-side, isolation + audit tamper, comparison chart with NOT RUN hatched, limits).
  Playback of a recorded run, not live. Job action `duel` and a "Record a fresh run" button use the existing worker queue. Metadata only, localhost,
  same CSP; the gateway request path is untouched.
Recording made on 2026-10-21 (`dashboard/runtime/observations/duel.json`, git-ignored): raw release 0.04-1.15 s (blocked median 0.05 s vs allowed median 0.27 s,
gap 222 ms; the slow probe 1.15 s); window_hard + continue 0.91-0.94 s for all 20 (gap 1 ms), probe 13 finished after the window (late) without cancel;
meter read STABLE after probe 10 (true batch score 20%) and IMPROVING after probe 20 (90%), 1 of 3 reads left; both audits VALID (43 events each).
Tests: `tests/test_duel.py` (7, including the recorder end-to-end), `tests/sbs_logic.test.cjs` (5, found and fixed two bugs: playback needed one extra tick at
the end; `percent(null)` drew a 1% bar for a NOT RUN value). 77 related Python tests, 16 + 5 JS tests pass.
NOT RUN: a live (not recorded) demo batch from the UI button, real model in this view, a separate dashboard container run of the new page.
Reproduce: `python -m dashboard.duel_run` (about a minute), then `uvicorn dashboard.app:app --port 8095` and open `/duel`.
Next: Step 4 (noisy neighbour, only when the machine is idle).

### Step 4, part 1: does overload carry Blue's secret? (load-observer, PARAMS v2) and the audit finding
Harness `eval/load_observer.py` (fixed in PARAMS.md v2 before the run): world 0 (rule A) blocks the flood prompts, world 1 (rule B) allows them (worst case for a
work difference); the observer is Red itself (the system has only three role tokens, so no second Red identity exists). 12 flood workers + 6 neutral observer
probes per run, 100 train + 100 unseen test runs per cell, timings x0.1, window 0.9 s, mock model, seed 20261023, audit ON.
Results (label "live gateway, mock model, local run"; 95% Wilson; 50% = guessing):
| Cell | Observer's A-vs-B accuracy | Verdict (README thresholds) | Observer release time median / p95 / max | Observer requests cancelled | Audit after a 20 s drain |
|---|---:|---|---|---:|---|
| bucket_hard (default) | 78.0% (68.9-85.0%) | LEAKED | 0.626 / 1.334 / 3.154 s | 80 | world 1: 9973 pending, 888 dead letters |
| window_hard + continue | 73.0% (63.6-80.7%) | LEAKED | 0.946 / 1.107 / 2.631 s | 0 | world 0: 9980 pending, 829 dead letters |
(An earlier attempt at the window_continue cell crashed at 40/200 runs with an httpx ReadTimeout when the laptop went to sleep; it produced no result and was rerun
with a keep-awake process.)
Reading: under a worst-case flood the tested observer separated rule A from B even with the fixed window + continue, so the earlier hope that
window_hard + continue is immune to the shared-load channel is NOT supported by this test. CAUTION (confound): in both cells ONE world's audit pipeline
backed up (a different world each time) while the other stayed healthy, so the classifier may partly be reading audit trouble, not the work difference. This
must be separated with audit-OFF control cells (to be fixed in PARAMS v3 before they are run).
Audit root cause (new, supported by measurement, not yet fixed): no server died (`dead_servers` empty, stderr empty except a harmless Windows socket reset in the
model). The collector alone appends >1000 events/s even across 250 runs (micro-benchmark, same code). But the gateway shipper (`audit_forwarder.py`) delivers
strictly one event per HTTP round trip (head -> POST -> ack), so under load its throughput is limited by the round-trip time (tens of ms, about 10-30 events/s)
while the flood offers about 30+ events/s; the outbox grows to its 10000-entry cap and entries expire after the 30 s give-up (dead letters). This matches the
247-INVALID repeat (delivery failures, no integrity failures). Candidate fix (NOT built): batch delivery (`head(limit=N)` already exists; a collector
`/append_batch`, order and per-run chain preserved), opt-in. Per-run lanes are the alternative.
NOT RUN: audit-OFF control cells, any mitigation cell, attack 9c re-run, a no-flood control.
Next: fix PARAMS v3 (audit-off controls + mitigation cells), then build the opt-in fixes and measure them; the long runs need an idle laptop.
