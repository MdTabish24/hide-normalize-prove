"""Generate local demo credentials, never print them or replace an existing file."""
import argparse
import secrets
from pathlib import Path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fast", action="store_true")
    parser.add_argument("--add-audit", action="store_true", help="Add only a missing local audit token to an existing .env")
    args = parser.parse_args()
    path = Path(__file__).with_name(".env")
    if args.add_audit:
        existing = path.read_text(encoding="utf-8")
        if any(line.startswith("AUDIT_TOKEN=") for line in existing.splitlines()):
            print("Local audit token already present; unchanged.")
        else:
            with path.open("a", encoding="utf-8") as file:
                file.write(("" if existing.endswith("\n") else "\n") + "AUDIT_TOKEN=" + secrets.token_hex(32) + "\n")
            print("Added local audit token; existing credentials unchanged.")
        raise SystemExit(0)
    values = {name: secrets.token_hex(32) for name in (
        "RED_TOKEN", "BLUE_TOKEN", "EVALUATOR_TOKEN", "GATEWAY_KEY",
        "BLUE_SERVICE_TOKEN", "MODEL_SERVICE_TOKEN", "AUDIT_TOKEN")}
    values.update(BUCKETS="0.3,0.6,0.9" if args.fast else "3,6,9",
                  HIT_SECONDS="0.01" if args.fast else "0.3",
                  MISS_SECONDS="0.08" if args.fast else "2.0", JITTER_SECONDS="0.002" if args.fast else "0.02")
    with path.open("x", encoding="utf-8") as file:
        file.write("\n".join(f"{key}={value}" for key, value in values.items()) + "\n")
    path.chmod(0o600)
    print("Created local .env (ignored). Keep its gateway key for encrypted-data restarts.")
