"""One evidence table. --cached never starts processes or makes HTTP requests."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
LOCAL = "live gateway, mock model, local run"
SIM = "simulated (Monte Carlo)"
REAL = "real model run, small sample"
RESULTS = {"BLOCKED", "BOUNDED LEAK", "LEAKED", "PASS", "NOT COVERED", "NOT RUN"}


def load(path):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None


def row(test, policy="—", result="NOT RUN", number="Missing saved evidence", label=LOCAL, audit="unknown", source=""):
    assert result in RESULTS
    return dict(test=test, policy=policy, result=result, key_number=number, label=label, audit_mode=audit, source=source)


def collect(root=ROOT):
    root = Path(root)
    rows = []
    fast = load(root / "evidence/fast_results.json") or {}
    unit = fast.get("unit_tests")
    if unit:
        rows.append(row("Unit/integration tests", result="PASS" if unit.get("returncode") == 0 else "NOT COVERED",
                        number=unit.get("summary", "No test summary"), audit="mixed test fixtures", source=unit.get("source", "")))
    else:
        path = root / "eval/test-output.txt"
        text = path.read_text(encoding="utf-8-sig") if path.exists() else ""
        matches = re.findall(r"\d+ passed[^\n]*", text)
        rows.append(row("Unit/integration tests", result="PASS" if matches and not re.search(r"\d+ failed", text) else "NOT RUN",
                        number=matches[-1] if matches else "No saved pytest summary", audit="mixed test fixtures", source=str(path)))
    isolation = fast.get("isolation") or load(root / "evidence/isolation.json")
    if isolation:
        rows.append(row("Container isolation", result=isolation.get("result", "NOT RUN"),
                        number=isolation.get("reason", "No snapshot"), audit="not applicable", source=isolation.get("source", "")))
    else:
        rows.append(row("Container isolation", number="No structured container run; inspect saved demo-output.txt if present",
                        audit="not applicable", source=str(root / "demo-output.txt")))

    attack_paths = [root / "attack_suite/results.json", root / "attack_suite_results.json", root / "attack_results.json"]
    attack = next(((p, load(p)) for p in attack_paths if load(p)), None)
    if not attack:
        rows.append(row("Attack suite", number="Attack suite/result file not present"))
    else:
        path, data = attack
        cases = data.get("results", data.get("tests", [])) if isinstance(data, dict) else data
        if isinstance(cases, dict):
            cases = [dict(value, name=name) for name, value in cases.items() if isinstance(value, dict)]
        for case in cases if isinstance(cases, list) else []:
            if isinstance(case, dict):
                status = case.get("result", case.get("status", "NOT RUN"))
                rows.append(row("Attack: " + str(case.get("name", "unnamed")), case.get("policy", "—"),
                                status if status in RESULTS else "NOT COVERED", str(case.get("summary", status)),
                                audit=str(case.get("audit_mode", "unknown")), source=str(path)))

    datasets = []
    for path in (root / "eval").glob("**/results.json"):
        data = load(path)
        if isinstance(data, dict) and isinstance(data.get("timing"), list):
            datasets.append((path, data))
    best = max(datasets, key=lambda item: sum(c.get("test_runs", 0) for c in item[1]["timing"]), default=None)
    timing = best[1]["timing"] if best else []
    for cohort in ("ordinary", "boundary", "overflow"):
        for policy in ("raw", "bucket", "bucket_hard", "window_hard"):
            cell = next((c for c in timing if c.get("cohort") == cohort and c.get("policy") == policy), None)
            if cell and all(k in cell for k in ("test_accuracy", "wilson_95", "test_runs")):
                acc, interval = cell["test_accuracy"], cell["wilson_95"]
                outcome = "LEAKED" if interval[0] > .5 else "BOUNDED LEAK"
                audit = "enabled" if best[1].get("audit_enabled_for_timing") else "disabled" if best[1].get("audit_enabled_for_timing") is False else "unknown"
                rows.append(row("Timing: " + cohort, policy, outcome,
                                f"{acc:.1%}; 95% Wilson {interval[0]:.1%}–{interval[1]:.1%}; test n={cell['test_runs']}",
                                audit=audit, source=str(best[0])))
            else:
                rows.append(row("Timing: " + cohort, policy, number="Policy/results unavailable; no fallback substituted"))

    audit_path = root / "audit-demo-output.txt"
    audit_text = audit_path.read_text(encoding="utf-8-sig") if audit_path.exists() else ""
    baseline = bool(re.search(r"^unmodified\s+VALID\s", audit_text, re.M))
    rows.append(row("Audit: unmodified", result="PASS" if baseline else "NOT RUN", number="VALID baseline" if baseline else "No saved VALID baseline",
                    audit="separate collector, local checkpoint", source=str(audit_path)))
    for name in ("edit one event", "delete middle event", "delete last 3 events", "reorder two events",
                 "duplicate/replay event", "rehash without signing key", "edit log and stored count"):
        matched = re.search(r"^" + re.escape(name) + r"\s+(VALID|INVALID)\s+([^\n]+)", audit_text, re.M)
        rows.append(row("Audit: " + name, result="BLOCKED" if baseline and matched and matched[1] == "INVALID" else "NOT COVERED" if matched else "NOT RUN",
                        number=matched[1] + ": " + matched[2] if matched else "No saved tamper observation",
                        audit="separate collector, local checkpoint", source=str(audit_path)))

    live_source = max((item for item in datasets if item[1].get("feedback_live")),
                      key=lambda item: sum(c.get("sets", 0) for c in item[1]["feedback_live"]), default=None)
    if live_source:
        for cell in live_source[1]["feedback_live"]:
            stable, blocked = cell.get("within_run_repeat_stable_after_restart"), cell.get("third_read_blocked_after_restart")
            rows.append(row("Feedback: same-run budget", cell["mode"], "PASS" if stable is True and blocked is True else "NOT COVERED",
                            f"repeat stable={stable}; third SAME-run read blocked={blocked}", audit="disabled", source=str(live_source[0])))
            share = cell.get("summary", {}).get("truth_at_range_center_share")
            if isinstance(share, (int, float)):
                rows.append(row("Feedback: range position", cell["mode"], "PASS", f"truth at center {share:.1%}; {cell['sets']} sets × K={cell['k']}",
                                audit="disabled", source=str(live_source[0])))
    else:
        rows.append(row("Feedback: same-run budget", number="No persisted live feedback artifact; timing results are not a substitute"))
    mc_source = next((item for item in datasets if item[1].get("feedback_monte_carlo")), None)
    if mc_source:
        for mode in ("run", "probeset"):
            cells = sorted([c for c in mc_source[1]["feedback_monte_carlo"] if c.get("mode") == mode], key=lambda c: c["k"])
            if cells:
                a, b = cells[0], cells[-1]
                rows.append(row("Feedback: cross-run averaging", mode,
                                "LEAKED" if b["mean_absolute_error"] < a["mean_absolute_error"] else "BOUNDED LEAK",
                                f"MAE K={a['k']}: {a['mean_absolute_error']:.3f} → K={b['k']}: {b['mean_absolute_error']:.3f}",
                                SIM, "not applicable", str(mc_source[0])))
    else:
        rows.append(row("Feedback: cross-run averaging", number="No persisted Monte Carlo result", label=SIM, audit="not applicable"))

    real_path = root.parent / "real_results.json"
    real = load(real_path)
    if isinstance(real, dict) and isinstance(real.get("metrics"), dict):
        m = real["metrics"]
        rows.append(row("Latency: " + str(real.get("provider", "unknown provider")), "offline buckets", "PASS",
                        f"n={real.get('sample_size')}; p50/p95/p99={m['p50_seconds']:.2f}/{m['p95_seconds']:.2f}/{m['p99_seconds']:.2f}s; padding +{m['mean_added_latency_seconds']:.2f}s",
                        REAL, "not applicable", str(real_path)))
    else:
        rows.append(row("Real-model latency", label=REAL, audit="not applicable"))
    leak_path = root.parent / "leak_counts.json"
    leaks = load(leak_path)
    if isinstance(leaks, dict) and isinstance(leaks.get("attempt_results"), list):
        samples = leaks["attempt_results"]
        for mode, field in (("raw", "raw_rule_leaked"), ("score-only gateway", "gateway_rule_leaked")):
            if samples and all(field in r for r in samples):
                count = sum(bool(r[field]) for r in samples)
                rows.append(row("Rule disclosures: " + str(leaks.get("provider", "unknown")), mode,
                                "LEAKED" if count else "BLOCKED" if mode != "raw" else "PASS",
                                f"{count}/{len(samples)} keyword matches" + ("; zero by construction" if mode != "raw" else ""),
                                REAL, "not applicable", str(leak_path)))
        if "raw_output_leaks" in leaks:
            rows.append(row("Exact-canary scan", "raw", "LEAKED" if leaks["raw_output_leaks"] else "PASS",
                            f"{leaks['raw_output_leaks']}/{leaks.get('attempts')}; does not detect paraphrases", REAL, "not applicable", str(leak_path)))
    else:
        rows.append(row("Real-model output leakage", label=REAL, audit="not applicable"))
    sessions = load(root / "agent_sessions.json") or []
    sessions = sessions.get("sessions", []) if isinstance(sessions, dict) else sessions
    for policy in ("raw", "bucket_hard", "window_hard"):
        trials = [s for s in sessions if s.get("policy") == policy]
        valid = [s for s in trials if s.get("protocol_valid") is True]
        rows.append(row("External-agent guesses", policy, "NOT COVERED" if trials else "NOT RUN",
                        f"{sum(s.get('correct') is True for s in valid)}/{len(valid)} valid guesses correct; {len(trials)} sessions recorded; target 5; qualitative only" if trials else "No sessions recorded; target 5 per policy",
                        audit=", ".join(sorted({s.get('audit_mode', 'unknown') for s in trials})) or "unknown", source=str(root / "agent_sessions.json")))
    return rows


def run_control(command, root, transcript, timeout=300):
    try:
        result = subprocess.run(command, cwd=root, capture_output=True, text=True, errors="replace", timeout=timeout)
        output = result.stdout + result.stderr
        transcript.parent.mkdir(parents=True, exist_ok=True)
        transcript.write_text(output, encoding="utf-8")
        return result.returncode, output
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, type(exc).__name__ + ": " + str(exc)


def run_fast(root=ROOT):
    root = Path(root)
    directory = root / "evidence"
    directory.mkdir(exist_ok=True)
    state = {}
    code, output = run_control([sys.executable, "-m", "pytest", "tests", "eval/tests", "evidence_tests", "-q", "-k", "not tiny_live_http_full_harness", "-p", "no:cacheprovider"], root, directory / "tests.txt")
    summaries = re.findall(r"\d+ passed[^\n]*", output)
    state["unit_tests"] = dict(returncode=code, summary=summaries[-1] if summaries else "NOT RUN: " + output[-250:], source=str(directory / "tests.txt"))
    code, output = run_control(["docker", "info", "--format", "{{.ServerVersion}}"], root, directory / "docker-info.txt", 10)
    if code != 0:
        state["isolation"] = dict(result="NOT RUN", reason="Docker Engine unavailable; see evidence/docker-info.txt")
    else:
        code, output = run_control(["docker", "compose", "exec", "-T", "red-client", "python", "demo_isolation.py"], root, directory / "isolation.txt", 60)
        state["isolation"] = dict(result="PASS" if code == 0 and "PASS" in output and "FAIL" not in output else "NOT RUN" if code != 0 else "NOT COVERED", reason="Container demo completed" if code == 0 else "red-client/stack unavailable; see isolation transcript", source=str(directory / "isolation.txt"))
    print("Running tiny HTTP smoke, not the full timing matrix...", flush=True)
    code, output = run_control([sys.executable, "-m", "eval.run", "--n", "2", "--train-n", "2", "--scale", "0.02", "--concurrency", "1", "--mc-sets", "2", "--live-sets", "2", "--no-audit", "--output", "eval/fast-output"], root, directory / "http-smoke.txt", 300)
    state["http_smoke"] = dict(returncode=code, reason="completed" if code == 0 else output[-250:])
    (directory / "fast_results.json").write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


def render(rows):
    def safe(value):
        return str(value).replace("|", "\\|").replace("\n", " ")
    lines = ["# Hide, Normalize, Prove — saved evidence", "", "PASS means that named check passed, not proof of secrecy. LEAKED timing means the held-out Wilson interval is entirely above 50%; intervals are per test, without multiple-comparison correction. BOUNDED LEAK is limited/inconclusive evidence for this attacker, not a formal information bound.", "", "| Test | Policy | Result | Key number | Label | Audit mode |", "|---|---|---|---|---|---|"]
    for r in rows:
        lines.append("| " + " | ".join(safe(r[k]) for k in ("test", "policy", "result", "key_number", "label", "audit_mode")) + " |")
    lines += ["", "## Sources", "", *["- " + source for source in sorted({r["source"] for r in rows if r["source"]})], "", "## What this does NOT show", "", "- Host escape resistance, shared CPU/GPU hardware side channels, or safety against a compromised gateway/collector.", "- Chance-level accuracy is not proof; a single tree/agent, small samples and localhost jitter limit conclusions.", "- Mock inference is not a real-model isolation test. Real DeepSeek timing was padded offline.", "- A hard cap does not hide which request lands in which earlier bucket. No missing policy or attack has been substituted.", "- Same-run report memoization does not prevent fresh-run averaging. Noise is heuristic, not formal differential privacy.", "- Local signed checkpoints need an independent freshness witness; events omitted before collection are undetectable.", "- An empty host workspace is not an OS sandbox. Agent filesystem/tool access must be separately restricted.", "- Missing evidence is NOT RUN. Cached mode never reruns checks or contacts Docker/APIs."]
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--cached", action="store_true")
    mode.add_argument("--fast", action="store_true")
    args = parser.parse_args()
    if args.fast:
        run_fast()
    rows = collect()
    text = render(rows)
    (ROOT / "EVIDENCE.md").write_text(text, encoding="utf-8")
    directory = ROOT / "evidence"
    directory.mkdir(exist_ok=True)
    (directory / "results.json").write_text(json.dumps({"generated_utc": datetime.now(timezone.utc).isoformat(), "mode": "fast" if args.fast else "cached", "rows": rows}, indent=2) + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
