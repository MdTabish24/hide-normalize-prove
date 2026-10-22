"""One-worker live mediator with deadline-bounded, buffered generic responses."""
import asyncio
import hashlib
import json
import math
import os
import secrets
import sys
import time
from pathlib import Path as FilePath
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
from meter import Params as MeterParams, body as meter_body


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
    """Buffer app output. Red sees 64-byte generic replies or a final noisy range.

    Finished-run artifacts are a separate evaluator-only variable-size exception.

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
        state = scope.get("state", {})
        operator_view = status == 200 and state.get("operator_artifacts") is True and state.get("role") == "evaluator"
        body = b"".join(chunks) if status == 200 else PENDING
        if (not operator_view and len(body) != 64) or len(body) > 4_000_000:
            body = PENDING
        if state.get("cancelled"):
            metadata("deadline_cancelled", state.get("run_id"), state.get("role"), bucket, state.get("prompt_hash"))
        elif error:
            metadata("rejected", state.get("run_id"), state.get("role"), bucket, state.get("prompt_hash"))
        metadata("release", state.get("run_id"), state.get("role"), bucket, state.get("prompt_hash"))
        await release_at(start + bucket)
        response_headers = dict(HEADERS, **{"content-length": str(len(body))})
        await send({"type": "http.response.start", "status": 202,
                    "headers": [(key.encode(), value.encode()) for key, value in response_headers.items()]})
        await send({"type": "http.response.body", "body": body})
        # Opt-in operator demo telemetry, AFTER release; never part of Red's reply.
        # Default/normal evaluations do not create this file or record model text.
        trace = state.get("demo_trace")
        if trace is not None:
            trace.update(compute_seconds=elapsed, scheduled_release_seconds=bucket,
                         released_seconds=time.perf_counter()-start)
            try:
                with FilePath(state["demo_trace_file"]).open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps(trace, separators=(",", ":"))+"\n")
            except OSError:
                metadata("demo_trace_unavailable")
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
    # Opt-in variant of window_hard: Red's reply is still released at exactly one window, but compute is NOT
    # cancelled at the deadline. It continues in the background up to a hard maximum, counts against the same
    # per-identity in-flight limit, and its result joins the sealed run record (late attempts are counted).
    continue_mode = policy == "window_hard" and config.get("WINDOW_CONTINUE") == "1"
    continue_max = float(config.get("WINDOW_CONTINUE_MAX_SECONDS") or 4 * window)
    if continue_mode and not (math.isfinite(continue_max) and window < continue_max <= 60):
        raise ValueError("WINDOW_CONTINUE_MAX_SECONDS must be greater than the window and at most 60")
    background = set()
    # Opt-in (BLUE_INLINE=1): the keyword rule is evaluated inside the gateway as DATA, so no Blue-side code ever receives Red's prompt.
    blue_inline = config.get("BLUE_INLINE") == "1"
    # Opt-in feedback: none (default) | meter (3 states, batched, budgeted) | exact (per-prompt baseline, EVAL_MODE=1 only).
    feedback_mode = config.get("FEEDBACK_MODE", "none")
    if feedback_mode not in ("none", "meter", "exact"):
        raise ValueError("Invalid FEEDBACK_MODE")
    if feedback_mode == "exact" and config.get("EVAL_MODE") != "1":
        metadata("feedback_ignored_without_eval_mode")
        feedback_mode = "none"
    meter_params = MeterParams.from_config(config) if feedback_mode == "meter" else None
    meter_tasks = set()
    tokens = {role: config[role.upper() + "_TOKEN"] for role in ("red", "blue", "evaluator")}
    if any(len(token) < 16 for token in tokens.values()) or len(set(tokens.values())) != 3:
        raise ValueError("Three distinct role tokens of at least 16 characters required")
    key = bytes.fromhex(config["GATEWAY_KEY"])
    if len(key) != 32:
        raise ValueError("GATEWAY_KEY must be a 32-byte hex key")
    store = Store(config.get("DATA_DIR", "/data"), key,
                  range_seed_mode=config.get("RANGE_SEED_MODE", "run"), range_generator=generate_range,
                  audit_queue_max=int(config.get("AUDIT_QUEUE_MAX", "10000")))
    demo_trace = config.get("EVAL_MODE") == "1" and config.get("DEMO_TRACE") == "1"
    # Opt-in diagnosis only (EVAL_MODE=1): record every event-loop stall above 0.1 s with wall time and load counters.
    lag_log = config.get("EVAL_MODE") == "1" and config.get("LOOP_LAG_LOG") == "1"
    # Fail closed if a persisted key/config is corrupt. No silent key rotation.
    defense = store.unseal()

    async def loop_lag_monitor():
        path, interval = FilePath(store.directory) / "loop-lag.jsonl", 0.05
        while True:
            before = time.perf_counter()
            await asyncio.sleep(interval)
            lag = time.perf_counter() - before - interval
            if lag > 0.1:
                row = dict(t=round(time.time(), 3), lag=round(lag, 3), background=len(background), inflight=sum(inflight.values()),
                           tasks=len(asyncio.all_tasks()))
                try:
                    with path.open("a", encoding="utf-8") as stream:
                        stream.write(json.dumps(row, separators=(",", ":")) + "\n")
                except OSError:
                    pass

    @asynccontextmanager
    async def lifespan(api):
        # Initialize the executor/crypto before a measured request, without any
        # model call or prompt/cache entry. Cold module/thread startup is not
        # useful compute and otherwise makes the first tiny demo bucket overrun.
        await asyncio.to_thread(store.vault.cover_read)
        async with httpx.AsyncClient(transport=transport, trust_env=False,
                                     timeout={"bucket_hard": buckets[-1], "window_hard": continue_max if continue_mode else deadline}.get(policy, 60)) as client:
            api.state.client = client
            api.state.audit = Forwarder(store.audit_queue, config, transport)
            api.state.audit.start()
            lag_task = asyncio.create_task(loop_lag_monitor()) if lag_log else None
            if transport is None:
                # Internal root GETs only establish HTTP pools; neither backend
                # generates text on GET /. Failure does not stop safe startup.
                urls = [config.get("BLUE_URL", "http://blue-defense:8000"),
                        config.get("MODEL_URL", "http://model-mock:8000")]
                await asyncio.gather(*(client.get(url.rstrip("/")+"/", timeout=.3) for url in urls),return_exceptions=True)
            try:
                yield
            finally:
                if lag_task is not None:
                    lag_task.cancel()
                for pending in list(background):
                    pending.cancel()
                if background:
                    await asyncio.gather(*background, return_exceptions=True)
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
        if continue_mode:
            task = asyncio.create_task(run_background(body, request, owner))
            background.add(task)

            def finished(done, owner=owner):
                background.discard(done)
                inflight[owner] -= 1
                if not done.cancelled():
                    done.exception()  # Mark retrieved; the route re-raises it when it finished in time.
            task.add_done_callback(finished)
            # Wait only until just before the deadline; unfinished work keeps running without delaying Red.
            await asyncio.wait({task}, timeout=max(0.0, deadline - 0.05 * window))
            if task.done() and not task.cancelled():
                task.result()
            return Response(status_code=202)
        try:
            return await handle_submit(body, request, owner)
        finally:
            inflight[owner] -= 1

    async def run_background(body, request, owner):
        try:
            async with asyncio.timeout(continue_max):
                return await handle_submit(body, request, owner)
        except TimeoutError:
            return None  # Hard maximum reached; handle_submit already recorded the attempt as cancelled.

    async def handle_submit(body, request, owner):
        started = time.perf_counter()
        trace = None
        if demo_trace:
            trace = {"run_id": body.run_id, "blue_allowed": None, "reason": "not_decided",
                     "model_called": False, "model_completed": False, "model_answer": None}
            request.state.demo_trace = trace
            request.state.demo_trace_file = str(store.directory / "demo-trace.jsonl")
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
        blue_allowed = None
        output = None
        try:
            # Disk creation/encryption must not serialize unrelated requests on
            # the event loop. Only published, complete record refs are readable.
            prompt = await asyncio.to_thread(store.save_prompt, attempt, body.run_id, owner, body.prompt)
            if blue_inline:  # Same casefolded substring rule as blue.py, with no request to the Blue service.
                result = {"allowed": api.state.defense["trigger"].casefold() not in prompt.casefold()}
            else:
                result = await internal("blue", "/check", {"prompt": prompt, "filter": api.state.defense})
            if not isinstance(result.get("allowed"), bool):
                raise ValueError("Invalid defense response")
            safe = result["allowed"]
            blue_allowed = safe
            if trace is not None:
                trace.update(blue_allowed=safe, reason="keyword_absent" if safe else "keyword_matched")
            if safe:
                model_body = {"prompt": prompt, "role": "red", "run_id": body.run_id}
                if config.get("EVAL_MODE") == "1" and body.sim_delay is not None:
                    if type(body.sim_delay) not in (int, float) or not math.isfinite(body.sim_delay) or not 0 <= body.sim_delay <= 30:
                        raise HTTPException(422)
                    model_body["sim_delay"] = body.sim_delay
                if trace is not None:
                    trace["model_called"] = True
                answer = await internal("model", "/generate", model_body)
                if not isinstance(answer.get("answer"), str) or len(answer["answer"].encode()) > 20000:
                    raise ValueError("Invalid model output")
                output = {k: answer[k] for k in ("answer", "backend", "model", "usage") if k in answer}
                if trace is not None:
                    # Only the known mock answer is eligible; never persist arbitrary LLM text.
                    trace.update(model_completed=True,
                                 model_answer="Dummy answer." if answer.get("answer") == "Dummy answer." else None)
        except asyncio.CancelledError:
            # Compute deadline hit. Recorded for the evaluator and audit only.
            cancelled = request.state.cancelled = True
            if trace is not None:
                trace["reason"] = "deadline_cancelled"
            if continue_mode:  # No middleware cancel here, so record the hard-maximum stop in the audit chain.
                api.state.audit.emit("deadline_cancelled", body.run_id, "red", window, request.state.prompt_hash)
            raise
        except Exception:
            if trace is not None:
                trace["reason"] = "internal_error"
            raise
        finally:
            output_ref = None
            try:
                output_ref = store.seal_output(body.run_id, owner, output)
            finally:
                late = continue_mode and not cancelled and time.perf_counter() - started > deadline
                store.end(attempt, safe, cancelled, blue_allowed=blue_allowed, output_ref=output_ref, late=late)
                if meter_params is not None:
                    # Off the request path: a worker thread publishes completed batches; nothing waits for it.
                    task = asyncio.create_task(asyncio.to_thread(store.meter_update, body.run_id, owner, meter_params, key))
                    meter_tasks.add(task)
                    task.add_done_callback(lambda done: (meter_tasks.discard(done), done.cancelled() or done.exception()))
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

    @api.get("/v1/run/{run_id}/feedback")
    async def feedback(run_id: RunId, request: Request):
        # Same envelope for every mode: Red always gets the standard 64-byte body at the policy's fixed release time.
        owner = authorize(request, "red")
        request.state.run_id = run_id
        if feedback_mode == "meter":
            return Response(meter_body(store.meter_read(owner, run_id, meter_params)), status_code=200)
        if feedback_mode == "exact":
            last = store.last_attempt_safe(run_id, owner)
            return Response(json.dumps({"exact": last}, separators=(",", ":")).encode().ljust(64, b" "), status_code=200)
        return Response(PENDING, status_code=200)

    @api.get("/v1/run/{run_id}/meter-evaluation")
    async def meter_evaluation(run_id: RunId, request: Request):
        # Evaluator-only: true per-batch score next to what Red was shown. Red/Blue keep the 64-byte envelope.
        authorize(request, "evaluator")
        request.state.run_id = run_id
        data = store.meter_evaluation(run_id)
        if data is None:
            return Response(PENDING, status_code=200)
        request.state.operator_artifacts = True
        return Response(data, status_code=200)

    @api.get("/v1/run/{run_id}/evaluation")
    async def evaluation(run_id: RunId, request: Request):
        # Sealed evaluator-only counts after finish; Red never sees these.
        authorize(request, "evaluator")
        request.state.run_id = run_id
        return Response(store.evaluation(run_id) or PENDING, status_code=200)

    @api.get("/v1/run/{run_id}/artifacts")
    async def artifacts(run_id: RunId, request: Request):
        # Private operator readout after completion. Red/Blue authorization fails
        # before loading records, and their responses keep the 64-byte envelope.
        authorize(request, "evaluator")
        with store.connect() as db:
            run = db.execute("SELECT owner, finished FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if not run or not run[1]:
            return Response(PENDING, status_code=200)
        rows = store.completed_payloads(run_id, run[0])
        request.state.operator_artifacts = True
        return Response(json.dumps({"run_id": run_id, "records": rows}, ensure_ascii=False).encode(), status_code=200)

    api.add_middleware(Boundary, buckets=buckets, policy=policy, window=window, deadline=deadline)
    return api


def factory():
    return create_app()
