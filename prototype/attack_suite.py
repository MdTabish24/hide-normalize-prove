"""Round 2 attack suite: one command, table output + attack_suite_results.json.

    python attack_suite.py            # all attacks (Docker ones need the compose stack up)
    python attack_suite.py --only 3 4 # selected attacks

Result classes: BLOCKED (attack failed in this test), BOUNDED LEAK (no clear
leak for this attacker/sample; residual risk remains, not proof), LEAKED,
NOT COVERED (out of scope), NOT RUN (could not run here; reason given).
HTTP attacks use their own local process stack (real Uvicorn processes,
throwaway tokens, mock model) labelled "live gateway, mock model, local run".
"""
import argparse
import asyncio
import json
import multiprocessing
import os
from pathlib import Path
import random
import secrets
import shutil
import subprocess
import tempfile
import time

import httpx

from common import HEADERS, PENDING
from eval.live import Server
from stats import ks_2samp, percentile, wilson

ROOT = Path(__file__).resolve().parent
LOCAL = "live gateway, mock model, local run"
DOCKER = "local Docker stack (Docker Desktop)"
SIM = "simulated (Monte Carlo)"
SCALE = 0.1
BUCKETS = [3 * SCALE, 6 * SCALE, 9 * SCALE]
WINDOW = BUCKETS[-1]
ROWS = []


def add(attack, name, result, summary, policy="-", label=LOCAL, audit="on", details=None):
    assert result in {"BLOCKED", "BOUNDED LEAK", "LEAKED", "NOT COVERED", "NOT RUN"}
    ROWS.append({"attack": attack, "name": name, "policy": policy, "result": result, "summary": summary,
                 "label": label, "audit_mode": audit, "details": details or {}})
    print(f"[{attack}] {name} | {policy} | {result} | {summary}", flush=True)


class Stack:
    """Blue, mock model, collector and gateway as local processes with known tokens."""

    def __init__(self, directory, policy, cache_namespace="on", trigger=None, extra=None):
        self.directory, self.policy = Path(directory), policy
        self.cache_namespace, self.extra = cache_namespace, extra or {}
        self.trigger = trigger or "canary" + secrets.token_hex(6)
        self.servers = []

    async def __aenter__(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        base = {k: v for k, v in os.environ.items() if not (k.endswith("_TOKEN") or k.endswith("_KEY") or k in {
            "AUDIT_URL", "AUDIT_MODE", "POLICY_MODE", "EVAL_MODE", "CACHE_NAMESPACE", "WINDOW_SECONDS"})}
        self.tokens = {n: secrets.token_hex(32) for n in ("RED_TOKEN", "BLUE_TOKEN", "EVALUATOR_TOKEN",
                                                         "BLUE_SERVICE_TOKEN", "MODEL_SERVICE_TOKEN", "AUDIT_TOKEN")}
        try:
            blue = self.start("blue:app", dict(base, SERVICE_TOKEN=self.tokens["BLUE_SERVICE_TOKEN"]))
            model = self.start("model:app", dict(base, SERVICE_TOKEN=self.tokens["MODEL_SERVICE_TOKEN"], EVAL_MODE="1",
                                                 CACHE_NAMESPACE=self.cache_namespace, MISS_SECONDS=str(2 * SCALE),
                                                 HIT_SECONDS=str(0.3 * SCALE), JITTER_SECONDS=str(0.02 * SCALE)))
            self.logs, self.checkpoints = self.directory / "audit-logs", self.directory / "checkpoints"
            collector = self.start("audit_collector:factory", dict(base, AUDIT_TOKEN=self.tokens["AUDIT_TOKEN"],
                                   AUDIT_LOG_DIR=str(self.logs), AUDIT_KEY_DIR=str(self.directory / "audit-keys"),
                                   CHECKPOINT_DIR=str(self.checkpoints)))
            self.data = self.directory / "gateway-data"
            self.config = dict(base, **self.tokens, GATEWAY_KEY=secrets.token_hex(32), EVAL_MODE="1",
                               POLICY_MODE=self.policy, DATA_DIR=str(self.data), BLUE_URL=blue.url, MODEL_URL=model.url,
                               AUDIT_URL=collector.url, BUCKETS=",".join(map(str, BUCKETS)), **self.extra)
            self.stdout = self.directory / "gateway-stdout.txt"
            self.gateway = self.start("gateway:factory", self.config, log=self.stdout)
            self.client = httpx.AsyncClient(base_url=self.gateway.url, trust_env=False, timeout=30,
                                            limits=httpx.Limits(max_connections=100))
            await self.call("POST", "/v1/defense", "blue", json={"trigger": self.trigger})
            return self
        except BaseException:
            await self.__aexit__()
            raise

    def start(self, module, env, log=None):
        server = Server(module, env, log)
        self.servers.append(server)
        return server.start()

    async def __aexit__(self, *args):
        if hasattr(self, "client"):
            await self.client.aclose()
        for server in reversed(self.servers):
            server.stop()

    async def call(self, method, path, role=None, token=None, **kwargs):
        headers = {"authorization": "Bearer " + (token or self.tokens[role.upper() + "_TOKEN"])} if (role or token) else {}
        headers.update(kwargs.pop("headers", {}))
        start = time.perf_counter()
        response = await self.client.request(method, path, headers=headers, **kwargs)
        return response, time.perf_counter() - start

    def db(self, query, args=()):
        import sqlite3
        from contextlib import closing
        uri = (self.data / "runs.sqlite").resolve().as_uri() + "?mode=ro"
        with closing(sqlite3.connect(uri, uri=True, timeout=10)) as db:
            return db.execute(query, args).fetchall()


def shape(response):
    return (response.status_code, tuple(sorted(response.headers.items())), len(response.content))


def generic(response):
    return response.status_code == 202 and dict(response.headers) == HEADERS and len(response.content) == 64


# ---------------------------------------------------------------- Docker (1, 2)

def compose(*args, timeout=60):
    return subprocess.run(["docker", "compose", *args], cwd=ROOT, capture_output=True, text=True,
                          errors="replace", timeout=timeout)


def docker_ready():
    try:
        if subprocess.run(["docker", "info"], capture_output=True, timeout=20).returncode:
            return "Docker Engine not reachable"
        running = compose("ps", "--status", "running", "--services").stdout.split()
        missing = {"gateway", "red-client", "blue-defense", "model-mock", "audit-collector"} - set(running)
        return f"compose services not running: {sorted(missing)} (run docker compose up -d)" if missing else None
    except (OSError, subprocess.TimeoutExpired) as error:
        return f"docker unavailable: {type(error).__name__}"


PROBE = """import socket, sys, json
out = {}
for target in sys.argv[1:]:
    host, port = target.rsplit(":", 1)
    try:
        socket.create_connection((host, int(port)), 1).close(); out[target] = "REACHABLE"
    except OSError as e:
        out[target] = "blocked:" + type(e).__name__
print(json.dumps(out))"""


def container_ips(service):
    cid = compose("ps", "-q", service).stdout.strip()
    raw = subprocess.run(["docker", "inspect", "-f", "{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}", cid],
                         capture_output=True, text=True).stdout
    return raw.split()


def attack_network():
    reason = docker_ready()
    if reason:
        return add(1, "Direct network from red-client", "NOT RUN", reason, label=DOCKER, audit="n/a")
    targets = [f"{ip}:8000" for svc in ("blue-defense", "model-mock", "audit-collector") for ip in container_ips(svc)]
    targets += ["blue-defense:8000", "model-mock:8000", "audit-collector:8000", "host.docker.internal:8000",
                "1.1.1.1:443", "8.8.8.8:53", "example.com:443"]
    result = compose("exec", "-T", "red-client", "python", "-c", PROBE, *targets)
    observed = json.loads(result.stdout.strip().splitlines()[-1]) if result.returncode == 0 else {}
    demo = compose("exec", "-T", "red-client", "python", "demo_isolation.py", timeout=120)
    reachable = [t for t, v in observed.items() if v == "REACHABLE"]
    ok = observed and not reachable and demo.returncode == 0
    add(1, "Direct network from red-client (Blue, model, audit IPs+names, host, internet)",
        "BLOCKED" if ok else ("LEAKED" if reachable else "NOT RUN"),
        f"{len(observed) - len(reachable)}/{len(observed)} targets blocked; isolation demo exit {demo.returncode}"
        + (f"; reachable: {reachable}" if reachable else ""), label=DOCKER, audit="n/a",
        details={"probes": observed, "demo_tail": demo.stdout.strip().splitlines()[-1:] if demo.stdout else []})


def attack_filesystem():
    reason = docker_ready()
    if reason:
        return add(2, "Filesystem / Docker socket / Blue config from red-client", "NOT RUN", reason, label=DOCKER, audit="n/a")
    check = ("import os, json; print(json.dumps({'docker_sock': os.path.exists('/var/run/docker.sock'),"
             "'defense_enc': any(os.path.exists(p) for p in ('/data/defense.enc','/gateway-data/defense.enc')),"
             "'env_secrets': sorted(k for k in os.environ if k.endswith(('_KEY','SERVICE_TOKEN')) or k in "
             "('BLUE_TOKEN','EVALUATOR_TOKEN','AUDIT_TOKEN','GATEWAY_KEY')),"
             "'audit_dirs': [p for p in ('/audit-logs','/checkpoints','/audit-keys') if os.listdir(p)],"
             "'root_writable': os.access('/', os.W_OK), 'uid': os.getuid()}))")
    result = compose("exec", "-T", "red-client", "python", "-c", check)
    cid = compose("ps", "-q", "red-client").stdout.strip()
    mounts = subprocess.run(["docker", "inspect", "-f", "{{json .Mounts}}", cid], capture_output=True, text=True).stdout.strip()
    try:
        seen = json.loads(result.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return add(2, "Filesystem / Docker socket / Blue config from red-client", "NOT RUN",
                   "probe failed: " + result.stderr[-200:], label=DOCKER, audit="n/a")
    leaked = seen["docker_sock"] or seen["defense_enc"] or seen["env_secrets"] or seen["audit_dirs"] or mounts not in ("[]", "null")
    add(2, "Filesystem / Docker socket / Blue config from red-client", "LEAKED" if leaked else "BLOCKED",
        f"docker.sock={seen['docker_sock']}, defense.enc visible={seen['defense_enc']}, secret env={seen['env_secrets']}, "
        f"mounts={mounts}, read-only root={not seen['root_writable']}, uid={seen['uid']}", label=DOCKER, audit="n/a", details=seen)


# ------------------------------------------------------------- HTTP (3, 4, 6-9)

async def attack_roles(base):
    for policy in ("bucket_hard", "window_hard"):
        async with Stack(base / f"roles-{policy}", policy) as stack:
            before = (stack.data / "defense.enc").read_bytes()
            await stack.call("POST", "/v1/submit", "red", json={"run_id": "victim", "prompt": "hello"})
            attempts = [
                ("red sets Blue defense", "POST", "/v1/defense", "red", {"json": {"trigger": "hijack"}}),
                ("red finishes a run", "POST", "/v1/run/victim/finish", "red", {}),
                ("red reads evaluator report", "GET", "/v1/run/victim/evaluation", "red", {}),
                ("blue submits as Red", "POST", "/v1/submit", "blue", {"json": {"run_id": "x1", "prompt": "hi"}}),
                ("evaluator submits as Red", "POST", "/v1/submit", "evaluator", {"json": {"run_id": "x2", "prompt": "hi"}}),
                ("red claims role=blue in JSON", "POST", "/v1/submit", "red", {"json": {"run_id": "x3", "prompt": "hi", "role": "blue"}}),
                ("no token", "POST", "/v1/submit", None, {"json": {"run_id": "x4", "prompt": "hi"}}),
                ("token without Bearer", "POST", "/v1/submit", None, {"json": {"run_id": "x5", "prompt": "hi"},
                                                                     "headers": {"authorization": stack.tokens["RED_TOKEN"]}}),
                ("path traversal run id", "GET", "/v1/run/..%2Fvictim/report", "red", {}),
                ("red reads report before finish", "GET", "/v1/run/victim/report", "red", {}),
            ]
            responses = [(label, await stack.call(m, p, r, **kw)) for label, m, p, r, kw in attempts]
            effects = {
                "defense changed": (stack.data / "defense.enc").read_bytes() != before,
                "run finished by red": stack.db("SELECT finished FROM runs WHERE run_id='victim'") != [(0,)],
                "attempts by non-red": stack.db("SELECT COUNT(*) FROM attempts WHERE run_id LIKE 'x%'")[0][0] > 0,
                "evaluation body leaked": any(r.content != PENDING for label, (r, _) in responses if "evaluator report" in label),
                "report before finish": any(r.content != PENDING for label, (r, _) in responses if "before finish" in label),
            }
            non_generic = [label for label, (r, _) in responses if not generic(r)]
            bad = [k for k, v in effects.items() if v] + non_generic
            add(3, "Role and token confusion (10 cases)", "LEAKED" if bad else "BLOCKED",
                "no effect, all generic 202" if not bad else f"failures: {bad}", policy, details={"effects": effects})


async def attack_error_oracle(base):
    for policy in ("bucket_hard", "window_hard"):
        async with Stack(base / f"errors-{policy}", policy) as stack:
            battery = [
                ("valid allowed", "POST", "/v1/submit", "red", {"json": {"run_id": "e", "prompt": "hello"}}),
                ("valid blocked", "POST", "/v1/submit", "red", {"json": {"run_id": "e", "prompt": stack.trigger}}),
                ("missing field", "POST", "/v1/submit", "red", {"json": {"run_id": "e"}}),
                ("extra field", "POST", "/v1/submit", "red", {"json": {"run_id": "e", "prompt": "a", "x": 1}}),
                ("bad JSON", "POST", "/v1/submit", "red", {"content": b"{not json", "headers": {"content-type": "application/json"}}),
                ("prompt too long", "POST", "/v1/submit", "red", {"json": {"run_id": "e", "prompt": "a" * 5000}}),
                ("body over 32 KiB", "POST", "/v1/submit", "red", {"content": b"x" * 40000}),
                ("bad run id", "POST", "/v1/submit", "red", {"json": {"run_id": "bad id!", "prompt": "a"}}),
                ("unknown route", "GET", "/admin", "red", {}),
                ("wrong method", "DELETE", "/v1/submit", "red", {}),
                ("bad token", "POST", "/v1/submit", None, {"json": {"run_id": "e", "prompt": "a"}, "headers": {"authorization": "Bearer nope"}}),
                ("report (pending)", "GET", "/v1/run/e/report", "red", {}),
            ]
            observed = []
            for label, method, path, role, kwargs in battery:
                response, elapsed = await stack.call(method, path, role, **kwargs)
                release = min(BUCKETS + [WINDOW], key=lambda b: abs(b - elapsed))
                observed.append({"case": label, "shape": shape(response), "body": response.content.decode(errors="replace").strip(),
                                 "elapsed": round(elapsed, 4), "release_point": release})
            shapes = {(o["shape"], o["body"]) for o in observed}
            timings = {o["release_point"] for o in observed}
            if len(shapes) > 1:
                result, text = "LEAKED", f"{len(shapes)} distinct response shapes"
            elif len(timings) > 1:
                result = "BOUNDED LEAK"
                text = (f"1 response shape; {len(timings)} release times {sorted(timings)}: Red can tell its own "
                        "malformed/unauthorized requests from processed ones by time (not shown to carry Blue's secret)")
            else:
                result, text = "BLOCKED", f"1 response shape and 1 release time ({timings.pop():g} s) across {len(observed)} cases"
            add(4, "Error oracle (12 request kinds)", result, text, policy, details={"observations": observed})


async def attack_cache(base, trials=40):
    conditions = (("raw", "on"), ("raw", "off"), ("window_hard", "off"), ("window_hard", "on"))
    for policy, namespace in conditions:
        async with Stack(base / f"cache-{policy}-{namespace}", policy, cache_namespace=namespace) as stack:
            rng, correct = random.Random(4242), 0

            async def trial(index):
                candidates = ["p" + secrets.token_hex(15), "p" + secrets.token_hex(15)]
                secret = rng.randrange(2)
                # Victim run uses the secret prefix; the attacker's own run then times both candidates.
                await stack.call("POST", "/v1/submit", "red", json={"run_id": f"victim-{index}", "prompt": candidates[secret] + " victim"})
                order = [0, 1] if rng.random() < 0.5 else [1, 0]
                times = {}
                for c in order:
                    _, times[c] = await stack.call("POST", "/v1/submit", "red", json={"run_id": f"attacker-{index}", "prompt": candidates[c] + " probe"})
                return int(min(times, key=times.get) == secret)

            for start in range(0, trials, 4):
                correct += sum(await asyncio.gather(*(trial(i) for i in range(start, min(trials, start + 4)))))
        low, high = wilson(correct, trials)
        text = f"{correct}/{trials} = {correct / trials:.0%} (95% Wilson {low:.0%}-{high:.0%}); cache namespace {namespace}"
        if namespace == "off" and policy == "raw":
            result, text = ("LEAKED" if low > 0.5 else "BOUNDED LEAK"), text + " (negative control, EVAL_MODE only)"
        elif low > 0.5:
            result = "LEAKED"
        else:
            result = "BLOCKED" if namespace == "on" else "BOUNDED LEAK"
        add(6, "Cross-run cache prefix probe", result, text, policy)


async def attack_feedback(base):
    async with Stack(base / "feedback", "raw") as stack:
        async def run(run_id, blocked, total=16):
            for i in range(total):
                prompt = (stack.trigger + " item " if i < blocked else "benign item ") + str(i)
                await stack.call("POST", "/v1/submit", "red", json={"run_id": run_id, "prompt": prompt})
            await stack.call("POST", f"/v1/run/{run_id}/finish", "evaluator")
            reads = [(await stack.call("GET", f"/v1/run/{run_id}/report", "red"))[0].content for _ in range(3)]
            return reads
        zero = await run("all-blocked", 16)
        full = await run("all-allowed", 0)
    budget_ok = zero[0] == zero[1] and zero[2] == PENDING and full[0] == full[1] and full[2] == PENDING
    add(7, "Feedback: same-run repeat + third read", "BLOCKED" if budget_ok else "LEAKED",
        "2 reads identical, 3rd read generic pending (both runs)" if budget_ok else "budget not enforced", "raw")
    ranges = [json.loads(zero[0])["safe_range"], json.loads(full[0])["safe_range"]]
    add(7, "Feedback: extreme counts (0 vs 16 of 16)", "LEAKED",
        f"safe count 0 always gives {ranges[0]}, 16 always gives {ranges[1]}: an extreme count is identifiable "
        "from its range (deterministic at the edges)", "raw", details={"ranges": ranges})
    mc = ROOT / "eval" / "output" / "feedback" / "results.json"
    try:
        cells = json.loads(mc.read_text(encoding="utf-8"))["monte_carlo"]
    except (OSError, ValueError, KeyError):
        return add(7, "Feedback: cross-run averaging", "NOT RUN", "Phase 5 Monte Carlo results not present", label=SIM, audit="n/a")
    for mode in ("run", "probeset"):
        rows = sorted((c for c in cells if c["mode"] == mode), key=lambda c: c["k"])
        first, last = rows[0], rows[-1]
        add(7, "Feedback: cross-run averaging", "LEAKED" if last["mean_absolute_error"] < first["mean_absolute_error"] - 0.5 else "BOUNDED LEAK",
            f"mean abs error K={first['k']}: {first['mean_absolute_error']:.2f} -> K={last['k']}: {last['mean_absolute_error']:.2f}",
            mode, label=SIM, audit="n/a")


async def attack_scan(base):
    marker = "rawprompt" + secrets.token_hex(6)
    async with Stack(base / "scan", "window_hard") as stack:
        for i in range(3):
            await stack.call("POST", "/v1/submit", "red", json={"run_id": "scan", "prompt": f"{marker} {i}"})
        await stack.call("POST", "/v1/submit", "red", json={"run_id": "scan", "prompt": f"{marker} {stack.trigger}"})
        await stack.call("POST", "/v1/run/scan/finish", "evaluator")
        await stack.call("GET", "/v1/run/scan/report", "red")
        await asyncio.sleep(2)  # Let the audit queue drain.
        needles = {"canary trigger": stack.trigger.encode(), "raw prompt marker": marker.encode(),
                   "red token": stack.tokens["RED_TOKEN"].encode(), "gateway key": stack.config["GATEWAY_KEY"].encode()}
        files = [p for p in stack.directory.rglob("*") if p.is_file() and "audit-keys" not in p.parts]
        hits = {name: [str(p.relative_to(stack.directory)) for p in files if needle in p.read_bytes()]
                for name, needle in needles.items()}
    found = {k: v for k, v in hits.items() if v}
    add(8, "Scan gateway stdout, audit logs, checkpoints, SQLite DBs, sealed config",
        "LEAKED" if found else "BLOCKED",
        f"{len(files)} files scanned; hits: {found or 'none'} (prompt SHA-256 hashes are stored and dictionary-guessable)",
        "window_hard", details={"files": len(files), "hits": hits})
    reason = docker_ready()
    if reason:
        return add(8, "Scan Docker volumes + container logs", "NOT RUN", reason, label=DOCKER)
    logs = compose("logs", "--no-color", timeout=60).stdout
    volume = compose("run", "--rm", "--entrypoint", "sh", "verifier", "-c",
                     "grep -rla -e pineapple -e 'Hello from the isolated' /audit-logs /checkpoints /gateway-data || true",
                     timeout=120).stdout.split()
    found = [n for n in ("pineapple", "Hello from the isolated Red client") if n in logs] + volume
    add(8, "Scan Docker volumes + container logs (configured trigger, demo raw prompt)",
        "LEAKED" if found else "BLOCKED", f"hits: {found or 'none'}", label=DOCKER)


async def attack_noisy_neighbor(base, n=60):
    for policy in ("bucket_hard", "window_hard"):
        async with Stack(base / f"noisy-{policy}", policy) as stack:
            # An unfinished run keeps Blue's defense frozen, so every Blue request
            # takes the same (rejected) path in both conditions.
            await stack.call("POST", "/v1/submit", "red", json={"run_id": "hold", "prompt": "hello"})

            async def blue_times(count):
                return [(await stack.call("POST", "/v1/defense", "blue", json={"trigger": "x"}))[1] for _ in range(count)]

            baseline, stop = [], asyncio.Event()

            async def burst(worker):
                i = 0
                while not stop.is_set():
                    i += 1
                    await stack.call("POST", "/v1/submit", "red", json={"run_id": f"burst-{worker}-{i}", "prompt": f"load {worker} {i}"})

            under = []
            for block in range(3):  # Interleave quiet and burst blocks.
                baseline += await blue_times(n // 3)
                stop.clear()
                workers = [asyncio.create_task(burst(w)) for w in range(32)]
                await asyncio.sleep(0.5)
                under += await blue_times(n // 3)
                stop.set()
                await asyncio.gather(*workers)
        d, p = ks_2samp(baseline, under)
        shift = percentile(under, 50) - percentile(baseline, 50)
        result = "LEAKED" if p < 0.01 else "BOUNDED LEAK"
        add(9, "Noisy neighbor: Red burst (32 workers) vs Blue's release times", result,
            f"median shift {shift * 1000:+.1f} ms, p95 {percentile(baseline, 95) * 1000:.0f} -> {percentile(under, 95) * 1000:.0f} ms, "
            f"KS D={d:.2f} p={p:.3f} (n={len(baseline)}/{len(under)})", policy)


def burn(stop_at):
    while time.time() < stop_at:
        pass


async def attack_cpu_slip(base, n=60):
    for policy in ("bucket_hard", "window_hard"):
        async with Stack(base / f"cpu-{policy}", policy) as stack:
            async def times(count, tag):
                out = []
                for i in range(count):
                    _, elapsed = await stack.call("POST", "/v1/submit", "red", json={"run_id": f"cpu-{tag}", "prompt": f"cpu probe {tag} {i}"})
                    out.append(elapsed)
                return out
            idle = await times(n, "idle")
            stop_at = time.time() + n * WINDOW * 1.5 + 10
            burners = [multiprocessing.Process(target=burn, args=(stop_at,)) for _ in range(os.cpu_count() or 4)]
            for b in burners:
                b.start()
            try:
                await asyncio.sleep(1)
                loaded = await times(n, "loaded")
            finally:
                for b in burners:
                    b.terminate()
        target = BUCKETS[0] if policy == "bucket_hard" else WINDOW  # Allowed miss lands in the first bucket.

        def late(values, ms):
            return sum(v - target > ms / 1000 for v in values)
        add("9b", "Release slip under host CPU load (all cores busy)", "BOUNDED LEAK" if late(loaded, 20) == 0 else "LEAKED",
            f"late >5 ms: idle {late(idle, 5)}/{n}, loaded {late(loaded, 5)}/{n}; late >20 ms: idle {late(idle, 20)}/{n}, "
            f"loaded {late(loaded, 20)}/{n}; max lateness idle {(max(idle) - target) * 1000:.0f} ms, loaded {(max(loaded) - target) * 1000:.0f} ms",
            policy, details={"idle": idle, "loaded": loaded, "target": target})


def attack_timing_from_matrix():
    path = ROOT / "eval" / "output" / "round2" / "results.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return add(5, "Timing A-vs-B (ordinary, boundary, overflow, deadline)", "NOT RUN", "Phase 3 results missing")
    audit = "on" if data.get("audit") else "off"
    for policy in ("raw", "bucket", "bucket_hard", "window_hard"):
        cells = [c for c in data["cells"] if c["policy"] == policy]
        if not cells:
            add(5, "Timing A-vs-B", "NOT RUN", "no cells for this policy", policy, audit=audit)
            continue
        leaks = [c for c in cells if c["wilson_95"][0] > 0.5]
        text = "; ".join(f"{c['cohort']} {c['test_accuracy']:.0%}" for c in cells) + f" (n={cells[0]['test_runs']} unseen runs/cell)"
        add(5, "Timing A-vs-B (live matrix)", "LEAKED" if leaks else "BOUNDED LEAK", text, policy, audit=audit)


def not_covered():
    for name in ("Host/kernel container escape", "Hardware and shared-GPU side channels (incl. real KV cache)",
                 "Compromised gateway or collector (trusted components)"):
        add(10, name, "NOT COVERED", "out of scope for this prototype; stated in threat model", audit="n/a", label="-")


async def run(selected):
    base = Path(tempfile.mkdtemp(prefix="attack-suite-"))
    jobs = {1: attack_network, 2: attack_filesystem, 3: attack_roles, 4: attack_error_oracle, 5: attack_timing_from_matrix,
            6: attack_cache, 7: attack_feedback, 8: attack_scan, 9: attack_noisy_neighbor, "9b": attack_cpu_slip, 10: not_covered}
    try:
        for key, job in jobs.items():
            if selected and str(key) not in selected:
                continue
            started = time.monotonic()
            try:
                outcome = job(base) if job.__code__.co_argcount else job()
                if asyncio.iscoroutine(outcome):
                    await outcome
            except Exception as error:  # Report, never hide, a crashed attack.
                add(key, job.__name__, "NOT RUN", f"attack crashed: {type(error).__name__}: {str(error)[:150]}")
            print(f"    ({job.__name__} took {time.monotonic() - started:.0f} s)", flush=True)
    finally:
        shutil.rmtree(base, ignore_errors=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--only", nargs="*", default=[], help="attack numbers, e.g. 3 4 9b")
    parser.add_argument("--output", type=Path, default=ROOT / "attack_suite_results.json")
    args = parser.parse_args()
    asyncio.run(run(set(args.only)))
    previous = []
    if args.only and args.output.exists():  # Partial re-run: replace only the selected attacks.
        previous = [r for r in json.loads(args.output.read_text(encoding="utf-8"))["results"] if str(r["attack"]) not in set(args.only)]
    rows = sorted(previous + ROWS, key=lambda r: (float(str(r["attack"]).rstrip("b")) + (0.5 if str(r["attack"]).endswith("b") else 0)))
    args.output.write_text(json.dumps({"generated": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "results": rows}, indent=2) + "\n",
                           encoding="utf-8")
    print(f"\n{'#':<3} {'Attack':<62} {'Policy':<12} {'Result':<13} Key number")
    for r in rows:
        print(f"{str(r['attack']):<3} {r['name'][:62]:<62} {r['policy']:<12} {r['result']:<13} {r['summary'][:150]}")


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
