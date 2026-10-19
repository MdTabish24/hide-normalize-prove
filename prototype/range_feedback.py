"""Production feedback generator, shared by gateway and Monte Carlo analysis."""
import hashlib
import hmac
import json
import secrets

from common import RANGE_WIDTH


def probe_digest(hashes):
    # Canonical multiset of prompt hashes: never store plaintext probes on disk.
    return hashlib.sha256(json.dumps(sorted(hashes), separators=(",", ":")).encode()).hexdigest()


def generate_range(safe_count, total, *, mode="run", key, identity, probes, version,
                   randbelow=None):
    if not 0 <= safe_count <= total <= 100 or mode not in {"run", "probeset"}:
        raise ValueError("Invalid feedback inputs")
    width = min(RANGE_WIDTH, total)
    low, high = max(0, safe_count - width), min(safe_count, total - width)
    size = high - low + 1
    if mode == "run":
        offset = (randbelow or secrets.randbelow)(size)
    else:
        payload = json.dumps(["range-v1", identity, probes, version], separators=(",", ":")).encode()
        # Rejection sampling avoids modulo bias. Seed/key never leave this function.
        counter, ceiling = 0, (1 << 256) - ((1 << 256) % size)
        while True:
            value = int.from_bytes(hmac.new(key, payload + counter.to_bytes(4, "big"), hashlib.sha256).digest(), "big")
            if value < ceiling:
                offset = value % size
                break
            counter += 1
    lower = low + offset
    return {"status": "complete", "safe_range": [lower, lower + width]}
