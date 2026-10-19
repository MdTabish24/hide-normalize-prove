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
