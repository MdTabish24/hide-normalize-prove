"""Run from prototype: python -m eval.run. Actual HTTP, no API/model credentials."""
import argparse
import asyncio
import bisect
import hashlib
import json
from pathlib import Path
import random
import statistics
import tempfile
import uuid

from sklearn.tree import DecisionTreeClassifier

from eval.feedback import LIVE_LABEL, SIM_LABEL, cross_check, live_validation, monte_carlo
from eval.live import LABEL, Lab

COHORTS = ("ordinary", "boundary", "overflow")
POLICIES = ("raw", "bucket", "bucket_hard")


def probe_plan(cohort, seed, scale):
    rng = random.Random(seed)
    suffix = " ".join(rng.choice(("orchard", "river", "cloud", "garden", "stone")) for _ in range(8))
    if cohort == "ordinary":
        # Random benign text, fixed known probe slots, repeated prefixes create
        # real within-run cache reuse. Labels never enter these plans.
        return [("pineapple " + suffix, None)] * 3 + [("neutral " + suffix, None)] * 3
    if cohort in ("deadline_near", "deadline_far"):
        # Round 2, predeclared: window_hard deadline D = 0.8 x last bucket (7.2 x scale).
        # A's allowed probes finish just below D; B's just above D, or far past the window.
        below, above = 6.9, (7.5 if cohort == "deadline_near" else 9.8)
    else:
        below, above = ((2.65, 3.25) if cohort == "boundary" else (8.2, 9.8))
    # A blocks pineapple and allows mango: its allowed requests are below the
    # target. B does the reverse: its allowed requests are above the target.
    return [("mango " + suffix, below * scale)] * 3 + [("pineapple " + suffix, above * scale)] * 3


def features(observations, buckets):
    """Only HTTP observations. No labels, IDs, prompt text, URLs or backend state."""
    result = []
    for field in ("total", "ttfb"):
        values = [row[field] for row in observations]
        result.extend(sorted(values))
        result.extend((statistics.mean(values), statistics.pstdev(values), min(values), max(values)))
    cuts = [buckets[0] / 2] + [(a + b) / 2 for a, b in zip(buckets, buckets[1:])] + [buckets[-1] + (buckets[-1] - buckets[-2]) / 2]
    for row in observations:
        result.extend((row["status"], row["body_length"], int(row["header_fingerprint"][:8], 16),
                       bisect.bisect_right(cuts, row["ttfb"])))
    return result


def wilson(correct, n):
    z = 1.959963984540054
    p, denominator = correct / n, 1 + z * z / n
    center = (p + z * z / (2 * n)) / denominator
    half = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / denominator
    return [center - half, center + half]


async def timing_cell(lab, cohort, n, train_n, seed, concurrency):
    jobs = []
    for split, size in (("train", train_n), ("test", n)):
        for secret in (0, 1):
            for index in range(size // 2):
                plan_seed = seed + index + (100000 if split == "test" else 0)
                jobs.append((split, secret, probe_plan(cohort, plan_seed, lab.scale)))
    random.Random(seed).shuffle(jobs)
    semaphore = asyncio.Semaphore(concurrency)
    completed = 0

    async def one(job):
        nonlocal completed
        split, secret, plan = job
        async with semaphore:
            world, run_id = lab.worlds[secret], "timing-" + uuid.uuid4().hex
            observations = [await world.observe(run_id, prompt, delay) for prompt, delay in plan]
            await world.finish(run_id)
            completed += 1
            if completed % 100 == 0:
                print(f"{LABEL}: {cohort}/{lab.policy} {completed}/{len(jobs)} runs", flush=True)
            return {"run_id": run_id, "split": split, "secret": secret, "observations": observations}

    samples = await asyncio.gather(*(one(job) for job in jobs))
    train, test = [[r for r in samples if r["split"] == split] for split in ("train", "test")]
    assert not ({r["run_id"] for r in train} & {r["run_id"] for r in test})
    attacker = DecisionTreeClassifier(max_depth=3, random_state=seed)
    attacker.fit([features(r["observations"], lab.buckets) for r in train], [r["secret"] for r in train])
    train_accuracy = float(attacker.score([features(r["observations"], lab.buckets) for r in train], [r["secret"] for r in train]))
    predictions = attacker.predict([features(r["observations"], lab.buckets) for r in test])
    correct = sum(int(p == row["secret"]) for p, row in zip(predictions, test))
    test_accuracy = correct / len(test)
    return {"label": LABEL, "cohort": cohort, "policy": lab.policy, "train_runs": len(train), "test_runs": len(test),
            "test_runs_per_secret": len(test) // 2, "requests_per_run": 6,
            "train_accuracy": train_accuracy, "test_accuracy": test_accuracy,
            "train_test_gap": train_accuracy - test_accuracy, "wilson_95": wilson(correct, len(test)),
            "samples": samples}


def save_outputs(directory, data):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "results.json").write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    lines = [f"# {LABEL}", "", f"Artifact status: {data.get('status', 'unknown')}. " + data.get('status_note', ''), "",
             "Held-out RUN accuracy. Fixed depth-3 decision tree; all response features are observed over HTTP.", "",
             f"Seed: {data['seed']}; buckets: {' / '.join(f'{b:g}' for b in data['buckets'])} seconds; concurrent runs: {data['concurrent_runs']}; "
             f"audit collector delivery: {'enabled' if data['audit_enabled_for_timing'] else 'disabled (--no-audit)'}. ", "",
             "| Cohort | Policy | Train accuracy (n) | Unseen test (95% Wilson) | Gap | Test runs |", "|---|---|---:|---:|---:|---:|"]
    for cell in data["timing"]:
        low, high = cell["wilson_95"]
        lines.append(f"| {cell['cohort']} | {cell['policy']} | {cell['train_accuracy']:.1%} (n={cell['train_runs']}) | {cell['test_accuracy']:.1%} ({low:.1%}–{high:.1%}) | {cell['train_test_gap']:+.1%} | {cell['test_runs']} |")
    if not data.get("feedback_live"):
        lines += ["", "Feedback artifacts: **NOT RUN / unavailable in this saved artifact**. Do not infer feedback results from timing measurements."]
    lines += ["", f"## {SIM_LABEL}", "", "Synthetic counts span 0..32; production width=12 and two-read per-run budget are unchanged.",
              "Estimate = mean of reported interval midpoints. Intersection estimate = midpoint of the intersection.", "",
              "| Mode | K | Sets | Mean absolute error | Intersection MAE | Truth in intersection | Truth at range center | Exact estimate | Estimate at intersection center |",
              "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for cell in data["feedback_monte_carlo"]:
        lines.append(f"| {cell['mode']} | {cell['k']} | {cell['sets']} | {cell['mean_absolute_error']:.3f} | {cell['intersection_mean_absolute_error']:.3f} | {cell['intersection_coverage']:.1%} | {cell['truth_at_range_center_share']:.1%} | {cell['exact_estimate_share']:.1%} | {cell['estimate_at_intersection_center_share']:.1%} |")
    lines += ["", f"### Extremes, separately — {SIM_LABEL}", "", "| Mode | K | Extreme sets | Mean absolute error | Intersection MAE | Coverage |", "|---|---:|---:|---:|---:|---:|"]
    for cell in data["feedback_monte_carlo"]:
        extreme = cell["extremes"]
        lines.append(f"| {cell['mode']} | {cell['k']} | {extreme['sets']} | {extreme['mean_absolute_error']:.3f} | {extreme['intersection_mean_absolute_error']:.3f} | {extreme['intersection_coverage']:.1%} |")
    lines += ["", "For true count 0 the interval is [0,12]; for 32 it is [20,32]. These disjoint ranges disclose the extreme hypothesis even though their midpoint estimates remain biased by 6. Per-extreme metrics are also in JSON.",
              "", f"### Unclipped interior (counts 12..20), predeclared — {SIM_LABEL}", "",
              "| Mode | K | Sets | Averaging MAE | Intersection MAE | Mean intersection width |", "|---|---:|---:|---:|---:|---:|"]
    for cell in data["feedback_monte_carlo"]:
        interior = cell["unclipped_interior"]
        if interior:
            lines.append(f"| {cell['mode']} | {cell['k']} | {interior['sets']} | {interior['mean_absolute_error']:.3f} | {interior['intersection_mean_absolute_error']:.3f} | {interior['mean_intersection_width']:.3f} |")
    lines += ["", f"## {LIVE_LABEL}", "",
              "The budget blocks the third read of the SAME run, including after restart. Three fresh run IDs each have their own allowance; this does not prevent cross-run averaging.", "",
              "| Mode | Live sets (K=3) | Live MAE | True count at range center | Inside, off-center | Monte Carlo 95% predictive interval | Agreement |", "|---|---:|---:|---:|---:|---|---|"]
    for cell in data["feedback_cross_check"]:
        interval = cell.get("mc_predictive_interval_95")
        summary = next(item["summary"] for item in data["feedback_live"] if item["mode"] == cell["mode"])
        center_share = summary["truth_at_range_center_share"]
        elsewhere = f"{1 - center_share:.1%}" if summary["intersection_coverage"] == 1 else "coverage failure"
        lines.append(f"| {cell['mode']} | {cell.get('live_sets', 'smoke')} | {cell.get('live_mae', 0):.3f} | {center_share:.1%} | {elsewhere} | {interval} | {cell['agreement']} |")
    for cell in data["feedback_live"]:
        lines += ["", f"{LIVE_LABEL} — {cell['mode']}: same-run repeat stable after restart={cell['within_run_repeat_stable_after_restart']}; third same-run read blocked={cell['third_read_blocked_after_restart']}; same probes across 3 fresh runs identical={cell['same_probes_cross_run_identical']}; changed probes yielded {cell['changed_probe_distinct_ranges']} distinct ranges across {cell['changed_probe_sets']} sets; truth inside all returned ranges={cell['summary']['intersection_coverage']:.1%}."]
    if any(c["agreement"] is False for c in data["feedback_cross_check"]):
        lines += ["", "**Live/simulated discrepancy: Monte Carlo is NOT validated as a description of these live feedback errors. Do not claim that equivalence.**"]
    lines += ["", "## LIMITATIONS", "", *["- " + note for note in data["limitations"]]]
    (directory / "results_table.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(10, 5))
    for index, policy in enumerate(POLICIES):
        cells = [next(c for c in data["timing"] if c["cohort"] == cohort and c["policy"] == policy) for cohort in COHORTS]
        x = [i + (index - 1) * 0.24 for i in range(3)]
        ax.bar(x, [c["test_accuracy"] for c in cells], width=0.24, label=policy)
    ax.axhline(0.5, color="black", linestyle="--", linewidth=1, label="50% chance")
    ax.set_xticks(range(3), COHORTS)
    ax.set_ylim(0, 1.08)
    ax.set_ylabel("Unseen-run attacker accuracy")
    ax.set_title(LABEL + "\n" + ("audit collector enabled" if data["audit_enabled_for_timing"] else "audit collector disabled"), fontsize=11)
    ax.legend()
    fig.tight_layout()
    fig.savefig(directory / "leakage_matrix.png", dpi=160)
    plt.close(fig)
    if not data["feedback_monte_carlo"]:
        return
    fig, ax = plt.subplots(figsize=(10, 5))
    for mode in ("run", "probeset"):
        cells = [c for c in data["feedback_monte_carlo"] if c["mode"] == mode]
        ax.plot([c["k"] for c in cells], [c["mean_absolute_error"] for c in cells], marker="o", label=mode)
    ax.set_title(SIM_LABEL, fontsize=11)
    ax.set_xlabel("Independent runs K")
    ax.set_ylabel("Mean absolute count-estimation error")
    ax.set_xticks([1, 3, 10, 30])
    ax.legend()
    fig.tight_layout()
    fig.savefig(directory / "feedback_error.png", dpi=160)
    plt.close(fig)


async def evaluate(output, n=200, train_n=200, scale=0.1, concurrency=4, mc_sets=200, live_sets=20, seed=7391, audit=False):
    cells = []
    with tempfile.TemporaryDirectory(prefix="live-eval-") as directory:
        for policy in POLICIES:
            async with Lab(Path(directory) / policy, scale, policy, audit=audit) as lab:
                for cohort in COHORTS:
                    print(f"{LABEL}: collecting {cohort}/{policy}, train={train_n}, unseen={n}", flush=True)
                    cell = await timing_cell(lab, cohort, n, train_n, seed, concurrency)
                    cells.append(cell)
                    Path(output).mkdir(parents=True, exist_ok=True)
                    (Path(output) / "results.json").write_text(json.dumps(
                        {"label": LABEL, "status": "in_progress", "seed": seed, "scale": scale, "timing": cells},
                        indent=2) + "\n", encoding="utf-8")
                    print(f"{LABEL}: {cohort}/{policy} unseen={cell['test_accuracy']:.1%}", flush=True)
        print(f"{LIVE_LABEL}: verifying feedback and restart", flush=True)
        live = await live_validation(Path(directory) / "feedback", live_sets, scale)
        # Persist completed HTTP evidence before optional statistical analysis.
        (Path(output) / "results.json").write_text(json.dumps({
            "label": LABEL, "status": "in_progress", "seed": seed, "scale": scale,
            "buckets": [3 * scale, 6 * scale, 9 * scale], "concurrent_runs": concurrency,
            "audit_enabled_for_timing": audit, "timing": cells, "feedback_live": live,
        }, indent=2) + "\n", encoding="utf-8")
    print(f"{SIM_LABEL}: {mc_sets} probe sets per K/mode", flush=True)
    simulated, banks = monte_carlo(mc_sets, seed)
    data = {"label": LABEL, "status": "complete", "seed": seed, "scale": scale, "buckets": [3 * scale, 6 * scale, 9 * scale],
            "concurrent_runs": concurrency, "audit_enabled_for_timing": audit, "timing": cells,
            "feedback_live": live, "feedback_monte_carlo": simulated, "feedback_cross_check": cross_check(live, banks, seed),
            "limitations": ["Mock model and handcrafted benign probe cohorts; no real-model or production-secrecy claim.",
                "Audit collector delivery is " + ("enabled" if audit else "disabled (--no-audit)") + " in the timing matrix; measurements apply only to this recorded configuration.",
                "Collector-disabled timing runs are marked audit_unavailable by the unchanged gateway and are not audit-certified publishable runs.",
                "Timing matrix uses live localhost TCP/HTTP processes; Docker network isolation is not measured here.",
                "Both secret worlds share host resources and backend processes; concurrent runs are separate IDs, not guaranteed statistically independent hardware observations.",
                "Local scheduling, SQLite/audit work, first-body-chunk TTFB measurement and persistent world processes may add noise or confounds.",
                "Scaling mock sleeps and bucket deadlines does not scale fixed HTTP/SQLite/OS overhead, so results at scale 0.1 are not predictions for production 3/6/9-second buckets.",
                "Only one predeclared depth-3 decision tree and seed; chance-level accuracy does not prove absence of leakage.",
                "Boundary and overflow probes are expected to leak under bucket; hard timeout does not fix boundary probes or all completion/timeout signals.",
                "The overflow cohort also reveals which probe is blocked: A's mango slots are slow and pineapple slots fast; B reverses them. A hard cap can equalize slow times without hiding their positions. This cohort does not isolate the over-9s tail channel alone.",
                "Raw removes timing padding only: generic bodies and other gateway controls remain. Raw/bucket retain a 60-second operational timeout.",
                "EVAL_MODE is enabled ONLY for these local test servers. Each world gets identical plans; delays apply only to allowed model requests.",
                "Feedback Monte Carlo uses synthetic true counts, the SAME production generator/Store.report/budget, and a fixed injected uniform RNG for reproducibility; live production randomness remains secrets.randbelow.",
                "Narrow clipped ranges reveal coarse extremes even when point estimates remain biased. Check extremes separately.",
                "Probeset seeding is heuristic, not formal differential privacy. Slightly changed sets get fresh noise; repeated legitimate evaluations lose statistical independence.",
                "Different probe hashes can map to the same finite range. Tests check nonconstant variation, not impossible collision-free outputs.",
                "Operator result files contain ground-truth labels for scoring, never included in attacker feature vectors or returned by the gateway."]}
    save_outputs(output, data)
    for check in data["feedback_cross_check"]:
        print(f"{LIVE_LABEL}: {check['mode']} Monte Carlo agreement={check['agreement']}", flush=True)
    print(f"{LABEL}: saved results to {Path(output).resolve()}", flush=True)
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("eval/output"))
    parser.add_argument("--n", type=int, default=200, help="Unseen test RUNS per cohort/policy, half per secret")
    parser.add_argument("--train-n", type=int, default=200)
    parser.add_argument("--scale", type=float, default=0.1)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--mc-sets", type=int, default=200)
    parser.add_argument("--live-sets", type=int, default=20)
    parser.add_argument("--seed", type=int, default=7391)
    parser.add_argument("--audit", action=argparse.BooleanOptionalAction, default=False,
                        help="Opt into collector delivery; local audit-enabled load run remains unresolved")
    args = parser.parse_args()
    if any(v < 2 or v % 2 for v in (args.n, args.train_n)) or not 0 < args.scale <= 1 or args.concurrency < 1 or args.mc_sets < 2 or args.live_sets < 2:
        parser.error("Even n/train-n >=2, scale in (0,1], concurrency>=1, sets>=2 required")
    asyncio.run(evaluate(args.output, args.n, args.train_n, args.scale, args.concurrency, args.mc_sets, args.live_sets, args.seed, args.audit))


if __name__ == "__main__":
    main()
