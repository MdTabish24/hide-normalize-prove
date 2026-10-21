"""History page: re-derives results from raw saved files; no model call, no secrets."""
import json

from fastapi.testclient import TestClient

from dashboard.app import create_app

ISOLATION = "# demo (2026-10-19T03:39:24Z)\n" + "".join(f"PASS  check {i}\n" for i in range(11)) + '{"passed": 11, "total": 11, "run_id": "x"}\n'
TAMPER = "".join(f"{n:<30} {r}  reason / 0\n" for n, r in (
    ("unmodified", "VALID"), ("edit one event", "INVALID"), ("delete middle event", "INVALID"),
    ("delete last 3 events", "INVALID"), ("reorder two events", "INVALID"), ("duplicate/replay event", "INVALID"),
    ("rehash without signing key", "INVALID"), ("edit log and stored count", "INVALID")))
HEADERS = {"x-demo-ui": "1"}


def client(tmp_path):
    (tmp_path / "evidence").mkdir()
    (tmp_path / "evidence/isolation.txt").write_text(ISOLATION)
    (tmp_path / "evidence/audit-docker.txt").write_text("## tamper demo on COPIES\n" + TAMPER)
    (tmp_path / "evidence/tests-in-docker.txt").write_text("65 passed in 72.86s\n")
    app = create_app(saved=tmp_path, runtime=tmp_path / "runtime", audit=tmp_path / "audit", eval_mode=False)
    return TestClient(app, base_url="http://127.0.0.1")


def by_id(rows):
    return {r["id"]: r for r in rows}


def test_listing_parses_saved_files_and_marks_missing_as_not_run(tmp_path):
    rows = by_id(client(tmp_path).get("/api/history").json()["entries"])
    assert rows["isolation"]["result"] == "PASS" and rows["isolation"]["headline"] == "11/11 checks PASS"
    assert rows["isolation"]["recorded_at"] == "2026-10-19T03:39:24Z"
    assert rows["audit-tamper"]["result"] == "PASS" and rows["audit-tamper"]["headline"].startswith("7/7")
    assert rows["tests-docker"]["headline"] == "65 passed"
    assert rows["matrix"]["result"] == "NOT RUN" and rows["matrix"]["sha256"] is None
    assert rows["real-none"]["result"] == "NOT RUN"


def test_tamper_demo_that_misses_an_edit_is_a_fail(tmp_path):
    c = client(tmp_path)
    (tmp_path / "evidence/audit-docker.txt").write_text(TAMPER.replace("edit one event".ljust(30) + " INVALID", "edit one event".ljust(30) + " VALID"))
    assert by_id(c.get("/api/history").json()["entries"])["audit-tamper"]["result"] == "FAIL"


def test_recheck_flags_a_file_edited_after_first_seen(tmp_path):
    c = client(tmp_path)
    c.get("/api/history")
    first = c.post("/api/history/recheck", json={"id": "isolation"}, headers=HEADERS).json()
    assert first["verdict"].startswith("UNCHANGED")
    (tmp_path / "evidence/isolation.txt").write_text(ISOLATION.replace("PASS  check 0", "FAIL  check 0"))
    second = c.post("/api/history/recheck", json={"id": "isolation"}, headers=HEADERS).json()
    assert second["verdict"].startswith("CHANGED") and second["result"] == "FAIL"


def test_real_run_archive_is_listed_without_answer_text(tmp_path):
    c = client(tmp_path)
    folder = tmp_path / "runtime/observations/history"
    folder.mkdir(parents=True)
    (folder / "real-1792500000.json").write_text(json.dumps(dict(
        status="complete", recorded_at=1792500000, audit="VALID", requests=[
            dict(case="allowed", status=202, envelope_exact=True, blue_allowed=True, backend="DeepSeek",
                 answer_sha256="ab" * 32)])))
    body = c.get("/api/history").text
    row = by_id(json.loads(body)["entries"])["real-1792500000"]
    assert row["result"] == "PASS" and row["recorded_at"].startswith("2026-10-")
    assert "answer" not in body.replace("answer_sha256", "")
    assert "real-none" not in body


def test_recheck_requires_ui_header_and_known_id(tmp_path):
    c = client(tmp_path)
    assert c.post("/api/history/recheck", json={"id": "isolation"}).status_code == 403
    assert c.post("/api/history/recheck", json={"id": "nope"}, headers=HEADERS).status_code == 404
    assert c.post("/api/history/recheck", json={"id": "../../etc/passwd"}, headers=HEADERS).status_code == 400
    assert c.post("/api/history/recheck", json={"id": "isolation", "path": "/x"}, headers=HEADERS).status_code == 400


def test_ui_job_archive_and_private_real_record(tmp_path):
    c = client(tmp_path)
    folder = tmp_path / "runtime/observations/history"
    folder.mkdir(parents=True)
    (folder / "isolation-1792500100.json").write_text(json.dumps(dict(
        action="isolation", status="complete", scenarios={"isolation": {"status": "PASS", "rows": []}})))
    (folder / "real-1792500000.json").write_text(json.dumps(dict(status="complete", recorded_at=1792500000, audit="VALID", requests=[])))
    private = tmp_path / "runtime/private"
    private.mkdir()
    (private / "real-1792500000.json").write_text(json.dumps(dict(run_id="real-x", requests=[
        dict(case="allowed", prompt="Write one short greeting.", answer="Hello there!", total=3.01)])))
    listing = c.get("/api/history").text
    rows = by_id(json.loads(listing)["entries"])
    assert rows["isolation-1792500100"]["result"] == "PASS" and rows["isolation-1792500100"]["group"] == "UI runs"
    assert "Hello there" not in listing  # model text only in the operator's per-run detail view
    detail = c.post("/api/history/recheck", json={"id": "real-1792500000"}, headers=HEADERS).json()
    assert any("model answer: Hello there!" in line for line in detail["details"])


def test_why_page_separates_baseline_from_ours_and_never_claims_unmeasured(tmp_path):
    c = client(tmp_path)
    data = c.get("/api/why").json()
    assert c.get("/why").status_code == 200
    names = [r["channel"] for r in data["channels"]]
    assert "Direct access (network, files, host, internet)" in names and "Timing: boundary traffic" in names
    timing = next(r for r in data["channels"] if r["channel"] == "Timing: ordinary traffic")
    assert timing["baseline"]["verdict"] == "NOT RUN" and timing["ours"]["window_hard"]["verdict"] == "NOT RUN"
    assert data["validity"]["status"] == "INCOMPLETE"  # timing never measured here
    assert any("CPU" in n["channel"] for n in data["not_covered"])


def test_why_names_the_failed_channels_per_policy(tmp_path):
    c = client(tmp_path)
    (tmp_path / "eval/output/round2").mkdir(parents=True)
    cells = [dict(cohort="boundary", policy="bucket", test_accuracy=1.0, wilson_95=[.98, 1.0], test_runs=200, train_accuracy=1.0, train_test_gap=0),
             dict(cohort="boundary", policy="raw", test_accuracy=1.0, wilson_95=[.98, 1.0], test_runs=200, train_accuracy=1.0, train_test_gap=0)]
    (tmp_path / "eval/output/round2/results.json").write_text(json.dumps(dict(cells=cells, status="in_progress")))
    rows = {p["policy"]: p for p in c.get("/api/why").json()["policies"]}
    soft = rows["bucket (soft)"]
    assert soft["verdict"] == "INVALID" and soft["failed"] == ["Timing: boundary traffic"]
    assert rows["window_hard (one fixed window)"]["verdict"] == "INCOMPLETE"


def test_why_summary_has_stopped_and_not_stopped_and_marks_missing_as_not_run(tmp_path):
    summary = client(tmp_path).get("/api/why").json()["summary"]
    assert {"attack", "without", "with", "result"} <= set(summary["stopped"][0])
    by_attack = {r["attack"]: r for r in summary["stopped"]}
    assert by_attack["Network, files, host, internet"]["result"] == "NOT RUN"  # no attack_suite_results.json here
    assert by_attack["Timing: Red learns Blue's rule from response time"]["result"] == "NOT RUN"
    assert any("CPU" in r["attack"] for r in summary["not_stopped"]) and summary["limits"]
