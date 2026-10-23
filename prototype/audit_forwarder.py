"""Background audit shipper. HTTP delivery never gates Red's release timer.

Ordered (FIFO) at-least-once delivery with retry and exponential backoff. The
collector drops duplicates by gw_seq, so a lost acknowledgement is harmless.
Only entries that stayed undeliverable for AUDIT_GIVE_UP_SECONDS (counted from
when THIS process first saw them, so a restart gets a fresh window) move to the
dead-letter table and flag their run audit_incomplete. Nothing is dropped silently.
"""
import asyncio
import json
import time

import httpx


class Forwarder:
    def __init__(self, queue, config, transport=None):
        self.queue, self.transport = queue, transport
        self.url = config.get("AUDIT_URL", "").rstrip("/")
        self.token = config.get("AUDIT_TOKEN", "")
        # An explicit audit-off mode exists only for evaluation runs (EVAL_MODE=1).
        audit_off = config.get("AUDIT_MODE") == "off" and config.get("EVAL_MODE") == "1"
        self.enabled = bool(self.url and self.token) and not audit_off
        self.timeout = float(config.get("AUDIT_TIMEOUT_SECONDS", "0.3"))
        self.give_up = float(config.get("AUDIT_GIVE_UP_SECONDS", "2"))
        # Opt-in: deliver up to this many consecutive /append events per HTTP round trip (0 or 1 = one event per request).
        self.batch = max(0, min(200, int(config.get("AUDIT_BATCH") or 0)))
        self.first_seen = {}  # row id -> monotonic time this process first saw it
        # Opt-in diagnosis (EVAL_MODE=1 and AUDIT_ERROR_LOG=1): exception TYPE names only (no payload, token or message) of failed deliveries.
        self.error_log = config.get("DATA_DIR", "") + "/audit-errors.jsonl" if config.get("EVAL_MODE") == "1" and config.get("AUDIT_ERROR_LOG") == "1" else None
        self.last_error_write = 0.0
        self.offload = config.get("LOOP_OFFLOAD") == "1"  # Opt-in: enqueue in a worker thread instead of on the event loop.
        self.wakeup = asyncio.Event()
        self.task = self.client = None

    def start(self):
        if self.enabled:
            # Own connection pool: audit traffic cannot starve Blue/model calls.
            self.client = httpx.AsyncClient(transport=self.transport, trust_env=False,
                                            limits=httpx.Limits(max_connections=1))
            self.wakeup.set()  # Resume persisted deliveries on startup.
            self.task = asyncio.create_task(self.worker())

    def _queued(self, row):
        if row is not None:
            self.first_seen[row] = time.monotonic()
        self.wakeup.set()

    def _enqueue(self, run_id, path, payload):
        self._queued(self.queue.enqueue(run_id, path, payload, self.enabled))

    async def _aenqueue(self, run_id, path, payload):
        if not self.offload:
            return self._enqueue(run_id, path, payload)
        self._queued(await asyncio.to_thread(self.queue.enqueue, run_id, path, payload, self.enabled))

    async def aemit(self, event_type, run_id, role=None, bucket=None, prompt_hash=None):
        await self._aenqueue(run_id, "/append", {"type": event_type, "run_id": run_id, "role": role,
                                                 "bucket": bucket, "timestamp": time.time(), "prompt_hash": prompt_hash})

    async def afinish(self, run_id):
        await self._aenqueue(run_id, "/finish", {"run_id": run_id})

    def emit(self, event_type, run_id, role=None, bucket=None, prompt_hash=None):
        self._enqueue(run_id, "/append", {"type": event_type, "run_id": run_id, "role": role,
                                          "bucket": bucket, "timestamp": time.time(), "prompt_hash": prompt_hash})

    def finish(self, run_id):
        self._enqueue(run_id, "/finish", {"run_id": run_id})

    async def deliver(self, run_id, path, payload):
        if path == "/finish":
            payload["audit_unavailable"] = await asyncio.to_thread(self.queue.failed, run_id)
        try:
            async with asyncio.timeout(self.timeout + 0.1):
                response = await self.client.post(self.url + path, json=payload, timeout=self.timeout,
                                                  headers={"authorization": "Bearer " + self.token})
            response.raise_for_status()
            return response.json() == {"ok": True}
        except Exception as error:
            # No exception details, credentials or payloads are logged or returned.
            self._note(error, "single", self.timeout, 1)
            return False

    def _note(self, error, where, timeout, events):
        if self.error_log is None or time.monotonic() - self.last_error_write < 0.2:
            return
        self.last_error_write = time.monotonic()
        try:
            with open(self.error_log, "a", encoding="utf-8") as stream:
                stream.write(json.dumps(dict(t=round(time.time(), 3), where=where, error=type(error).__name__, timeout=timeout, events=events)) + "\n")
        except OSError:
            pass

    async def deliver_batch(self):
        """Ship the leading run of /append entries in one request. Returns how many were acknowledged (0 on failure)."""
        rows = await asyncio.to_thread(self.queue.head, self.batch)
        batch = []
        for row in rows:
            if row[2] != "/append":
                break  # /finish is shipped alone: its audit_unavailable flag is computed when it is sent.
            batch.append(row)
        if not batch:
            return 0
        for row in batch:
            self.first_seen.setdefault(row[0], time.monotonic())
        timeout = self.timeout + 0.002 * len(batch)
        try:
            async with asyncio.timeout(timeout + 0.1):
                response = await self.client.post(self.url + "/append_batch", json={"events": [json.loads(r[3]) for r in batch]},
                                                  timeout=timeout, headers={"authorization": "Bearer " + self.token})
            response.raise_for_status()
            if response.json() != {"ok": True}:
                return 0
        except Exception as error:
            self._note(error, "batch", timeout, len(batch))
            return 0
        await asyncio.to_thread(self.queue.ack_many, [r[0] for r in batch])
        for row in batch:
            self.first_seen.pop(row[0], None)
        return len(batch)

    async def worker(self):
        backoff = 0.05
        while True:
            await self.wakeup.wait()
            self.wakeup.clear()
            while (row := await asyncio.to_thread(self.queue.head)) is not None:
                row_id, run_id, path, encoded = row
                self.first_seen.setdefault(row_id, time.monotonic())
                if self.batch > 1 and path == "/append":
                    if await self.deliver_batch():
                        backoff = 0.05
                        continue
                elif await self.deliver(run_id, path, json.loads(encoded)):
                    await asyncio.to_thread(self.queue.ack, row_id)
                    self.first_seen.pop(row_id, None)
                    backoff = 0.05
                    continue
                # Only the entry that was actually attempted can expire. The next
                # entry gets its own attempt (it may be deliverable).
                if time.monotonic() - self.first_seen[row_id] >= self.give_up:
                    await asyncio.to_thread(self.queue.dead_letter, [row_id], "collector unreachable")
                    self.first_seen.pop(row_id, None)
                    continue
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 0.5)

    async def close(self):
        if self.task is not None:
            try:
                async with asyncio.timeout(0.5):
                    while await asyncio.to_thread(self.queue.head) is not None:
                        await asyncio.sleep(0.01)
            except TimeoutError:
                pass  # Undelivered entries stay queued and resume after restart.
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        if self.client is not None:
            await self.client.aclose()
