"""DELIBERATELY WEAK Blue service for a positive control (PARAMS v14): same decisions as blue.py, but it writes every prompt and the rule to a log file,
the way a careless service might. Used only by eval/weak_controls.py to check that the log scan of attack 8 can find a plaintext leak."""
import os

from fastapi import Depends, FastAPI

from blue import Check
from common import service_auth

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)


@app.post("/check", dependencies=[Depends(service_auth)])
async def check(body: Check):
    with open(os.environ["NAIVE_BLUE_LOG"], "a", encoding="utf-8") as stream:
        stream.write(f"{body.filter.trigger}\t{body.prompt}\n")
    return {"allowed": body.filter.trigger.casefold() not in body.prompt.casefold()}
