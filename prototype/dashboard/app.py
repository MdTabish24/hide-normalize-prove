"""Read-only evidence UI plus an allowlisted filesystem queue to the host operator."""
import asyncio
import json
import os
from pathlib import Path
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from pydantic import BaseModel, ConfigDict
from typing import Literal

from .data import LABEL, audit_events, evidence, matrix, public_observations

HERE = Path(__file__).parent


class Job(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["traffic", "isolation", "audit", "story"]
    policy: Literal["raw", "bucket_hard", "window_hard"] = "bucket_hard"
    secret: Literal["A", "B"] = "A"


def create_app(saved=None, runtime=None, audit=None, eval_mode=None):
    saved = Path(saved or os.getenv("DASHBOARD_SAVED", HERE.parent))
    runtime = Path(runtime or os.getenv("DASHBOARD_RUNTIME", HERE / "runtime"))
    audit = Path(audit or os.getenv("DASHBOARD_AUDIT", HERE.parent / "audit-logs"))
    requests = Path(os.getenv("DASHBOARD_REQUESTS", runtime / "requests"))
    observations = Path(os.getenv("DASHBOARD_OBSERVATIONS", runtime / "observations"))
    test_only = os.getenv("EVAL_MODE") == "1" if eval_mode is None else eval_mode
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"])
    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        return JSONResponse({"status": "rejected", "reason": "Invalid demo options"}, status_code=400)

    @app.middleware("http")
    async def headers(request, call_next):
        response = await call_next(request)
        response.headers.update({"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'self'; connect-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors 'none'"})
        return response

    def snapshot():
        live = public_observations(observations / "state.json")
        heartbeat = live.get("heartbeat")
        live["worker_connected"] = heartbeat is not None and 0 <= time.time() - heartbeat < 15
        return dict(label=LABEL, test_only=test_only, live=live, matrix=matrix(saved),
                    evidence=evidence(saved), audit_events=audit_events(audit))

    @app.get("/")
    async def index():
        return FileResponse(HERE / "static/index.html")

    # Separate presentation endpoint; original dashboard and its API projections stay intact.
    @app.get("/story")
    async def story_page():
        return FileResponse(HERE / "static/story.html")

    @app.get("/api/story")
    async def story_snapshot():
        from .story import snapshot as story_data
        data = await asyncio.to_thread(story_data, saved, observations)
        data["test_only"] = test_only
        return data

    @app.get("/api/story/events")
    async def story_events(request: Request):
        async def stream():
            while not await request.is_disconnected():
                data = await story_snapshot()
                yield "data: " + json.dumps(data, separators=(",", ":")) + "\n\n"
                await asyncio.sleep(.4 if data["worker_status"] == "running" else 2)
        return StreamingResponse(stream(), media_type="text/event-stream")

    @app.get("/api/snapshot")
    async def get_snapshot():
        return await asyncio.to_thread(snapshot)

    @app.get("/api/red")
    async def red_only():
        live = await asyncio.to_thread(public_observations, observations / "state.json")
        fields = ("index", "status", "body_length", "ttfb", "total", "headers", "response")
        return {"requests": [{k: r[k] for k in fields} for r in live["requests"]]}

    @app.get("/api/events")
    async def events(request: Request):
        async def stream():
            previous = None
            while not await request.is_disconnected():
                current = json.dumps(await asyncio.to_thread(snapshot), separators=(",", ":"))
                if current != previous:
                    yield "data: " + current + "\n\n"
                    previous = current
                else:
                    yield ": heartbeat\n\n"
                await asyncio.sleep(2)
        return StreamingResponse(stream(), media_type="text/event-stream")

    @app.post("/api/jobs")
    async def submit_job(job: Job, request: Request):
        # No arbitrary commands, URLs, prompts, credentials or filesystem paths accepted.
        origin = request.headers.get("origin")
        if request.headers.get("x-demo-ui") != "1" or (origin and origin != str(request.base_url).rstrip("/")):
            return JSONResponse({"status": "rejected"}, status_code=403)
        if job.policy == "raw" and not test_only:
            return JSONResponse({"status": "rejected", "reason": "raw requires EVAL_MODE=1 (test-only)"}, status_code=403)
        live = await asyncio.to_thread(public_observations, observations / "state.json")
        if not live.get("heartbeat") or time.time() - live["heartbeat"] > 15 or live.get("matrix_active") or live["status"] == "running":
            return JSONResponse({"status": "NOT RUN", "reason": "Worker unavailable, busy, or timing matrix active"}, status_code=409)
        requests.mkdir(parents=True, exist_ok=True)
        if any(requests.glob("*.json")):
            return JSONResponse({"status": "NOT RUN", "reason": "A demo is already queued"}, status_code=409)
        job_id = uuid.uuid4().hex
        temporary = requests / (job_id + ".tmp")
        temporary.write_text(job.model_dump_json(), encoding="utf-8")
        temporary.replace(requests / (job_id + ".json"))
        return {"status": "queued"}

    return app


app = create_app()
