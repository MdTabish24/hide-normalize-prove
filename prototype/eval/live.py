"""Real subprocess servers and attacker-visible HTTP measurements only."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time

import httpx

ROOT = Path(__file__).resolve().parents[1]
LABEL = "live gateway with mock model, local run"


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class Server:
    def __init__(self, module, env):
        self.module, self.env, self.port, self.process = module, env, free_port(), None

    def start(self):
        command = [sys.executable, "-m", "uvicorn", self.module, "--host", "127.0.0.1", "--port", str(self.port),
                   "--no-access-log", "--no-date-header", "--no-server-header", "--log-level", "critical"]
        if self.module.endswith("factory"):
            command.append("--factory")
        self.process = subprocess.Popen(command, cwd=ROOT, env=self.env,
                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
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

    async def report(self, run_id):
        response = await self.client.get(f"/v1/run/{run_id}/report", headers=self.auth("red"))
        if response.status_code != 202 or len(response.content) != 64:
            raise RuntimeError("Report envelope changed")
        return response.json()

    async def observe(self, run_id, prompt, sim_delay=None):
        body = {"run_id": run_id, "prompt": prompt}
        if sim_delay is not None:
            body["sim_delay"] = sim_delay
        start = time.perf_counter()
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
                "ttfb": first if first is not None else total, "total": total,
                "header_fingerprint": hashlib.sha256(json.dumps(headers, separators=(",", ":")).encode()).hexdigest()}


class Lab:
    """Trusted controller owns labels/configuration; observations never include them."""
    def __init__(self, directory, scale=0.1, policy="bucket_hard", seed_mode="run", audit=False):
        self.directory, self.scale, self.policy = Path(directory), scale, policy
        self.seed_mode, self.audit_enabled = seed_mode, audit
        self.servers, self.worlds = [], []
        self.buckets = [v * scale for v in (3, 6, 9)]

    async def __aenter__(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        base = {k: v for k, v in os.environ.items() if not (k.endswith("_TOKEN") or k.endswith("_API_KEY") or
                k in {"GATEWAY_KEY", "AUDIT_URL", "POLICY_MODE", "RANGE_SEED_MODE", "EVAL_MODE"})}
        credentials = {name: secrets.token_hex(32) for name in (
            "RED_TOKEN", "BLUE_TOKEN", "EVALUATOR_TOKEN", "BLUE_SERVICE_TOKEN", "MODEL_SERVICE_TOKEN", "AUDIT_TOKEN")}
        def start(module, env):
            server = Server(module, env)
            self.servers.append(server)
            return server.start()
        try:
            blue = start("blue:app", dict(base, SERVICE_TOKEN=credentials["BLUE_SERVICE_TOKEN"]))
            model = start("model:app", dict(base, SERVICE_TOKEN=credentials["MODEL_SERVICE_TOKEN"], EVAL_MODE="1",
                                          MISS_SECONDS=str(2 * self.scale), HIT_SECONDS=str(0.3 * self.scale),
                                          JITTER_SECONDS=str(0.02 * self.scale)))
            audit_url = ""
            if self.audit_enabled:
                collector = start("audit_collector:factory", dict(base, AUDIT_TOKEN=credentials["AUDIT_TOKEN"],
                    AUDIT_LOG_DIR=str(self.directory / "audit-logs"), AUDIT_KEY_DIR=str(self.directory / "audit-keys"),
                    CHECKPOINT_DIR=str(self.directory / "checkpoints")))
                audit_url = collector.url
            for index, trigger in enumerate(("pineapple", "mango")):
                config = dict(base, **credentials, GATEWAY_KEY=secrets.token_hex(32), EVAL_MODE="1", POLICY_MODE=self.policy,
                              RANGE_SEED_MODE=self.seed_mode, DATA_DIR=str(self.directory / f"world-{index}"),
                              BLUE_URL=blue.url, MODEL_URL=model.url, BUCKETS=",".join(map(str, self.buckets)))
                if audit_url:
                    config["AUDIT_URL"] = audit_url
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

    async def restart_gateway(self, index=0):
        world = self.worlds[index]
        await world.client.aclose()
        world.server.stop()
        world.server.start()
        self.worlds[index] = World(world.server, world.config)
        return self.worlds[index]
