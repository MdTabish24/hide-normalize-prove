"""Run INSIDE red-client. Report actual observations, including failures honestly."""
import argparse
import ipaddress
import json
import os
from pathlib import Path
import socket
import struct
import uuid

import httpx

from common import PENDING


def resolves(name):
    try:
        return list({item[4][0] for item in socket.getaddrinfo(name, None, socket.AF_INET)})
    except OSError:
        return []


def connects(host, port):
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


def bridge_gateways():
    # Inspect the connected subnet's gateway too; lack of host DNS is not proof.
    addresses = []
    try:
        for line in Path("/proc/net/route").read_text().splitlines()[1:]:
            fields = line.split()
            if fields[1] == "00000000" and fields[2] != "00000000":
                addresses.append(socket.inet_ntoa(struct.pack("<I", int(fields[2], 16))))
            elif fields[1] != "00000000":
                network = socket.inet_ntoa(struct.pack("<I", int(fields[1], 16)))
                addresses.append(str(ipaddress.IPv4Address(network) + 1))
    except OSError:
        pass
    return addresses


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--blue-ip")
    parser.add_argument("--model-ip")
    parser.add_argument("--host-ip")
    args = parser.parse_args()
    results = []

    def record(name, passed):
        results.append((name, passed))
        print(f"{'PASS' if passed else 'FAIL'}  {name}", flush=True)

    for service in ("blue-defense", "model-mock"):
        record("Direct " + service + " blocked", not connects(service, 8000))
    for service, ip in (("Blue", args.blue_ip), ("model", args.model_ip)):
        if ip:
            record("Direct " + service + " IP blocked", not connects(ip, 8000))
    host_ips = resolves("host.docker.internal") + resolves("gateway.docker.internal")
    host_ips += bridge_gateways()
    if args.host_ip:
        host_ips.append(args.host_ip)
    # A resolvable host alias counts as exposure, even if chosen TCP ports refuse.
    record("Host aliases do not resolve", not resolves("host.docker.internal") and not resolves("gateway.docker.internal"))
    record("Host TCP probes blocked (80/443/8000)", not any(connects(ip, port) for ip in set(host_ips) for port in (80, 443, 8000)))
    record("External DNS lookup blocked", not resolves("example.com"))
    record("Internet IP probes blocked", not any(connects(ip, port) for ip, port in (("1.1.1.1", 443), ("8.8.8.8", 53))))
    record("Docker socket absent", not Path("/var/run/docker.sock").exists())
    with httpx.Client(base_url=os.getenv("GATEWAY_URL", "http://gateway:8000"), trust_env=False, timeout=15,
                      headers={"authorization": "Bearer " + os.environ["RED_TOKEN"]}) as client:
        response = client.post("/v1/defense", json={"trigger": "test"})
        record("Red defense request is generic", response.status_code == 202 and response.content == PENDING)
        run_id = "isolation-" + uuid.uuid4().hex[:12]
        response = client.post("/v1/submit", json={"run_id": run_id, "prompt": "Hello from the isolated Red client."})
        record("Gateway submit is 202 pending", response.status_code == 202 and response.content == PENDING)
    print("\nIsolation probe summary (local Docker prototype)")
    print(f"{'Check':<46} Result")
    for name, passed in results:
        print(f"{name:<46} {'PASS' if passed else 'FAIL'}")
    print(json.dumps({"passed": sum(p for _, p in results), "total": len(results), "run_id": run_id}))
    return 0 if all(p for _, p in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
