"""Verifier failure reasons are separated for diagnosis; verdicts are unchanged. Server error capture and liveness helpers."""
import hashlib

import pytest

from audit_store import Collector
from eval.live import Server
from verify_audit import verify


@pytest.fixture
def chain(tmp_path):
    collector = Collector(tmp_path / "logs", tmp_path / "keys", tmp_path / "checkpoints")
    for index in range(3):
        collector.append({"type": "submit_received", "run_id": "r", "role": "red", "bucket": None, "timestamp": 1000.0 + index,
                          "prompt_hash": hashlib.sha256(f"d{index}".encode()).hexdigest()})
    collector.finish("r")
    log, checkpoint = collector.paths("r")
    return log, checkpoint, collector.checkpoints / "public_key.bin"


def test_missing_log_checkpoint_and_key_have_distinct_reasons(chain, tmp_path):
    log, checkpoint, key = chain
    assert verify(log, checkpoint, key, "r") == (True, "VALID", 0)
    assert verify(tmp_path / "nope.jsonl", checkpoint, key, "r")[:2] == (False, "log file missing")
    assert verify(log, tmp_path / "nope.json", key, "r")[:2] == (False, "checkpoint missing (chain never reached complete)")
    assert verify(log, checkpoint, tmp_path / "nope.bin", "r")[:2] == (False, "public key missing")


def test_unreadable_gateway_status_is_its_own_reason_and_real_failures_keep_their_reason(chain, tmp_path):
    log, checkpoint, key = chain
    assert verify(log, checkpoint, key, "r", gateway_db=tmp_path / "no-dir" / "runs.sqlite")[:2] == (False, "gateway audit status unreadable")
    bad = tmp_path / "bad.jsonl"
    bad.write_bytes(log.read_bytes().replace(b"submit_received", b"submit_receivee", 1))
    valid, reason, _ = verify(bad, checkpoint, key, "r")
    assert not valid and reason != "log file missing" and "missing" not in reason


def test_server_keeps_error_output_when_asked(tmp_path):
    err = tmp_path / "server.err"
    server = Server("no_such_module_for_test:app", {}, err_log=err, log_level="error")
    with pytest.raises(RuntimeError):
        server.start()
    assert err.exists() and err.stat().st_size > 0  # the failure is diagnosable instead of discarded
