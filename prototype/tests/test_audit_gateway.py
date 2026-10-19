"""Audit integration without changing Task 1 tests or public responses."""
import asyncio
from contextlib import asynccontextmanager
import hashlib
import json
import secrets
import time

import httpx
import pytest

from audit_collector import create_app as collector_app
from common import PENDING
from gateway import create_app
from verify_audit import verify


def config_for(tmp_path):
    config = {name: secrets.token_hex(32) for name in (
        "RED_TOKEN", "BLUE_TOKEN", "EVALUATOR_TOKEN", "GATEWAY_KEY",
        "BLUE_SERVICE_TOKEN", "MODEL_SERVICE_TOKEN", "AUDIT_TOKEN")}
    config.update(DATA_DIR=str(tmp_path / "gateway"), BUCKETS="0.15,0.3,0.45",
                  AUDIT_URL="http://audit-collector", AUDIT_LOG_DIR=str(tmp_path / "logs"),
                  AUDIT_KEY_DIR=str(tmp_path / "keys"), CHECKPOINT_DIR=str(tmp_path / "cp"),
                  # Round 2: failed deliveries are retried (not dropped) for this
                  # outage window before a run is flagged; keep outage tests short.
                  AUDIT_GIVE_UP_SECONDS="1")
    return config


def headers(config, role):
    return {"authorization": "Bearer " + config[role.upper() + "_TOKEN"]}


@asynccontextmanager
async def audited(config, failure):
    collector = collector_app(config)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=collector)) as sink:
        async def dispatch(request):
            if request.url.host == "audit-collector":
                payload = json.loads(request.content)
                if failure.get("slow"):
                    await asyncio.sleep(0.8)
                if failure.get("down") or (failure.get("type") and payload.get("type") == failure["type"]):
                    raise httpx.ConnectError("collector unavailable", request=request)
                response = await sink.post(str(request.url), content=request.content, headers=request.headers)
                if failure.pop("lose_ack_once", False):
                    # Collector stored the event but the acknowledgement is lost.
                    raise httpx.ReadTimeout("acknowledgement lost", request=request)
                return response
            return httpx.Response(200, json={"allowed": True} if request.url.host == "blue-defense" else {"answer": "dummy"})
        app = create_app(config, httpx.MockTransport(dispatch))
        async with app.router.lifespan_context(app), httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://gateway") as client:
            yield app, client, collector.state.collector


async def drain(app):
    async with asyncio.timeout(4):
        while app.state.store.audit_next() is not None:
            await asyncio.sleep(0.01)


async def finished_run(config, app, client):
    await client.post("/v1/defense", json={"trigger": "pineapple"}, headers=headers(config, "blue"))
    response = await client.post("/v1/submit", json={"run_id": "r", "prompt": "private test prompt"}, headers=headers(config, "red"))
    assert response.status_code == 202 and response.content == PENDING
    await client.post("/v1/run/r/finish", headers=headers(config, "evaluator"))
    await drain(app)


def verified(config, collector, gateway_status=True):
    log, checkpoint = collector.paths("r")
    return verify(log, checkpoint, collector.checkpoints / "public_key.bin", "r",
                  collector.logs.parent / "gateway" / "runs.sqlite" if gateway_status else None)


@pytest.mark.timing
def test_all_required_events_and_report_snapshot_refresh(tmp_path):
    config = config_for(tmp_path)
    async def scenario():
        async with audited(config, {}) as (app, client, collector):
            await finished_run(config, app, client)
            assert verified(config, collector)[0]
            await client.get("/v1/run/r/report", headers=headers(config, "red"))
            await drain(app)
            assert verified(config, collector)[0]
            log, _ = collector.paths("r")
            events = [json.loads(raw) for raw in log.read_bytes().splitlines()]
            assert {e["type"] for e in events} >= {"submit_received", "bucket_released", "report_served", "run_finished", "complete"}
            assert events[0]["prompt_hash"] == hashlib.sha256(b"private test prompt").hexdigest()
            assert b"private test prompt" not in log.read_bytes() and b"pineapple" not in log.read_bytes()
            config_log, config_checkpoint = collector.paths("@gateway")
            assert "defense_stored" in {json.loads(raw)["type"] for raw in config_log.read_bytes().splitlines()}
            assert verify(config_log, config_checkpoint, collector.checkpoints / "public_key.bin", "@gateway")[0]
            assert not (tmp_path / "gateway" / "signing_key.bin").exists()
    asyncio.run(scenario())


def test_outage_after_checkpoint_marks_sticky_status_across_gateway_restart(tmp_path):
    config, failure = config_for(tmp_path), {}
    async def scenario():
        async with audited(config, failure) as (app, client, collector):
            await finished_run(config, app, client)
            failure["down"] = True
            response = await client.get("/v1/run/r/report", headers=headers(config, "red"))
            assert response.status_code == 202 and response.json()["status"] == "complete"
            await drain(app)
            assert app.state.store.audit_failed("r")
            assert verified(config, collector)[1] == "gateway marks audit_unavailable"
        async with audited(config, failure) as (app, client, collector):
            assert app.state.store.audit_failed("r")
            assert verified(config, collector)[1] == "gateway marks audit_unavailable"
            second = await client.get("/v1/run/r/report", headers=headers(config, "red"))
            assert second.content == response.content
    asyncio.run(scenario())


def test_partial_outage_is_signed_into_complete_record(tmp_path):
    config = config_for(tmp_path)
    async def scenario():
        async with audited(config, {"type": "submit_received"}) as (app, client, collector):
            await finished_run(config, app, client)
            assert app.state.store.audit_failed("r")
            assert verified(config, collector, gateway_status=False)[1] == "audit_unavailable recorded"
    asyncio.run(scenario())


@pytest.mark.timing
def test_slow_collector_cannot_delay_pending_envelope(tmp_path):
    config = config_for(tmp_path)
    async def scenario():
        async with audited(config, {"slow": True}) as (app, client, _):
            await client.post("/v1/defense", json={"trigger": "pineapple"}, headers=headers(config, "blue"))
            start = time.perf_counter()
            response = await client.post("/v1/submit", json={"run_id": "r", "prompt": "hello"}, headers=headers(config, "red"))
            assert response.status_code == 202 and response.content == PENDING
            assert 0.145 <= time.perf_counter() - start < 0.27
            await drain(app)
            assert app.state.store.audit_failed("r")
    asyncio.run(scenario())
