"""Container hardening check of the running Docker stack (PARAMS v11). Reads `docker inspect` only; changes nothing.

    python -m eval.hardening_check          # writes eval/output/hardening/results.json

Checks what THIS prototype controls about container escape and shared hardware: it does NOT test kernel exploits, runtime bugs or GPU side channels.
Label: local Docker stack (Docker Desktop).
"""
import json
from pathlib import Path
import subprocess

OUTPUT = Path("eval/output/hardening/results.json")
NETWORKS_THAT_MUST_BE_INTERNAL = ("red-net", "blue-net", "model-net", "audit-net")


def run(*args):
    return subprocess.run(args, capture_output=True, text=True, errors="replace", timeout=60).stdout


def inspect_all():
    names = [n for n in run("docker", "ps", "--format", "{{.Names}}").split() if n]
    if not names:
        return []
    return json.loads(run("docker", "inspect", *names))


def check(container):
    host, config = container["HostConfig"], container["Config"]
    mounts = container.get("Mounts") or []
    rows = dict(
        privileged=bool(host.get("Privileged")) is False,
        cap_drop_all="ALL" in (host.get("CapDrop") or []),
        no_new_privileges=any("no-new-privileges" in s for s in (host.get("SecurityOpt") or [])),
        read_only_rootfs=bool(host.get("ReadonlyRootfs")),
        non_root_user=(config.get("User") or "") not in ("", "0", "root", "0:0"),
        no_docker_socket=not any("docker.sock" in (m.get("Source") or "") + (m.get("Destination") or "") for m in mounts),
        no_host_pid_or_net=host.get("PidMode") in ("", None) and host.get("NetworkMode") != "host",
        memory_limited=bool(host.get("Memory")),
        pids_limited=bool(host.get("PidsLimit")),
        cpu_limited=bool(host.get("NanoCpus") or host.get("CpuQuota") or host.get("CpusetCpus")),
        no_published_ports_except_localhost=all(b.get("HostIp") in ("127.0.0.1", "::1") for binds in (host.get("PortBindings") or {}).values() for b in (binds or [])),
    )
    return container["Name"].lstrip("/"), rows


def networks():
    out = {}
    for name in run("docker", "network", "ls", "--format", "{{.Name}}").split():
        if any(name.endswith(n) for n in NETWORKS_THAT_MUST_BE_INTERNAL):
            data = json.loads(run("docker", "network", "inspect", name))[0]
            out[name] = dict(internal=bool(data.get("Internal")))
    return out


def main():
    containers = inspect_all()
    if not containers:
        raise SystemExit("No running containers: start the stack first (docker compose up -d).")
    results = dict(check(c) for c in containers)
    nets = networks()
    summary = {check_name: sum(1 for r in results.values() if r[check_name]) for check_name in next(iter(results.values()))}
    out = dict(label="local Docker stack (Docker Desktop)", params_version=11, containers=len(results), per_container=results, networks=nets, passed_per_check=summary,
               not_tested="kernel and container-runtime exploits, hypervisor/hardware and shared-GPU side channels, a compromised gateway or collector")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(dict(containers=len(results), passed_per_check=summary, networks=nets), indent=1))
    for name, rows in results.items():
        failed = [k for k, v in rows.items() if not v]
        print(f"{name}: {'all checks passed' if not failed else 'FAILED: ' + ', '.join(failed)}")


if __name__ == "__main__":
    main()
