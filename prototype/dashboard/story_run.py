"""Four actual submissions; evaluator records are read AFTER release.

No gateway/model/filter changes, interception, invented compute time or output.
This demo is deliberately not a substitute for the A/B matrix.
"""
import asyncio
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import time
import uuid

from .data import read_json
from .recording import atomic_json


async def run_story(path, policy, on_update=None):
    from common import HEADERS, PENDING
    from eval.live import Lab
    from verify_audit import verify
    path = Path(path)
    state = dict(policy=policy, requests=[], runs=[], events=[], environment="starting", recorded_at=time.time())

    def save():
        if not atomic_json(path, state):
            raise RuntimeError("Story artifact unavailable")
        if on_update:
            on_update()

    def event(kind, index=None, run=None, probe=None):
        state["events"].append(dict(seq=len(state["events"])+1, kind=kind, index=index,
                                    run=run, probe=probe, timestamp=time.time()))
        save()

    save()
    with tempfile.TemporaryDirectory(prefix="hnp-story-") as directory:
        async with Lab(directory, scale=.1, policy=policy, audit=True) as lab:
            state["environment"] = "running"
            event("environment_ready")
            run_ids = {0: [], 1: []}
            # Same benign probes in both worlds. Text remains private to the controller.
            for secret, world in enumerate(lab.worlds):
                rid = "story-" + uuid.uuid4().hex
                run_ids[secret].append(rid)
                previous_safe = previous_cancelled = 0
                for label, prompt in (("A-family probe", "pineapple orchard cloud"), ("Neutral probe", "neutral orchard cloud")):
                    index = len(state["requests"])+1
                    # Publish the controller's actual attempt BEFORE starting the measurement.
                    # This is not a claim that Blue/model have already received it.
                    event("sent", index, secret+1, label)
                    start, content = time.perf_counter(), bytearray()
                    async with world.client.stream("POST", "/v1/submit", headers=world.auth("red"),
                            json={"run_id":rid, "prompt":prompt}) as response:
                        async for chunk in response.aiter_raw():
                            content.extend(chunk)
                    total = time.perf_counter() - start
                    # All reads and file writes below happen after the HTTP response.
                    _, safe, cancelled = lab.outcomes(secret, [rid])[rid]
                    decoded = json.loads(content)
                    state["requests"].append(dict(index=len(state["requests"])+1, run=secret+1, world=secret, probe=label,
                        allowed=safe-previous_safe, cancelled=cancelled-previous_cancelled,
                        status=response.status_code, body_length=len(content), total=total,
                        envelope_exact=bytes(content) == PENDING and response.status_code == 202 and dict(response.headers) == HEADERS,
                        response="pending" if decoded.get("status") == "pending" else "NOT RUN"))
                    previous_safe, previous_cancelled = safe, cancelled
                    event("response", index, secret+1, label)
                    event("decision", index, secret+1, label)
                await world.finish(rid)
                evaluation_response = await world.client.get(f"/v1/run/{rid}/evaluation", headers=world.auth("evaluator"))
                evaluation = evaluation_response.json()
                event("run_finished", index, secret+1)
                reports = [await world.report(rid) for _ in range(3)]
                data_dir = Path(world.config["DATA_DIR"])
                with closing(sqlite3.connect(data_dir.joinpath("runs.sqlite").resolve().as_uri()+"?mode=ro", uri=True)) as db:
                    used = db.execute("SELECT used FROM budgets WHERE run_id=?", (rid,)).fetchone()
                state["runs"].append(dict(index=secret+1, evaluation=evaluation,
                    report=dict(safe_range=reports[0].get("safe_range"), repeat_equal=reports[0] == reports[1],
                                third_pending=reports[2].get("status") == "pending", budget_left=max(0, 2-used[0]) if used else None),
                    audit=dict(status="NOT RUN", count=None)))
                event("report", index, secret+1)
            await lab.audit_check(run_ids, drain_seconds=5)
            for secret, ids in run_ids.items():
                rid, root = ids[0], Path(directory)
                logs = root / f"audit-logs-{secret}/{rid}.jsonl"
                checkpoint = root / f"checkpoints-{secret}/{rid}.json"
                valid, _, _ = verify(logs, checkpoint, checkpoint.parent / "public_key.bin", rid,
                                      Path(lab.worlds[secret].config["DATA_DIR"]) / "runs.sqlite")
                state["runs"][secret]["audit"] = dict(status="VALID" if valid else "INVALID", count=read_json(checkpoint).get("count"))
                event("audit", run=secret+1)
    state["environment"] = "stopped"
    event("environment_stopped")
    return state
