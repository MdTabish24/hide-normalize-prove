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
