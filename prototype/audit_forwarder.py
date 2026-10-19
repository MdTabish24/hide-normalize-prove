"""Ordered, durable audit outbox. HTTP delivery never gates Red's release timer."""
import asyncio
import json
import time


class Forwarder:
    def __init__(self, store, config, client):
        self.store, self.client = store, client
        self.url = config.get("AUDIT_URL", "").rstrip("/")
        self.token = config.get("AUDIT_TOKEN", "")
        self.enabled = bool(self.url and self.token)
        self.wakeup = asyncio.Event()
        self.task = None

    def start(self):
        if self.enabled:
            self.wakeup.set()  # Resume persisted deliveries on startup.
            self.task = asyncio.create_task(self.worker())

    def emit(self, event_type, run_id, role=None, bucket=None, prompt_hash=None):
        payload = {"type": event_type, "run_id": run_id, "role": role,
                   "bucket": bucket, "timestamp": time.time(), "prompt_hash": prompt_hash}
        self.store.audit_enqueue(run_id, "/append", payload, self.enabled)
        self.wakeup.set()

    def finish(self, run_id):
        self.store.audit_enqueue(run_id, "/finish", {"run_id": run_id}, self.enabled)
        self.wakeup.set()

    async def worker(self):
        while True:
            await self.wakeup.wait()
            self.wakeup.clear()
            while (row := self.store.audit_next()) is not None:
                delivery_id, run_id, path, encoded = row
                payload = json.loads(encoded)
                if path == "/finish":
                    payload["audit_unavailable"] = self.store.audit_failed(run_id)
                failed = False
                try:
                    async with asyncio.timeout(0.2):
                        response = await self.client.post(self.url + path, json=payload,
                                                          headers={"authorization": "Bearer " + self.token}, timeout=0.2)
                    response.raise_for_status()
                    if response.json() != {"ok": True}:
                        raise ValueError("Audit acknowledgement invalid")
                except Exception:
                    # Sticky flag survives restarts. No new response or logging
                    # of exception details, credentials or payloads to Red.
                    failed = True
                self.store.audit_ack(delivery_id, run_id, failed)

    async def close(self):
        if self.task is not None:
            try:
                async with asyncio.timeout(0.5):
                    while self.store.audit_next() is not None:
                        await asyncio.sleep(0.01)
            except TimeoutError:
                pass
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
