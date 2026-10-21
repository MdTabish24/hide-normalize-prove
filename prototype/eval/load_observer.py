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
import json
from pathlib import Path
import random
import statistics
import tempfile
import time

from sklearn.tree import DecisionTreeClassifier

from dashboard.story import timing_verdict
from eval.live import LABEL, Lab
from eval.run import features
from stats import percentile, wilson

SEED = 20261023
FLOOD_WORKERS, OBSERVER_PROBES, WARMUP_SECONDS = 12, 6, 0.3
SCALE, WINDOW = 0.1, 0.9
FLOOD_KEYWORD = "pineapple"  # world 0 blocks it (cheap path), world 1 allows it (model call)
CELLS = {
    "bucket_hard": dict(policy="bucket_hard", window_continue=False),
    "window_continue": dict(policy="window_hard", window_continue=True),
}


async def one_run(world, run_id):
    """One run: a flood of FLOOD_WORKERS workers while the same client measures OBSERVER_PROBES neutral requests."""
    stop, flood_requests = asyncio.Event(), 0

    async def flood(slot):
        nonlocal flood_requests
        count = 0
        while not stop.is_set():
            count += 1
            try:
                await world.observe(f"{run_id}-f{slot}", f"flood {slot} {count} {FLOOD_KEYWORD} orchard cloud")
                flood_requests += 1
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


async def run_cell(name, n_train, n_test, output):
    spec = CELLS[name]
    jobs = [(split, k % 2) for split, size in (("train", n_train), ("test", n_test)) for k in range(size)]
    random.Random(SEED).shuffle(jobs)
    started = time.time()
    rows = []
    with tempfile.TemporaryDirectory(prefix="load-observer-") as directory:
        async with Lab(Path(directory) / name, SCALE, spec["policy"], audit=True, window_continue=spec["window_continue"],
                       capture_dir=output / "logs" / name) as lab:
            for index, (split, secret) in enumerate(jobs):
                run_id = f"obs-{name}-{index}"
                observations, flood_requests = await one_run(lab.worlds[secret], run_id)
                attempts = lab.outcomes(secret, [run_id])[run_id]
                rows.append(dict(split=split, secret=secret, features=features(observations, lab.buckets),
                                 totals=[o["total"] for o in observations], flood_requests=flood_requests,
                                 observer_attempts=attempts[0], observer_cancelled=attempts[2]))
                if (index + 1) % 20 == 0:
                    print(f"{LABEL}: {name} {index + 1}/{len(jobs)} runs", flush=True)
            queue = (await lab.audit_check({0: [], 1: []}, drain_seconds=20))["queue"]
            dead = lab.dead_servers()
    train, test = [[r for r in rows if r["split"] == s] for s in ("train", "test")]
    tree = DecisionTreeClassifier(max_depth=3, random_state=SEED).fit([r["features"] for r in train], [r["secret"] for r in train])
    correct = sum(int(p == r["secret"]) for p, r in zip(tree.predict([r["features"] for r in test]), test))
    low, high = wilson(correct, len(test))
    totals = [t for r in rows for t in r["totals"]]
    verdict = timing_verdict(correct / len(test), len(test), [low, high])
    return dict(label=LABEL, cell=name, policy=spec["policy"], window_continue=spec["window_continue"], params_version=2, seed=SEED,
                flood_workers=FLOOD_WORKERS, observer_probes=OBSERVER_PROBES, scale=SCALE, train_runs=len(train), test_runs=len(test),
                accuracy=correct / len(test), wilson_95=[low, high], train_accuracy=float(tree.score([r["features"] for r in train], [r["secret"] for r in train])),
                verdict=verdict["status"], observer_release_seconds=dict(median=round(statistics.median(totals), 4), p95=round(percentile(totals, 95), 4),
                                                                         max=round(max(totals), 4)),
                mean_observer_attempts_recorded=round(statistics.mean(r["observer_attempts"] for r in rows), 3),
                observer_cancelled=sum(r["observer_cancelled"] for r in rows),
                mean_flood_requests_per_run=round(statistics.mean(r["flood_requests"] for r in rows), 1),
                audit_queue_after_drain=queue, dead_servers=dead, minutes=round((time.time() - started) / 60, 1))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cell", choices=sorted(CELLS), required=True)
    parser.add_argument("--smoke", action="store_true", help="6 + 6 runs only; checks the harness, not a result")
    parser.add_argument("--output", type=Path, default=Path("eval/output/load_observer"))
    args = parser.parse_args()
    n_train, n_test = (6, 6) if args.smoke else (100, 100)
    result = asyncio.run(run_cell(args.cell, n_train, n_test, args.output))
    args.output.mkdir(parents=True, exist_ok=True)
    suffix = "-smoke" if args.smoke else ""
    (args.output / f"{args.cell}{suffix}.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "label"}, indent=1))


if __name__ == "__main__":
    main()
