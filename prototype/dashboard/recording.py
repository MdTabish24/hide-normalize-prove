"""Operator-side atomic writes; tolerate brief Windows reader/antivirus locks."""
import json
from pathlib import Path
import time
import uuid


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        temporary.write_text(json.dumps(value), encoding="utf-8")
        for attempt in range(6):
            try:
                temporary.replace(path)
                return True
            except PermissionError:
                time.sleep(.005 * (attempt + 1))
        return False  # Keep last valid file; next heartbeat retries instead of dying.
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except PermissionError:
            pass  # A locked temporary artifact is preferable to killing the worker.
