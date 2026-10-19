"""One-worker live mediator with deadline-bounded, buffered generic responses."""
import asyncio
import hashlib
import json
import math
import os
import secrets
import sys
import time
from contextlib import asynccontextmanager
from typing import Annotated

import httpx
from fastapi import FastAPI, HTTPException, Path, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field

from common import HEADERS, PENDING
from audit_forwarder import Forwarder
from storage import Store
from range_feedback import generate_range


RunId = Annotated[str, Path(pattern="^[A-Za-z0-9_-]{1,64}$")]
POLICIES = {"raw", "bucket", "bucket_hard", "window_hard"}
EVAL_ONLY_POLICIES = {"raw", "bucket"}


class Submit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: str = Field(pattern="^[A-Za-z0-9_-]{1,64}$")
    prompt: str = Field(min_length=1, max_length=4096)
    sim_delay: object = None  # Ignored unless BOTH gateway and mock enable EVAL_MODE.


class Defense(BaseModel):
    model_config = ConfigDict(extra="forbid")
    trigger: str = Field(min_length=1, max_length=128)


def parse_buckets(value):
    buckets = tuple(float(item) for item in value.split(","))
    if len(buckets) != 3 or any(not math.isfinite(x) or x <= 0 for x in buckets) or sorted(set(buckets)) != list(buckets):
        raise ValueError("BUCKETS must contain three increasing positive seconds")
    return buckets


def metadata(event, run_id=None, role=None, bucket=None, prompt_hash=None):
    # No exception objects, URL/query strings, credentials, payloads or rules.
    print(json.dumps({"event": event, "run_id": run_id, "role": role,
                      "bucket": bucket, "timestamp": time.time(), "prompt_hash": prompt_hash}), flush=True)


SPIN_SECONDS = 0.003


async def release_at(deadline):
    """Never release early; release as close to the deadline as the loop allows.

    Timer wake-ups are coarse and their lateness depends on unrelated event-loop
    activity (for example audit shipping). Sleep to just before the deadline,
    then yield in a tight loop, so lateness no longer varies with that activity.
    """
    while (remaining := deadline - time.perf_counter()) > SPIN_SECONDS:
        await asyncio.sleep(remaining - SPIN_SECONDS)
    while time.perf_counter() < deadline:
        await asyncio.sleep(0)


class Boundary:
    """Buffer all app output. Only a successful authorized report may vary its body.

    Bucket policies: application errors use the last fixed bucket, so even an
    error arising late has the same deadline. window_hard: EVERY request (done,
    blocked, error, report, or cancelled at the compute deadline) is released at
    exactly `window` seconds. Timing starts at ASGI dispatch (after HTTP headers).
    """
    def __init__(self, app, buckets, policy="bucket_hard", window=None, deadline=None):
        self.app, self.buckets, self.policy = app, buckets, policy
        self.window = window
        self.limit = {"bucket_hard": buckets[-1], "window_hard": deadline}.get(policy, 60)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        start = time.perf_counter()
        status, chunks, size = 202, [], 0

        async def capture(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            elif message["type"] == "http.response.body":
                chunks.append(message.get("body", b""))

        async def limited_receive():
            nonlocal size
            message = await receive()
            size += len(message.get("body", b""))
            if size > 32768:
                raise ValueError("Request too large")
            return message

        try:
            async with asyncio.timeout(self.limit):
                await self.app(scope, limited_receive, capture)
        except (Exception, asyncio.TimeoutError):
            status, chunks = 500, []
        elapsed = time.perf_counter() - start
        error = status >= 400
        bucket = self.buckets[-1] if error else next((b for b in self.buckets if b >= elapsed), self.buckets[-1])
        if self.policy == "window_hard":
            bucket = self.window
        elif not error and self.policy == "raw":
            bucket = elapsed
        elif not error and self.policy == "bucket" and elapsed > self.buckets[-1]:
            bucket = elapsed
        body = b"".join(chunks) if status == 200 else PENDING
        if len(body) != 64:
            body = PENDING
        state = scope.get("state", {})
        if state.get("cancelled"):
            metadata("deadline_cancelled", state.get("run_id"), state.get("role"), bucket, state.get("prompt_hash"))
        elif error:
            metadata("rejected", state.get("run_id"), state.get("role"), bucket, state.get("prompt_hash"))
        metadata("release", state.get("run_id"), state.get("role"), bucket, state.get("prompt_hash"))
        await release_at(start + bucket)
        await send({"type": "http.response.start", "status": 202,
                    "headers": [(key.encode(), value.encode()) for key, value in HEADERS.items()]})
        await send({"type": "http.response.body", "body": body})
        if state.get("audit_report"):
            metadata("report_read", state.get("run_id"), state.get("role"), bucket)
        # Persist audit metadata only after sending, so collector I/O cannot move
        # a response into another bucket or expose collector health to Red.
        audit = state.get("audit")
        if audit:
            run_id = state.get("audit_run_id", state.get("run_id"))
            audit.emit("bucket_released", run_id, state.get("role"), bucket, state.get("prompt_hash"))
            if state.get("cancelled"):
                audit.emit("deadline_cancelled", run_id, state.get("role"), bucket, state.get("prompt_hash"))
            if state.get("audit_report"):
                audit.emit("report_served", run_id, state.get("role"), bucket)
            if state.get("audit_finish"):
                audit.emit("run_finished", run_id, state.get("role"), bucket)
                audit.finish(run_id)


def fine_timer():
    """Windows wakes asyncio timers on a 15.6 ms tick by default, so release
    precision would depend on unrelated event-loop activity. Ask for 1 ms
    (process-scoped on Windows 10 2004+). Linux containers need nothing."""
    if sys.platform == "win32":
        import ctypes
        ctypes.WinDLL("winmm").timeBeginPeriod(1)


def create_app(settings=None, transport=None):
    config = dict(os.environ if settings is None else settings)
    fine_timer()
    buckets = parse_buckets(config.get("BUCKETS", "3,6,9"))
    policy = config.get("POLICY_MODE", "bucket_hard")
    if policy not in POLICIES:
        raise ValueError("Invalid POLICY_MODE")
    if policy in EVAL_ONLY_POLICIES and config.get("EVAL_MODE") != "1":
        # Weak baselines exist only for evaluation, never silently in service.
        metadata("policy_ignored_without_eval_mode")
        policy = "bucket_hard"
    window = float(config.get("WINDOW_SECONDS") or buckets[-1])
    deadline = window * float(config.get("DEADLINE_FRACTION", "0.8"))
    if not (math.isfinite(window) and window > 0 and 0 < deadline < window):
        raise ValueError("window_hard needs WINDOW_SECONDS > 0 and 0 < DEADLINE_FRACTION < 1")
    max_inflight = int(config.get("MAX_INFLIGHT_PER_IDENTITY", "16"))
    inflight = {}
    tokens = {role: config[role.upper() + "_TOKEN"] for role in ("red", "blue", "evaluator")}
    if any(len(token) < 16 for token in tokens.values()) or len(set(tokens.values())) != 3:
        raise ValueError("Three distinct role tokens of at least 16 characters required")
    key = bytes.fromhex(config["GATEWAY_KEY"])
    if len(key) != 32:
        raise ValueError("GATEWAY_KEY must be a 32-byte hex key")
    store = Store(config.get("DATA_DIR", "/data"), key,
                  range_seed_mode=config.get("RANGE_SEED_MODE", "run"), range_generator=generate_range,
                  audit_queue_max=int(config.get("AUDIT_QUEUE_MAX", "10000")))
    # Fail closed if a persisted key/config is corrupt. No silent key rotation.
    defense = store.unseal()

    @asynccontextmanager
    async def lifespan(api):
        async with httpx.AsyncClient(transport=transport, trust_env=False,
                                     timeout={"bucket_hard": buckets[-1], "window_hard": deadline}.get(policy, 60)) as client:
            api.state.client = client
            api.state.audit = Forwarder(store.audit_queue, config, transport)
            api.state.audit.start()
            try:
                yield
            finally:
                await api.state.audit.close()

    api = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    api.state.store = store
    api.state.defense = defense
    api.state.policy = policy

    def authorize(request, expected):
        supplied = request.headers.get("authorization", "")
        role = next((r for r, token in tokens.items() if secrets.compare_digest(supplied, "Bearer " + token)), None)
        request.state.role = role
        if role != expected:
            raise HTTPException(403)
        # Stable principal survives restart and cannot be supplied in JSON.
        return hashlib.sha256(tokens[role].encode()).hexdigest()

    async def internal(service, path, body):
        url = config.get(service.upper() + "_URL", "http://" + ("blue-defense" if service == "blue" else "model-mock") + ":8000")
        response = await api.state.client.post(url + path, json=body,
                                              headers={"authorization": "Bearer " + config[service.upper() + "_SERVICE_TOKEN"]})
        response.raise_for_status()
        return response.json()

    @api.post("/v1/submit")
    async def submit(body: Submit, request: Request):
        owner = authorize(request, "red")
        request.state.run_id = body.run_id
        if policy != "window_hard":
            return await handle_submit(body, request, owner)
        # Queue rule: no queue. Over the fixed per-identity limit, reject at
        # once (still released at the window), so waiting never shifts compute.
        if inflight.get(owner, 0) >= max_inflight:
            raise HTTPException(429)
        inflight[owner] = inflight.get(owner, 0) + 1
        try:
            return await handle_submit(body, request, owner)
        finally:
            inflight[owner] -= 1

    async def handle_submit(body, request, owner):
        request.state.prompt_hash = hashlib.sha256(body.prompt.encode()).hexdigest()
        request.state.audit = api.state.audit
        api.state.audit.emit("submit_received", body.run_id, "red", prompt_hash=request.state.prompt_hash)
        version = hashlib.sha256(json.dumps(api.state.defense, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        attempt = store.begin(body.run_id, owner, request.state.prompt_hash, version)
        if attempt is None or api.state.defense is None:
            if attempt is not None:
                store.end(attempt, False)
            raise HTTPException(403)
        safe = cancelled = False
        try:
            result = await internal("blue", "/check", {"prompt": body.prompt, "filter": api.state.defense})
            if not isinstance(result.get("allowed"), bool):
                raise ValueError("Invalid defense response")
            safe = result["allowed"]
            if safe:
                model_body = {"prompt": body.prompt, "role": "red", "run_id": body.run_id}
                if config.get("EVAL_MODE") == "1" and body.sim_delay is not None:
                    if type(body.sim_delay) not in (int, float) or not math.isfinite(body.sim_delay) or not 0 <= body.sim_delay <= 30:
                        raise HTTPException(422)
                    model_body["sim_delay"] = body.sim_delay
                await internal("model", "/generate", model_body)
        except asyncio.CancelledError:
            # Compute deadline hit. Recorded for the evaluator and audit only.
            cancelled = request.state.cancelled = True
            raise
        finally:
            store.end(attempt, safe, cancelled)
        return Response(status_code=202)

    @api.post("/v1/defense")
    async def set_defense(body: Defense, request: Request):
        authorize(request, "blue")
        # Freeze one filter while unfinished runs exist: avoid mixing defenses.
        with store.connect() as db:
            if db.execute("SELECT COUNT(*) FROM runs WHERE finished=0").fetchone()[0]:
                raise HTTPException(403)
            store.seal(body.model_dump())
            api.state.defense = body.model_dump()
        request.state.audit = api.state.audit
        request.state.audit_run_id = "@gateway"
        request.state.audit_finish = True
        api.state.audit.emit("defense_stored", "@gateway", "blue")
        return Response(status_code=202)

    @api.post("/v1/run/{run_id}/finish")
    async def finish(run_id: RunId, request: Request):
        authorize(request, "evaluator")
        request.state.run_id = run_id
        if store.finish(run_id):
            request.state.audit = api.state.audit
            request.state.audit_finish = True
        return Response(status_code=202)

    @api.get("/v1/run/{run_id}/report")
    async def report(run_id: RunId, request: Request):
        owner = authorize(request, "red")
        request.state.run_id = run_id
        request.state.audit = api.state.audit
        request.state.audit_report = True
        body = store.report(run_id, owner)
        return Response(body or PENDING, status_code=200)

    @api.get("/v1/run/{run_id}/evaluation")
    async def evaluation(run_id: RunId, request: Request):
        # Sealed evaluator-only counts after finish; Red never sees these.
        authorize(request, "evaluator")
        request.state.run_id = run_id
        return Response(store.evaluation(run_id) or PENDING, status_code=200)

    api.add_middleware(Boundary, buckets=buckets, policy=policy, window=window, deadline=deadline)
    return api


def factory():
    return create_app()
