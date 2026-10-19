"""Round 2 Phase 1: audit off the critical path (durable queue, retry, dedupe, bounds)."""
import asyncio
import json
import time

import httpx
import pytest

import audit_store
from audit_queue import AuditQueue
from audit_store import Collector
from common import PENDING
from stats import ks_2samp, summary
from test_audit_gateway import audited, config_for, drain, finished_run, headers, verified


async def released_times(config, failure, n):
    async with audited(config, failure) as (app, client, _):
        await client.post("/v1/defense", json={"trigger": "pineapple"}, headers=headers(config, "blue"))
        times = []
        for index in range(n):
            start = time.perf_counter()
            response = await client.post("/v1/submit", json={"run_id": "r", "prompt": f"probe {index}"},
                                         headers=headers(config, "red"))
            times.append(time.perf_counter() - start)
            assert response.status_code == 202 and response.content == PENDING
        return times


@pytest.mark.timing
def test_collector_healthy_slow_down_give_same_release_times(tmp_path, capsys):
    """Collector health must not move Red's release time (medians, p95, KS)."""
    async def scenario():
        # Interleaved blocks: a burst of machine noise hits every condition,
        # instead of whichever condition happened to be running.
        results = {"healthy": [], "slow": [], "down": []}
        for block in range(3):
            for name, failure in (("healthy", {}), ("slow", {"slow": True}), ("down", {"down": True})):
                results[name] += await released_times(config_for(tmp_path / f"{name}-{block}"), failure, 15)
        return results
    results = asyncio.run(scenario())
    healthy = summary(results["healthy"])
    with capsys.disabled():
        print(f"\nhealthy {healthy}")
    for name in ("slow", "down"):
        other = summary(results[name])
        d, p = ks_2samp(results["healthy"], results[name])
        with capsys.disabled():
            print(f"{name} {other} KS D={d:.3f} p={p:.3f}")
        assert abs(other["median"] - healthy["median"]) < 0.010
        assert abs(other["p95"] - healthy["p95"]) < 0.020
        assert p > 0.001


def test_restart_with_undelivered_entries_still_verifies_valid(tmp_path):
    config, failure = config_for(tmp_path), {"down": True}
    config["AUDIT_GIVE_UP_SECONDS"] = "60"  # The outage is shorter than the window.

    async def scenario():
        async with audited(config, failure) as (app, client, _):
            await client.post("/v1/defense", json={"trigger": "pineapple"}, headers=headers(config, "blue"))
            await client.post("/v1/submit", json={"run_id": "r", "prompt": "hello"}, headers=headers(config, "red"))
            await client.post("/v1/run/r/finish", headers=headers(config, "evaluator"))
            assert app.state.store.audit_next() is not None  # Undelivered at shutdown.
        failure.clear()  # Collector back; a NEW gateway process resumes the queue.
        async with audited(config, failure) as (app, client, collector):
            await drain(app)
            assert not app.state.store.audit_failed("r")
            assert verified(config, collector) == (True, "VALID", 0)
    asyncio.run(scenario())


def test_lost_acknowledgement_is_retried_without_duplicates(tmp_path):
    config, failure = config_for(tmp_path), {"lose_ack_once": True}

    async def scenario():
        async with audited(config, failure) as (app, client, collector):
            await finished_run(config, app, client)
            log, _ = collector.paths("r")
            events = [json.loads(raw) for raw in log.read_bytes().splitlines()]
            seqs = [e["gw_seq"] for e in events if e["gw_seq"] is not None]
            assert seqs == list(range(1, len(seqs) + 1))  # No duplicate or gap.
            assert verified(config, collector) == (True, "VALID", 0)
    asyncio.run(scenario())


def test_full_queue_flags_run_and_never_delays_release(tmp_path):
    config = config_for(tmp_path)
    config["AUDIT_QUEUE_MAX"] = "2"

    async def scenario():
        async with audited(config, {"down": True}) as (app, client, _):
            start = time.perf_counter()
            for index in range(4):
                response = await client.post("/v1/submit", json={"run_id": "r", "prompt": f"p{index}"},
                                             headers=headers(config, "red"))
                assert response.status_code == 202 and response.content == PENDING
            assert time.perf_counter() - start < 4 * 0.45 + 0.4  # No waiting on the queue.
            assert app.state.store.audit_failed("r")
            with app.state.store.audit_queue.connect() as db:
                reason = db.execute("SELECT reason FROM audit_state WHERE run_id='r'").fetchone()[0]
            assert reason == "queue full"
    asyncio.run(scenario())


def test_collector_seals_sequence_gap_as_unavailable(tmp_path):
    collector = Collector(tmp_path / "logs", tmp_path / "keys", tmp_path / "cp")
    base = {"type": "submit_received", "run_id": "g", "role": "red", "bucket": None,
            "timestamp": 1000.0, "prompt_hash": None}
    collector.append(dict(base, gw_seq=1))
    collector.append(dict(base, gw_seq=1))  # Duplicate retry: ignored.
    collector.append(dict(base, gw_seq=3))  # Event 2 never arrived.
    collector.finish("g")
    log, checkpoint = collector.paths("g")
    assert len(log.read_bytes().splitlines()) == 3
    assert audit_store.verify(log, checkpoint, collector.checkpoints / "public_key.bin", "g")[1] == "audit_unavailable recorded"
    # A restarted collector recomputes the gap from the log itself.
    restarted = Collector(tmp_path / "logs", tmp_path / "keys", tmp_path / "cp")
    restarted.finish("g")
    assert restarted.heads["g"]["gap"] is True


def test_collector_verifies_once_then_appends_incrementally(tmp_path, monkeypatch):
    collector = Collector(tmp_path / "logs", tmp_path / "keys", tmp_path / "cp")
    calls = []
    original = audit_store.inspect_chain
    monkeypatch.setattr(audit_store, "inspect_chain", lambda *a: calls.append(1) or original(*a))
    event = {"type": "submit_received", "run_id": "i", "role": "red", "bucket": None,
             "timestamp": 1000.0, "prompt_hash": None}
    for seq in range(1, 51):
        collector.append(dict(event, gw_seq=seq))
    collector.finish("i")
    collector.append(dict(event, type="report_served", gw_seq=51))
    assert len(calls) == 0  # New stream: nothing to re-read; never re-hashes the log.
    log, checkpoint = collector.paths("i")
    assert audit_store.verify(log, checkpoint, collector.checkpoints / "public_key.bin", "i")[0]


def test_queue_survives_reopen_and_keeps_sequence(tmp_path):
    queue = AuditQueue(tmp_path / "q.sqlite")
    queue.enqueue("r", "/append", {"type": "submit_received"})
    reopened = AuditQueue(tmp_path / "q.sqlite")
    reopened.enqueue("r", "/append", {"type": "bucket_released"})
    payloads = [json.loads(row[3]) for row in reopened.head(10)]
    assert [p["gw_seq"] for p in payloads] == [1, 2]
