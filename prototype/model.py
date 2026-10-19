"""Mock prefix cache. No real model, key or internet request."""
import asyncio
import hashlib
import os
import random
import math

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from common import service_auth


app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
cache = set()


class Generate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: str = Field(pattern="^(red|blue)$")
    run_id: str = Field(pattern="^[A-Za-z0-9_-]{1,64}$")
    prompt: str = Field(max_length=4096)
    sim_delay: object = None


@app.post("/generate", dependencies=[Depends(service_auth)])
async def generate(body: Generate):
    # Hash the first 32 characters as a deliberately simple simulated prefix.
    prefix = hashlib.sha256(body.prompt[:32].encode()).digest()
    key = (body.role, body.run_id, prefix)
    if os.getenv("EVAL_MODE") == "1" and os.getenv("CACHE_NAMESPACE") == "off":
        key = (prefix,)  # Evaluation-only negative control: one cache shared by all runs.
    hit = key in cache
    delay = float(os.getenv("HIT_SECONDS", "0.3") if hit else os.getenv("MISS_SECONDS", "2.0"))
    if os.getenv("EVAL_MODE") == "1" and body.sim_delay is not None:
        if type(body.sim_delay) not in (int, float) or not math.isfinite(body.sim_delay) or not 0 <= body.sim_delay <= 30:
            raise HTTPException(422)
        delay = body.sim_delay
    await asyncio.sleep(delay + random.uniform(0, float(os.getenv("JITTER_SECONDS", "0.02"))))
    cache.add(key)
    return {"answer": "Dummy answer."}
