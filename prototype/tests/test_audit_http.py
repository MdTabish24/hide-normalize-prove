"""Separate collector/gateway OS processes, real HTTP, restart and outage."""
import os
import time

import httpx

from test_audit_gateway import config_for, headers
from test_live_http import start, stop, unused_port
from verify_audit import verify


def test_separate_collector_process_restart_and_outage(tmp_path):
    config = config_for(tmp_path)
    blue_port, model_port, audit_port, gateway_port = [unused_port() for _ in range(4)]
    config.update(AUDIT_URL=f"http://127.0.0.1:{audit_port}", BLUE_URL=f"http://127.0.0.1:{blue_port}",
                  MODEL_URL=f"http://127.0.0.1:{model_port}", BUCKETS="0.3,0.6,0.9")
    base = dict(os.environ)
    collector_env = dict(base, **{key: config[key] for key in (
        "AUDIT_TOKEN", "AUDIT_LOG_DIR", "AUDIT_KEY_DIR", "CHECKPOINT_DIR")})
    processes = []
    try:
        processes.append(start("blue:app", blue_port, dict(base, SERVICE_TOKEN=config["BLUE_SERVICE_TOKEN"])))
        processes.append(start("model:app", model_port, dict(base, SERVICE_TOKEN=config["MODEL_SERVICE_TOKEN"],
                                                          HIT_SECONDS="0.01", MISS_SECONDS="0.04", JITTER_SECONDS="0")))
        processes.append(start("audit_collector:factory", audit_port, collector_env))
        processes.append(start("gateway:factory", gateway_port, dict(base, **config)))

        def verify_run():
            return verify(tmp_path / "logs" / "r.jsonl", tmp_path / "cp" / "r.json",
                          tmp_path / "cp" / "public_key.bin", "r", tmp_path / "gateway" / "runs.sqlite")

        def wait_for(expected):
            deadline = time.perf_counter() + 4
            while time.perf_counter() < deadline:
                result = verify_run()
                if (expected == "VALID" and result[0]) or result[1] == expected:
                    return
                time.sleep(0.03)
            raise AssertionError(result)

        with httpx.Client(base_url=f"http://127.0.0.1:{gateway_port}", trust_env=False, timeout=4) as client:
            client.post("/v1/defense", json={"trigger": "pineapple"}, headers=headers(config, "blue"))
            client.post("/v1/submit", json={"run_id": "r", "prompt": "hello"}, headers=headers(config, "red"))
            client.post("/v1/run/r/finish", headers=headers(config, "evaluator"))
            wait_for("VALID")
            public_key = (tmp_path / "cp" / "public_key.bin").read_bytes()
            stop(processes[2])
            processes[2] = start("audit_collector:factory", audit_port, collector_env)
            first = client.get("/v1/run/r/report", headers=headers(config, "red"))
            assert first.status_code == 202 and first.json()["status"] == "complete"
            wait_for("VALID")
            assert (tmp_path / "cp" / "public_key.bin").read_bytes() == public_key
            stop(processes[2])
            second = client.get("/v1/run/r/report", headers=headers(config, "red"))
            assert second.status_code == 202 and second.content == first.content
            wait_for("gateway marks audit_unavailable")
            print("AUDIT LIVE HTTP PASS: separate collector key, signed checkpoint VALID; collector restart preserves key; outage keeps API unchanged and verifier INVALID.")
    finally:
        for process in reversed(processes):
            stop(process)
