"""Canonical, byte-exact audit format; contains no signing key or network code."""
import hashlib
import json

ZERO_HASH = "0" * 64
META = {"type", "run_id", "role", "bucket", "timestamp", "prompt_hash"}
# Records written since Round 2 also carry gw_seq; older logs stay verifiable.
SEQUENCED = META | {"gw_seq"}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def record(event, seq, previous):
    value = dict(event, seq=seq, prev_hash=previous)
    value["current_hash"] = hashlib.sha256(canonical(value)).hexdigest()
    return value


def line(value):
    return canonical(value) + b"\n"


class InvalidAudit(ValueError):
    def __init__(self, reason, index=0):
        self.reason, self.index = reason, index
        super().__init__(f"{reason} (index {index})")


def inspect_chain(data, run_id):
    """Indices are 1-based records; 0 means file/checkpoint/status failure."""
    previous, records, byte_count = ZERO_HASH, [], 0
    for index, raw in enumerate(data.splitlines(keepends=True), 1):
        try:
            value = json.loads(raw)
            required = (SEQUENCED if "gw_seq" in value else META) | {"seq", "prev_hash", "current_hash"}
            if value.get("type") == "complete":
                required |= {"count", "bytes", "audit_unavailable"}
            if set(value) != required or (value.get("gw_seq") is not None and type(value["gw_seq"]) is not int):
                raise InvalidAudit("record fields", index)
            if raw != line(value):
                raise InvalidAudit("noncanonical record or missing newline", index)
            if value["run_id"] != run_id:
                raise InvalidAudit("run ID mismatch", index)
            if type(value["seq"]) is not int or value["seq"] != index:
                raise InvalidAudit("sequence discontinuity or replay", index)
            if value["prev_hash"] != previous:
                raise InvalidAudit("previous hash mismatch", index)
            unsigned = {k: v for k, v in value.items() if k != "current_hash"}
            if hashlib.sha256(canonical(unsigned)).hexdigest() != value["current_hash"]:
                raise InvalidAudit("event hash mismatch", index)
            byte_count += len(raw)
            if value["type"] == "complete":
                if type(value["count"]) is not int or value["count"] != index:
                    raise InvalidAudit("complete event count mismatch", index)
                if type(value["bytes"]) is not int or value["bytes"] != byte_count:
                    raise InvalidAudit("complete byte length mismatch", index)
                if type(value["audit_unavailable"]) is not bool:
                    raise InvalidAudit("invalid audit availability flag", index)
            records.append(value)
            previous = value["current_hash"]
        except InvalidAudit:
            raise
        except (ValueError, TypeError, AttributeError, KeyError):
            raise InvalidAudit("malformed record", index) from None
    if not records:
        raise InvalidAudit("empty log")
    return records
