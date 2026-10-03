"""Verify the local audit demo against its checkpoint. No API calls."""
import argparse
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from experiment import verify_audit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log", default="demo_audit/events.jsonl")
    parser.add_argument("--checkpoint", default="demo_audit/checkpoint.json")
    parser.add_argument("--public-key", default="demo_audit/public_key.bin")
    parser.add_argument("--run-id", default="demo-run")
    args = parser.parse_args()
    try:
        key = Ed25519PublicKey.from_public_bytes(Path(args.public_key).read_bytes())
        valid = verify_audit(Path(args.log), Path(args.checkpoint), key, args.run_id)
    except (OSError, ValueError):
        valid = False
    print(f"AUDIT {'VALID' if valid else 'INVALID'} (local PoC)")
    print("Production requires an independently trusted public key and checkpoint.")
    return 0 if valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
