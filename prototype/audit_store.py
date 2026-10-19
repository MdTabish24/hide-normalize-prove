"""Single-process collector storage. Signing keys are created only here."""
import os
import json
from pathlib import Path
import threading
import time

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from audit_format import ZERO_HASH, canonical, inspect_chain, line, record
from verify_audit import verify


class Collector:
    def __init__(self, logs, keys, checkpoints):
        self.logs, self.keys, self.checkpoints = map(Path, (logs, keys, checkpoints))
        for directory in (self.logs, self.keys, self.checkpoints):
            directory.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        key_file = self.keys / "signing_key.bin"
        if key_file.exists():
            self.key = Ed25519PrivateKey.from_private_bytes(key_file.read_bytes())
        else:
            self.key = Ed25519PrivateKey.generate()
            with os.fdopen(os.open(key_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as file:
                file.write(self.key.private_bytes_raw())
                file.flush()
                os.fsync(file.fileno())
        public = self.key.public_key().public_bytes_raw()
        public_file = self.checkpoints / "public_key.bin"
        if public_file.exists() and public_file.read_bytes() != public:
            raise ValueError("Audit signing key differs from pinned local public key")
        if not public_file.exists():
            public_file.write_bytes(public)

    def paths(self, run_id):
        # Also guard callers outside the API (tests/demo helpers).
        from re import fullmatch
        if not fullmatch(r"[A-Za-z0-9_@-]{1,64}", run_id):
            raise ValueError("Invalid run ID")
        return self.logs / (run_id + ".jsonl"), self.checkpoints / (run_id + ".json")

    def read(self, run_id):
        log, checkpoint = self.paths(run_id)
        data = log.read_bytes() if log.exists() else b""
        records = inspect_chain(data, run_id) if data else []
        if checkpoint.exists():
            # A crash may leave an unsigned suffix after an older checkpoint.
            # Authenticate that signed prefix before ever extending the file.
            cp = json.loads(checkpoint.read_bytes())
            signed = {k: v for k, v in cp.items() if k != "signature"}
            self.key.public_key().verify(bytes.fromhex(cp["signature"]), canonical(signed))
            count = cp["count"]
            if not 1 <= count <= len(records) or cp["run_id"] != run_id:
                raise ValueError("Checkpoint prefix count/run mismatch")
            if records[count - 1]["current_hash"] != cp["head_hash"] or sum(len(line(r)) for r in records[:count]) != cp["bytes"]:
                raise ValueError("Checkpoint prefix changed")
        if records and records[-1]["type"] == "complete":
            # Do not bless a changed signed history when collecting later reports.
            valid, reason, _ = verify(log, checkpoint, self.checkpoints / "public_key.bin", run_id)
            # An unavailable run remains appendable but can never become VALID.
            if not valid and reason != "audit_unavailable recorded":
                raise ValueError(reason)
        return data, records

    def write_line(self, run_id, value):
        log, _ = self.paths(run_id)
        with log.open("ab") as file:
            file.write(line(value))
            file.flush()
            os.fsync(file.fileno())

    def seal(self, run_id, data, records, unavailable):
        event = {"type": "complete", "run_id": run_id, "role": "evaluator",
                 "bucket": None, "timestamp": time.time(), "prompt_hash": None,
                 "count": len(records) + 1, "bytes": 0, "audit_unavailable": bool(unavailable)}
        previous = records[-1]["current_hash"] if records else ZERO_HASH
        # Byte length includes this complete line. Hash length is fixed; the
        # decimal byte count stabilizes in a few iterations (no hash fixed point).
        while True:
            value = record(event, len(records) + 1, previous)
            size = len(data) + len(line(value))
            if event["bytes"] == size:
                break
            event["bytes"] = size
        self.write_line(run_id, value)
        checkpoint = {"run_id": run_id, "count": value["count"], "bytes": size,
                      "head_hash": value["current_hash"]}
        checkpoint["signature"] = self.key.sign(canonical(checkpoint)).hex()
        _, path = self.paths(run_id)
        temporary = path.with_suffix(".tmp")
        with temporary.open("wb") as file:
            file.write(canonical(checkpoint) + b"\n")
            file.flush()
            os.fsync(file.fileno())
        temporary.replace(path)

    def append(self, event):
        run_id = event["run_id"]
        with self.lock:
            data, records = self.read(run_id)
            was_finished = bool(records and records[-1]["type"] == "complete")
            unavailable = any(r.get("audit_unavailable", False) for r in records)
            value = record(event, len(records) + 1, records[-1]["current_hash"] if records else ZERO_HASH)
            self.write_line(run_id, value)
            if was_finished:
                # Reports happen after finish: extend the chain and sign a new
                # complete snapshot. Previous checkpoints require freshness pinning.
                self.seal(run_id, data + line(value), records + [value], unavailable)

    def finish(self, run_id, unavailable=False):
        with self.lock:
            data, records = self.read(run_id)
            unavailable |= any(r.get("audit_unavailable", False) for r in records)
            if records and records[-1]["type"] == "complete" and records[-1]["audit_unavailable"] == unavailable:
                return  # Idempotent finish with unchanged state.
            self.seal(run_id, data, records, unavailable)
