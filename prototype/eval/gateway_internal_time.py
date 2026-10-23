"""Gateway-internal time, blocked vs allowed (mock model, sim_delay=0, so no model wait). python -m eval.gateway_internal_time. Result 2026-10-22: blocked 62.1 ms vs allowed 78.1 ms median (audit off), 76.5 vs 97.4 ms (audit on); one run, idle laptop."""
import asyncio, json, random, statistics as st, sys, tempfile, uuid
from pathlib import Path
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))
from eval.live import Lab


async def main(policy, audit):
    rows = []
    with tempfile.TemporaryDirectory() as directory:
        async with Lab(Path(directory) / "x", 0.1, policy, audit=audit, demo_trace=True) as lab:
            world = lab.worlds[0]  # rule "pineapple"
            plan = ["blocked"] * 100 + ["allowed"] * 100
            random.Random(7).shuffle(plan)
            for case in plan:
                run_id = "t-" + uuid.uuid4().hex
                prompt = "orchard pineapple cloud" if case == "blocked" else "orchard cloud banana"
                await world.observe(run_id, prompt, sim_delay=0)
            await asyncio.sleep(1)
            trace = [json.loads(l) for l in (Path(world.config["DATA_DIR"]) / "demo-trace.jsonl").read_text().splitlines() if l.strip().startswith("{")]
    out = {}
    for name, flag in (("blocked", False), ("allowed", True)):
        v = sorted(t["compute_seconds"] * 1000 for t in trace if t.get("blue_allowed") is flag)
        out[name] = dict(n=len(v), median_ms=round(st.median(v), 1), p95_ms=round(v[int(0.95 * len(v)) - 1], 1), mean_ms=round(st.mean(v), 1))
    print(policy, "audit" if audit else "noaudit", json.dumps(out))

for policy, audit in (("raw", False), ("raw", True)):
    asyncio.run(main(policy, audit))
