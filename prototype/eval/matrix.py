"""Round 2 live timing matrix (Phase 3). Run from prototype: python -m eval.matrix

Same attacker, cohorts, N, seed and timing scale as the Round 1 matrix
(eval/run.py), plus window_hard and deadline probes. Audit delivery is ON by
default. Every policy is set explicitly per Lab; nothing relies on defaults.
"""
import argparse
import asyncio
import json
from pathlib import Path
import platform
import statistics
import tempfile
import time

from eval.live import Lab
from eval.run import timing_cell

LABEL = "live gateway, mock model, local run"
POLICIES = ("raw", "bucket", "bucket_hard", "window_hard")
COHORTS = ("ordinary", "boundary", "overflow")
DEADLINE_COHORTS = ("deadline_near", "deadline_far")
DEADLINE_POLICIES = ("bucket_hard", "window_hard")
OLD_RESULTS = Path(__file__).parent / "output" / "results.json"


def cohorts_for(policy):
    return COHORTS + (DEADLINE_COHORTS if policy in DEADLINE_POLICIES else ())


def summarize_cell(cell, outcomes):
    totals = [o["total"] for r in cell["samples"] for o in r["observations"]]
    attempts = sum(row[0] for row in outcomes.values())
    allowed = sum(row[1] for row in outcomes.values())
    cancelled = sum(row[2] for row in outcomes.values())
    shapes = {(o["status"], o["body_length"], o["header_fingerprint"]) for r in cell["samples"] for o in r["observations"]}
    return {k: v for k, v in cell.items() if k != "samples"} | {
        "mean_latency_seconds": statistics.mean(totals), "max_latency_seconds": max(totals),
        "attempts": attempts, "allowed": allowed, "cancelled": cancelled,
        "timeout_rate_of_allowed": cancelled / allowed if allowed else 0.0,
        "distinct_response_shapes": len(shapes)}


def old_cells():
    try:
        data = json.loads(OLD_RESULTS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {(c["cohort"], c["policy"]): {k: c[k] for k in ("test_accuracy", "wilson_95", "test_runs")}
            for c in data.get("timing", [])}


def save(output, data):
    output.mkdir(parents=True, exist_ok=True)
    (output / "results.json").write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    old = old_cells()
    lines = [f"# Round 2 timing matrix: {LABEL}", "",
             f"Status: **{data['status']}**. Audit delivery: **{'ON' if data['audit'] else 'OFF'}**. "
             f"Scale factor {data['scale']} (buckets {' / '.join(f'{b:g}' for b in data['buckets'])} s; "
             f"window_hard W = {data['window']:g} s, deadline D = {data['deadline']:g} s). Seed {data['seed']}, "
             f"concurrency {data['concurrency']}, platform {data['platform']}.", "",
             "Unseen-run accuracy of the predeclared depth-3 decision tree (same attacker as Round 1). "
             "50% = this attacker could not tell A from B; it is not proof of no leak. "
             "Old = Round 1 matrix (audit OFF, before the Phase 1 release changes).", "",
             "| Cohort | Policy | Unseen accuracy (95% Wilson) | Train-test gap | Old (audit off) | Timeout rate of allowed | Mean latency | Added vs raw | Response shapes | Test runs |",
             "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    raw_latency = {c["cohort"]: c["mean_latency_seconds"] for c in data["cells"] if c["policy"] == "raw"}
    for cell in data["cells"]:
        low, high = cell["wilson_95"]
        previous = old.get((cell["cohort"], cell["policy"]))
        old_text = f"{previous['test_accuracy']:.1%}" if previous else "n/a"
        base = raw_latency.get(cell["cohort"])
        added = f"{cell['mean_latency_seconds'] - base:+.3f} s" if base is not None else "n/a"
        lines.append(f"| {cell['cohort']} | {cell['policy']} | {cell['test_accuracy']:.1%} ({low:.1%}–{high:.1%}) | "
                     f"{cell['train_test_gap']:+.1%} | {old_text} | {cell['timeout_rate_of_allowed']:.1%} | "
                     f"{cell['mean_latency_seconds']:.3f} s | {added} | {cell['distinct_response_shapes']} | {cell['test_runs']} |")
    for cohort, policy in data["not_run"]:
        lines.append(f"| {cohort} | {policy} | NOT RUN (runtime cap) | | | | | | | |")
    lines += ["", "## Audit status after each policy", "",
              "| Policy | Runs verified | VALID | Not valid (reasons) | Queue after drain |", "|---|---:|---:|---|---|"]
    for policy, audit in data["audit_checks"].items():
        lines.append(f"| {policy} | {audit['runs']} | {audit['valid']} | {audit['reasons'] or '-'} | {audit['queue']} |")
    lines += ["", "## Notes", "", *["- " + note for note in data["notes"]]]
    (output / "results_table.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


async def run_matrix(output, n, train_n, scale, concurrency, seed, audit, policies, max_minutes):
    started = time.monotonic()
    buckets = [3 * scale, 6 * scale, 9 * scale]
    data = {"label": LABEL, "status": "in_progress", "seed": seed, "scale": scale, "buckets": buckets,
            "window": buckets[-1], "deadline": 0.8 * buckets[-1], "concurrency": concurrency, "audit": audit,
            "n_test": n, "n_train": train_n, "platform": f"{platform.system()} host processes, Python {platform.python_version()}",
            "cells": [], "not_run": [], "audit_checks": {}, "notes": [
                "Timings are scaled down 10x (scale 0.1); fixed HTTP/SQLite/OS overhead is NOT scaled, which likely inflates timing differences relative to 3/6/9 s production buckets.",
                "Boundary and deadline cohorts use the EVAL_MODE sim_delay hook: the attacker controls compute time exactly (worst case, not a realistic Red).",
                "Overflow and deadline cohorts also contain a per-position fast/slow channel (A's slow slots are mango probes, B's are pineapple). Bucket policies cannot hide WHICH request is slow.",
                "Timeout rate = deadline/hard-timeout cancellations among Blue-allowed attempts, read by the trusted controller from the gateway DB.",
                "Response shapes = distinct (status, body length, header set) seen by Red across the cell; 1 means no error/shape oracle.",
                "Mean latency includes the policy's padding; added latency of a policy = its mean minus raw's mean for the same cohort.",
                "Windows host processes request 1 ms timer resolution (Phase 1). Results are not comparable 1:1 with Round 1 for that reason too.",
            ]}
    with tempfile.TemporaryDirectory(prefix="round2-matrix-") as directory:
        for policy in policies:
            async with Lab(Path(directory) / policy, scale, policy, audit=audit) as lab:
                run_ids = {0: [], 1: []}
                for cohort in cohorts_for(policy):
                    if (time.monotonic() - started) / 60 > max_minutes:
                        data["not_run"].append([cohort, policy])
                        continue
                    print(f"{LABEL}: {cohort}/{policy} train={train_n} unseen={n}", flush=True)
                    t0 = time.monotonic()
                    cell = await timing_cell(lab, cohort, n, train_n, seed, concurrency)
                    outcomes = {}
                    for world in (0, 1):
                        ids = [r["run_id"] for r in cell["samples"] if r["secret"] == world]
                        run_ids[world] += ids
                        outcomes |= lab.outcomes(world, ids)
                    summary = summarize_cell(cell, outcomes) | {"wall_seconds": round(time.monotonic() - t0, 1)}
                    data["cells"].append(summary)
                    with (output / "samples.jsonl").open("a", encoding="utf-8") as file:
                        file.write(json.dumps({"cohort": cohort, "policy": policy, "samples": cell["samples"]}) + "\n")
                    save(output, data)
                    print(f"{LABEL}: {cohort}/{policy} unseen={summary['test_accuracy']:.1%} "
                          f"timeouts={summary['timeout_rate_of_allowed']:.1%} ({summary['wall_seconds']} s)", flush=True)
                data["audit_checks"][policy] = await lab.audit_check(run_ids)
                save(output, data)
    data["status"] = "complete" if not data["not_run"] else "partial (runtime cap reached; see NOT RUN rows)"
    data["total_minutes"] = round((time.monotonic() - started) / 60, 1)
    save(output, data)
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("eval/output/round2"))
    parser.add_argument("--n", type=int, default=200)
    parser.add_argument("--train-n", type=int, default=200)
    parser.add_argument("--scale", type=float, default=0.1)
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--seed", type=int, default=7391)
    parser.add_argument("--audit", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--policies", nargs="+", choices=POLICIES, default=list(POLICIES))
    parser.add_argument("--max-minutes", type=float, default=120)
    parser.add_argument("--render-only", action="store_true", help="Rebuild tables from saved results.json")
    args = parser.parse_args()
    if args.render_only:
        return save(args.output, json.loads((args.output / "results.json").read_text(encoding="utf-8")))
    if any(v < 2 or v % 2 for v in (args.n, args.train_n)):
        parser.error("Even n/train-n >= 2 required")
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "samples.jsonl").unlink(missing_ok=True)
    data = asyncio.run(run_matrix(args.output, args.n, args.train_n, args.scale, args.concurrency, args.seed,
                                  args.audit, args.policies, args.max_minutes))
    print(f"{LABEL}: {data['status']} in {data['total_minutes']} min; saved {args.output.resolve()}", flush=True)


if __name__ == "__main__":
    main()
