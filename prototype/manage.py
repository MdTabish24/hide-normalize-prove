"""Trusted operator helper, run on the host. Never copy evaluator/Blue tokens to Red."""
import argparse
from pathlib import Path

import httpx


def env_file():
    return dict(line.split("=", 1) for line in Path(__file__).with_name(".env").read_text().splitlines()
                if line.strip() and not line.startswith("#"))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["configure", "finish", "report"])
    parser.add_argument("--run-id", default="demo-run")
    parser.add_argument("--trigger", default="pineapple")
    args = parser.parse_args()
    config = env_file()
    role = {"configure": "BLUE", "finish": "EVALUATOR", "report": "RED"}[args.action]
    with httpx.Client(base_url="http://127.0.0.1:8000", trust_env=False, timeout=15,
                      headers={"authorization": "Bearer " + config[role + "_TOKEN"]}) as client:
        if args.action == "configure":
            response = client.post("/v1/defense", json={"trigger": args.trigger})
        elif args.action == "finish":
            response = client.post(f"/v1/run/{args.run_id}/finish")
        else:
            response = client.get(f"/v1/run/{args.run_id}/report")
    print(response.status_code, response.text.strip())
    if args.action == "configure":
        print("Generic acknowledgement only; configure before starting runs. Check operator metadata/tests for success.")
