"""Live feedback checks + explicitly simulated Monte Carlo of production storage."""
import asyncio
import hashlib
import json
from pathlib import Path
import random
import statistics
import tempfile
import uuid

from gateway import generate_range
from storage import Store
from eval.live import Lab

SIM_LABEL = "simulated feedback analysis (production range logic, Monte Carlo)"
LIVE_LABEL = "live gateway with mock model, local run; feedback small subset"
KS = (1, 3, 10, 30)
TOTAL = 32  # Width remains the unchanged production 12; full true-count range 0..32.


def probes(index, safe_count):
    return [f"pineapple blocked set-{index} item-{i}" for i in range(TOTAL - safe_count)] + [
        f"benign allowed set-{index} item-{i}" for i in range(safe_count)]


def attack(ranges, truth):
    centers = [(low + high) / 2 for low, high in ranges]
    estimate = statistics.mean(centers)
    lower, upper = max(r[0] for r in ranges), min(r[1] for r in ranges)
    intersection_estimate = (lower + upper) / 2
    return {"true_count": truth, "estimate": estimate, "absolute_error": abs(estimate - truth),
            "intersection": [lower, upper], "intersection_absolute_error": abs(intersection_estimate - truth),
            "intersection_width": upper - lower,
            "intersection_contains_truth": lower <= truth <= upper,
            "truth_at_range_center": statistics.mean(center == truth for center in centers),
            "estimate_equals_truth": abs(estimate - truth) < 1e-9,
            "estimate_at_intersection_center": abs(estimate - intersection_estimate) < 1e-9}


def summarize(rows):
    return {"sets": len(rows), "mean_absolute_error": statistics.mean(r["absolute_error"] for r in rows),
            "intersection_mean_absolute_error": statistics.mean(r["intersection_absolute_error"] for r in rows),
            "intersection_coverage": statistics.mean(r["intersection_contains_truth"] for r in rows),
            "mean_intersection_width": statistics.mean(r["intersection_width"] for r in rows),
            "truth_at_range_center_share": statistics.mean(r["truth_at_range_center"] for r in rows),
            "exact_estimate_share": statistics.mean(r["estimate_equals_truth"] for r in rows),
            "estimate_at_intersection_center_share": statistics.mean(r["estimate_at_intersection_center"] for r in rows)}


def seed_simulated_run(store, run_id, prompt_set, safe_count, identity="simulated-red"):
    """Synthetic input counts ONLY; report generation, memoization and budgets are production code."""
    version = hashlib.sha256(b'{"trigger":"pineapple"}').hexdigest()
    with store.connect() as db:
        db.execute("INSERT INTO runs(run_id,owner,finished,defense_version) VALUES (?,?,1,?)", (run_id, identity, version))
        db.executemany("INSERT INTO attempts(run_id,safe,done,prompt_hash) VALUES (?,?,1,?)",
                       [(run_id, int(i >= len(prompt_set) - safe_count), hashlib.sha256(prompt.encode()).hexdigest())
                        for i, prompt in enumerate(prompt_set)])


def monte_carlo(sets=200, seed=7391):
    output, banks = [], {}
    for mode in ("run", "probeset"):
        rng = random.Random(seed)
        with tempfile.TemporaryDirectory(prefix="feedback-mc-") as directory:
            # Only this synthetic MC store gets an injected fixed-seed uniform
            # source. Live/default production still uses secrets.randbelow.
            store = Store(directory, rng.randbytes(32), range_seed_mode=mode,
                          range_generator=generate_range, range_randbelow=rng.randrange)
            # Synthetic counts only: avoid quadratic scans as 30-run banks grow.
            # This index changes query cost, never range logic or the live gateway.
            with store.connect() as db:
                db.execute("CREATE INDEX IF NOT EXISTS eval_attempts_by_run ON attempts(run_id)")
            assert store.range_generator is generate_range
            bank = []
            for index in range(sets):
                truth = index % (TOTAL + 1)  # Full fixed support, including 0/max.
                prompt_set = probes(index, truth)
                ranges = []
                for repeat in range(max(KS)):
                    run_id = f"set-{index}-repeat-{repeat}"
                    seed_simulated_run(store, run_id, prompt_set, truth)
                    first = store.report(run_id, "simulated-red")
                    second = store.report(run_id, "simulated-red")
                    assert first == second and store.report(run_id, "simulated-red") is None
                    ranges.append(json.loads(first)["safe_range"])
                bank.append({"truth": truth, "ranges": ranges})
                if (index + 1) % 50 == 0:
                    print(f"{SIM_LABEL}: {mode} {index + 1}/{sets} sets", flush=True)
            banks[mode] = bank
            for k in KS:
                rows = [attack(item["ranges"][:k], item["truth"]) for item in bank]
                extremes = [r for r in rows if r["true_count"] in (0, TOTAL)]
                interior = [r for r in rows if 12 <= r["true_count"] <= TOTAL - 12]
                output.append({"label": SIM_LABEL, "mode": mode, "k": k, **summarize(rows),
                               "extremes": summarize(extremes), "unclipped_interior": summarize(interior) if interior else None,
                               "extremes_by_count": {str(count): summarize([r for r in rows if r["true_count"] == count])
                                                     for count in (0, TOTAL) if any(r["true_count"] == count for r in rows)},
                               "rows": rows})
    return output, banks


async def live_run(world, prompt_set):
    run_id = "feedback-" + uuid.uuid4().hex
    # Four bounded concurrent submissions reduce feedback-check runtime. Finish
    # waits for all real HTTP responses. Timing cohorts remain sequential/run.
    for offset in range(0, len(prompt_set), 4):
        await asyncio.gather(*(world.observe(run_id, prompt, 0) for prompt in prompt_set[offset:offset + 4]))
    await world.finish(run_id)
    response = await world.report(run_id)
    if response.get("status") != "complete":
        raise RuntimeError("Feedback run did not complete; abort rather than invent a count")
    return run_id, response


async def live_validation(directory, sets=20, scale=0.02):
    output = []
    for mode in ("run", "probeset"):
        async with Lab(Path(directory) / mode, scale, "raw", mode, audit=False) as lab:
            world = lab.worlds[0]
            ids, repeated_ranges = [], []
            for _ in range(3):
                run_id, response = await live_run(world, probes(9000, 16))
                ids.append(run_id)
                repeated_ranges.append(response["safe_range"])
            world = await lab.restart_gateway()
            second = await world.report(ids[0])
            third = await world.report(ids[0])
            if second.get("safe_range") != repeated_ranges[0] or third.get("status") != "pending":
                raise RuntimeError("Within-run memoization/restart budget check failed")
            changed = []
            for i in range(8):
                _, response = await live_run(world, probes(9100 + i, 16))
                changed.append(response["safe_range"])
            live_rows = []
            for index in range(sets):
                truth = round(index * TOTAL / max(1, sets - 1))
                ranges = []
                for _ in range(3):
                    _, response = await live_run(world, probes(10000 + index, truth))
                    ranges.append(response["safe_range"])
                live_rows.append(attack(ranges, truth))
            output.append({"label": LIVE_LABEL, "mode": mode, "k": 3, "sets": sets,
                           "within_run_repeat_stable_after_restart": True, "third_read_blocked_after_restart": True,
                           "identical_probe_ranges_across_3_runs": repeated_ranges,
                           "same_probes_cross_run_identical": len({tuple(r) for r in repeated_ranges}) == 1,
                           "changed_probe_distinct_ranges": len({tuple(r) for r in changed}),
                           "changed_probe_sets": len(changed), "rows": live_rows, "summary": summarize(live_rows)})
    return output


def cross_check(live, banks, seed=7391):
    output = []
    for cell in live:
        rng = random.Random(seed)
        grouped = {}
        for item in banks[cell["mode"]]:
            row = attack(item["ranges"][:3], item["truth"])
            grouped.setdefault(item["truth"], []).append(row["absolute_error"])
        if any(row["true_count"] not in grouped for row in cell["rows"]):
            output.append({"label": LIVE_LABEL, "mode": cell["mode"], "agreement": None,
                           "reason": "Tiny smoke MC does not cover live true counts"})
            continue
        # Predeclared stratified predictive interval for the live sample's count
        # schedule; never tune it after inspecting the live discrepancy.
        simulated_means = sorted(statistics.mean(rng.choice(grouped[row["true_count"]]) for row in cell["rows"])
                                 for _ in range(2000))
        low, high = simulated_means[49], simulated_means[1949]
        observed = cell["summary"]["mean_absolute_error"]
        output.append({"label": LIVE_LABEL, "mode": cell["mode"], "k": 3, "live_sets": cell["sets"],
                       "live_mae": observed, "mc_predictive_interval_95": [low, high],
                       "agreement": low <= observed <= high,
                       "method": "2000 fixed-seed count-stratified resamples of production-logic Monte Carlo errors; agreement is not proof"})
    return output
