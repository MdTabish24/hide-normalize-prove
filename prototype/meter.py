"""Opt-in 3-state feedback meter (LOW / STABLE / IMPROVING): pure logic shared by the gateway and the simulations.

Red never sees a per-prompt result or the exact movement. See PARAMS.md for the fixed parameters and definitions.
"""
from dataclasses import dataclass
import hashlib
import hmac
import json

STATES = ("LOW", "STABLE", "IMPROVING")
EPS = 1e-9


@dataclass(frozen=True)
class Params:
    batch: int = 10
    delta_up: float = 0.30
    delta_down: float = 0.30
    inner: float = 0.10
    noise_q: float = 0.0
    reads_per_run: int = 3
    reads_total: int = 12

    def __post_init__(self):
        if not 2 <= self.batch <= 100:
            raise ValueError("METER_BATCH must be 2..100")
        if not (0 < self.delta_up <= 1 and 0 < self.delta_down <= 1):
            raise ValueError("METER deltas must be in (0, 1]")
        if not 0 <= self.inner < min(self.delta_up, self.delta_down):
            raise ValueError("METER_INNER must be at least 0 and below both deltas")
        if not 0 <= self.noise_q <= 0.5:
            raise ValueError("METER_NOISE_Q must be 0..0.5")
        if self.reads_per_run < 0 or self.reads_total < 0:
            raise ValueError("Read budgets must not be negative")

    @classmethod
    def from_config(cls, config):
        def number(name, default, kind=float):
            return kind(config.get(name) or default)
        return cls(batch=number("METER_BATCH", 10, int), delta_up=number("METER_DELTA_UP", 0.30),
                   delta_down=number("METER_DELTA_DOWN", 0.30), inner=number("METER_INNER", 0.10),
                   noise_q=number("METER_NOISE_Q", 0.0), reads_per_run=number("METER_READS_PER_RUN", 3, int),
                   reads_total=number("METER_READS_TOTAL", 12, int))


def transition(state, reference, score, params):
    """Hysteresis. Returns (new_state, new_reference); the reference only moves when the state changes or re-centres."""
    if score >= reference + params.delta_up - EPS:
        return "IMPROVING", score
    if score <= reference - params.delta_down + EPS:
        return "LOW", score
    if state in ("IMPROVING", "LOW") and abs(score - reference) <= params.inner + EPS:
        return "STABLE", score
    return state, reference


def batch_digest(key, items):
    """Keyed hash of the SORTED batch content (prompt hash, safe flag): same content, same digest, any order."""
    payload = json.dumps(sorted([str(h or ""), int(bool(s))] for h, s in items), separators=(",", ":")).encode()
    return hmac.new(key, b"meter-batch|" + payload, hashlib.sha256).hexdigest()


def keyed_unit(key, label, digest):
    return int(hmac.new(key, label + digest.encode(), hashlib.sha256).hexdigest()[:8], 16) / 0x100000000


def publish(state, digest, key, params):
    """Optional noise arm: with probability q publish a different state, keyed to the batch content (repeat-proof)."""
    if params.noise_q <= 0 or keyed_unit(key, b"meter-noise|", digest) >= params.noise_q:
        return state
    others = [s for s in STATES if s != state]
    return others[int(keyed_unit(key, b"meter-pick|", digest) * len(others))]


def body(state):
    return json.dumps({"meter": state}, separators=(",", ":")).encode().ljust(64, b" ")
