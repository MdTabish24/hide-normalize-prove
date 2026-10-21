"""Read-only verifier. VALID requires signed integrity AND gateway availability."""
import argparse
import json
from pathlib import Path
import sqlite3
from contextlib import closing

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from audit_format import InvalidAudit, canonical, inspect_chain


def verify(log, checkpoint, public_key, run_id, gateway_db=None):
    try:
        # Separate reasons (diagnosis only; the verdict is unchanged): a missing log is a delivery failure,
        # a missing checkpoint means the chain never reached `complete`, neither is a cryptographic failure.
        try:
            data = Path(log).read_bytes()
        except FileNotFoundError:
            raise InvalidAudit("log file missing") from None
        records = inspect_chain(data, run_id)
        try:
            checkpoint = json.loads(Path(checkpoint).read_bytes())
        except FileNotFoundError:
            raise InvalidAudit("checkpoint missing (chain never reached complete)") from None
        if set(checkpoint) != {"run_id", "count", "bytes", "head_hash", "signature"}:
            raise InvalidAudit("checkpoint fields")
        # Check signature before comparing checkpoint/log: a rewritten checkpoint
        # cannot hide a recomputed chain without the collector's private key.
        try:
            key = Ed25519PublicKey.from_public_bytes(Path(public_key).read_bytes())
        except FileNotFoundError:
            raise InvalidAudit("public key missing") from None
        signed = {k: v for k, v in checkpoint.items() if k != "signature"}
        try:
            key.verify(bytes.fromhex(checkpoint["signature"]), canonical(signed))
        except (InvalidSignature, ValueError, TypeError):
            raise InvalidAudit("checkpoint signature invalid") from None
        if checkpoint["run_id"] != run_id:
            raise InvalidAudit("checkpoint run ID mismatch")
        final = records[-1]
        if final["type"] != "complete":
            raise InvalidAudit("missing terminal complete record", len(records))
        if checkpoint["count"] != len(records) or checkpoint["count"] != final["count"]:
            raise InvalidAudit("checkpoint event count mismatch", len(records))
        if checkpoint["bytes"] != len(data) or checkpoint["bytes"] != final["bytes"]:
            raise InvalidAudit("checkpoint byte length mismatch", len(records))
        if checkpoint["head_hash"] != final["current_hash"]:
            raise InvalidAudit("signed checkpoint head mismatch", len(records))
        if any(r.get("audit_unavailable", False) for r in records):
            raise InvalidAudit("audit_unavailable recorded", len(records))
        if gateway_db is not None:
            # The gateway's audit queue lives next to its run database.
            # Read-only mode does not create a missing database or update it.
            queue = Path(gateway_db).with_name("audit_queue.sqlite")
            uri = queue.resolve().as_uri() + "?mode=ro"
            try:
                with closing(sqlite3.connect(uri, uri=True)) as db:
                    status = db.execute("SELECT unavailable FROM audit_state WHERE run_id=?", (run_id,)).fetchone()
                    pending = db.execute("SELECT COUNT(*) FROM audit_outbox WHERE run_id=?", (run_id,)).fetchone()[0]
            except sqlite3.Error:
                raise InvalidAudit("gateway audit status unreadable") from None
            if status is None:
                raise InvalidAudit("gateway audit status missing")
            if status[0]:
                raise InvalidAudit("gateway marks audit_unavailable")
            if pending:
                raise InvalidAudit("gateway audit events still pending")
        return True, "VALID", 0
    except InvalidAudit as error:
        return False, error.reason, error.index
    except (OSError, ValueError, TypeError, KeyError, sqlite3.Error):
        return False, "missing or unreadable audit/checkpoint/key/status file", 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--logs", default="/audit-logs")
    parser.add_argument("--checkpoints", default="/checkpoints")
    parser.add_argument("--public-key", help="Independently pinned key; default is the local checkpoint volume's key")
    parser.add_argument("--gateway-db", default="/gateway-data/runs.sqlite")
    args = parser.parse_args()
    # Treat IDs as identifiers, never arbitrary filesystem paths.
    from re import fullmatch
    if not fullmatch(r"[A-Za-z0-9_@-]{1,64}", args.run_id):
        print("INVALID: invalid run ID (index 0)")
        return 1
    valid, reason, index = verify(Path(args.logs) / (args.run_id + ".jsonl"),
                                  Path(args.checkpoints) / (args.run_id + ".json"),
                                  args.public_key or Path(args.checkpoints) / "public_key.bin",
                                  args.run_id, args.gateway_db)
    print("VALID" if valid else f"INVALID: {reason} (index {index})")
    return 0 if valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
