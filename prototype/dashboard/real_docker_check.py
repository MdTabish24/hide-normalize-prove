"""Docker check with the real model (PARAMS v5 step 5): isolation from inside red-client, fixed release time, reply shape and signed audit.

    python -m dashboard.real_docker_check             # real overlay; DeepSeek key from env, prototype/.env or a hidden prompt
    python -m dashboard.real_docker_check --mock --requests 6    # same flow with the default mock stack (no key), harness check only

Brings the stack up, runs the checks, and takes it down again (volumes are kept). Label: real model run, small sample, local (Docker stack).
"""
import argparse
import json
import os
from pathlib import Path
import re
import statistics
import subprocess
import time
import uuid

import httpx

ROOT = Path(__file__).resolve().parents[1]
LABEL = "real model run, small sample, local (Docker stack)"


def compose(files, *args, env=None, timeout=900):
    command = ["docker", "compose", *[part for f in files for part in ("-f", f)], *args]
    return subprocess.run(command, cwd=ROOT, capture_output=True, text=True, errors="replace", timeout=timeout, env=env)


def service_ip(files, env, service):
    container = compose(files, "ps", "-q", service, env=env).stdout.strip()
    out = subprocess.run(["docker", "inspect", "-f", "{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}", container],
                         capture_output=True, text=True, timeout=30).stdout.split()
    return out[0] if out else None


def run_check(real=True, requests_total=30, key=None):
    from common import HEADERS, PENDING
    from manage import env_file
    probe = subprocess.run(["docker", "info", "--format", "{{.ServerVersion}}"], capture_output=True, text=True, timeout=60)
    if probe.returncode:
        return dict(status="NOT RUN", reason="Docker Engine not reachable", label=LABEL)
    port = os.environ.get("GATEWAY_PORT", "8088")
    env = dict(os.environ, GATEWAY_PORT=port, AUDIT_BATCH="50")
    if real:
        if not key:
            from dashboard.real_batch import get_key
            key = get_key()
        env.update(DEEPSEEK_API_KEY=key, REAL_POLICY_MODE="window_hard", REAL_WINDOW_CONTINUE="1", REAL_WINDOW_SECONDS="3",
                   PROVIDER_TIMEOUT_SECONDS="12")
        files = ["docker-compose.yml", "docker-compose.real.yml"]
    else:
        env.update(POLICY_MODE="window_hard", WINDOW_CONTINUE="1")
        files = ["docker-compose.yml"]
    if not (ROOT / ".env").exists():
        return dict(status="NOT RUN", reason="prototype/.env is missing (run init_env.py)", label=LABEL)
    result = dict(label=LABEL if real else "MOCK dry run (not a real model)", status="running", started=time.strftime("%Y-%m-%dT%H:%M:%S%z"))
    started = time.time()
    try:
        up = compose(files, "up", "-d", "--build", env=env)
        if up.returncode:
            return dict(result, status="FAILED", reason="compose up failed", detail=up.stderr[-300:].replace(key or "\0", "[key]"))
        deadline = time.time() + 90
        while time.time() < deadline:
            running = set(compose(files, "ps", "--status", "running", "--services", env=env).stdout.split())
            if {"gateway", "red-client", "blue-defense", "model-mock", "audit-collector", "operator-proxy"} <= running:
                break
            time.sleep(3)
        time.sleep(10)
        tokens = env_file()
        window = 3.0 if real else float(tokens.get("BUCKETS", "0.3,0.6,0.9").split(",")[-1])
        client = httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=65, trust_env=False)
        bearer = lambda role: {"authorization": "Bearer " + tokens[role.upper() + "_TOKEN"]}  # noqa: E731
        for _ in range(40):  # The proxy accepts connections before the gateway is ready; wait for a real reply.
            try:
                client.get("/ready")
                break
            except httpx.HTTPError:
                time.sleep(3)
        client.post("/v1/defense", json={"trigger": "pineapple"}, headers=bearer("blue"))
        # 1. Isolation from inside the Red container.
        blue_ip, model_ip = service_ip(files, env, "blue-defense"), service_ip(files, env, "model-mock")
        iso = compose(files, "exec", "-T", "red-client", "python", "demo_isolation.py", "--blue-ip", str(blue_ip), "--model-ip", str(model_ip), env=env)
        match = re.findall(r'"passed": (\d+), "total": (\d+)', iso.stdout)
        result["isolation"] = dict(passed=int(match[-1][0]), total=int(match[-1][1])) if match else dict(passed=None, total=None, reason="no summary line")
        # 2. Traffic through the operator proxy as Red: timing and shape.
        run_id = "dockercheck-" + uuid.uuid4().hex[:10]
        blocked_n = max(1, requests_total // 3)
        prompts = [("blocked", f"pineapple orchard {i} cloud") for i in range(blocked_n)] + \
                  [("allowed", f"neutral river {i} stone") for i in range(requests_total - blocked_n)]
        rows = []
        for case, prompt in prompts:
            start = time.perf_counter()
            reply = client.post("/v1/submit", json={"run_id": run_id, "prompt": prompt}, headers=bearer("red"))
            rows.append(dict(case=case, seconds=time.perf_counter() - start, status=reply.status_code, body=len(reply.content),
                             exact=reply.status_code == 202 and reply.content == PENDING and dict(reply.headers) == HEADERS))
        totals = [r["seconds"] for r in rows]
        result["traffic"] = dict(
            requests=len(rows), window_seconds=window, release_seconds=dict(min=round(min(totals), 3), median=round(statistics.median(totals), 3),
                                                                           max=round(max(totals), 3)),
            median_by_case={c: round(statistics.median([r["seconds"] for r in rows if r["case"] == c]), 3) for c in ("blocked", "allowed")},
            envelope_exact=sum(r["exact"] for r in rows), distinct_status_body=len({(r["status"], r["body"]) for r in rows}))
        # 3. Finish, then the evaluator's sealed counts and (real run) the model backend of the allowed outputs.
        evaluation = {}
        for _ in range(25):
            client.post(f"/v1/run/{run_id}/finish", headers=bearer("evaluator"))
            body = client.get(f"/v1/run/{run_id}/evaluation", headers=bearer("evaluator")).content
            if body != PENDING:
                evaluation = json.loads(body)
                break
            time.sleep(2)
        result["evaluation"] = evaluation or dict(status="NOT RUN: run did not finish")
        records = client.get(f"/v1/run/{run_id}/artifacts", headers=bearer("evaluator"))
        if records.content != PENDING:
            rec = json.loads(records.content).get("records", [])
            result["outputs"] = dict(allowed_with_output=sum(1 for r in rec if r.get("output")),
                                     backends=sorted({(r.get("output") or {}).get("backend") for r in rec if r.get("output")}))
        # 4. Signed audit via the network-less verifier container.
        time.sleep(5)
        verdict = compose(files, "run", "--rm", "verifier", "--run-id", run_id, env=env)
        result["audit"] = verdict.stdout.strip().splitlines()[-1] if verdict.stdout.strip() else "NOT RUN"
        result["status"] = "complete"
    except Exception as error:  # Recorded, never hidden; the stack is still taken down below.
        result.update(status="FAILED", reason=type(error).__name__)
    finally:
        compose(files, "down", env=env)
    result["minutes"] = round((time.time() - started) / 60, 1)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mock", action="store_true")
    parser.add_argument("--requests", type=int, default=30)
    parser.add_argument("--output", type=Path, default=ROOT / "eval/output/real_suite/docker_check.json")
    args = parser.parse_args()
    result = run_check(real=not args.mock, requests_total=args.requests)
    text = json.dumps(result, indent=2)
    key = os.environ.get("DEEPSEEK_API_KEY")
    if key and key in text:
        raise SystemExit("Key found in the result; nothing was written.")
    if not args.mock:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
