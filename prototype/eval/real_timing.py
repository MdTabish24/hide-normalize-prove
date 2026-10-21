"""Real-model timing test (PARAMS.md v4): can Red tell Blue's rule A from B by release time with a real model?

    python -m eval.real_timing --cell raw                 # DeepSeek key from env, prototype/.env or a hidden prompt
    python -m eval.real_timing --cell window_continue
    python -m eval.real_timing --cell window_continue --mock --smoke      # harness check, scaled mock, no key, not a result

Label: real model run, small sample, local (localhost processes, not Docker isolation). About 10 minutes per cell.
The key is never printed or written; every output file is checked for it and removed if it appears.
"""
import argparse
import asyncio
import json
import os
from pathlib import Path
import statistics
import tempfile
import time

from dashboard.real_batch import get_key
from dashboard.story import timing_verdict
from eval.live import Lab
from eval.matrix import summarize_cell
from eval.run import timing_cell
from stats import percentile

SEED = 20261024
LABEL = "real model run, small sample, local"
CELLS = {"raw": dict(policy="raw", window_continue=False), "window_continue": dict(policy="window_hard", window_continue=True)}


async def run_cell(name, n_train, n_test, concurrency, mock):
    spec = CELLS[name]
    key = None if mock else get_key()
    if key:
        os.environ["DEEPSEEK_API_KEY"] = key  # Lab hands it only to the provider adapter process.
    scale, window = (0.1, 0.9) if mock else (1, 3.0)
    started = time.time()
    with tempfile.TemporaryDirectory(prefix="real-timing-") as directory:
        async with Lab(Path(directory) / name, scale, spec["policy"], audit=True, backend="mock" if mock else "deepseek",
                       window_continue=spec["window_continue"], window_seconds=window, extra_env={"AUDIT_BATCH": "50"}) as lab:
            cell = await timing_cell(lab, "ordinary", n_test, n_train, SEED, concurrency)
            ids = {w: [r["run_id"] for r in cell["samples"] if r["secret"] == w] for w in (0, 1)}
            outcomes, late = {}, 0
            for w in (0, 1):
                outcomes |= lab.outcomes(w, ids[w])
                late += sum(lab.late_counts(w, ids[w]).values()) if spec["window_continue"] else 0
            audit = await lab.audit_check(ids, drain_seconds=60)
            dead = lab.dead_servers()
    summary = summarize_cell(cell, outcomes)
    totals = [o["total"] for r in cell["samples"] for o in r["observations"]]
    low, high = summary["wilson_95"]
    allowed = sum(row[1] for row in outcomes.values())
    result = dict(label=LABEL if not mock else "MOCK dry run (not a real model)", cell=name, policy=spec["policy"], window_seconds=window,
                  deadline_seconds=round(0.8 * window, 3), params_version=4, seed=SEED, train_runs=summary["train_runs"], test_runs=summary["test_runs"],
                  accuracy=summary["test_accuracy"], wilson_95=[low, high], train_accuracy=summary["train_accuracy"],
                  verdict=timing_verdict(summary["test_accuracy"], summary["test_runs"], [low, high])["status"],
                  release_seconds=dict(median=round(statistics.median(totals), 3), p95=round(percentile(totals, 95), 3),
                                       p99=round(percentile(totals, 99), 3), min=round(min(totals), 3), max=round(max(totals), 3)),
                  blue_allowed_attempts=allowed, cancelled=summary["cancelled"], late_after_deadline=late if spec["window_continue"] else None,
                  late_share_of_allowed=None if not spec["window_continue"] or not allowed else round(late / allowed, 4),
                  distinct_response_shapes=summary["distinct_response_shapes"],
                  audit=dict(runs=audit["runs"], valid=audit["valid"], reasons=audit["reasons"], queue=audit["queue"]), dead_servers=dead,
                  minutes=round((time.time() - started) / 60, 1))
    return result, key


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cell", choices=sorted(CELLS), required=True)
    parser.add_argument("--mock", action="store_true", help="scaled mock model, no key (harness check only)")
    parser.add_argument("--smoke", action="store_true", help="6 + 6 runs")
    parser.add_argument("--output", type=Path, default=Path("eval/output/real_timing"))
    args = parser.parse_args()
    n_train, n_test = (6, 6) if args.smoke else (60, 60)
    print(f"{'MOCK DRY RUN' if args.mock else LABEL}: cell {args.cell}, {n_train}+{n_test} runs, concurrency 4", flush=True)
    result, key = asyncio.run(run_cell(args.cell, n_train, n_test, 4, args.mock))
    text = json.dumps(result, indent=2) + "\n"
    if key and key in text:
        raise SystemExit("Key found in the result; nothing was written. Regenerate the key.")
    if not args.mock:
        args.output.mkdir(parents=True, exist_ok=True)
        (args.output / f"{args.cell}.json").write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
