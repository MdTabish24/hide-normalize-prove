"""Small shared protocol. Values mirror experiment.py; no ML/API imports."""
import os
import secrets

from fastapi import HTTPException, Request
from fastapi.responses import Response


PENDING = b'{"status":"pending"}'.ljust(64, b" ")
HEADERS = {"content-type": "application/json", "content-length": "64"}
REPORT_BUDGET = 2
RANGE_WIDTH = 12
MAX_ATTEMPTS_PER_RUN = 100


def envelope(body=PENDING):
    assert len(body) == 64
    return Response(body, status_code=202, headers=HEADERS)


def service_auth(request: Request):
    expected = os.environ["SERVICE_TOKEN"]
    supplied = request.headers.get("authorization", "")
    if not secrets.compare_digest(supplied, "Bearer " + expected):
        raise HTTPException(403)
