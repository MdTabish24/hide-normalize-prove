"""Real subprocess servers and attacker-visible HTTP measurements only."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import secrets
import socket
import sqlite3
import subprocess
import sys
import time
from contextlib import closing

import httpx

from verify_audit import verify

ROOT = Path(__file__).resolve().parents[1]
LABEL = "live gateway with mock model, local run"


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class Server:
    def __init__(self, module, env, log=None, err_log=None, log_level="critical"):
        self.module, self.env, self.port, self.process = module, env, free_port(), None
        self.err_log, self.log_level = err_log, log_level  # Optional stderr capture (errors only), for diagnosis.
        self.log = log  # Optional file for the server's stdout metadata (log scans).

    def start(self):
        command = [sys.executable, "-m", "uvicorn", self.module, "--host", "127.0.0.1", "--port", str(self.port),
                   "--no-access-log", "--no-date-header", "--no-server-header", "--log-level", self.log_level]
        if self.module.endswith("factory"):
            command.append("--factory")
        stdout = open(self.log, "ab") if self.log else subprocess.DEVNULL
        stderr = open(self.err_log, "ab") if self.err_log else subprocess.DEVNULL
        self.process = subprocess.Popen(command, cwd=ROOT, env=self.env, stdout=stdout, stderr=stderr)
        if self.log:
            stdout.close()  # The child keeps its own handle.
        if self.err_log:
            stderr.close()
        deadline = time.perf_counter() + 20
        while time.perf_counter() < deadline:
            if self.process.poll() is not None:
                raise RuntimeError(f"{self.module} failed to start")
            try:
                with socket.create_connection(("127.0.0.1", self.port), timeout=0.1):
                    return self
            except OSError:
                time.sleep(0.04)
        self.stop()
        raise RuntimeError(f"{self.module} startup timeout")

    def stop(self):
        if self.process and self.process.poll() is None:
            if os.name == "nt":
                # uv-managed Windows Python launchers can leave the real
                # interpreter child alive when only the launcher is stopped.
                subprocess.run(["taskkill", "/PID", str(self.process.pid), "/T", "/F"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               check=False)
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    pass
                return
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)

    @property
    def url(self):
        return f"http://127.0.0.1:{self.port}"


class World:
    def __init__(self, server, config):
        self.server, self.config = server, config
        self.client = httpx.AsyncClient(base_url=server.url, trust_env=False, timeout=65,
                                        limits=httpx.Limits(max_connections=32, max_keepalive_connections=16))

    def auth(self, role):
        return {"authorization": "Bearer " + self.config[role.upper() + "_TOKEN"]}

    async def configure(self, trigger):
        await self.client.post("/v1/defense", json={"trigger": trigger}, headers=self.auth("blue"))
        if not (Path(self.config["DATA_DIR"]) / "defense.enc").exists():
            raise RuntimeError("Evaluation defense configuration failed")

    async def finish(self, run_id):
        await self.client.post(f"/v1/run/{run_id}/finish", headers=self.auth("evaluator"))
        if self.config.get("WINDOW_CONTINUE") != "1":
            return
        # Continue mode: the gateway refuses to finish while background compute runs. Only this evaluator
        # waits (bounded by the hard maximum); Red's replies were already released at the fixed window.
        deadline = time.monotonic() + float(self.config.get("WINDOW_CONTINUE_MAX_SECONDS", "60")) + 5
        uri = (Path(self.config["DATA_DIR"]) / "runs.sqlite").resolve().as_uri() + "?mode=ro"
        while time.monotonic() < deadline:
            with closing(sqlite3.connect(uri, uri=True, timeout=10)) as db:
                row = db.execute("SELECT finished FROM runs WHERE run_id=?", (run_id,)).fetchone()
            if row is None or row[0]:
                return
            await asyncio.sleep(0.1)
            await self.client.post(f"/v1/run/{run_id}/finish", headers=self.auth("evaluator"))

    async def report(self, run_id):
        response = await self.client.get(f"/v1/run/{run_id}/report", headers=self.auth("red"))
        if response.status_code != 202 or len(response.content) != 64:
            raise RuntimeError("Report envelope changed")
        return response.json()

    async def observe(self, run_id, prompt, sim_delay=None):
        body = {"run_id": run_id, "prompt": prompt}
        if sim_delay is not None:
            body["sim_delay"] = sim_delay
        start, started_at = time.perf_counter(), time.time()
        first, size = None, 0
        async with self.client.stream("POST", "/v1/submit", json=body, headers=self.auth("red")) as response:
            status = response.status_code
            headers = sorted(response.headers.multi_items())
            async for chunk in response.aiter_raw():
                if first is None:
                    first = time.perf_counter() - start
                size += len(chunk)
        total = time.perf_counter() - start
        if status != 202 or size != 64:
            raise RuntimeError("Submit envelope changed; evaluation aborted, not filtered")
        return {"status": status, "headers": headers, "body_length": size,
                "ttfb": first if first is not None else total, "total": total, "started_at": started_at,
                "header_fingerprint": hashlib.sha256(json.dumps(headers, separators=(",", ":")).encode()).hexdigest()}


class Lab:
    """Trusted controller owns labels/configuration; observations never include them."""
    def __init__(self, directory, scale=0.1, policy="bucket_hard", seed_mode="run", audit=False, demo_trace=False, backend="mock",
                 window_continue=False, window_seconds=None, extra_env=None, capture_dir=None):
        self.capture_dir = Path(capture_dir) if capture_dir else None  # Keep each server's error output here when set.
        self.window_continue = window_continue
        self.extra_env = dict(extra_env or {})  # Opt-in gateway settings, e.g. FEEDBACK_MODE; empty by default.
        self.window_seconds = window_seconds
        self.directory, self.scale, self.policy = Path(directory), scale, policy
        self.seed_mode, self.audit_enabled = seed_mode, audit
        self.demo_trace = demo_trace
        if backend not in ("mock", "deepseek"):
            raise ValueError("Unsupported lab backend")
        self.backend = backend
        self.servers, self.worlds = [], []
        self.buckets = [v * scale for v in (3, 6, 9)]

    async def __aenter__(self):
        if self.backend == "deepseek" and not os.environ.get("DEEPSEEK_API_KEY"):
            raise ValueError("Set DEEPSEEK_API_KEY in the launching terminal; no mock fallback")
        self.directory.mkdir(parents=True, exist_ok=True)
        base = {k: v for k, v in os.environ.items() if not (k.endswith("_TOKEN") or k.endswith("_API_KEY") or
                k in {"GATEWAY_KEY", "AUDIT_URL", "AUDIT_MODE", "POLICY_MODE", "RANGE_SEED_MODE", "EVAL_MODE",
                      "WINDOW_SECONDS", "DEADLINE_FRACTION", "MAX_INFLIGHT_PER_IDENTITY",
                      "WINDOW_CONTINUE", "WINDOW_CONTINUE_MAX_SECONDS"})}
        credentials = {name: secrets.token_hex(32) for name in (
            "RED_TOKEN", "BLUE_TOKEN", "EVALUATOR_TOKEN", "BLUE_SERVICE_TOKEN", "MODEL_SERVICE_TOKEN", "AUDIT_TOKEN")}
        def start(module, env):
            err = None
            if self.capture_dir:
                self.capture_dir.mkdir(parents=True, exist_ok=True)
                err = self.capture_dir / f"{module.replace(':', '-')}-{len(self.servers)}.err"
            server = Server(module, env, err_log=err, log_level="error" if err else "critical")
            self.servers.append(server)
            return server.start()
        try:
            blue = start("blue:app", dict(base, SERVICE_TOKEN=credentials["BLUE_SERVICE_TOKEN"]))
            model_env = dict(base, SERVICE_TOKEN=credentials["MODEL_SERVICE_TOKEN"], EVAL_MODE="1",
                             MISS_SECONDS=str(2 * self.scale), HIT_SECONDS=str(0.3 * self.scale),
                             JITTER_SECONDS=str(0.02 * self.scale))
            if self.backend == "deepseek":
                # Provider credential goes ONLY to the adapter child. No .env load.
                model_env["DEEPSEEK_API_KEY"] = os.environ["DEEPSEEK_API_KEY"]
                if self.window_continue:  # The adapter must not cut the call before the gateway's hard maximum.
                    model_env["PROVIDER_TIMEOUT_SECONDS"] = str(4 * (self.window_seconds or self.buckets[-1]))
            model = start("provider:factory" if self.backend == "deepseek" else "model:app", model_env)
            for index, trigger in enumerate(("pineapple", "mango")):
                # Each world is its own deployment with its own collector: two
                # gateways must never share one per-run sequence stream.
                collector = start("audit_collector:factory", dict(base, AUDIT_TOKEN=credentials["AUDIT_TOKEN"],
                    AUDIT_LOG_DIR=str(self.directory / f"audit-logs-{index}"),
                    AUDIT_KEY_DIR=str(self.directory / f"audit-keys-{index}"),
                    CHECKPOINT_DIR=str(self.directory / f"checkpoints-{index}")))
                config = dict(base, **credentials, GATEWAY_KEY=secrets.token_hex(32), EVAL_MODE="1", POLICY_MODE=self.policy,
                              RANGE_SEED_MODE=self.seed_mode, DATA_DIR=str(self.directory / f"world-{index}"),
                              BLUE_URL=blue.url, MODEL_URL=model.url, BUCKETS=",".join(map(str, self.buckets)),
                              AUDIT_URL=collector.url, AUDIT_GIVE_UP_SECONDS="30", AUDIT_TIMEOUT_SECONDS="1")
                if self.window_seconds:
                    config["WINDOW_SECONDS"] = str(self.window_seconds)
                if self.window_continue:
                    config["WINDOW_CONTINUE"] = "1"
                    config["WINDOW_CONTINUE_MAX_SECONDS"] = str(4 * (self.window_seconds or self.buckets[-1]))
                config.update(self.extra_env)
                if not self.audit_enabled:
                    config["AUDIT_MODE"] = "off"  # Explicit; honored only because EVAL_MODE=1.
                config["DEMO_TRACE"] = "1" if self.demo_trace else "0"
                gateway = start("gateway:factory", config)
                world = World(gateway, config)
                self.worlds.append(world)
                await world.configure(trigger)
            return self
        except BaseException:
            await self.__aexit__(None, None, None)
            raise

    async def __aexit__(self, *args):
        for world in self.worlds:
            await world.client.aclose()
        for server in reversed(self.servers):
            server.stop()

    def outcomes(self, index, run_ids):
        """Operator ground truth from the gateway DB (never an attacker feature)."""
        uri = (Path(self.worlds[index].config["DATA_DIR"]) / "runs.sqlite").resolve().as_uri() + "?mode=ro"
        with closing(sqlite3.connect(uri, uri=True, timeout=10)) as db:
            rows = {}
            for run_id in run_ids:
                rows[run_id] = db.execute("SELECT COUNT(*), COALESCE(SUM(safe),0), COALESCE(SUM(cancelled),0) "
                                          "FROM attempts WHERE run_id=?", (run_id,)).fetchone()
        return rows

    def dead_servers(self):
        """Modules whose process has exited (a collector or gateway that died or crashed during a run)."""
        return [s.module for s in self.servers if s.process is not None and s.process.poll() is not None]

    def late_counts(self, index, run_ids):
        """Attempts that finished after the window deadline (continue mode only), from the gateway DB."""
        uri = (Path(self.worlds[index].config["DATA_DIR"]) / "runs.sqlite").resolve().as_uri() + "?mode=ro"
        with closing(sqlite3.connect(uri, uri=True, timeout=10)) as db:
            return {run_id: db.execute("SELECT COALESCE(SUM(late),0) FROM attempts WHERE run_id=?", (run_id,)).fetchone()[0]
                    for run_id in run_ids}

    async def audit_check(self, run_ids_by_world, drain_seconds=120):
        """Wait for each gateway queue to drain, then run the verifier on every run."""
        result = {"enabled": self.audit_enabled, "runs": 0, "valid": 0, "reasons": {}, "queue": []}
        if not self.audit_enabled:
            return result
        for index, run_ids in run_ids_by_world.items():
            data = Path(self.worlds[index].config["DATA_DIR"])
            uri = (data / "audit_queue.sqlite").resolve().as_uri() + "?mode=ro"
            deadline = time.monotonic() + drain_seconds
            while True:
                with closing(sqlite3.connect(uri, uri=True, timeout=10)) as db:
                    pending, dead = (db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("audit_outbox", "audit_dead"))
                if not pending or time.monotonic() > deadline:
                    break
                await asyncio.sleep(0.5)
            result["queue"].append({"world": index, "pending_after_drain": pending, "dead_letters": dead})
            logs, checkpoints = self.directory / f"audit-logs-{index}", self.directory / f"checkpoints-{index}"
            for run_id in run_ids:
                valid, reason, _ = verify(logs / f"{run_id}.jsonl", checkpoints / f"{run_id}.json",
                                          checkpoints / "public_key.bin", run_id, data / "runs.sqlite")
                result["runs"] += 1
                result["valid"] += int(valid)
                if not valid:
                    result["reasons"][reason] = result["reasons"].get(reason, 0) + 1
        return result

    async def restart_gateway(self, index=0):
        world = self.worlds[index]
        await world.client.aclose()
        world.server.stop()
        world.server.start()
        self.worlds[index] = World(world.server, world.config)
        return self.worlds[index]
