"""Round 2 Phase 2: deadline-capped fixed window (POLICY_MODE=window_hard) and EVAL_MODE gating."""
import asyncio
import json
import time

import httpx
import pytest

import model
from audit_forwarder import Forwarder
from common import PENDING
from gateway import create_app
from test_audit_gateway import audited, config_for, drain, headers, verified
from test_gateway import auth, client_for, configure, generic, settings  # noqa: F401 (fixture)

WINDOW = 0.3  # Deadline = 0.8 * WINDOW = 0.24 s.


def window_settings(settings, **extra):
    return dict(settings, POLICY_MODE="window_hard", WINDOW_SECONDS=str(WINDOW), **extra)


async def timed(client, method, path, **kwargs):
    start = time.perf_counter()
    response = await client.request(method, path, **kwargs)
    return response, time.perf_counter() - start


def at_window(elapsed):
    return WINDOW - 0.002 <= elapsed < WINDOW + 0.06


@pytest.mark.timing
def test_every_request_kind_is_released_at_the_window(settings):
    config = window_settings(settings)

    async def scenario():
        async with client_for(config) as (app, client):
            assert app.state.policy == "window_hard"
            await configure(client, config)
            red = auth(config, "red")
            requests = [
                ("POST", "/v1/submit", {"json": {"run_id": "w", "prompt": "hello"}, "headers": red}),      # miss
                ("POST", "/v1/submit", {"json": {"run_id": "w", "prompt": "hello"}, "headers": red}),      # hit
                ("POST", "/v1/submit", {"json": {"run_id": "w", "prompt": "pineapple"}, "headers": red}),  # blocked
                ("POST", "/v1/submit", {"json": {"run_id": "w", "prompt": "x"}, "headers": {"authorization": "Bearer bad"}}),
                ("POST", "/v1/defense", {"json": {"trigger": "x"}, "headers": red}),
                ("POST", "/v1/submit", {"json": {}, "headers": red}),
                ("GET", "/unknown", {}),
                ("GET", "/v1/run/w/report", {"headers": red}),
            ]
            for method, path, kwargs in requests:
                response, elapsed = await timed(client, method, path, **kwargs)
                generic(response)
                assert at_window(elapsed), (path, elapsed)
    asyncio.run(scenario())


@pytest.mark.timing
def test_compute_past_deadline_is_cancelled_released_at_window_and_recorded(settings, monkeypatch, capsys):
    monkeypatch.setenv("MISS_SECONDS", "0.5")  # Longer than the 0.24 s deadline.
    config = window_settings(settings)

    async def scenario():
        async with client_for(config) as (app, client):
            await configure(client, config)
            response, elapsed = await timed(client, "POST", "/v1/submit", json={"run_id": "slow", "prompt": "hello"},
                                            headers=auth(config, "red"))
            generic(response)
            assert at_window(elapsed)
            assert not model.cache  # Backend compute was cancelled, never completed.
            with app.state.store.connect() as db:
                assert db.execute("SELECT done, safe, cancelled FROM attempts").fetchone() == (1, 1, 1)
            # Evaluator-only sealed counts exist only after finish.
            early = await client.get("/v1/run/slow/evaluation", headers=auth(config, "evaluator"))
            assert early.content == PENDING
            await client.post("/v1/run/slow/finish", headers=auth(config, "evaluator"))
            sealed = await client.get("/v1/run/slow/evaluation", headers=auth(config, "evaluator"))
            assert sealed.json() == {"attempts": 1, "safe": 1, "cancelled": 1}
            # Red cannot read it, and Red's own report has no cancellation field.
            generic(await client.get("/v1/run/slow/evaluation", headers=auth(config, "red")))
            report = await client.get("/v1/run/slow/report", headers=auth(config, "red"))
            assert set(report.json()) == {"status", "safe_range"}
    asyncio.run(scenario())
    events = [json.loads(line)["event"] for line in capsys.readouterr().out.splitlines()]
    assert events.count("deadline_cancelled") == 1


@pytest.mark.timing
def test_over_identity_limit_is_rejected_without_queueing(settings, monkeypatch):
    monkeypatch.setenv("MISS_SECONDS", "0.1")
    config = window_settings(settings, MAX_INFLIGHT_PER_IDENTITY="2")

    async def scenario():
        async with client_for(config) as (app, client):
            await configure(client, config)
            jobs = [timed(client, "POST", "/v1/submit", json={"run_id": "c", "prompt": f"distinct prefix {i}"},
                          headers=auth(config, "red")) for i in range(4)]
            for response, elapsed in await asyncio.gather(*jobs):
                generic(response)
                assert at_window(elapsed)  # Rejected requests are not released early.
            with app.state.store.connect() as db:
                assert db.execute("SELECT COUNT(*), SUM(cancelled) FROM attempts").fetchone() == (2, 0)
    asyncio.run(scenario())


def test_deadline_cancellation_reaches_signed_audit(tmp_path):
    config = config_for(tmp_path)
    config.update(POLICY_MODE="window_hard", WINDOW_SECONDS=str(WINDOW))

    async def scenario():
        async with audited(config, {"model_delay": 0.5}) as (app, client, collector):
            await client.post("/v1/defense", json={"trigger": "pineapple"}, headers=headers(config, "blue"))
            await client.post("/v1/submit", json={"run_id": "r", "prompt": "hello"}, headers=headers(config, "red"))
            await client.post("/v1/run/r/finish", headers=headers(config, "evaluator"))
            await drain(app)
            log, _ = collector.paths("r")
            types = [json.loads(raw)["type"] for raw in log.read_bytes().splitlines()]
            assert types.count("deadline_cancelled") == 1
            assert verified(config, collector) == (True, "VALID", 0)
    asyncio.run(scenario())


def test_weak_policies_and_audit_off_need_eval_mode(settings):
    for policy in ("raw", "bucket"):
        assert create_app(dict(settings, POLICY_MODE=policy)).state.policy == "bucket_hard"
        assert create_app(dict(settings, POLICY_MODE=policy, EVAL_MODE="1")).state.policy == policy
    assert create_app(dict(settings, POLICY_MODE="window_hard")).state.policy == "window_hard"
    assert create_app(settings).state.policy == "bucket_hard"  # Default unchanged.
    audit = {"AUDIT_URL": "http://audit-collector", "AUDIT_TOKEN": "t" * 32, "AUDIT_MODE": "off"}
    assert Forwarder(None, audit).enabled  # Ignored outside evaluation.
    assert not Forwarder(None, dict(audit, EVAL_MODE="1")).enabled
    with pytest.raises(ValueError):
        create_app(dict(settings, POLICY_MODE="window_hard", DEADLINE_FRACTION="1"))
    with pytest.raises(ValueError):
        create_app(dict(settings, POLICY_MODE="nonsense"))
