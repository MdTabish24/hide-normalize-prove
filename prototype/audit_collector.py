"""Private append/finish-only FastAPI service. No key or log retrieval API."""
import os
import secrets
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from audit_store import Collector


class Event(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    type: Literal["submit_received", "bucket_released", "defense_stored", "report_served", "run_finished"]
    run_id: str = Field(pattern="^[A-Za-z0-9_@-]{1,64}$")
    role: Literal["red", "blue", "evaluator"] | None
    bucket: float | None = Field(ge=0)
    timestamp: float = Field(ge=0)
    prompt_hash: str | None = Field(pattern="^[0-9a-f]{64}$")


class Finish(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: str = Field(pattern="^[A-Za-z0-9_@-]{1,64}$")
    audit_unavailable: bool = False


def create_app(settings=None):
    config = dict(os.environ if settings is None else settings)
    token = config["AUDIT_TOKEN"]
    if len(token) < 16:
        raise ValueError("A local collector token is required")
    collector = Collector(config.get("AUDIT_LOG_DIR", "/audit-logs"),
                          config.get("AUDIT_KEY_DIR", "/audit-keys"),
                          config.get("CHECKPOINT_DIR", "/checkpoints"))
    api = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    api.state.collector = collector

    def authorize(request: Request):
        if not secrets.compare_digest(request.headers.get("authorization", ""), "Bearer " + token):
            raise HTTPException(403)

    @api.post("/append", dependencies=[Depends(authorize)])
    def append(event: Event):
        collector.append(event.model_dump())
        return {"ok": True}

    @api.post("/finish", dependencies=[Depends(authorize)])
    def finish(body: Finish):
        collector.finish(body.run_id, body.audit_unavailable)
        return {"ok": True}

    return api


def factory():
    return create_app()
