"""Private keyword filter; reachable only on blue-net."""
from fastapi import Depends, FastAPI
from pydantic import BaseModel, ConfigDict, Field

from common import service_auth


app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)


class Filter(BaseModel):
    model_config = ConfigDict(extra="forbid")
    trigger: str = Field(min_length=1, max_length=128)


class Check(BaseModel):
    prompt: str = Field(max_length=4096)
    filter: Filter


@app.post("/check", dependencies=[Depends(service_auth)])
async def check(body: Check):
    # No persistent plaintext file. The gateway supplies the sealed configuration
    # after decryption; only this private service evaluates the filter.
    return {"allowed": body.filter.trigger.casefold() not in body.prompt.casefold()}
