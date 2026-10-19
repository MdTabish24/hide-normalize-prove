"""Tamper with COPIES only. No signing key import, mount or signature generation."""
import argparse
import copy
import json
from pathlib import Path
import shutil
import tempfile

from audit_format import ZERO_HASH, canonical, line, record
from verify_audit import verify


def rehash_without_key(records):
    output, previous = b"", ZERO_HASH
    for seq, value in enumerate(records, 1):
        event = {k: v for k, v in value.items() if k not in ("seq", "prev_hash", "current_hash")}
        if event["type"] == "complete":
            event.update(count=seq, bytes=0)
        while True:
            updated = record(event, seq, previous)
            size = len(output) + len(line(updated))
            if event["type"] != "complete" or event["bytes"] == size:
                break
            event["bytes"] = size
        output += line(updated)
        previous = updated["current_hash"]
    return output


def tamper_cases(data, checkpoint_data):
    records = [json.loads(raw) for raw in data.splitlines()]
    if len(records) < 5:
        raise ValueError("Use a finished run with at least five records")
    encode = lambda rows: b"".join(line(row) for row in rows)
    edited = copy.deepcopy(records)
    edited[0]["role"] = "blue" if edited[0]["role"] != "blue" else "red"
    reordered = records.copy()
    reordered[0], reordered[1] = reordered[1], reordered[0]
    rehashed = rehash_without_key(edited)
    # The attacker updates the claimed checkpoint head/count/bytes, retaining
    # the old signature. Recomputed hashes alone cannot authenticate a new head.
    forged_checkpoint = json.loads(checkpoint_data)
    forged_checkpoint.update(head_hash=json.loads(rehashed.splitlines()[-1])["current_hash"],
                             count=len(records), bytes=len(rehashed))
    changed_count = copy.deepcopy(edited)
    changed_count[-1]["count"] -= 1
    return {
        "unmodified": (data, checkpoint_data),
        "edit one event": (encode(edited), checkpoint_data),
        "delete middle event": (encode(records[:2] + records[3:]), checkpoint_data),
        "delete last 3 events": (encode(records[:-3]), checkpoint_data),
        "reorder two events": (encode(reordered), checkpoint_data),
        "duplicate/replay event": (encode(records[:2] + [records[0]] + records[2:]), checkpoint_data),
        "rehash without signing key": (rehashed, canonical(forged_checkpoint) + b"\n"),
        "edit log and stored count": (encode(changed_count), checkpoint_data),
    }


def run_demo(log, checkpoint, public_key, run_id):
    results = []
    with tempfile.TemporaryDirectory(prefix="audit-tamper-") as directory:
        directory = Path(directory)
        # Never copy the signing-key directory or mutate any source artifact.
        shutil.copyfile(public_key, directory / "public_key.bin")
        cases = tamper_cases(Path(log).read_bytes(), Path(checkpoint).read_bytes())
        print(f"{'Case':<32} {'Result':<8} First failing reason / index")
        for name, (data, checkpoint_data) in cases.items():
            copied_log, copied_checkpoint = directory / "copy.jsonl", directory / "checkpoint.json"
            copied_log.write_bytes(data)
            copied_checkpoint.write_bytes(checkpoint_data)
            valid, reason, index = verify(copied_log, copied_checkpoint, directory / "public_key.bin", run_id)
            results.append((name, valid, reason, index))
            print(f"{name:<32} {'VALID' if valid else 'INVALID':<8} {reason} / {index}")
    print("Local integrity demo only. Publication also requires clean gateway audit status.")
    print("A replayed checkpoint plus matching old log needs an independent freshness witness.")
    print("Events omitted before collection are undetectable; the collector is trusted.")
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--logs", default="/audit-logs")
    parser.add_argument("--checkpoints", default="/checkpoints")
    args = parser.parse_args()
    from re import fullmatch
    if not fullmatch(r"[A-Za-z0-9_@-]{1,64}", args.run_id):
        parser.error("Invalid run ID")
    try:
        results = run_demo(Path(args.logs) / (args.run_id + ".jsonl"),
                           Path(args.checkpoints) / (args.run_id + ".json"),
                           Path(args.checkpoints) / "public_key.bin", args.run_id)
    except (OSError, ValueError):
        print("INVALID: source audit artifacts missing, too short or malformed")
        return 1
    return 0 if all(valid == (name == "unmodified") for name, valid, _, _ in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
