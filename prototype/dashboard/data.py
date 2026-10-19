"""Bounded, allowlisted projections of saved evidence; never serve raw files."""
import hashlib
import json
import math
import re
from pathlib import Path

LABEL = "live gateway, mock model, local run"
POLICIES = ("raw", "bucket", "bucket_hard", "window_hard")
EXPECTED = [(c, p) for p in POLICIES for c in ("ordinary", "boundary", "overflow")]
EXPECTED += [(c, p) for p in POLICIES[2:] for c in ("deadline_near", "deadline_far")]
EVENTS = {
    "submit_received": ("RED", "Request received by gateway"),
    "bucket_released": ("ENVIRONMENT", "Gateway recorded release"),
    "defense_stored": ("BLUE", "Encrypted defense configuration stored"),
    "report_served": ("RED", "Gateway served report"),
    "run_finished": ("ENVIRONMENT", "Run finished"),
    "deadline_cancelled": ("ENVIRONMENT", "Compute deadline cancelled"),
    "complete": ("ENVIRONMENT", "Collector completed the audit chain"),
}
EVIDENCE_NAMES = (
    "Test suite (host, Windows)", "Test suite (inside Docker image)",
    "docker compose ps", "Isolation demo inside red-client", "Audit verifier",
    "Audit tamper demo", "Round 2 leakage matrix", "Attack suite", "Feedback",
    "Real model", "Agent", "Extra probes (audit/proxy from Red; egress of gateway, Blue, model)",
    "Timing A-vs-B: ordinary", "Timing A-vs-B: boundary", "Timing A-vs-B: overflow",
    "Audit under matrix load (verifier on every run)", "Timing matrix status",
    "Feedback analysis (Phase 5)", "Real-model latency vs 3/6/9 s buckets",
    "Offline replay: window_hard W=3 s, D=2.4 s on the measured real latencies",
    "Real-model exact-canary scan of raw outputs",
    "Real-model rule disclosure in raw outputs (keyword scan + manual review)",
    "Same outputs behind score-only gateway", "External coding-agent red team",
)


def read_json(path, limit=1_000_000):
    try:
        path = Path(path)
        if path.stat().st_size > limit:
            return {}
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def number(value):
    return value if type(value) in (int, float) and math.isfinite(value) else None


def objects(value, limit=100):
    return [r for r in value[-limit:] if isinstance(r, dict)] if isinstance(value, list) else []


def matrix(root):
    source = read_json(Path(root) / "eval/output/round2/results.json")
    cells = source.get("cells", [])
    cells = cells if isinstance(cells, list) else []
    index = {(r.get("cohort"), r.get("policy")): r for r in cells if isinstance(r, dict)}
    rows = []
    for cohort, policy in EXPECTED:
        r = index.get((cohort, policy), {})
        accuracy = number(r.get("test_accuracy"))
        interval = r.get("wilson_95")
        interval = [number(v) for v in interval] if isinstance(interval, list) and len(interval) == 2 else None
        rows.append(dict(cohort=cohort, policy=policy, status="SAVED" if accuracy is not None else "NOT RUN",
                         accuracy=accuracy, interval=interval, n=number(r.get("test_runs")),
                         train_accuracy=number(r.get("train_accuracy")), gap=number(r.get("train_test_gap"))))
    return dict(label=LABEL, saved=sum(r["status"] == "SAVED" for r in rows), total=len(EXPECTED),
                scale=number(source.get("scale")), audit=source.get("audit") is True, rows=rows,
                # An on-disk in_progress marker is not a process liveness check.
                note="Saved evidence only; missing cells are NOT RUN. Process status comes from the worker.")


def evidence(root):
    source = read_json(Path(root) / "evidence/results.json")
    rows = []
    for r in source.get("rows", []) if isinstance(source.get("rows"), list) else []:
        if not isinstance(r, dict):
            continue
        name = next((name for name in EVIDENCE_NAMES if str(r.get("test", "")).startswith(name)), None)
        if name is None:
            name = "Other saved check"
        result = r.get("result")
        # Return a constrained numeric summary, never arbitrary evidence prose.
        metric = ""
        value = str(r.get("key_number", ""))
        for pattern in (r"\d+ passed, \d+ failed", r"\d+/\d+ checks PASS", r"\d+/\d+ runs VALID",
                        r"\d+/\d+ tamper", r"\d+/\d+ raw outputs", r"\d+/\d+ exact canary hits",
                        r"\d+\.\d+% \(95% [\d.]+%-[\d.]+%\)", r"n=\d+", r"\d+/\d+", r"\d+ blocked, \d+ reachable"):
            match = re.search(pattern, value)
            if match:
                metric = match.group()
                break
        if result == "NOT RUN":
            metric = "NOT RUN"
        rows.append(dict(test=name, result=result if result in ("PASS", "FAIL", "PARTIAL", "NOT RUN", "VALID", "INVALID", "LEAKED", "BOUNDED LEAK", "BLOCKED") else "NOT RUN", metric=metric))
    checks = read_json(Path(root) / "evidence/dashboard-verification.json")
    for key, name in (("backend", "Dashboard backend tests"), ("selected", "Selected non-timing regression checks"),
                      ("collector_timing", "Collector timing check (isolated host run)"),
                      ("compose", "Dashboard Compose config validation"), ("docker_runtime", "Dashboard Docker runtime / isolation")):
        check = checks.get(key)
        if isinstance(check, dict):
            count = number(check.get("passed"))
            rows.append(dict(test=name, result=check.get("status") if check.get("status") in ("PASS", "FAIL", "NOT RUN") else "NOT RUN",
                             metric=f"{count} passed" if count is not None else ""))
    return dict(status="SAVED" if rows else "NOT RUN", rows=rows,
                note="Historical saved evidence, not a fresh Docker health check.")


def audit_events(directory):
    """Tail only a bounded number of public log records, never keys/checkpoints."""
    result = []
    try:
        paths = sorted(Path(directory).glob("*.jsonl"), key=lambda p: p.stat().st_mtime)[-3:]
        for path in paths:
            with path.open("rb") as stream:
                stream.seek(max(0, path.stat().st_size - 16384))
                if stream.tell():
                    stream.readline()
                lines = stream.read(16384).splitlines()[-20:]
            for line in lines:
                try:
                    row = json.loads(line)
                    kind = row.get("type")
                    if kind not in EVENTS:
                        continue
                    lane, text = EVENTS[kind]
                    digest = hashlib.sha256(line).hexdigest()
                    result.append(dict(id=digest, lane=lane, text=text, source="collector metadata",
                                       request="run-" + hashlib.sha256(str(row.get("run_id", "")).encode()).hexdigest()[:8],
                                       bucket=number(row.get("bucket"))))
                except (ValueError, AttributeError):
                    continue
    except OSError:
        pass
    return result[-40:]


def public_observations(path):
    """Worker writes sanitized projections; re-allowlist at the HTTP boundary."""
    source = read_json(path)
    output = {"status": "NOT RUN", "events": [], "requests": [], "scenarios": {}, "accuracy": None}
    if source.get("status") in ("idle", "running", "complete", "blocked", "failed"):
        output["status"] = source["status"]
    output["heartbeat"] = number(source.get("heartbeat"))
    output["matrix_active"] = source.get("matrix_active") is True
    output["policy"] = source.get("policy") if source.get("policy") in POLICIES else "NOT RUN"
    output["report"] = None
    report = source.get("report")
    if isinstance(report, dict):
        values = report.get("safe_range")
        if isinstance(values, list) and len(values) == 2 and all(type(v) is int and 0 <= v <= 100000 for v in values):
            output["report"] = dict(safe_range=values, repeat_equal=report.get("repeat_equal") is True,
                                    third_pending=report.get("third_pending") is True)
    checked = source.get("audit_verified", {})
    output["audit_verified"] = {k: number(checked.get(k)) for k in ("runs", "valid")} if isinstance(checked, dict) else {}
    for event in objects(source.get("events"), 80):
        if event.get("kind") not in ("sent", "response", "evaluation", "audit"):
            continue
        text = {"sent": "Red sent request", "response": "Red received HTTP response",
                "evaluation": "Evaluator read gateway outcome", "audit": "Audit verification finished"}[event["kind"]]
        lane = {"sent": "RED", "response": "ENVIRONMENT", "evaluation": "BLUE", "audit": "ENVIRONMENT"}[event["kind"]]
        # Correlation identifiers are generated integers, not caller strings.
        idx = number(event.get("index"))
        output["events"].append(dict(id=f"{number(source.get('started'))}-{number(event.get('seq'))}",
                                      request=idx, lane=lane, text=text, source="operator observed HTTP / DB"))
    for row in objects(source.get("requests"), 64):
        r = {k: number(row.get(k)) for k in ("index", "status", "body_length", "ttfb", "total", "allowed", "cancelled")}
        r["response"] = "pending" if row.get("response") == "pending" else "NOT RUN"
        r["world"] = "keyword filter B" if row.get("world") == 1 else "keyword filter A"
        r["split"] = "test" if row.get("split") == "test" else "train"
        r["compute"] = "NOT RUN"  # Gateway currently records no compute-duration telemetry.
        headers = row.get("headers")
        headers = [v for v in headers if isinstance(v, list) and len(v) == 2] if isinstance(headers, list) else []
        r["headers"] = {k: v for k, v in headers
                        if (k == "content-type" and v == "application/json") or (k == "content-length" and v == "64")}
        output["requests"].append(r)
    a = source.get("accuracy")
    if isinstance(a, dict):
        output["accuracy"] = {k: number(a.get(k)) for k in ("correct", "n", "train_n", "train_accuracy", "gap")}
        output["accuracy"]["interval"] = [number(v) for v in a.get("interval", [])][:2]
    for name in ("isolation", "audit"):
        scenarios = source.get("scenarios")
        s = scenarios.get(name, {}) if isinstance(scenarios, dict) else {}
        s = s if isinstance(s, dict) else {}
        names = ISOLATION_CASES if name == "isolation" else TAMPER_CASES
        rows = [{"name": n, "result": r.get("result") if r.get("result") in ("PASS", "FAIL", "VALID", "INVALID") else "NOT RUN"}
                for r in objects(s.get("rows")) for n in names if r.get("name") == n]
        output["scenarios"][name] = {"status": s.get("status") if s.get("status") in ("PASS", "FAIL") else "NOT RUN", "rows": rows}
    return output


ISOLATION_CASES = ("Direct blue-defense blocked", "Direct model-mock blocked", "Direct Blue IP blocked",
    "Direct model IP blocked", "Host aliases do not resolve", "Host TCP probes blocked (80/443/8000)",
    "External DNS lookup blocked", "Internet IP probes blocked", "Docker socket absent",
    "Red defense request is generic", "Gateway submit is 202 pending")
TAMPER_CASES = ("unmodified", "edit one event", "delete middle event", "delete last 3 events",
    "reorder two events", "duplicate/replay event", "rehash without signing key", "edit log and stored count")
