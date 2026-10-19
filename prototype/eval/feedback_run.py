"""Phase 5 feedback analysis. Run from prototype: python -m eval.feedback_run

Live HTTP checks (within-run repeat, third read blocked, restart persistence,
small K=3 cross-check) plus a Monte Carlo of cross-run averaging that calls
the SAME production range function and Store.report (tests assert identity).
This is a heuristic noise scheme, NOT formal differential privacy.
"""
import argparse
import asyncio
import json
from pathlib import Path
import tempfile
import time

from eval.feedback import KS, LIVE_LABEL, SIM_LABEL, TOTAL, cross_check, live_validation, monte_carlo

FIELDS = ("sets", "mean_absolute_error", "intersection_mean_absolute_error", "intersection_coverage", "mean_intersection_width")


def strip(cell):
    return {k: v for k, v in cell.items() if k != "rows"}


def save(output, data):
    output.mkdir(parents=True, exist_ok=True)
    (output / "results.json").write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    lines = [f"# Feedback analysis (Round 2, Phase 5)", "",
             f"True safe counts span 0..{TOTAL}; production range width 12; per-run budget 2 reads. "
             "Red's estimate = mean of range midpoints over K fresh runs of the same probe set. "
             "Heuristic noise, not formal differential privacy.", "",
             f"## {SIM_LABEL}", "", f"{data['mc_sets']} probe sets per K and mode, seed {data['seed']}.", "",
             "| Mode | K | Mean abs error (all counts) | Intersection MAE | Truth inside intersection | Mean intersection width | Extremes (0 and 32) MAE | Interior (12..20) MAE |",
             "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for c in data["monte_carlo"]:
        interior = c["unclipped_interior"]["mean_absolute_error"] if c["unclipped_interior"] else float("nan")
        lines.append(f"| {c['mode']} | {c['k']} | {c['mean_absolute_error']:.2f} | {c['intersection_mean_absolute_error']:.2f} | "
                     f"{c['intersection_coverage']:.0%} | {c['mean_intersection_width']:.1f} | {c['extremes']['mean_absolute_error']:.2f} | {interior:.2f} |")
    lines += ["", "Extremes, separately: a true count of 0 always yields [0,12] and 32 always yields [20,32], so the "
              "extreme outcome itself is identifiable from ONE report even though midpoints are biased by 6.", "",
              f"## {LIVE_LABEL}", "", "| Mode | Repeat stable after restart | Third same-run read blocked | Same probes, 3 fresh runs identical | "
              "Changed probe sets: distinct ranges | Live K=3 MAE | MC 95% predictive interval | Agreement |", "|---|---|---|---|---|---:|---|---|"]
    for live, check in zip(data["live"], data["cross_check"]):
        interval = check.get("mc_predictive_interval_95")
        interval = f"{interval[0]:.2f}-{interval[1]:.2f}" if interval else "n/a"
        lines.append(f"| {live['mode']} | {live['within_run_repeat_stable_after_restart']} | {live['third_read_blocked_after_restart']} | "
                     f"{live['same_probes_cross_run_identical']} | {live['changed_probe_distinct_ranges']}/{live['changed_probe_sets']} | "
                     f"{live['summary']['mean_absolute_error']:.2f} | {interval} | {check['agreement']} |")
    if any(c["agreement"] is False for c in data["cross_check"]):
        lines += ["", "**Live/simulated discrepancy: the Monte Carlo is NOT validated against live behavior for that mode.**"]
    lines += ["", "## What this shows / does not show", "",
              "- The per-run budget blocks a third read of the SAME run, including after a gateway restart.",
              "- It does NOT stop cross-run averaging: fresh run IDs each get their own budget (residual risk).",
              "- `probeset` mode returns the same range for the same probe set, so repeating it adds nothing; any change to the set gets fresh noise.",
              "- Monte Carlo uses synthetic counts with the production generator and Store.report; live noise uses secrets.randbelow."]
    (output / "results_table.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


async def run(output, mc_sets, live_sets, scale, seed):
    started = time.monotonic()
    data = {"label": "feedback", "status": "in_progress", "seed": seed, "mc_sets": mc_sets, "live_sets": live_sets,
            "live_scale": scale, "ks": list(KS)}
    with tempfile.TemporaryDirectory(prefix="feedback-live-") as directory:
        live = await live_validation(Path(directory), live_sets, scale)
    data["live"] = live
    save_partial = {k: v for k, v in data.items()}
    (output / "results.json").parent.mkdir(parents=True, exist_ok=True)
    (output / "results.json").write_text(json.dumps(save_partial, indent=2) + "\n", encoding="utf-8")
    simulated, banks = monte_carlo(mc_sets, seed)
    data.update(status="complete", monte_carlo=[strip(c) for c in simulated], cross_check=cross_check(live, banks, seed),
                live=[strip(c) | {"rows": c["rows"]} for c in live], minutes=round((time.monotonic() - started) / 60, 1))
    save(output, data)
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("eval/output/feedback"))
    parser.add_argument("--mc-sets", type=int, default=200)
    parser.add_argument("--live-sets", type=int, default=20)
    parser.add_argument("--scale", type=float, default=0.02)
    parser.add_argument("--seed", type=int, default=7391)
    args = parser.parse_args()
    data = asyncio.run(run(args.output, args.mc_sets, args.live_sets, args.scale, args.seed))
    print(f"feedback analysis {data['status']} in {data['minutes']} min; saved {args.output.resolve()}")


if __name__ == "__main__":
    main()
