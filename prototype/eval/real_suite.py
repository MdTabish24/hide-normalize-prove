"""Complete real-model suite (PARAMS.md v5): one command, one key prompt, about 45-60 minutes.

    python -m eval.real_suite                    # real DeepSeek; key from env, prototype/.env or a hidden prompt
    python -m eval.real_suite --mock --smoke     # harness check only: scaled mock model, tiny sizes, no key

Steps (a failing step is recorded and skipped; only a transport error is retried once with identical parameters, both attempts recorded):
  1 raw ordinary (seed 20261025, also the latency / modality analysis)   2 window_continue ordinary (repeat, seed 20261025)
  3 raw real_long (seed 20261026)   4 window_continue real_long (seed 20261026)   5 Docker real check (isolation, timing, audit)
Keeps Windows awake while it runs. Label: real model run, small sample, local. The key is never printed or written.
"""
import argparse
import asyncio
import json
from pathlib import Path
import sys
import time

import httpx

from dashboard.real_batch import get_key
from dashboard.real_docker_check import run_check
from eval.real_timing import run_cell, save

OUTPUT = Path("eval/output/real_timing")
SUMMARY = Path("eval/output/real_suite/summary.json")
STEPS = (
    ("1 raw, ordinary, seed 20261025", dict(name="raw", cohort="ordinary", seed=20261025, n_train=60, n_test=60)),
    ("2 window_continue, ordinary, seed 20261025 (repeat)", dict(name="window_continue", cohort="ordinary", seed=20261025, n_train=60, n_test=60)),
    ("3 raw, real_long, seed 20261026", dict(name="raw", cohort="real_long", seed=20261026, n_train=40, n_test=40)),
    ("4 window_continue, real_long, seed 20261026", dict(name="window_continue", cohort="real_long", seed=20261026, n_train=40, n_test=40)),
)


def keep_awake():
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000001)  # ES_CONTINUOUS | ES_SYSTEM_REQUIRED; ends with this process


def brief(result):
    if "accuracy" not in result:
        return result.get("status", "?") + (": " + result["reason"] if result.get("reason") else "")
    text = (f"accuracy {100 * result['accuracy']:.1f}% ({100 * result['wilson_95'][0]:.1f}-{100 * result['wilson_95'][1]:.1f}%), {result['verdict']}, "
            f"train {100 * result['train_accuracy']:.0f}%, release {result['release_seconds']['min']}-{result['release_seconds']['max']} s, "
            f"cancelled {result['cancelled']}, late {result['late_after_deadline']}, audit {result['audit']['valid']}/{result['audit']['runs']}")
    if "latency_analysis" in result:
        analysis = result["latency_analysis"]
        text += f"; latency {analysis['reading']} (BC {analysis['bimodality_coefficient']}), median by repetition {analysis['median_by_repetition_seconds']}"
    return text


async def main_async(mock, smoke):
    keep_awake()
    key = None if mock else get_key()
    summary = dict(label="real model run, small sample, local" if not mock else "MOCK dry run (not a real model)", params_version=5, steps=[])
    started = time.time()
    for title, spec in STEPS:
        step = dict(step=title)
        begin = time.time()
        print(f"\n=== {title} ===", flush=True)
        n_train, n_test = (6, 6) if smoke else (spec["n_train"], spec["n_test"])
        for attempt in (1, 2):
            step["attempts"] = attempt
            try:
                result, key = await run_cell(spec["name"], n_train, n_test, 4, mock, spec["cohort"], spec["seed"], key)
                if not mock:
                    step["file"] = str(save(result, key, OUTPUT))
                step["result"] = brief(result)
                break
            except Exception as error:  # Recorded, never hidden; the suite continues.
                step["result"] = f"FAILED: {type(error).__name__}"
                if attempt == 1 and isinstance(error, (httpx.TransportError, OSError)):
                    print(f"transport error ({type(error).__name__}); one retry with identical parameters", flush=True)
                    continue
                break
        step["minutes"] = round((time.time() - begin) / 60, 1)
        print(step["result"], flush=True)
        summary["steps"].append(step)
    print("\n=== 5 Docker real check ===", flush=True)
    begin = time.time()
    docker = await asyncio.to_thread(run_check, not mock, 6 if smoke else 30, key)
    step = dict(step="5 Docker real check", minutes=round((time.time() - begin) / 60, 1))
    if not mock:
        SUMMARY.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(docker, indent=2)
        if key and key in text:
            raise SystemExit("Key found in the Docker result; nothing was written.")
        (SUMMARY.parent / "docker_check.json").write_text(text + "\n", encoding="utf-8")
    step["result"] = (f"{docker.get('status')}; isolation {docker.get('isolation')}; traffic {docker.get('traffic', {}).get('release_seconds')}; "
                      f"envelope exact {docker.get('traffic', {}).get('envelope_exact')}/{docker.get('traffic', {}).get('requests')}; "
                      f"evaluation {docker.get('evaluation')}; outputs {docker.get('outputs')}; audit {docker.get('audit')}")
    summary["steps"].append(step)
    print(step["result"], flush=True)
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
        SUMMARY.parent.mkdir(parents=True, exist_ok=True)
        SUMMARY.write_text(text + "\n", encoding="utf-8")
    print("\n=== SUMMARY ===")
    for step in summary["steps"]:
        print(f"- {step['step']} ({step['minutes']} min): {step['result']}")
    print(f"Total {summary['total_minutes']} minutes. Send this summary (no key) back; files are in eval/output/real_timing and eval/output/real_suite.")


if __name__ == "__main__":
    main()
