"""Opt-in LOOP_OFFLOAD=1: store and audit-queue work runs in worker threads; behaviour and Red's replies are unchanged."""
import asyncio
import sqlite3
from contextlib import closing

from test_gateway import auth, client_for, configure, generic, settings, submit  # noqa: F401 (fixture)


def run(config):
    out = {}

    async def scenario():
        async with client_for(config) as (app, client):
            await configure(client, config)
            for index, prompt in enumerate(("hello", "pineapple", "orchard")):
                response, _ = await submit(client, config, prompt, "r-" + str(index))
                generic(response)
            await client.post("/v1/run/r-0/finish", headers=auth(config, "evaluator"))
            with app.state.store.connect() as db:
                out["attempts"] = db.execute("SELECT done, safe, cancelled FROM attempts ORDER BY id").fetchall()
            out["audit_rows"] = len(app.state.store.audit_queue.head(50) or [])
            with closing(sqlite3.connect(app.state.store.database)) as db:
                out["journal"] = db.execute("PRAGMA journal_mode").fetchone()[0]
    asyncio.run(scenario())
    return out


def test_offload_gives_the_same_stored_results_and_uses_wal(settings):
    base = run(dict(settings))
    fast = run(dict(settings, LOOP_OFFLOAD="1", DATA_DIR=str(settings["DATA_DIR"]) + "-offload"))
    assert fast["attempts"] == base["attempts"] == [(1, 1, 0), (1, 0, 0), (1, 1, 0)]  # every attempt finished, same decisions
    assert fast["journal"] == "wal" and base["journal"] != "wal"
