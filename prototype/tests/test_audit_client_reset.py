"""After a failed delivery the audit shipper uses a fresh HTTP client (a stuck pool once stalled the whole audit queue)."""
import asyncio

import httpx

from audit_forwarder import Forwarder
from audit_queue import AuditQueue

EVENT = {"type": "submit_received", "run_id": "a", "role": "red", "bucket": None, "timestamp": 1.0, "prompt_hash": None}


def forwarder_for(tmp_path, dispatch, batch):
    config = {"AUDIT_URL": "http://audit-collector", "AUDIT_TOKEN": "t" * 32, "AUDIT_TIMEOUT_SECONDS": "1", "AUDIT_BATCH": str(batch)}
    queue = AuditQueue(tmp_path / "queue.sqlite")
    queue.enqueue("a", "/append", EVENT)
    return Forwarder(queue, config, httpx.MockTransport(dispatch)), queue


def test_failed_batch_delivery_replaces_the_client(tmp_path):
    async def scenario():
        def dispatch(request):
            raise httpx.ConnectError("down", request=request)
        forwarder, queue = forwarder_for(tmp_path, dispatch, 10)
        forwarder.start()
        try:
            first = forwarder.client
            assert await forwarder.deliver_batch() == 0
            assert forwarder.client is not first  # fresh pool after the failure
            assert queue.head() is not None  # nothing was lost
        finally:
            await forwarder.close()
    asyncio.run(scenario())


def test_failed_single_delivery_replaces_the_client(tmp_path):
    async def scenario():
        def dispatch(request):
            raise httpx.ConnectError("down", request=request)
        forwarder, _ = forwarder_for(tmp_path, dispatch, 0)
        forwarder.start()
        try:
            first = forwarder.client
            assert await forwarder.deliver("a", "/append", EVENT) is False
            assert forwarder.client is not first
        finally:
            await forwarder.close()
    asyncio.run(scenario())
