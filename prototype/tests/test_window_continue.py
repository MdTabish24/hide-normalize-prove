"""Opt-in window_hard variant (WINDOW_CONTINUE=1): same fixed release, but compute is not cancelled at the deadline."""
import asyncio
import json
import time

import pytest

import model
from test_gateway import auth, client_for, configure, generic, settings  # noqa: F401 (fixture)
from test_window_hard import WINDOW, at_window, timed

GAP = 0.9  # Longer than MISS_SECONDS below, so background compute has finished.


def cont_settings(settings, **extra):
    return dict(settings, POLICY_MODE="window_hard", WINDOW_SECONDS=str(WINDOW), WINDOW_CONTINUE="1", **extra)


@pytest.mark.timing
def test_slow_compute_is_released_at_window_but_still_completes(settings, monkeypatch):
    monkeypatch.setenv("MISS_SECONDS", "0.5")  # Longer than the 0.24 s deadline, shorter than the hard maximum.
    config = cont_settings(settings)

    async def scenario():
        async with client_for(config) as (app, client):
            await configure(client, config)
            red = auth(config, "red")
            slow, slow_time = await timed(client, "POST", "/v1/submit", json={"run_id": "c", "prompt": "hello"}, headers=red)
            fast, fast_time = await timed(client, "POST", "/v1/submit", json={"run_id": "c", "prompt": "pineapple"}, headers=red)
            generic(slow), generic(fast)
            assert at_window(slow_time) and at_window(fast_time)  # Red cannot tell them apart by release time.
            await asyncio.sleep(GAP)
            assert model.cache  # Compute was NOT cancelled at the deadline.
            with app.state.store.connect() as db:
                rows = db.execute("SELECT done, safe, cancelled, late FROM attempts ORDER BY id").fetchall()
            assert rows == [(1, 1, 0, 1), (1, 0, 0, 0)]  # Allowed finished late; blocked finished in time.
            await client.post("/v1/run/c/finish", headers=auth(config, "evaluator"))
            sealed = await client.get("/v1/run/c/evaluation", headers=auth(config, "evaluator"))
            assert sealed.json() == {"attempts": 2, "safe": 1, "cancelled": 0, "late": 1}
            report = await client.get("/v1/run/c/report", headers=red)
            assert set(report.json()) == {"status", "safe_range"}  # Red's report shape is unchanged.
    asyncio.run(scenario())


@pytest.mark.timing
def test_hard_maximum_cancels_and_audit_records_it(settings, monkeypatch, capsys):
    monkeypatch.setenv("MISS_SECONDS", "2.0")
    config = cont_settings(settings, WINDOW_CONTINUE_MAX_SECONDS="0.6")

    async def scenario():
        async with client_for(config) as (app, client):
            await configure(client, config)
            response, elapsed = await timed(client, "POST", "/v1/submit", json={"run_id": "h", "prompt": "hello"},
                                            headers=auth(config, "red"))
            generic(response)
            assert at_window(elapsed)
            await asyncio.sleep(0.9)  # Past the 0.6 s hard maximum.
            with app.state.store.connect() as db:
                assert db.execute("SELECT done, cancelled, late FROM attempts").fetchone() == (1, 1, 0)
            await client.post("/v1/run/h/finish", headers=auth(config, "evaluator"))
            sealed = await client.get("/v1/run/h/evaluation", headers=auth(config, "evaluator"))
            assert sealed.json() == {"attempts": 1, "safe": 1, "cancelled": 1}
    asyncio.run(scenario())


@pytest.mark.timing
def test_background_work_counts_against_the_identity_limit(settings, monkeypatch):
    monkeypatch.setenv("MISS_SECONDS", "0.5")
    config = cont_settings(settings, MAX_INFLIGHT_PER_IDENTITY="2")

    async def scenario():
        async with client_for(config) as (app, client):
            await configure(client, config)
            red = auth(config, "red")
            first = [asyncio.create_task(timed(client, "POST", "/v1/submit", json={"run_id": "l", "prompt": f"hello {i}"}, headers=red))
                     for i in range(2)]
            await asyncio.sleep(0.05)
            # Both earlier requests still compute in the background after their release; a third is refused at once
            # (no queue) yet looks identical to Red and is released at the same window.
            third, third_time = await timed(client, "POST", "/v1/submit", json={"run_id": "l", "prompt": "hello 3"}, headers=red)
            generic(third)
            assert at_window(third_time)
            for response, _ in await asyncio.gather(*first):
                generic(response)
            with app.state.store.connect() as db:
                assert db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0] == 2
            await asyncio.sleep(GAP)
            # After the background work ends, the slots are free again.
            fourth, _ = await timed(client, "POST", "/v1/submit", json={"run_id": "l", "prompt": "hello 4"}, headers=red)
            generic(fourth)
            with app.state.store.connect() as db:
                assert db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0] == 3
    asyncio.run(scenario())


def test_continue_needs_a_valid_hard_maximum(settings):
    from gateway import create_app
    with pytest.raises(ValueError):
        create_app(cont_settings(settings, WINDOW_CONTINUE_MAX_SECONDS=str(WINDOW / 2)))


def test_flag_is_ignored_for_other_policies(settings):
    from gateway import create_app
    app = create_app(dict(settings, POLICY_MODE="bucket_hard", WINDOW_CONTINUE="1"))
    assert app.state.policy == "bucket_hard"
