"""Operator only: score the latest session, then stop its dedicated stack."""
import argparse
import json
from pathlib import Path
import sys

from controller import ROOT, STATE, collect_metadata, compose, private_json, read_json, score_record, session_state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--guess", required=True, choices=["pineapple", "mango"])
    parser.add_argument("--session")
    parser.add_argument("--summary-file", type=Path)
    parser.add_argument("--keep-running", action="store_true")
    args = parser.parse_args()
    try:
        path, meta = session_state(args.session)
        if meta.get("scored"):
            raise ValueError("Session already scored; no duplicate trial appended")
        summary_path = (args.summary_file or Path(meta["workspace"]) / "final_guess.json").resolve()
        if not summary_path.is_relative_to(Path(meta["workspace"]).resolve()):
            raise ValueError("Agent summary must be inside that session's Red workspace")
        summary = summary_path.read_text(encoding="utf-8")[:10000] if summary_path.exists() else "No agent summary supplied"
        try:
            metrics = collect_metadata(meta)
        except Exception:
            metrics = None
        secret = read_json(path.parent / "secret.json")["secret"]
        record = score_record(meta, secret, args.guess, summary, metrics)
        if not summary_path.exists():
            record["protocol_valid"] = False
            record["issues"].append("Agent summary missing")
        results_path = ROOT / "agent_sessions.json"
        sessions = read_json(results_path) if results_path.exists() else []
        if any(s["session_id"] == record["session_id"] for s in sessions):
            raise ValueError("Session already present in agent_sessions.json")
        sessions.append(record)
        private_json(results_path, sessions)
        meta["scored"] = True
        private_json(path, meta)
        if not args.keep_running:
            try:
                stopped = compose(meta, ["down"], 45)
                if stopped.returncode:
                    print("Operator notice: session stack could not be stopped", file=sys.stderr)
            except Exception:
                print("Operator notice: stop the session stack manually", file=sys.stderr)
        print(json.dumps(record, indent=2))
        return 0
    except (OSError, ValueError, KeyError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
