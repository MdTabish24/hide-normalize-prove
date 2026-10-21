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
        self.heads = {}  # run_id -> verified tail state (incremental appends)
        self.pending_checkpoints = {}  # our signed, fsynced tail awaiting publication
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
        temporary = checkpoint.with_suffix(".tmp")
        if temporary.exists():
            # A crash/reader lock may leave the already-signed replacement here.
            # Recover only a signature that authenticates the ENTIRE current log;
            # never sign or bless an unsigned suffix found on disk.
            valid, reason, _ = verify(log, temporary, self.checkpoints / "public_key.bin", run_id)
            if valid or reason == "audit_unavailable recorded":
                self.pending_checkpoints[run_id] = json.loads(temporary.read_bytes())
                self.publish_checkpoint(run_id)
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

    def state(self, run_id):
        """Full chain + checkpoint check once per stream per process, then incremental.

        Later appends extend the cached, already-verified head instead of
        re-reading and re-hashing the whole log on every event. A file whose size
        no longer matches the cache is fully re-checked. Complete verification of
        published runs is the verifier's job, not the hot path's.
        """
        log, _ = self.paths(run_id)
        size = log.stat().st_size if log.exists() else 0
        cached = self.heads.get(run_id)
        if cached and cached["bytes"] == size:
            return cached
        data, records = self.read(run_id)
        seqs = [r["gw_seq"] for r in records if r.get("gw_seq") is not None]
        completes = [r for r in records if r["type"] == "complete"]
        cached = {"bytes": len(data), "count": len(records),
                  "head": records[-1]["current_hash"] if records else ZERO_HASH,
                  "finished": bool(completes), "last_flag": completes[-1]["audit_unavailable"] if completes else None,
                  "sealed_at": len(records) if records and records[-1]["type"] == "complete" else None,
                  "unavailable": any(r["audit_unavailable"] for r in completes),
                  "gap": seqs != list(range(1, len(seqs) + 1)), "last_gw_seq": max(seqs, default=0)}
        self.heads[run_id] = cached
        return cached

    def _write(self, run_id, state, value):
        self.write_line(run_id, value)
        state["bytes"] += len(line(value))
        state["count"] += 1
        state["head"] = value["current_hash"]

    def seal(self, run_id, state, unavailable):
        event = {"type": "complete", "run_id": run_id, "role": "evaluator",
                 "bucket": None, "timestamp": time.time(), "prompt_hash": None, "gw_seq": None,
                 "count": state["count"] + 1, "bytes": 0, "audit_unavailable": bool(unavailable)}
        # Byte length includes this complete line. Hash length is fixed; the
        # decimal byte count stabilizes in a few iterations (no hash fixed point).
        while True:
            value = record(event, state["count"] + 1, state["head"])
            size = state["bytes"] + len(line(value))
            if event["bytes"] == size:
                break
            event["bytes"] = size
        self._write(run_id, state, value)
        state.update(finished=True, last_flag=bool(unavailable), sealed_at=state["count"])
        state["unavailable"] |= bool(unavailable)
        checkpoint = {"run_id": run_id, "count": value["count"], "bytes": size,
                      "head_hash": value["current_hash"]}
        checkpoint["signature"] = self.key.sign(canonical(checkpoint)).hex()
        self.pending_checkpoints[run_id] = checkpoint
        self.publish_checkpoint(run_id)

    def publish_checkpoint(self, run_id):
        """Windows readers can briefly lock replace; retry the SAME signed head.

        A lost HTTP acknowledgement must not discard a pending checkpoint when
        the gateway retries its already-appended gw_seq. No unsigned disk suffix
        is trusted on restart; recovery requires a valid already-signed temporary
        checkpoint matching the entire log.
        """
        checkpoint = self.pending_checkpoints.get(run_id)
        if checkpoint is None:
            return
        _, path = self.paths(run_id)
        temporary = path.with_suffix(".tmp")
        with temporary.open("wb") as file:
            file.write(canonical(checkpoint) + b"\n")
            file.flush()
            os.fsync(file.fileno())
        for attempt in range(6):
            try:
                temporary.replace(path)
                del self.pending_checkpoints[run_id]
                return
            except PermissionError:
                if attempt == 5:
                    raise
                time.sleep(.005 * (attempt + 1))

    def append(self, event):
        run_id = event["run_id"]
        event = dict(event)
        event.setdefault("gw_seq", None)
        with self.lock:
            state = self.state(run_id)
            self.publish_checkpoint(run_id)
            seq = event["gw_seq"]
            if seq is not None and seq <= state["last_gw_seq"]:
                return  # Retried delivery already stored (lost acknowledgement).
            if seq is not None:
                state["gap"] |= seq != state["last_gw_seq"] + 1
                state["last_gw_seq"] = seq
            self._write(run_id, state, record(event, state["count"] + 1, state["head"]))
            if state["finished"]:
                # Reports happen after finish: extend the chain and sign a new
                # complete snapshot. Previous checkpoints require freshness pinning.
                self.seal(run_id, state, state["unavailable"] or state["gap"])

    def finish(self, run_id, unavailable=False):
        with self.lock:
            state = self.state(run_id)
            self.publish_checkpoint(run_id)
            # A gateway sequence gap means events are missing: never VALID.
            unavailable = bool(unavailable or state["unavailable"] or state["gap"])
            if state["last_flag"] == unavailable and state["sealed_at"] == state["count"]:
                return  # Idempotent: nothing appended and no status change since the last seal.
            self.seal(run_id, state, unavailable)
