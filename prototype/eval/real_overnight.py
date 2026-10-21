"""Overnight real-model suite (PARAMS.md v6): ONE command, ONE key prompt, about 3-4 hours.

    python -m eval.real_overnight                     # real DeepSeek; key from env, prototype/.env or a hidden prompt
    python -m eval.real_overnight --mock --smoke      # harness check only: scaled mock model, tiny sizes, no key

Steps (every step saves its result and EVERY request immediately, so a crash loses at most the running step):
  A1 window_continue, ordinary, seed 20261027   A2 window_continue, ordinary, seed 20261028   A3 window_continue, real_long, seed 20261029
  B1 real-model flood, window_continue (seed 20261030)   B2 real-model flood, bucket_hard (default policy)
Each step runs with diagnostics (per-request server-side lateness + event-loop lag). At the end REAL_MODEL_REPORT.md is generated from all saved files.
Keeps Windows awake while it runs. A transport error is retried once with identical parameters. The key is never printed or written.
"""
import argparse
import asyncio
import json
import os
from pathlib import Path
import sys
import time

import httpx

from dashboard.real_batch import get_key
from eval import load_observer, real_report
from eval.real_timing import run_cell as timing_cell_run
from eval.real_timing import save as save_timing

OUTPUT = Path("eval/output/real_overnight")
SUMMARY = OUTPUT / "summary.json"
TIMING_STEPS = (
    ("A1 window_continue, ordinary, seed 20261027", dict(name="window_continue", cohort="ordinary", seed=20261027, n_train=60, n_test=60)),
    ("A2 window_continue, ordinary, seed 20261028", dict(name="window_continue", cohort="ordinary", seed=20261028, n_train=60, n_test=60)),
    ("A3 window_continue, real_long, seed 20261029", dict(name="window_continue", cohort="real_long", seed=20261029, n_train=40, n_test=40)),
)
FLOOD_STEPS = (("B1 real-model flood, window_continue", "real_window_continue"), ("B2 real-model flood, bucket_hard", "real_bucket_hard"))


def keep_awake():
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000001)


def brief(result):
    text = (f"accuracy {100 * result['accuracy']:.1f}% ({100 * result['wilson_95'][0]:.1f}-{100 * result['wilson_95'][1]:.1f}%), {result['verdict']}, "
            f"train {100 * result['train_accuracy']:.0f}%")
    release = result.get("release_seconds") or result.get("observer_release_seconds") or {}
    text += f", release {release.get('median')} median / {release.get('max')} max s"
    if result.get("diagnostics"):
        d = result["diagnostics"]
        text += (f"; slipped {d['slipped_requests']}/{d['requests_observed']}, gateway-side late>0.25s {d['server_side_late_over_0_25_s']}, "
                 f"loop-lag events {d['loop_lag']['events']} (max {d['loop_lag']['max_seconds']} s)")
    if result.get("permutation_check"):
        text += f"; permutation p {result['permutation_check']['two_sided_p']}"
    return text


async def attempt(label, runner, key, summary):
    step = dict(step=label)
    begin = time.time()
    print(f"\n=== {label} ===", flush=True)
    for number in (1, 2):
        step["attempts"] = number
        try:
            result = await runner()
            step["file"] = result["file"]
            step["result"] = brief(result["data"])
            if key and key in json.dumps(result["data"]):
                raise SystemExit("Key found in a result; stopping. Regenerate the key.")
            break
        except Exception as error:  # Recorded, never hidden; the suite continues.
            step["result"] = f"FAILED: {type(error).__name__}"
            if number == 1 and isinstance(error, (httpx.TransportError, OSError)):
                print(f"transport error ({type(error).__name__}); one retry with identical parameters", flush=True)
                continue
            break
    step["minutes"] = round((time.time() - begin) / 60, 1)
    print(step["result"], flush=True)
    summary["steps"].append(step)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    SUMMARY.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")  # Written after every step.


async def main_async(mock, smoke):
    keep_awake()
    key = None if mock else get_key()
    if key:
        os.environ["DEEPSEEK_API_KEY"] = key
    summary = dict(label="real model run, small sample, local" if not mock else "MOCK dry run (not a real model)", params_version=6, steps=[])
    started = time.time()
    for label, spec in TIMING_STEPS:
        n_train, n_test = (6, 6) if smoke else (spec["n_train"], spec["n_test"])

        async def runner(spec=spec, n_train=n_train, n_test=n_test):
            result, _ = await timing_cell_run(spec["name"], n_train, n_test, 4, mock, spec["cohort"], spec["seed"], key, diagnostics=True)
            path = save_timing(result, key, OUTPUT) if not mock else None
            return dict(data=result, file=str(path))
        await attempt(label, runner, key, summary)
    for label, cell in FLOOD_STEPS:
        n_train, n_test = (6, 6) if smoke else (60, 60)

        async def runner(cell=cell, n_train=n_train, n_test=n_test):
            result = await load_observer.run_cell(cell, n_train, n_test, OUTPUT, diagnostics=True, mock=mock)
            path = OUTPUT / f"{cell}.json"
            text = json.dumps(result, indent=2) + "\n"
            if key and key in text:
                raise SystemExit("Key found in a result; nothing was written. Regenerate the key.")
            if not mock:
                path.write_text(text, encoding="utf-8")
            return dict(data=result, file=str(path))
        await attempt(label, runner, key, summary)
    summary["total_minutes"] = round((time.time() - started) / 60, 1)
    return summary, key


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mock", action="store_true")
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()
    summary, key = asyncio.run(main_async(args.mock, args.smoke))
    text = json.dumps(summary, indent=2)
    if key and key in text:
        raise SystemExit("Key found in the summary; nothing was written.")
    if not args.mock:
        OUTPUT.mkdir(parents=True, exist_ok=True)
        SUMMARY.write_text(text + "\n", encoding="utf-8")
        (real_report.ROOT / "REAL_MODEL_REPORT.md").write_text(real_report.build(), encoding="utf-8")
        print("\nWrote REAL_MODEL_REPORT.md from the saved files.")
    print("\n=== SUMMARY ===")
    for step in summary["steps"]:
        print(f"- {step['step']} ({step['minutes']} min, attempts {step['attempts']}): {step['result']}")
    print(f"Total {summary['total_minutes']} minutes. Send this summary (no key) back. Files: eval/output/real_overnight, REAL_MODEL_REPORT.md.")


if __name__ == "__main__":
    main()
