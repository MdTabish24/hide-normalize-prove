"""Load-observer evaluation (PARAMS.md v2): does overload carry Blue's secret?

Red floods its gateway with prompts that world 0 (rule A) blocks and world 1 (rule B) allows, while the same Red client
measures its own six neutral probes. The attacker classifies the world from those observations only.

    python -m eval.load_observer --cell window_continue     # ~16 min per cell; keep the laptop idle
    python -m eval.load_observer --cell bucket_hard
    python -m eval.load_observer --cell window_continue --smoke      # harness check only, not a result

Label: live gateway, mock model, local run (timings x0.1). Parameters are fixed in PARAMS.md (version 2).
"""
import argparse
import asyncio
from contextlib import closing
import json
from pathlib import Path
import random
import sqlite3
import statistics
import tempfile
import time

from sklearn.tree import DecisionTreeClassifier

from dashboard.story import timing_verdict
from eval.live import LABEL, Lab
from eval.real_diagnostics import collect, permutation_check, slips
from eval.real_records import harvest
from eval.run import features
from stats import percentile, wilson

SEED = 20261023
FLOOD_WORKERS, OBSERVER_PROBES, WARMUP_SECONDS = 12, 6, 0.3
SCALE, WINDOW = 0.1, 0.9
FLOOD_KEYWORD = "pineapple"  # world 0 blocks it (cheap path), world 1 allows it (model call)
FINAL_FLAGS = {"AUDIT_BATCH": "50", "LOOP_OFFLOAD": "1", "BLUE_INLINE": "1", "RANGE_SEED_MODE": "coarse"}  # PARAMS v10 final profile
CELLS = {
    "bucket_hard": dict(policy="bucket_hard", window_continue=False),
    "window_continue": dict(policy="window_hard", window_continue=True),
    # Version 3 controls: identical except audit OFF, to separate the work channel from audit backlog.
    "bucket_hard_noaudit": dict(policy="bucket_hard", window_continue=False, audit=False),
    "window_continue_noaudit": dict(policy="window_hard", window_continue=True, audit=False),
    # Version 3 addendum: throughput check of the opt-in audit batching under the same flood.
    "window_continue_batch50": dict(policy="window_hard", window_continue=True, extra_env={"AUDIT_BATCH": "50"}),
    # PARAMS v7: LOOP_OFFLOAD flood test (mock model); seed 20261101.
    "window_continue_batch50_s2": dict(policy="window_hard", window_continue=True, extra_env={"AUDIT_BATCH": "50"}, seed=20261101),
    "window_continue_offload": dict(policy="window_hard", window_continue=True, extra_env={"AUDIT_BATCH": "50", "LOOP_OFFLOAD": "1"}, seed=20261101),
    "bucket_hard_offload": dict(policy="bucket_hard", window_continue=False, extra_env={"AUDIT_BATCH": "50", "LOOP_OFFLOAD": "1"}, seed=20261101),
    # PARAMS v10: final profile vs old default, with leave-one-out cells; seed 20261201.
    "final_profile": dict(policy="window_hard", window_continue=True, extra_env=dict(FINAL_FLAGS), seed=20261201),
    "bucket_hard_old": dict(policy="bucket_hard", window_continue=False, seed=20261201),
    "final_no_offload": dict(policy="window_hard", window_continue=True, extra_env={k: v for k, v in FINAL_FLAGS.items() if k != "LOOP_OFFLOAD"}, seed=20261201),
    "final_no_batch": dict(policy="window_hard", window_continue=True, extra_env={k: v for k, v in FINAL_FLAGS.items() if k != "AUDIT_BATCH"}, seed=20261201),
    "final_no_inline": dict(policy="window_hard", window_continue=True, extra_env={k: v for k, v in FINAL_FLAGS.items() if k != "BLUE_INLINE"}, seed=20261201),
    "real_final": dict(policy="window_hard", window_continue=True, extra_env=dict(FINAL_FLAGS), real=True),
    # PARAMS v6: the same flood with the REAL provider (real window W = 3 s, real buckets 3 / 6 / 9 s); audit ON with batching in both.
    "real_window_continue": dict(policy="window_hard", window_continue=True, extra_env={"AUDIT_BATCH": "50"}, real=True),
    "real_bucket_hard": dict(policy="bucket_hard", window_continue=False, extra_env={"AUDIT_BATCH": "50"}, real=True),
}


async def one_run(world, run_id, world_index=0, flood_log=None):
    """One run: a flood of FLOOD_WORKERS workers while the same client measures OBSERVER_PROBES neutral requests."""
    stop, flood_requests = asyncio.Event(), 0

    async def flood(slot):
        nonlocal flood_requests
        count = 0
        while not stop.is_set():
            count += 1
            try:
                seen = await world.observe(f"{run_id}-f{slot}", f"flood {slot} {count} {FLOOD_KEYWORD} orchard cloud")
                flood_requests += 1
                if flood_log is not None:
                    flood_log.append(dict(role="flood", world=world_index, run_id=f"{run_id}-f{slot}", index=count - 1, case="flood", client=seen))
            except RuntimeError:
                pass  # An unexpected envelope is not part of the observer's features; keep flooding.
    tasks = [asyncio.create_task(flood(slot)) for slot in range(FLOOD_WORKERS)]
    await asyncio.sleep(WARMUP_SECONDS)
    observations = []
    for probe in range(OBSERVER_PROBES):
        observations.append(await world.observe(run_id, f"observer {run_id} {probe} neutral river stone"))
    stop.set()
    await asyncio.gather(*tasks, return_exceptions=True)
    return observations, flood_requests


def outbox_size(lab, index):
    """Current number of undelivered audit events of one world (read-only; None if unreadable)."""
    uri = (Path(lab.worlds[index].config["DATA_DIR"]) / "audit_queue.sqlite").resolve().as_uri() + "?mode=ro"
    try:
        with closing(sqlite3.connect(uri, uri=True, timeout=2)) as db:
            return db.execute("SELECT COUNT(*) FROM audit_outbox").fetchone()[0]
    except sqlite3.Error:
        return None


async def sample_outbox(lab, stop, seen):
    while not stop.is_set():
        for index in (0, 1):
            size = outbox_size(lab, index)
            if size is not None:
                seen[index] = max(seen[index], size)
        try:
            await asyncio.wait_for(stop.wait(), 2)
        except asyncio.TimeoutError:
            pass


async def run_cell(name, n_train, n_test, output, diagnostics=False, mock=False):
    spec = CELLS[name]
    real = bool(spec.get("real")) and not mock
    seed = spec.get("seed", SEED)
    scale, window = (1, 3.0) if real else (SCALE, WINDOW)
    extra = dict(spec.get("extra_env") or {}) | ({"LOOP_LAG_LOG": "1"} if diagnostics else {})
    jobs = [(split, k % 2) for split, size in (("train", n_train), ("test", n_test)) for k in range(size)]
    random.Random(seed).shuffle(jobs)
    started = time.time()
    rows, max_pending, sampler_stop, flood_log = [], {0: 0, 1: 0}, asyncio.Event(), []
    with tempfile.TemporaryDirectory(prefix="load-observer-") as directory:
        async with Lab(Path(directory) / name, scale, spec["policy"], audit=spec.get("audit", True), window_continue=spec["window_continue"],
                       backend="deepseek" if real else "mock", window_seconds=window if real else None, demo_trace=diagnostics,
                       extra_env=extra, capture_dir=None if (spec.get("real") and mock) else output / "logs" / name) as lab:
            sampler = asyncio.create_task(sample_outbox(lab, sampler_stop, max_pending)) if spec.get("audit", True) else None
            for index, (split, secret) in enumerate(jobs):
                run_id = f"obs-{name}-{index}"
                observations, flood_requests = await one_run(lab.worlds[secret], run_id, secret, flood_log)
                attempts = lab.outcomes(secret, [run_id])[run_id]
                rows.append(dict(split=split, secret=secret, run_id=run_id, observations=observations, features=features(observations, lab.buckets),
                                 totals=[o["total"] for o in observations], flood_requests=flood_requests,
                                 observer_attempts=attempts[0], observer_cancelled=attempts[2]))
                if (index + 1) % 20 == 0:
                    print(f"{LABEL}: {name} {index + 1}/{len(jobs)} runs", flush=True)
            queue = (await lab.audit_check({0: [], 1: []}, drain_seconds=20))["queue"]
            dead = lab.dead_servers()
            sampler_stop.set()
            if sampler:
                await sampler
            trace, lags = collect(lab) if diagnostics else ([], [])
            # Every request (observer and flood) with what Red saw and what the evaluator knows. These runs were never finished, so they are finished here.
            requests = [dict(role="observer", world=r["secret"], run_id=r["run_id"], index=i, split=r["split"], case="allowed", client=o)
                        for r in rows for i, o in enumerate(r["observations"])] + flood_log
            records = await harvest(lab, requests, name, save=real, finish=True)
    train, test = [[r for r in rows if r["split"] == s] for s in ("train", "test")]
    tree = DecisionTreeClassifier(max_depth=3, random_state=seed).fit([r["features"] for r in train], [r["secret"] for r in train])
    correct = sum(int(p == r["secret"]) for p, r in zip(tree.predict([r["features"] for r in test]), test))
    low, high = wilson(correct, len(test))
    totals = [t for r in rows for t in r["totals"]]
    verdict = timing_verdict(correct / len(test), len(test), [low, high])
    return dict(label=LABEL, cell=name, policy=spec["policy"], window_continue=spec["window_continue"], audit=spec.get("audit", True),
                params_version=7 if "seed" in spec and not real else 6 if (real or diagnostics) else 3 if name.endswith("noaudit") else 2, seed=seed, real_model=real, window_seconds=window if real else None,
                flood_workers=FLOOD_WORKERS, observer_probes=OBSERVER_PROBES, scale=scale, train_runs=len(train), test_runs=len(test),
                accuracy=correct / len(test), wilson_95=[low, high], train_accuracy=float(tree.score([r["features"] for r in train], [r["secret"] for r in train])),
                verdict=verdict["status"], observer_release_seconds=dict(median=round(statistics.median(totals), 4), p95=round(percentile(totals, 95), 4),
                                                                         max=round(max(totals), 4)),
                mean_observer_attempts_recorded=round(statistics.mean(r["observer_attempts"] for r in rows), 3),
                observer_cancelled=sum(r["observer_cancelled"] for r in rows),
                mean_flood_requests_per_run=round(statistics.mean(r["flood_requests"] for r in rows), 1),
                audit_queue_after_drain=queue, dead_servers=dead, minutes=round((time.time() - started) / 60, 1),
                audit_batch=(spec.get("extra_env") or {}).get("AUDIT_BATCH"), max_outbox_sampled=max_pending if spec.get("audit", True) else None,
                throughput_check=None if not spec.get("audit", True) else dict(
                    passed=bool(max(max_pending.values()) < 10000 and all(q["dead_letters"] == 0 and q["pending_after_drain"] == 0 for q in queue) and not dead),
                    rule="max sampled pending < 10000, 0 dead letters, 0 pending after the 20 s drain, no dead server (PARAMS v3 addendum)"),
                records=records, permutation_check=permutation_check([dict(split=r["split"], secret=r["secret"], features=r["features"]) for r in rows]),
                **({"diagnostics": slips([o for r in rows for o in r["observations"]], trace, lags, window)} if diagnostics else {}),
                samples=[dict(split=r["split"], secret=r["secret"], totals=[round(o["total"], 3) for o in r["observations"]],
                              starts=[round(o["started_at"], 3) for o in r["observations"]]) for r in rows])


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cell", choices=sorted(CELLS), required=True)
    parser.add_argument("--smoke", action="store_true", help="6 + 6 runs only; checks the harness, not a result")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--diagnostics", action="store_true", help="demo trace + event-loop lag monitor (PARAMS v6)")
    parser.add_argument("--mock", action="store_true", help="use the scaled mock model even for the real_* cells (harness check)")
    args = parser.parse_args()
    real = bool(CELLS[args.cell].get("real")) and not args.mock
    output = args.output or Path("eval/output/real_overnight" if CELLS[args.cell].get("real") else "eval/output/load_observer")
    n_train, n_test = (6, 6) if args.smoke else (60, 60) if CELLS[args.cell].get("real") else (100, 100)
    result = asyncio.run(run_cell(args.cell, n_train, n_test, output, diagnostics=args.diagnostics or bool(CELLS[args.cell].get("real")), mock=args.mock))
    if real or not CELLS[args.cell].get("real"):
        output.mkdir(parents=True, exist_ok=True)
        suffix = "-smoke" if args.smoke else ""
        (output / f"{args.cell}{suffix}.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k not in ("label", "samples")}, indent=1))


if __name__ == "__main__":
    main()
