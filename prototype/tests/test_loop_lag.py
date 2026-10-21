"""Opt-in event-loop lag diagnosis: only with EVAL_MODE=1 and LOOP_LAG_LOG=1; Red-visible replies are unchanged."""
import asyncio
import json
import time

from test_gateway import auth, client_for, configure, generic, settings, submit  # noqa: F401 (fixture)


def lag_rows(config):
    from pathlib import Path
    path = Path(config["DATA_DIR"]) / "loop-lag.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def test_a_blocked_loop_is_recorded_only_when_the_flag_and_eval_mode_are_set(settings):
    async def scenario(config):
        async with client_for(config) as (app, client):
            await configure(client, config)
            time.sleep(0.4)  # Blocks the event loop on purpose.
            await asyncio.sleep(0.25)
            response, _ = await submit(client, config, "hello", "r")
            generic(response)  # Red-visible reply is unchanged either way.
    on = dict(settings, EVAL_MODE="1", LOOP_LAG_LOG="1")
    asyncio.run(scenario(on))
    rows = lag_rows(on)
    assert rows and max(r["lag"] for r in rows) >= 0.3 and {"t", "lag", "background", "inflight", "tasks"} <= set(rows[0])


def test_flag_is_ignored_without_eval_mode_and_off_by_default(tmp_path, settings):
    async def scenario(config):
        async with client_for(config) as (app, client):
            await configure(client, config)
            time.sleep(0.4)
            await asyncio.sleep(0.25)
    no_eval = dict(settings, LOOP_LAG_LOG="1")
    asyncio.run(scenario(no_eval))
    assert lag_rows(no_eval) == []
