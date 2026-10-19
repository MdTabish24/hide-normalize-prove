"""Explicit host operator: tiny local HTTP demos, never a matrix rerun.

The UI container has no tokens, Docker socket or gateway route. Only this host
process can execute the three fixed scenarios. It never reads .env files.
"""
import argparse
import asyncio
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import random
import re
import subprocess
import tempfile
import time
import uuid

from .app import Job
from .data import ISOLATION_CASES, read_json
from .recording import atomic_json

ROOT = Path(__file__).resolve().parents[1]


def matrix_active():
    """Fail closed if process enumeration fails; never print process arguments."""
    try:
        if os.name == "nt":
            script = r"""$p=Get-CimInstance Win32_Process -Filter "Name LIKE 'python%'"; @($p | Where-Object { $_.CommandLine -match '-m\s+eval\.(matrix|run)(\s|$)' }).Count"""
            result = subprocess.run(["powershell", "-NoProfile", "-Command", script], capture_output=True, text=True, timeout=8)
            return result.returncode != 0 or int(result.stdout.strip()) > 0
        for path in Path("/proc").glob("[0-9]*/cmdline"):
            try:
                command = path.read_bytes().replace(b"\0", b" ").decode(errors="replace")
                if re.search(r"-m\s+eval\.(matrix|run)(\s|$)", command):
                    return True
            except (OSError, PermissionError):
                pass
        return not Path("/proc").exists()
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return True


class Worker:
    def __init__(self, runtime):
        self.runtime = Path(runtime)
        for name in ("requests", "observations"):
            (self.runtime / name).mkdir(parents=True, exist_ok=True)
        self.state = dict(status="idle", events=[], requests=[], scenarios={}, started=time.time())
        old = read_json(self.runtime / "observations/state.json")
        for key in ("events", "requests", "scenarios", "started", "accuracy", "policy", "report", "audit_verified"):
            if key in old:
                self.state[key] = old[key]

    def save(self):
        self.state["heartbeat"] = time.time()
        path = self.runtime / "observations/state.json"
        return atomic_json(path, self.state)

    def emit(self, kind, index=None):
        events = self.state["events"]
        events.append(dict(kind=kind, index=index, seq=len(events) + 1))
        self.save()

    async def traffic(self, job):
        from eval.live import Lab
        from eval.run import features, wilson
        from sklearn.tree import DecisionTreeClassifier
        # Predeclared tiny sample: 4 train + 4 held-out groups, 2 HTTP requests each.
        # A/B receive the same probes. Run IDs, ground truth and rule names are NOT features.
        self.state.update(events=[], requests=[], accuracy=None, report=None, policy=job.policy, started=time.time())
        groups = [(split, world, i) for split in ("train", "test") for world in (0, 1) for i in range(2)]
        rng = random.Random(7391)
        groups = [g for split in ("train", "test") for g in rng.sample([g for g in groups if g[0] == split], 4)]
        if job.secret == "B":
            groups = [(s, 1 - w, i) for s, w, i in groups]
        with tempfile.TemporaryDirectory(prefix="hnp-dashboard-") as directory:
            async with Lab(directory, scale=0.1, policy=job.policy, audit=True) as lab:
                training, correct, tests, run_ids = [], 0, 0, {0: [], 1: []}
                attacker = DecisionTreeClassifier(max_depth=3, random_state=7391)
                for split, secret, group in groups:
                    world, obs, rows = lab.worlds[secret], [], []
                    # Secrets never enter the feature vector or emitted event payload.
                    for prompt in ("pineapple orchard cloud", "neutral orchard cloud"):
                        idx = len(self.state["requests"]) + 1
                        rid = "dash-" + uuid.uuid4().hex
                        self.emit("sent", idx)
                        start, first, body = time.perf_counter(), None, bytearray()
                        async with world.client.stream("POST", "/v1/submit", headers=world.auth("red"),
                                json={"run_id": rid, "prompt": prompt}) as response:
                            headers = sorted(response.headers.multi_items())
                            async for chunk in response.aiter_raw():
                                if first is None:
                                    first = time.perf_counter() - start
                                body.extend(chunk)
                        total = time.perf_counter() - start
                        value = json.loads(body)
                        row = dict(index=idx, status=response.status_code, headers=headers, body_length=len(body),
                                   ttfb=first if first is not None else total, total=total,
                                   response="pending" if value.get("status") == "pending" else "NOT RUN",
                                   world=secret, split=split)
                        self.state["requests"].append(row)
                        self.emit("response", idx)
                        obs.append(dict(row, header_fingerprint=hashlib.sha256(json.dumps(headers, separators=(",", ":")).encode()).hexdigest()))
                        rows.append((rid, row))
                        run_ids[secret].append(rid)
                    # Finish outside submit measurements; query actual gateway state as operator.
                    await asyncio.gather(*(world.finish(rid) for rid, _ in rows))
                    truth = lab.outcomes(secret, [rid for rid, _ in rows])
                    for rid, row in rows:
                        _, row["allowed"], row["cancelled"] = truth[rid]
                        self.emit("evaluation", row["index"])
                    vector = features(obs, lab.buckets)
                    if split == "train":
                        training.append((vector, secret))
                        if len(training) == 4:
                            attacker.fit([x for x, _ in training], [y for _, y in training])
                    else:
                        tests += 1
                        correct += int(attacker.predict([vector])[0] == secret)
                        train_accuracy = float(attacker.score([x for x, _ in training], [y for _, y in training]))
                        self.state["accuracy"] = dict(correct=correct, n=tests, train_n=4, interval=wilson(correct, tests),
                                                      train_accuracy=train_accuracy, gap=train_accuracy - correct / tests)
                        self.save()
                # A real final report, stable repeat and budget-denied third read.
                reports = [await world.report(rows[-1][0]) for _ in range(3)]
                self.state["report"] = dict(safe_range=reports[0].get("safe_range"),
                    repeat_equal=reports[0] == reports[1], third_pending=reports[2].get("status") == "pending")
                audit = await lab.audit_check(run_ids, drain_seconds=5)
                self.state["audit_verified"] = {"valid": audit["valid"], "runs": audit["runs"]}
                self.emit("audit")

    async def audit(self):
        from eval.live import Lab
        from demo_audit_tamper import run_demo
        with tempfile.TemporaryDirectory(prefix="hnp-dashboard-audit-") as directory:
            async with Lab(directory, scale=0.03, policy="bucket_hard", audit=True) as lab:
                rid = "dash-audit-" + uuid.uuid4().hex
                for prompt in ("neutral orchard", "neutral river"):
                    await lab.worlds[0].observe(rid, prompt)
                await lab.worlds[0].finish(rid)
                checked = await lab.audit_check({0: [rid]}, drain_seconds=5)
                if checked["valid"] != 1:
                    self.state["scenarios"]["audit"] = dict(status="FAIL", rows=[])
                    return
                root = Path(directory)
                with contextlib.redirect_stdout(io.StringIO()):
                    results = run_demo(root / f"audit-logs-0/{rid}.jsonl", root / f"checkpoints-0/{rid}.json",
                                       root / "checkpoints-0/public_key.bin", rid)
                self.state["scenarios"]["audit"] = dict(
                    status="PASS" if all(valid == (name == "unmodified") for name, valid, _, _ in results) else "FAIL",
                    rows=[dict(name=name, result="VALID" if valid else "INVALID") for name, valid, _, _ in results])

    def isolation(self):
        """Only an explicit host operator action may call Docker; no stack startup."""
        def docker(*args, allow_failure=False):
            result = subprocess.run(["docker", *args], cwd=ROOT, capture_output=True, text=True, timeout=55)
            if result.returncode and not allow_failure:
                raise RuntimeError("Docker command unavailable")
            return result.stdout

        def container(name):
            # Labels avoid Compose's automatic .env loading entirely.
            ids = docker("ps", "--filter", "label=com.docker.compose.project=" + os.getenv("COMPOSE_PROJECT_NAME", "hide-normalize-prove"),
                         "--filter", "label=com.docker.compose.service=" + name, "--format", "{{.ID}}").splitlines()
            if len(ids) != 1 or not re.fullmatch(r"[a-f0-9]+", ids[0]):
                raise RuntimeError("Stack unavailable or ambiguous")
            return ids[0]
        ips = []
        for name in ("blue-defense", "model-mock"):
            value = docker("inspect", "--format", "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}", container(name)).strip()
            if not re.fullmatch(r"[0-9.]+", value):
                raise RuntimeError("IP unavailable")
            ips.append(value)
        output = docker("exec", container("red-client"), "python", "demo_isolation.py", "--blue-ip", ips[0], "--model-ip", ips[1], allow_failure=True)
        rows = []
        for name in ISOLATION_CASES:
            match = re.search(r"^(PASS|FAIL)\s+" + re.escape(name) + r"\s*$", output, re.M)
            rows.append(dict(name=name, result=match[1] if match else "NOT RUN"))
        status = "NOT RUN" if all(r["result"] == "NOT RUN" for r in rows) else "PASS" if all(r["result"] == "PASS" for r in rows) else "FAIL"
        self.state["scenarios"]["isolation"] = dict(status=status, rows=rows)

    async def execute(self, job):
        self.state["matrix_active"] = await asyncio.to_thread(matrix_active)
        if self.state["matrix_active"] or (job.policy == "raw" and os.getenv("EVAL_MODE") != "1"):
            self.state["status"] = "blocked"
            self.save()
            return
        self.state["status"] = "running"
        self.save()
        try:
            if job.action == "story":
                from .story_run import run_story
                await run_story(self.runtime / "observations/story.json", job.policy, self.save)
            elif job.action == "traffic":
                await self.traffic(job)
            elif job.action == "audit":
                await self.audit()
            else:
                await asyncio.to_thread(self.isolation)
            self.state["status"] = "complete"
        except Exception:
            # Exceptions/commands can contain private paths or data; do not publish them.
            self.state["status"] = "failed"
            if job.action in ("isolation", "audit"):
                self.state["scenarios"][job.action] = dict(status="NOT RUN", rows=[])
            print("Demo unavailable/failed; no result asserted. Check local prerequisites.", flush=True)
        self.save()

    async def serve(self, once=None):
        async def heartbeat():
            while True:
                self.save()
                await asyncio.sleep(3)
        task = asyncio.create_task(heartbeat())
        try:
            if once:
                await self.execute(once)
                return
            print("Dashboard operator ready. Tiny explicit demos only; no .env loading.", flush=True)
            while True:
                self.state["matrix_active"] = await asyncio.to_thread(matrix_active)
                for path in sorted((self.runtime / "requests").glob("*.json"))[:1]:
                    try:
                        job = Job.model_validate_json(path.read_bytes())
                    except (ValueError, OSError):
                        path.unlink(missing_ok=True)
                        continue
                    path.unlink()
                    await self.execute(job)
                self.save()
                await asyncio.sleep(1)
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
            # Immediately disconnect stale UI controls when this worker exits.
            self.state["heartbeat"] = 0
            atomic_json(self.runtime / "observations/state.json", self.state)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, default=ROOT / "dashboard/runtime")
    parser.add_argument("--once", choices=("traffic", "audit", "isolation", "story"))
    parser.add_argument("--policy", choices=("raw", "bucket_hard", "window_hard"), default="bucket_hard")
    parser.add_argument("--secret", choices=("A", "B"), default="A")
    args = parser.parse_args()
    asyncio.run(Worker(args.runtime).serve(Job(action=args.once, policy=args.policy, secret=args.secret) if args.once else None))


if __name__ == "__main__":
    main()
