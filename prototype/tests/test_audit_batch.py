"""Opt-in AUDIT_BATCH: batched delivery keeps order, the per-run chain and dedupe; the default stays one event per request."""
import asyncio
import json
import secrets

import httpx
import pytest
from fastapi.testclient import TestClient

from audit_collector import create_app as collector_app
from audit_forwarder import Forwarder
from audit_queue import AuditQueue
from verify_audit import verify


def collector_config(tmp_path):
    return {"AUDIT_TOKEN": secrets.token_hex(16), "AUDIT_LOG_DIR": str(tmp_path / "logs"), "AUDIT_KEY_DIR": str(tmp_path / "keys"),
            "CHECKPOINT_DIR": str(tmp_path / "cp")}


def event(run_id, index, **extra):
    return dict({"type": "submit_received", "run_id": run_id, "role": "red", "bucket": None, "timestamp": 1000.0 + index,
                 "prompt_hash": None}, **extra)


def auth(config):
    return {"authorization": "Bearer " + config["AUDIT_TOKEN"]}


def test_ack_many_deletes_only_the_given_rows(tmp_path):
    queue = AuditQueue(tmp_path / "q.sqlite")
    ids = [queue.enqueue("r", "/append", event("r", i)) for i in range(5)]
    queue.ack_many(ids[:3])
    assert [row[0] for row in queue.head(10)] == ids[3:]


def test_collector_batch_appends_in_order_for_interleaved_runs_and_chains_verify(tmp_path):
    config = collector_config(tmp_path)
    client = TestClient(collector_app(config))
    batch = [event("a" if i % 2 == 0 else "b", i, gw_seq=i // 2 + 1) for i in range(8)]
    assert client.post("/append_batch", json={"events": batch}, headers=auth(config)).json() == {"ok": True}
    collector = client.app.state.collector
    for run in ("a", "b"):
        client.post("/finish", json={"run_id": run}, headers=auth(config))
        log, checkpoint = collector.paths(run)
        records = [json.loads(line) for line in log.read_bytes().splitlines()]
        assert [r["timestamp"] for r in records if r["type"] == "submit_received"] == sorted(
            e["timestamp"] for e in batch if e["run_id"] == run)  # order preserved within the run
        assert verify(log, checkpoint, collector.checkpoints / "public_key.bin", run)[0]


def test_batch_is_validated_as_a_whole_bounded_authenticated_and_retry_safe(tmp_path):
    config = collector_config(tmp_path)
    client = TestClient(collector_app(config))
    collector = client.app.state.collector
    good, bad = event("r", 1, gw_seq=1), dict(event("r", 2, gw_seq=2), type="not_an_event")
    assert client.post("/append_batch", json={"events": [good, bad]}, headers=auth(config)).status_code == 422
    assert not collector.paths("r")[0].exists()  # nothing was appended from the invalid batch
    assert client.post("/append_batch", json={"events": [event("r", i, gw_seq=i + 1) for i in range(201)]}, headers=auth(config)).status_code == 422
    assert client.post("/append_batch", json={"events": [good]}).status_code == 403
    for _ in range(2):  # a retried batch is deduplicated by gw_seq
        assert client.post("/append_batch", json={"events": [good]}, headers=auth(config)).json() == {"ok": True}
    assert len(collector.paths("r")[0].read_bytes().splitlines()) == 1


async def ship(tmp_path, count, batch, fail_first_batch=False):
    config = collector_config(tmp_path)
    collector = collector_app(config)
    queue = AuditQueue(tmp_path / "q.sqlite")
    for i in range(count):
        run = "a" if i % 2 == 0 else "b"
        queue.enqueue(run, "/append", event(run, i))
    for run in ("a", "b"):
        queue.enqueue(run, "/finish", {"run_id": run})
    calls = []
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=collector)) as sink:
        async def dispatch(request):
            calls.append((request.url.path, len(json.loads(request.content).get("events", [1]))))
            if fail_first_batch and request.url.path == "/append_batch" and not any(p == "failed" for p, _ in calls):
                calls.append(("failed", 0))
                raise httpx.ConnectError("collector unavailable", request=request)
            return await sink.post(str(request.url), content=request.content, headers=request.headers)
        forwarder_config = dict(config, AUDIT_URL="http://audit-collector", AUDIT_TIMEOUT_SECONDS="1", AUDIT_GIVE_UP_SECONDS="5")
        if batch:
            forwarder_config["AUDIT_BATCH"] = str(batch)
        forwarder = Forwarder(queue, forwarder_config, httpx.MockTransport(dispatch))
        forwarder.start()
        try:
            async with asyncio.timeout(10):
                while queue.head() is not None:
                    await asyncio.sleep(0.01)
        finally:
            await forwarder.close()
    return collector.state.collector, queue, calls


def test_batched_delivery_uses_few_requests_and_keeps_both_chains_valid(tmp_path):
    collector, queue, calls = asyncio.run(ship(tmp_path, 45, 20))
    paths = [p for p, _ in calls]
    assert paths.count("/append") == 0 and paths.count("/finish") == 2
    assert 3 <= paths.count("/append_batch") <= 4 and sum(n for p, n in calls if p == "/append_batch") >= 45
    assert queue.counts()["dead"] == 0 and queue.counts()["pending"] == 0
    for run in ("a", "b"):
        log, checkpoint = collector.paths(run)
        assert verify(log, checkpoint, collector.checkpoints / "public_key.bin", run)[0]
        assert len([json.loads(line) for line in log.read_bytes().splitlines() if json.loads(line)["type"] == "submit_received"]) in (22, 23)


def test_a_failed_batch_is_retried_without_loss_or_duplicates(tmp_path):
    collector, queue, calls = asyncio.run(ship(tmp_path, 30, 10, fail_first_batch=True))
    assert queue.counts() == {"pending": 0, "dead": 0, "incomplete_runs": 0}
    total = 0
    for run in ("a", "b"):
        log, checkpoint = collector.paths(run)
        assert verify(log, checkpoint, collector.checkpoints / "public_key.bin", run)[0]
        total += len([1 for line in log.read_bytes().splitlines() if json.loads(line)["type"] == "submit_received"])
    assert total == 30  # every event stored once


def test_default_is_still_one_event_per_request(tmp_path):
    collector, queue, calls = asyncio.run(ship(tmp_path, 12, 0))
    paths = [p for p, _ in calls]
    assert paths.count("/append") == 12 and paths.count("/append_batch") == 0
    assert queue.counts()["dead"] == 0
