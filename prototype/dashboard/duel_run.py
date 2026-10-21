"""Record ONE request sequence under two policies for the side-by-side view.

Label: live gateway, mock model, local run (scaled 0.1 timings). Left arm: raw timing. Right arm: window_hard +
continue + feedback meter. Same auth, Blue filter, encryption, output shaping and audit in both; only timing
(and the opt-in meter) differ. Every number is read from the gateway or its database; nothing is invented.

    python -m dashboard.duel_run        # about 1 minute, light CPU
"""
import argparse
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

LABEL = "live gateway, mock model, local run"
SCALE = 0.1
RULE = "keyword rule A"  # Blue's private rule is named, never its keyword, in every projection.
# (case, text, slow-compute seconds). Batch 1 (probes 1-10) is mostly blocked, batch 2 (11-20) mostly allowed, so the
# 3-state meter has something real to report. Probe 13 asks for long compute (beyond the fixed window); probe 11 repeats probe 3.
SEQUENCE = [
    ("blocked", "pineapple orchard cloud", None), ("blocked", "pineapple tea cloud", None), ("allowed", "neutral orchard cloud", None),
    ("blocked", "pineapple river cloud", None), ("blocked", "pineapple stone cloud", None), ("blocked", "pineapple glass cloud", None),
    ("allowed", "neutral river cloud", None), ("blocked", "pineapple mist cloud", None), ("blocked", "pineapple wind cloud", None),
    ("blocked", "pineapple salt cloud", None),
    ("repeat", "neutral orchard cloud", None), ("allowed", "neutral tea cloud", None), ("slow", "neutral slow cloud", 1.1),
    ("allowed", "neutral glass cloud", None), ("allowed", "neutral stone cloud", None), ("blocked", "pineapple dust cloud", None),
    ("allowed", "neutral mist cloud", None), ("allowed", "neutral wind cloud", None), ("allowed", "neutral salt cloud", None),
    ("allowed", "neutral dust cloud", None),
]
GROUP = dict(blocked=RULE + " type", allowed="neutral", repeat="neutral (repeat of probe 3)", slow="neutral, long compute")
READ_AFTER = (9, 19)  # request indexes after which Red reads the meter (a batch of 10 is complete)


def sequence():
    return [dict(index=i, probe=f"Probe {i + 1}", case=case, group=GROUP[case], prompt=text, slow_compute=delay)
            for i, (case, text, delay) in enumerate(SEQUENCE)]


def attempts(world, run_id):
    uri = (Path(world.config["DATA_DIR"]) / "runs.sqlite").resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True, timeout=10)) as db:
        return db.execute("SELECT blue_allowed, cancelled, late, done FROM attempts WHERE run_id=? ORDER BY id", (run_id,)).fetchall()


async def record_arm(directory, name, title, policy, continue_mode, feedback, save):
    from common import PENDING
    from eval.live import Lab
    from verify_audit import verify
    extra = {"FEEDBACK_MODE": "meter"} if feedback else {}
    async with Lab(Path(directory) / name, scale=SCALE, policy=policy, audit=True, window_continue=continue_mode, extra_env=extra) as lab:
        world, rid = lab.worlds[0], "duel-" + uuid.uuid4().hex  # world 0 holds the fictional keyword rule
        arm = dict(name=name, title=title, policy=policy, window_continue=continue_mode, feedback_mode="meter" if feedback else "none",
                   requests=[], meter=None, audit=dict(status="NOT RUN"))
        reads = []
        for item in sequence():
            try:
                seen = await world.observe(rid, item["prompt"], item["slow_compute"])
                red = dict(status=seen["status"], body_length=seen["body_length"], release_seconds=round(seen["total"], 4), envelope_exact=True)
            except RuntimeError:
                red = dict(status=None, body_length=None, release_seconds=None, envelope_exact=False)
            arm["requests"].append(dict(index=item["index"], red=red))
            if feedback and item["index"] in READ_AFTER:
                await asyncio.sleep(0.4)  # the worker thread publishes after the response was released
                response = await world.client.get(f"/v1/run/{rid}/feedback", headers=world.auth("red"))
                body = response.content
                reads.append(dict(after_probe=item["index"] + 1, state=None if body == PENDING else json.loads(body).get("meter")))
            save(arm)
        await world.finish(rid)
        for request, row in zip(arm["requests"], attempts(world, rid)):
            allowed, cancelled, late = (None if row[0] is None else bool(row[0])), bool(row[1]), bool(row[2])
            request["evaluator"] = dict(blue_allowed=allowed, model_called=bool(allowed), model_completed=bool(allowed) and not cancelled,
                                        cancelled=cancelled, late=late)
        if feedback:
            truth = await world.client.get(f"/v1/run/{rid}/meter-evaluation", headers=world.auth("evaluator"))
            truth = truth.json() if truth.content != PENDING else {}
            arm["meter"] = dict(reads=reads, reads_used=truth.get("reads"), reads_budget=3, batches=truth.get("batches", []))
        await lab.audit_check({0: [rid]}, drain_seconds=15)
        root = Path(directory) / name
        checkpoint = root / f"checkpoints-0/{rid}.json"
        ok, reason, _ = verify(root / f"audit-logs-0/{rid}.jsonl", checkpoint, checkpoint.parent / "public_key.bin", rid,
                               Path(world.config["DATA_DIR"]) / "runs.sqlite")
        arm["audit"] = dict(status="VALID" if ok else "INVALID", count=read_json(checkpoint).get("count"))
        save(arm)
        return arm


async def run_duel(path):
    path = Path(path)
    state = dict(label=LABEL, recorded_at=time.time(), status="running", scale=SCALE, sequence=sequence(), arms={})

    def save(arm=None):
        if arm is not None:
            state["arms"][arm["name"]] = arm
        if not atomic_json(path, state):
            raise RuntimeError("Side-by-side recording unavailable")
    save()
    try:
        with tempfile.TemporaryDirectory(prefix="hnp-duel-") as directory:
            await record_arm(directory, "raw", "Bina defense (raw timing)", "raw", False, False, save)
            await record_arm(directory, "ours", "Hamare solution ke saath (window_hard + continue)", "window_hard", True, True, save)
        state["status"] = "complete"
        save()
    except BaseException:
        state["status"] = "failed"
        save()
        raise
    return state


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(__file__).parent / "runtime/observations/duel.json")
    args = parser.parse_args()
    result = asyncio.run(run_duel(args.output))
    for name, arm in result["arms"].items():
        times = [r["red"]["release_seconds"] for r in arm["requests"] if r["red"]["release_seconds"] is not None]
        print(f"{LABEL}: {name}: {len(times)} requests, release {min(times):.3f}-{max(times):.3f} s, audit {arm['audit']['status']}")
