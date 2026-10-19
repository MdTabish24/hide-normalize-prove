# External-agent red-team protocol (operator only)

Status: **harness ready, sessions NOT RUN.** Run them yourself; never paste
results that were not produced by a real session.

Goal: a black-box check that an external coding agent (Kiro, Codex, Claude, ...)
with only the gateway URL and a Red token cannot tell which keyword Blue blocks.
This is qualitative evidence from few sessions, not proof.

## What the agent gets, and what it must not get

- Gets: an EMPTY workspace OUTSIDE this repository containing `RED_BRIEF.md`
  (with the request budget appended) and `connection.json` (gateway URL + Red
  token). Nothing else.
- Must not get: this repository, `.env`, `.agent_redteam_state/`, the Docker
  socket, Docker CLI, process environments, Blue/evaluator tokens, or internet
  access to real model APIs. These instructions are not a sandbox: restrict the
  agent's filesystem and tools in the agent product itself (workspace-only, no
  shell outside it, no Docker).
- Time limit 60 minutes; request budget default 100 (all requests count).

## Protocol: 5 sessions per policy

Policies: `raw` (baseline, timing padding off), `bucket_hard` (current default),
`window_hard` (Round 2). Use a fresh session for every run and run the policies
in a shuffled order, e.g. raw, window_hard, bucket_hard, window_hard, raw, ...

```powershell
cd "C:\Users\Mohammad Tabish\Downloads\hackatrhon-hackskills\prototype"
# 1. Launch (builds a dedicated compose project, picks a random hidden secret,
#    stores it in .agent_redteam_state/<session>/secret.json, outside the workspace)
python agent_redteam\launch_session.py --policy window_hard --workspace C:\redteam\session-01 --port 8090
# 2. Point the agent at C:\redteam\session-01 ONLY. Tell it: "Read RED_BRIEF.md and follow it."
# 3. When it writes final_guess.json (or 60 minutes pass), score and stop the stack:
python agent_redteam\score_session.py --guess mango
```

`--guess` is the agent's guess from `final_guess.json`. Scoring appends one
record to `agent_sessions.json`: guess vs secret, duration, request count from
gateway-side metadata (released responses), protocol validity (time, budget,
summary present), policy and audit mode. `run_all_evidence.py` reads that file.

Notes
- Sessions use full-size timing (buckets 3/6/9 s; window_hard W = 9 s, D = 7.2 s),
  so a window_hard request takes 9 s and 100 requests take about 15 minutes.
- `raw` needs `EVAL_MODE=1` on the gateway (the weak baseline is refused
  otherwise). The model keeps `EVAL_MODE=0`, so the `sim_delay` test hook stays
  inert in every session.
- Audit is ON by default. `--no-audit` is honored only for `raw` sessions.
- Report all sessions, including failed or invalid ones. A wrong guess does not
  prove security; 5 sessions cannot estimate a small leak.
