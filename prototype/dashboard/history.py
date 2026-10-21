"""Dated history of saved runs. Allowlisted files only; read-only, no model calls.

Every entry is re-derived from the raw saved file, with its SHA-256, so a viewer can
press Recheck and compare the claim with the artifact. Model text is never exposed.
"""
import hashlib
import json
from pathlib import Path
import re
import time

from .data import number, read_json
from .recording import atomic_json

HEADER_DATE = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ")
PASSED = re.compile(r"(\d+) passed(?:, (\d+) failed)?")

# (id, title, group, relative path, parser, what it shows)
REGISTRY = (
    ("isolation", "Red cannot reach Blue, model, host or internet", "Isolation", "evidence/isolation.txt", "isolation",
     "Probes run from inside the Red container. Each blocked route is a PASS."),
    ("isolation-extra", "Audit collector and egress probes", "Isolation", "evidence/isolation-extra.txt", "text",
     "Extra reachability probes for the audit collector and service egress."),
    ("audit-tamper", "Tampered audit log is detected", "Audit", "evidence/audit-docker.txt", "tamper",
     "Seven edited copies of a signed log must all be INVALID; only the untouched copy is VALID."),
    ("tests-docker", "Test suite inside the Docker image", "Tests", "evidence/tests-in-docker.txt", "tests",
     "Gateway, audit and policy tests run on Linux inside the image."),
    ("tests-full", "Full report tests (host)", "Tests", "evidence/full-report-tests.txt", "tests",
     "Host regression run recorded with the full evidence report."),
    ("tests-paired", "Paired-story gateway tests", "Tests", "evidence/paired-story-tests.txt", "tests",
     "Tests for the paired raw vs protected comparison."),
    ("matrix", "Timing leakage matrix (A vs B)", "Leakage", "eval/output/round2/results.json", "matrix",
     "Red's unseen-run accuracy at telling secret A from B; 50% is guessing."),
    ("paired", "Paired raw vs protected comparison", "Leakage", "evidence/paired-comparison.json", "json",
     "Eight measured HTTP submissions against fresh localhost services."),
    ("controls", "Measured controls: vault, identity, feedback, audit", "Controls", "evidence/controls-comparison.json", "json",
     "Diagnostic baselines against the mock backend."),
    ("story", "Four-request story run", "Story", "evidence/story-results.json", "json",
     "Stable repeats, third-read budget and matched audit."),
)
BY_ID = {row[0]: row for row in REGISTRY}


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(65536), b""):
            digest.update(block)
    return digest.hexdigest()


def iso(epoch):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(epoch))


def text_of(path, limit=400_000):
    raw = Path(path).read_bytes()[:limit]
    # Logs redirected by Windows PowerShell are UTF-16 with a BOM.
    encoding = "utf-16" if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else "utf-8-sig"
    return raw.decode(encoding, errors="replace")


def parse_isolation(text):
    passes = len(re.findall(r"^PASS\s", text, re.M))
    fails = len(re.findall(r"^FAIL\s", text, re.M))
    summary = re.findall(r'"passed": (\d+), "total": (\d+)', text)
    if summary:
        passed, total = map(int, summary[-1])
    else:
        passed, total = passes, passes + fails
    rows = [line[6:].strip() + ": PASS" for line in text.splitlines() if line.startswith("PASS  ")]
    return ("PASS" if total and passed == total and not fails else "FAIL" if total else "NOT RUN",
            f"{passed}/{total} checks PASS" if total else "NOT RUN", rows[:12])


def parse_tamper(text):
    cases = re.findall(r"^(unmodified|edit one event|delete middle event|delete last \d+ events|reorder two events|"
                       r"duplicate/replay event|rehash without signing key|edit log and stored count)\s+(VALID|INVALID)\b", text, re.M)
    if not cases:
        return "NOT RUN", "NOT RUN", []
    tampered = [c for c in cases if c[0] != "unmodified"]
    caught = sum(r == "INVALID" for _, r in tampered)
    clean = any(c == ("unmodified", "VALID") for c in cases)
    ok = clean and tampered and caught == len(tampered)
    return ("PASS" if ok else "FAIL", f"{caught}/{len(tampered)} tampered copies INVALID; unmodified "
            + ("VALID" if clean else "not VALID"), [f"{name}: {result}" for name, result in cases])


def parse_tests(text):
    found = PASSED.findall(text)
    if not found:
        return "NOT RUN", "NOT RUN", []
    # Hand-annotated logs may list several runs; report the largest and fail on any failure.
    passed = max(int(p) for p, _ in found)
    failed = sum(int(f or 0) for _, f in found)
    return ("FAIL" if failed else "PASS", f"{passed} passed" + (f", {failed} failed" if failed else ""), [])


def parse_text(text):
    blocked = len(re.findall(r"-> blocked", text))
    open_ = len(re.findall(r"-> (?:open|reachable|connected)", text))
    if blocked or open_:
        return ("FAIL" if open_ else "PASS", f"{blocked} blocked, {open_} reachable", [])
    passes, fails = len(re.findall(r"\bPASS\b", text)), len(re.findall(r"\bFAIL\b", text))
    if not passes and not fails:
        return "NOT RUN", "NOT RUN", []
    return "FAIL" if fails else "PASS", f"{passes} PASS, {fails} FAIL", []


def parse_matrix(data):
    cells = [c for c in data.get("cells", []) if isinstance(c, dict) and number(c.get("test_accuracy")) is not None]
    if not cells:
        return "NOT RUN", "NOT RUN", []
    rows = [f"{c.get('cohort')} / {c.get('policy')}: {100 * c['test_accuracy']:.1f}%" for c in cells]
    state = "complete" if data.get("status") == "complete" else "partial"
    return ("PASS" if state == "complete" else "PARTIAL", f"{len(cells)} cells saved ({state}); 50% = guessing", rows)


def parse_json(data):
    status = data.get("status") or data.get("worker_status")
    arms = data.get("arms")
    result = "PASS" if status == "complete" else "PARTIAL" if status else "NOT RUN"
    rows = [f"{k}: {data[k]}" for k in ("policy", "source") if isinstance(data.get(k), (str, int, float))]
    return result, (f"status {status}" if status else "saved record"), rows + ([f"{len(arms)} arms"] if isinstance(arms, list) else [])


def parse_real(data):
    """Real-model run metadata. Only hashes and booleans; the answer text is never stored here."""
    rows = []
    for r in data.get("requests", []) if isinstance(data.get("requests"), list) else []:
        if isinstance(r, dict):
            rows.append(f"{r.get('case')}: Red saw HTTP {r.get('status')}, envelope exact={r.get('envelope_exact')}, "
                        f"Blue allowed={r.get('blue_allowed')}, backend={r.get('backend') or 'model not completed'}")
    if isinstance(data.get("summary_lines"), list):  # Batch runs carry the six-point summary first.
        rows = [str(line)[:240] for line in data["summary_lines"]] + rows
    audit, status = data.get("audit"), data.get("status")
    ok = status == "complete" and audit == "VALID"
    return ("PASS" if ok else "FAIL" if status == "failed" else "PARTIAL", f"real model run {status}; audit {audit}", rows)


JOB_TITLES = dict(traffic="Demo traffic run (mock model)", isolation="Isolation check run from the UI",
                  audit="Audit tamper check run from the UI", story="Story run", comparison="Paired raw vs protected run",
                  controls="Measured controls run", duel="Side-by-side recording (raw vs window_hard + continue)")


def parse_job(data):
    """A dated copy of one UI job: what Red saw and each scenario result, metadata only."""
    rows = [f"{k}: {v.get('status')}" for k, v in (data.get("scenarios") or {}).items() if isinstance(v, dict)]
    requests = data.get("requests")
    if isinstance(requests, list):
        rows.append(f"{len(requests)} requests recorded")
    accuracy = number(data.get("accuracy"))
    if accuracy is not None:
        rows.append(f"Red guess accuracy {100 * accuracy:.1f}%")
    status = data.get("status") or data.get("worker_status")
    scenario = (data.get("scenarios") or {}).get(data.get("action"))
    result = (scenario or {}).get("status") if isinstance(scenario, dict) else None
    result = result if result in ("PASS", "FAIL", "NOT RUN") else "FAIL" if status == "failed" else "RECORDED"
    return result, f"{data.get('action')} job {status}", rows


PARSERS = {"isolation": parse_isolation, "tamper": parse_tamper, "tests": parse_tests, "text": parse_text}
JSON_PARSERS = {"job": parse_job, "matrix": parse_matrix, "json": parse_json, "real": parse_real}


def when(path, text=None, data=None):
    if text:
        found = HEADER_DATE.search(text[:600])
        if found:
            return found.group(), "date written in the saved log header"
    if data and number(data.get("recorded_at")):
        return iso(data["recorded_at"]), "recorded_at inside the saved file"
    return iso(Path(path).stat().st_mtime), "file modified time"


def build(entry_id, title, group, relative, kind, explains, root):
    """One entry re-derived from the raw saved file; NOT RUN when it does not exist."""
    path = Path(root) / relative
    base = dict(id=entry_id, title=title, group=group, file=relative, explains=explains)
    try:
        size = path.stat().st_size
        if size > 8_000_000:
            raise OSError("too large")
        if kind in PARSERS:
            text = text_of(path)
            result, headline, details = PARSERS[kind](text)
            recorded, source = when(path, text=text)
        else:
            data = read_json(path, 8_000_000)
            if not data:
                raise OSError("unreadable")
            result, headline, details = JSON_PARSERS[kind](data)
            recorded, source = when(path, data=data)
        return base | dict(result=result, headline=headline, details=details[:16], recorded_at=recorded,
                           recorded_source=source, sha256=sha256(path), bytes=size)
    except (OSError, ValueError):
        return base | dict(result="NOT RUN", headline="NOT RUN: no saved file", details=[], recorded_at=None,
                           recorded_source=None, sha256=None, bytes=None)


def archived_real_runs(observations):
    """Each real model run archived by run_real; the newest live file is also kept."""
    folder = Path(observations) / "history"
    return sorted(folder.glob("real-*.json"))[-20:] if folder.is_dir() else []


def archived_jobs(observations):
    folder = Path(observations) / "history"
    return [p for p in sorted(folder.glob("*-*.json"))[-60:] if not p.name.startswith("real-")] if folder.is_dir() else []


def job_entry(path):
    action = path.stem.rsplit("-", 1)[0]
    title = JOB_TITLES.get(action)
    if title is None:
        return None
    row = build(path.stem, title, "UI runs", str(path), "job", "A dated copy of a run started from the dashboard.", "/")
    return row | dict(file="observations/history/" + path.name)


def private_details(observations, entry_id):
    """Operator-only full record of a real run (prompts and model text), if it was saved locally."""
    path = Path(observations).parent / "private" / (entry_id + ".json")
    data = read_json(path, 2_000_000)
    lines = []
    for r in data.get("requests", []) if isinstance(data.get("requests"), list) else []:
        if isinstance(r, dict):
            lines.append(f"[{r.get('case')}] prompt: {r.get('prompt')}")
            lines.append(f"[{r.get('case')}] model answer: {r.get('answer') if r.get('answer') else 'none (blocked or not completed)'}"
                         f" · total {number(r.get('total')) and round(r['total'], 3)}s")
    if data.get("run_id"):
        lines.append(f"run id: {data['run_id']}")
    return lines


def entries(saved, observations):
    rows = [build(*row[:3], row[3], row[4], row[5], saved) for row in REGISTRY]
    real = archived_real_runs(observations)
    for path in real:
        entry_id = path.stem
        row = build(entry_id, "Real DeepSeek run (small sample)", "Real model", str(path), "real",
                    "Two benign probes through the real gateway. Red only ever saw the generic pending reply.", "/")
        rows.append(row | dict(file="observations/history/" + path.name))
    rows += [r for r in map(job_entry, archived_jobs(observations)) if r]
    if not real:
        rows.append(dict(id="real-none", title="Real DeepSeek run (small sample)", group="Real model", file="",
                         explains="No real model call has been recorded yet.", result="NOT RUN",
                         headline="NOT RUN: no real model call recorded", details=[], recorded_at=None,
                         recorded_source=None, sha256=None, bytes=None))
    return rows


def resolve(entry_id, saved, observations):
    for row in REGISTRY:
        if row[0] == entry_id:
            return build(*row[:3], row[3], row[4], row[5], saved)
    for path in archived_jobs(observations):
        if path.stem == entry_id:
            return job_entry(path)
    for path in archived_real_runs(observations):
        if path.stem == entry_id:
            row = build(entry_id, "Real DeepSeek run (small sample)", "Real model", str(path), "real",
                        "Two benign probes through the real gateway.", "/")
            return row | dict(file="observations/history/" + path.name)
    return None


def ledger_update(ledger, rows):
    """Remember the first hash this dashboard saw per entry, to flag later edits."""
    book = read_json(ledger)
    book = {k: v for k, v in book.items() if isinstance(v, dict)}
    dirty = False
    for row in rows:
        if not row["sha256"]:
            continue
        first = book.get(row["id"])
        if first is None:
            book[row["id"]] = first = dict(sha256=row["sha256"], first_seen=iso(time.time()))
            dirty = True
        row["first_seen"] = first.get("first_seen")
        row["changed_since_first_seen"] = first.get("sha256") != row["sha256"]
    if dirty:
        atomic_json(ledger, book)  # best effort; a read-only volume just skips the ledger
    return rows


def listing(saved, observations, ledger):
    rows = ledger_update(ledger, entries(saved, observations))
    rows.sort(key=lambda r: r["recorded_at"] or "", reverse=True)
    return dict(entries=rows, now=iso(time.time()),
                note="Re-read from saved files. Recheck re-parses the raw file and compares its SHA-256; "
                     "it does not rerun the experiment and makes no model call.")


def recheck(entry_id, saved, observations, ledger):
    row = resolve(entry_id, saved, observations)
    if row is None:
        return None
    ledger_update(ledger, [row])
    if row["sha256"] is None:
        verdict = "NOT RUN: there is no saved file to check"
    elif row.get("changed_since_first_seen"):
        verdict = "CHANGED: the file differs from the first version this dashboard saw"
    else:
        verdict = "UNCHANGED since first seen; result re-derived from the raw file"
    private = private_details(observations, entry_id) if entry_id.startswith("real-") else []
    return row | dict(verdict=verdict, checked_at=iso(time.time()), details=row["details"] + private)
