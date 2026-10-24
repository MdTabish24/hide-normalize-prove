"""Positive controls (PARAMS v14): run our own attack tests against DELIBERATELY WEAK setups, to show that they detect a leak when there is one.

    python -m eval.weak_controls            # attacks 1, 2 (Docker, needs Docker Desktop) and 8 (local processes)
    python -m eval.weak_controls --only 8

A test that has never been seen to fail on a bad setup says little when it passes on a good one. Each control weakens exactly one protection:
  1  red-client is also attached to the Blue, model and audit networks (docker-compose.weak.yml)
  2  red-client gets Blue's token and the gateway key as environment variables and mounts the gateway data volume (same file)
  8  the Blue service writes every prompt and the rule to a log file (eval/naive_blue.py)
Attack 3 (role and token confusion) has NO control here: a gateway that ignores roles would need a different gateway, and we did not build one.
Writes eval/output/weak_controls/results.json. Label: weak setups, local; the weak files are used only here.
"""
import argparse
import asyncio
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time

import httpx

import attack_suite as S

OUTPUT = Path("eval/output/weak_controls/results.json")
FILES = ["-f", "docker-compose.yml", "-f", "docker-compose.weak.yml"]
PORT = os.environ.get("GATEWAY_PORT", "8088")


def weak_compose(*args, timeout=60):
    return subprocess.run(["docker", "compose", *FILES, *args], cwd=S.ROOT, capture_output=True, text=True, errors="replace",
                          timeout=timeout, env=dict(os.environ, GATEWAY_PORT=PORT))


def configure_defense():
    from manage import env_file
    env = env_file()
    deadline = time.time() + 40
    while time.time() < deadline:
        try:
            response = httpx.post(f"http://127.0.0.1:{PORT}/v1/defense", json={"trigger": "pineapple"}, trust_env=False, timeout=5,
                                  headers={"authorization": "Bearer " + env["BLUE_TOKEN"]})
            if response.status_code == 202:
                return True
        except httpx.HTTPError:
            pass
        time.sleep(2)
    return False


def docker_controls(selected):
    S.compose = weak_compose  # attack_suite's Docker helpers now use the weak overlay as well
    up = weak_compose("up", "-d", "--force-recreate", "--no-build", timeout=240)
    if up.returncode:
        return [dict(attack=a, setup="weak", result="NOT RUN", summary="compose up failed: " + up.stderr[-160:]) for a in selected]
    time.sleep(8)
    configured = configure_defense()
    try:
        if "1" in selected:
            S.attack_network()
        if "2" in selected:
            S.attack_filesystem()
    finally:
        weak_compose("down", timeout=180)
    rows = list(S.ROWS)
    S.ROWS.clear()
    return [dict(r, defense_configured=configured) for r in rows]


class NaiveStack(S.Stack):
    """Same local stack, but Blue's service is eval/naive_blue.py, which logs prompts and the rule."""
    def start(self, module, env, log=None):
        if module == "blue:app":
            module, env = "eval.naive_blue:app", dict(env, NAIVE_BLUE_LOG=str(self.directory / "naive-blue.log"))
        return super().start(module, env, log)


def log_control():
    S.Stack = NaiveStack
    with tempfile.TemporaryDirectory(prefix="weak-scan-") as directory:
        asyncio.run(S.attack_scan(Path(directory)))
    rows = [r for r in S.ROWS if r["attack"] == 8][:1]  # the local scan; the Docker part below it is not part of this control
    S.ROWS.clear()
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--only", nargs="*", default=["1", "2", "8"])
    args = parser.parse_args()
    results = []
    docker_wanted = [a for a in args.only if a in ("1", "2")]
    if docker_wanted:
        results += docker_controls(docker_wanted)
    if "8" in args.only:
        results += log_control()
    out = []
    for row in results:
        detected = row["result"] == "LEAKED"
        out.append(dict(attack=row["attack"], weak_setup={"1": "red-client attached to every service network", "2": "secrets in red-client's environment and the data volume mounted",
                                                          "8": "Blue service logs every prompt and the rule"}[str(row["attack"])],
                        result=row["result"], detected_by_our_test=detected, summary=row["summary"], label=row.get("label")))
    out.append(dict(attack=3, weak_setup="none built", result="NOT RUN", detected_by_our_test=None,
                    summary="No positive control: it would need a gateway that ignores roles."))
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(dict(label="deliberately weak setups, local", params_version=14, results=out), indent=2) + "\n", encoding="utf-8")
    for row in out:
        print(f"attack {row['attack']}: {row['result']} (detected={row['detected_by_our_test']}) | {row['weak_setup']} | {row['summary'][:150]}")


if __name__ == "__main__":
    main()
