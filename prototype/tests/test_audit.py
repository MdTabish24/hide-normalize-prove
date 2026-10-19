import asyncio
import hashlib
import json
import secrets

import httpx
import pytest

from audit_collector import create_app
from audit_store import Collector
from demo_audit_tamper import run_demo, tamper_cases
from verify_audit import verify


@pytest.fixture
def collected(tmp_path):
    collector = Collector(tmp_path / "logs", tmp_path / "keys", tmp_path / "checkpoints")
    for index in range(7):
        collector.append({"type": "submit_received", "run_id": "audit-run", "role": "red",
                          "bucket": None, "timestamp": 1000.0 + index,
                          "prompt_hash": hashlib.sha256(f"dummy-{index}".encode()).hexdigest()})
    collector.finish("audit-run")
    log, checkpoint = collector.paths("audit-run")
    return collector, log, checkpoint, collector.checkpoints / "public_key.bin"


@pytest.mark.parametrize("case", ["unmodified", "edit one event", "delete middle event",
                                   "delete last 3 events", "reorder two events", "duplicate/replay event",
                                   "rehash without signing key", "edit log and stored count"])
def test_each_tamper_case(collected, tmp_path, case):
    _, log, checkpoint, public_key = collected
    data, cp = tamper_cases(log.read_bytes(), checkpoint.read_bytes())[case]
    copy_log, copy_cp = tmp_path / "copy.jsonl", tmp_path / "copy.json"
    copy_log.write_bytes(data)
    copy_cp.write_bytes(cp)
    valid, reason, index = verify(copy_log, copy_cp, public_key, "audit-run")
    assert valid == (case == "unmodified"), (reason, index)
    if case == "rehash without signing key":
        assert reason == "checkpoint signature invalid"
    if case == "edit one event":
        assert index == 1


def test_restart_key_persistence_and_post_finish_append(collected):
    original, log, checkpoint, public_key = collected
    key_bytes = (original.keys / "signing_key.bin").read_bytes()
    old_checkpoint = checkpoint.read_bytes()
    restarted = Collector(original.logs, original.keys, original.checkpoints)
    assert (restarted.keys / "signing_key.bin").read_bytes() == key_bytes
    assert verify(log, checkpoint, public_key, "audit-run")[0]
    restarted.append({"type": "report_served", "run_id": "audit-run", "role": "red",
                      "bucket": 3.0, "timestamp": 2000.0, "prompt_hash": None})
    assert checkpoint.read_bytes() != old_checkpoint
    assert verify(log, checkpoint, public_key, "audit-run")[0]
    stable = log.read_bytes(), checkpoint.read_bytes()
    restarted.finish("audit-run")
    assert stable == (log.read_bytes(), checkpoint.read_bytes())
    assert not (original.checkpoints / "signing_key.bin").exists()


def test_completed_count_and_bytes_include_terminal_line(collected):
    _, log, checkpoint, public_key = collected
    data = log.read_bytes()
    records = [json.loads(raw) for raw in data.splitlines()]
    final, cp = records[-1], json.loads(checkpoint.read_bytes())
    assert final["count"] == cp["count"] == len(records)
    assert final["bytes"] == cp["bytes"] == len(data)
    assert final["current_hash"] == cp["head_hash"]
    assert verify(log, checkpoint, public_key, "audit-run")[0]


def test_tamper_demo_changes_only_copies(collected):
    _, log, checkpoint, public_key = collected
    originals = log.read_bytes(), checkpoint.read_bytes(), public_key.read_bytes()
    results = run_demo(log, checkpoint, public_key, "audit-run")
    assert [valid for _, valid, _, _ in results] == [True] + [False] * 7
    assert originals == (log.read_bytes(), checkpoint.read_bytes(), public_key.read_bytes())


def test_collector_auth_and_metadata_only_schema(tmp_path):
    config = {"AUDIT_TOKEN": secrets.token_hex(32), "AUDIT_LOG_DIR": str(tmp_path / "logs"),
              "AUDIT_KEY_DIR": str(tmp_path / "keys"), "CHECKPOINT_DIR": str(tmp_path / "cp")}
    app = create_app(config)

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://audit-collector") as client:
            event = {"type": "submit_received", "run_id": "r", "role": "red", "bucket": None,
                     "timestamp": 1000, "prompt_hash": "a" * 64}
            assert (await client.post("/append", json=event)).status_code == 403
            headers = {"authorization": "Bearer " + config["AUDIT_TOKEN"]}
            assert (await client.post("/append", json=dict(event, prompt="must never be stored"), headers=headers)).status_code == 422
            assert (await client.post("/append", json=event, headers=headers)).json() == {"ok": True}
            assert (await client.post("/finish", json={"run_id": "r"}, headers=headers)).json() == {"ok": True}
            assert (await client.get("/logs", headers=headers)).status_code == 404
            assert (await client.get("/key", headers=headers)).status_code == 404
    asyncio.run(scenario())
    assert b"must never be stored" not in (tmp_path / "logs" / "r.jsonl").read_bytes()


def test_missing_completion_and_unavailable_flag_are_invalid(tmp_path):
    collector = Collector(tmp_path / "logs", tmp_path / "keys", tmp_path / "cp")
    collector.finish("lost", unavailable=True)
    log, checkpoint = collector.paths("lost")
    assert verify(log, checkpoint, collector.checkpoints / "public_key.bin", "lost")[1] == "audit_unavailable recorded"
    collector.finish("lost", unavailable=False)
    assert verify(log, checkpoint, collector.checkpoints / "public_key.bin", "lost")[1] == "audit_unavailable recorded"
