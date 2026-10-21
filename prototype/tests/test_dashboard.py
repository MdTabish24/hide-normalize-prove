"""Small dashboard checks: no timing evaluations or Docker startup."""
import json
import time
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from dashboard.app import create_app
from dashboard.data import EXPECTED, matrix


@pytest.fixture
def ui(tmp_path):
    (tmp_path / "runtime/observations").mkdir(parents=True)
    app = create_app(saved=tmp_path, runtime=tmp_path / "runtime", audit=tmp_path / "logs", eval_mode=False)
    return TestClient(app), tmp_path


def state(root, **changes):
    value = dict(status="idle", heartbeat=time.time(), events=[], requests=[], scenarios={})
    value.update(changes)
    (root / "runtime/observations/state.json").write_text(json.dumps(value))


def test_missing_is_not_run(ui):
    client, _ = ui
    data = client.get("/api/snapshot").json()
    assert data["live"]["status"] == "NOT RUN"
    assert data["matrix"]["saved"] == 0 and data["matrix"]["total"] == 16
    assert all(r["status"] == "NOT RUN" for r in data["matrix"]["rows"])
    assert data["evidence"]["status"] == "NOT RUN"
    root = ui[1]
    (root / "evidence").mkdir()
    (root / "evidence/dashboard-verification.json").write_text(json.dumps({"collector_timing":{"status":"FAIL"}}))
    assert client.get("/api/snapshot").json()["evidence"]["rows"][0]["result"] == "FAIL"


def test_partial_matrix_not_completed(tmp_path):
    path = tmp_path / "eval/output/round2/results.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"status":"in_progress", "cells":[{"cohort":"ordinary", "policy":"raw", "test_accuracy":.98}]}))
    result = matrix(tmp_path)
    assert result["saved"] == 1 and len(result["rows"]) == len(EXPECTED) == 16


def test_secrets_never_projected_or_validation_echoed(ui):
    client, root = ui
    secret = "pineapple mango FRUIT_FILTERED BLUE_SECRET_CANARY_7391 sk-private-key"
    state(root, events=[dict(kind="sent", index=1, seq=1, prompt=secret)],
          requests=[dict(index=1, status=202, body_length=64, total=.3, allowed=1, cancelled=0,
                         headers=[["authorization", secret],["content-type","application/json"]], response=secret, world=0,
                         prompt=secret, key=secret)],
          scenarios={"audit":{"status":"PASS", "rows":[{"name":secret,"result":"VALID"}]}})
    logs = root / "logs"
    logs.mkdir()
    (logs / "log.jsonl").write_text(json.dumps(dict(type="submit_received",run_id=secret,prompt=secret,key=secret))+"\n")
    output = client.get("/api/snapshot").text
    for word in secret.split():
        assert word not in output
    assert client.get("/api/red").json()["requests"][0]["status"] == 202
    assert "allowed" not in client.get("/api/red").text
    response = client.post("/api/jobs",headers={"x-demo-ui":"1"},json={"action":secret})
    assert response.status_code == 400 and secret not in response.text


def test_raw_requires_explicit_test_flag(ui):
    client, root = ui
    state(root)
    response = client.post("/api/jobs",headers={"x-demo-ui":"1"},json={"action":"traffic","policy":"raw"})
    assert response.status_code == 403


def test_real_call_requires_worker_key_availability_and_never_falls_back(ui):
    client, root = ui
    state(root)
    response=client.post('/api/jobs',headers={'x-demo-ui':'1'},json={'action':'real'})
    assert response.status_code==409
    assert not list((root/'runtime/requests').glob('*.json'))
    state(root,real_provider_available=True)
    assert client.post('/api/jobs',headers={'x-demo-ui':'1'},json={'action':'real'}).json()['status']=='queued'


@pytest.mark.parametrize("action", ["audit", "controls"])
def test_queue_only_allowlisted_jobs_and_guard(ui, action):
    client, root = ui
    state(root)
    assert client.post("/api/jobs",json={"action":"audit"}).status_code == 403
    assert client.post("/api/jobs",headers={"x-demo-ui":"1","origin":"https://untrusted.invalid"},json={"action":"audit"}).status_code == 403
    state(root,matrix_active=True)
    assert client.post("/api/jobs",headers={"x-demo-ui":"1"},json={"action":"audit"}).status_code == 409
    state(root)
    accepted = client.post("/api/jobs",headers={"x-demo-ui":"1"},json={"action":action}).json()
    assert accepted["status"] == "queued"
    assert [p.stem for p in (root / "runtime/requests").glob("*.json")] == [accepted["job_id"]]
    assert client.post("/api/jobs",headers={"x-demo-ui":"1"},json={"action":"audit"}).status_code == 409
    # Completion correlation must survive the API allowlist, otherwise the UI
    # stays QUEUED forever even after the worker has measured the result.
    state(root,status="complete",job=dict(id=accepted["job_id"],action=action,started_at=1,finished_at=2))
    assert client.get("/api/story").json()["job"] == dict(id=accepted["job_id"],action=action,started_at=1,finished_at=2)


def test_raw_explicit_flag_and_no_external_assets(tmp_path):
    client = TestClient(create_app(saved=tmp_path,runtime=tmp_path,eval_mode=True))
    assert client.get("/api/snapshot").json()["test_only"] is True
    html = client.get("/").text
    assert 'https://' not in html and 'http://' not in html
    assert "frame-ancestors 'none'" in client.get("/").headers["content-security-policy"]
    assert client.get("/",headers={"host":"untrusted.invalid"}).status_code == 400


def test_malformed_worker_file_is_safe(ui):
    client, root = ui
    state(root, events=None, requests=[None, {"headers":[None,"bad",["authorization","secret"]]}], scenarios=None)
    response = client.get("/api/snapshot")
    assert response.status_code == 200 and "secret" not in response.text


def test_red_report_projection_excludes_ground_truth(ui):
    client, root = ui
    state(root, report={"safe_range":[0,1], "repeat_equal":True,"third_pending":True,"true_count":1},
          policy="window_hard")
    snapshot = client.get("/api/snapshot").json()
    assert snapshot["live"]["report"] == {"safe_range":[0,1],"repeat_equal":True,"third_pending":True}
    assert snapshot["live"]["policy"] == "window_hard"
    assert "true_count" not in json.dumps(snapshot)


def test_compose_dashboard_has_no_red_route_or_credentials():
    # Parse the service block without interpolating .env / exposing Compose secrets.
    text = (Path(__file__).parents[1] / "docker-compose.yml").read_text()
    service = text.split("  dashboard:\n",1)[1].split("  dashboard-proxy:\n",1)[0]
    assert 'networks: [dash-net]' in service
    assert 'red-net' not in service and 'docker.sock' not in service and 'ports:' not in service
    assert '_TOKEN' not in service and 'GATEWAY_KEY' not in service
    assert 'audit-logs:/audit-logs:ro' in service
    assert './eval/output:/saved/eval/output:ro' in service
    assert 'dash-net:\n    driver: bridge\n    internal: true' in text
    assert '127.0.0.1:${DASHBOARD_PORT:-8090}:8000' in text


def test_worker_guard_cannot_run_raw_by_accident(tmp_path, monkeypatch):
    import asyncio
    from dashboard.app import Job
    from dashboard.worker import Worker
    monkeypatch.delenv("EVAL_MODE",raising=False)
    monkeypatch.setattr("dashboard.worker.matrix_active",lambda:False)
    worker = Worker(tmp_path)
    asyncio.run(worker.execute(Job(action="traffic",policy="raw")))
    assert worker.state["status"] == "blocked"
    # A failed isolation check must remain FAIL, not get swallowed as NOT RUN.
    from types import SimpleNamespace
    from dashboard.data import ISOLATION_CASES
    def fake_docker(command, **kwargs):
        assert "compose" not in command  # no automatic .env loading
        if command[1] == "ps":
            return SimpleNamespace(returncode=0,stdout="abcdef012345\n")
        if command[1] == "inspect":
            return SimpleNamespace(returncode=0,stdout="172.25.0.2\n")
        return SimpleNamespace(returncode=1,stdout="\n".join(("FAIL" if i == 0 else "PASS")+"  "+name for i,name in enumerate(ISOLATION_CASES)))
    monkeypatch.setattr("dashboard.worker.subprocess.run", fake_docker)
    worker.isolation()
    assert worker.state["scenarios"]["isolation"]["status"] == "FAIL"
    assert len(worker.state["scenarios"]["isolation"]["rows"]) == 11


def test_job_completion_is_correlated_and_failure_cannot_reuse_old_pass(tmp_path, monkeypatch):
    import asyncio
    from dashboard.app import Job
    from dashboard.worker import Worker
    from dashboard.data import public_observations
    monkeypatch.setattr("dashboard.worker.matrix_active", lambda: False)
    worker = Worker(tmp_path)
    worker.state["scenarios"]["isolation"] = dict(status="PASS", rows=[dict(name="Docker socket absent", result="PASS")])
    def unavailable():
        assert worker.state["job"]["finished_at"] is None
        raise RuntimeError("private diagnostic must not be published")
    monkeypatch.setattr(worker, "isolation", unavailable)
    job_id = "a"*32
    asyncio.run(worker.execute(Job(action="isolation"), job_id))
    projected = public_observations(tmp_path / "observations/state.json")
    assert projected["job"]["id"] == job_id
    assert projected["job"]["finished_at"] >= projected["job"]["started_at"]
    assert projected["status"] == "failed"
    assert projected["scenarios"]["isolation"]["rows"] == []
    assert projected["scenarios"]["isolation"]["recorded_at"] is not None
    assert "private diagnostic" not in json.dumps(projected)
