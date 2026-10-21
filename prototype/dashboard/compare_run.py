"""Tiny paired HTTP demo. This is an instrumented mock run, not a leakage score."""
import argparse
import asyncio
import json
from pathlib import Path
import tempfile
import time
import uuid

from .recording import atomic_json
from .data import read_json


async def run_comparison(path):
    from common import HEADERS, PENDING
    from eval.live import Lab
    from verify_audit import verify
    path = Path(path)
    state = dict(recorded_at=time.time(), status="running", arms=[],
                 label="Paired live HTTP gateway, mock model, local instrumented run")
    def save():
        if not atomic_json(path, state):
            raise RuntimeError("Comparison artifact unavailable")
    save()
    # Both arms retain auth, Blue, encryption, output shaping and audit.
    # ONLY the timing policy differs. No fictional unprotected deployment.
    try:
        with tempfile.TemporaryDirectory(prefix="hnp-paired-") as directory:
            for policy in ("raw", "bucket_hard"):
                async with Lab(Path(directory)/policy, scale=.1, policy=policy, audit=True, demo_trace=True) as lab:
                    world = lab.worlds[0]  # Same pineapple keyword rule in both arms.
                    rid = "paired-"+uuid.uuid4().hex
                    arm = dict(policy=policy, requests=[], audit=dict(status="NOT RUN"))
                    state["arms"].append(arm); save()
                    for key, prompt, delay in (
                        ("blocked", "pineapple orchard cloud", None),
                        ("allowed", "neutral orchard cloud", None),
                        ("repeat", "neutral orchard cloud", None),
                        ("overflow", "neutral slow cloud", 1.1),
                    ):
                        start = time.perf_counter()
                        response = await world.client.post("/v1/submit", headers=world.auth("red"),
                            json={"run_id":rid, "prompt":prompt, **({"sim_delay":delay} if delay else {})})
                        total = time.perf_counter()-start
                        trace_path = Path(world.config["DATA_DIR"])/"demo-trace.jsonl"
                        traces = []
                        for _ in range(30):
                            if trace_path.exists():
                                traces = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines() if line]
                                traces = [row for row in traces if row.get("run_id")==rid]
                            if len(traces)>len(arm["requests"]): break
                            await asyncio.sleep(.01)
                        if len(traces)<=len(arm["requests"]):
                            raise RuntimeError("Actual decision trace missing; comparison not asserted")
                        trace=traces[len(arm["requests"])]
                        trace.pop("run_id",None)
                        arm["requests"].append(dict(case=key, total=total, status=response.status_code,
                            body_length=len(response.content), envelope_exact=response.content==PENDING and
                            response.status_code==202 and dict(response.headers)==HEADERS, trace=trace))
                        save()
                    await world.finish(rid)
                    await lab.audit_check({0:[rid]},drain_seconds=5)
                    root=Path(directory)/policy
                    checkpoint=root/f"checkpoints-0/{rid}.json"
                    ok,_,_=verify(root/f"audit-logs-0/{rid}.jsonl",checkpoint,checkpoint.parent/"public_key.bin",rid,
                                  Path(world.config["DATA_DIR"])/"runs.sqlite")
                    arm["audit"]=dict(status="VALID" if ok else "INVALID",count=read_json(checkpoint).get("count"))
                    save()
        state["status"]="complete";save()
    except BaseException:
        state["status"]="failed";save();raise
    return state


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path,default=Path(__file__).parent/"runtime/observations/comparison.json")
    args=parser.parse_args()
    result=asyncio.run(run_comparison(args.output))
    for arm in result["arms"]:
        print(arm["policy"],[(r["case"],round(r["total"],3),r["trace"]["reason"]) for r in arm["requests"]],arm["audit"])
