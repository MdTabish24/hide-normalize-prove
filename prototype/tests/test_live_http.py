"""Actual localhost HTTP through Uvicorn processes; NOT a Docker isolation test."""
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time

import httpx
import pytest

from common import HEADERS, PENDING


ROOT = Path(__file__).resolve().parents[1]


def unused_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def start(module, port, environment):
    command = [sys.executable, "-m", "uvicorn", module, "--host", "127.0.0.1", "--port", str(port),
               "--no-access-log", "--no-server-header", "--no-date-header", "--log-level", "critical"]
    if module.endswith("factory"):
        command.append("--factory")
    process = subprocess.Popen(command, cwd=ROOT, env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline = time.perf_counter() + 15
        while time.perf_counter() < deadline:
            if process.poll() is not None:
                raise AssertionError(f"{module} exited during startup")
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                    return process
            except OSError:
                time.sleep(0.05)
        raise AssertionError(f"{module} did not start")
    except BaseException:
        stop(process)
        raise


def stop(process):
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


@pytest.mark.timing
def test_real_http_envelope_timing_and_restart_budget(tmp_path):
    env = dict(os.environ)
    env.update({name: secrets.token_hex(32) for name in (
        "RED_TOKEN", "BLUE_TOKEN", "EVALUATOR_TOKEN", "GATEWAY_KEY", "BLUE_SERVICE_TOKEN", "MODEL_SERVICE_TOKEN")})
    blue_port, model_port, gateway_port = unused_port(), unused_port(), unused_port()
    env.update(BLUE_URL=f"http://127.0.0.1:{blue_port}", MODEL_URL=f"http://127.0.0.1:{model_port}",
               DATA_DIR=str(tmp_path), BUCKETS="0.3,0.6,0.9", HIT_SECONDS="0.01", MISS_SECONDS="0.08", JITTER_SECONDS="0")
    processes = []
    try:
        processes.append(start("blue:app", blue_port, dict(env, SERVICE_TOKEN=env["BLUE_SERVICE_TOKEN"])))
        processes.append(start("model:app", model_port, dict(env, SERVICE_TOKEN=env["MODEL_SERVICE_TOKEN"])))
        processes.append(start("gateway:factory", gateway_port, env))
        with httpx.Client(base_url=f"http://127.0.0.1:{gateway_port}", timeout=4, trust_env=False) as client:
            def request(method, path, role="red", **kwargs):
                start_time = time.perf_counter()
                response = client.request(method, path, headers={"authorization": "Bearer " + env[role.upper() + "_TOKEN"]}, **kwargs)
                assert response.status_code == 202
                assert dict(response.headers) == HEADERS
                assert len(response.content) == 64
                return response, time.perf_counter() - start_time

            request("POST", "/v1/defense", "blue", json={"trigger": "pineapple"})
            for prompt in ("hello", "hello", "pineapple"):
                response, elapsed = request("POST", "/v1/submit", json={"run_id": "live", "prompt": prompt})
                assert response.content == PENDING
                assert 0.29 <= elapsed < 0.5
            before, _ = request("GET", "/v1/run/live/report")
            assert before.content == PENDING
            wrong, elapsed = request("POST", "/v1/defense", json={"trigger": "bad"})
            assert wrong.content == PENDING and 0.89 <= elapsed < 1.15
            bad = client.get("/bad-route", headers={"authorization": "Bearer invalid"})
            assert bad.status_code == 202 and dict(bad.headers) == HEADERS and bad.content == PENDING
            request("POST", "/v1/run/live/finish", "evaluator")
            first, _ = request("GET", "/v1/run/live/report")
            assert first.json()["status"] == "complete"
            stop(processes.pop())
            processes.append(start("gateway:factory", gateway_port, env))
            second, _ = request("GET", "/v1/run/live/report")
            assert first.content == second.content
            third, _ = request("GET", "/v1/run/live/report")
            assert third.content == PENDING
            assert b"pineapple" not in (tmp_path / "defense.enc").read_bytes()
            # Replace the private mock process with a deliberately slow backend.
            stop(processes[1])
            slow_env = dict(env, SERVICE_TOKEN=env["MODEL_SERVICE_TOKEN"], MISS_SECONDS="2")
            processes[1] = start("model:app", model_port, slow_env)
            timeout, elapsed = request("POST", "/v1/submit", json={"run_id": "slow", "prompt": "new prefix"})
            assert timeout.content == PENDING and 0.89 <= elapsed < 1.15
            print("LIVE HTTP PASS: allowed/blocked/hit/miss ~0.3s; generic error/overflow ~0.9s; persistent report budget after process restart.")
    finally:
        for process in reversed(processes):
            stop(process)
