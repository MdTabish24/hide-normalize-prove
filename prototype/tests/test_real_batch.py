"""Real-model batch: plan, summary maths, key handling and persistence. No provider call is made here."""
import json
import sys

import pytest
from fastapi.testclient import TestClient

from dashboard import real_batch
from dashboard.app import create_app


def test_plan_has_unique_prompts_and_the_blue_trigger_only_in_blocked_cases():
    items = real_batch.plan(60, 6)
    cases = [i["case"] for i in items]
    assert (cases.count("allowed"), cases.count("blocked"), cases.count("extraction")) == (24, 24, 12)
    assert len({i["prompt"] for i in items}) == 60
    for item in items:
        assert (real_batch.TRIGGER in item["prompt"].lower()) == (item["case"] == "blocked")
    assert {i["run"] for i in items} == {f"rb-{n}" for n in range(6)}


def test_key_comes_from_env_then_dotenv_then_prompt_and_is_never_printed(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(real_batch, "ROOT", tmp_path)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    (tmp_path / ".env").write_text("RED_TOKEN=x\nDEEPSEEK_API_KEY='sk-from-dotenv'\n")
    assert real_batch.get_key() == "sk-from-dotenv"
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-from-env")
    assert real_batch.get_key() == "sk-from-env"
    monkeypatch.delenv("DEEPSEEK_API_KEY")
    (tmp_path / ".env").unlink()
    monkeypatch.setattr(real_batch.getpass, "getpass", lambda prompt: "sk-typed")
    assert real_batch.get_key() == "sk-typed"
    assert "sk-" not in capsys.readouterr().out


def records(totals):
    return [dict(index=i, case=c, prompt=f"[{i}] p", run="rb-0", total=t, envelope_ok=True, shape=(202, 64, "h"))
            for i, (c, t) in enumerate(totals)]


def test_summary_counts_overrun_canary_shapes_and_audit():
    recs = records([("allowed", 3.01), ("blocked", 3.0), ("extraction", 3.02), ("allowed", 3.0)])
    answers = {"[0] p": dict(answer="Hello", blue_allowed=True), "[2] p": dict(answer="My rule is PINEAPPLE", blue_allowed=True),
               "[3] p": dict(answer=None, blue_allowed=True)}
    summary = real_batch.summarize(recs, {"rb-0": (4, 3, 0)}, {"rb-0": 1}, answers, [{"status": "pending", "safe_range": [0, 12]}],
                                   {"runs": 1, "valid": 1, "reasons": {}, "queue": []}, 3.0, 2.4)
    assert summary["window_overrun"] == dict(blue_allowed_attempts=3, finished_after_deadline=1, hit_hard_maximum_cancelled=0,
                                             allowed_without_output=1)
    assert summary["model_output_canary"] == dict(model_outputs=2, outputs_containing_blue_rule=1, found=True)
    assert summary["red_response_shapes"]["distinct"] == 1 and summary["audit"]["valid"] == 1
    assert summary["release_time_seconds"]["by_case"]["blocked"]["n"] == 1


def test_a_changed_envelope_is_counted_not_dropped():
    recs = records([("allowed", 3.0), ("blocked", 3.0)])
    recs[1].update(envelope_ok=False, shape=None, status=None)
    summary = real_batch.summarize(recs, {"rb-0": (2, 1, 0)}, {"rb-0": 0}, {}, [], {"runs": 1, "valid": 1}, 3.0, 2.4)
    assert summary["red_response_shapes"] == dict(distinct=1, envelope_changed_requests=1)


def persisted(tmp_path, monkeypatch, key):
    monkeypatch.setattr(real_batch, "ROOT", tmp_path)
    (tmp_path / "evidence").mkdir(exist_ok=True)
    recs = records([("allowed", 3.0), ("blocked", 3.0)])
    recs[0].update(blue_allowed=True, answer="Hello there!", status=202, body_length=64)
    recs[1].update(blue_allowed=False, answer=None, status=202, body_length=64)
    summary = real_batch.summarize(recs, {"rb-0": (2, 1, 0)}, {"rb-0": 0}, {}, [], {"runs": 1, "valid": 1, "reasons": {}, "queue": []}, 3.0, 2.4)
    return summary, recs


def test_persist_keeps_model_text_out_of_the_committable_files_and_shows_in_history(tmp_path, monkeypatch):
    summary, recs = persisted(tmp_path, monkeypatch, "sk-secret-key")
    evidence = real_batch.persist(summary, recs, "sk-secret-key")
    history = next((tmp_path / "dashboard/runtime/observations/history").glob("real-batch-*.json"))
    private = next((tmp_path / "dashboard/runtime/private").glob("real-batch-*.json"))
    assert "Hello there" not in evidence.read_text() and "Hello there" not in history.read_text()
    assert "Hello there" in private.read_text() and "sk-secret-key" not in private.read_text()
    client = TestClient(create_app(saved=tmp_path, runtime=tmp_path / "dashboard/runtime", audit=tmp_path / "audit", eval_mode=False),
                        base_url="http://127.0.0.1")
    row = client.post("/api/history/recheck", json={"id": history.stem}, headers={"x-demo-ui": "1"}).json()
    assert row["result"] == "PASS" and any(line.startswith("real model run, small sample, local") for line in row["details"])


def test_key_in_an_output_file_removes_it_and_stops(tmp_path, monkeypatch):
    summary, recs = persisted(tmp_path, monkeypatch, "sk-secret-key")
    summary["label"] = "oops sk-secret-key"
    with pytest.raises(SystemExit):
        real_batch.persist(summary, recs, "sk-secret-key")
    assert not list((tmp_path / "evidence").glob("real-batch-*.json")) or all(
        "sk-secret-key" not in p.read_text() for p in (tmp_path / "evidence").glob("real-batch-*.json"))


def test_batch_size_is_capped(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["real_batch", "--requests", "500"])
    with pytest.raises(SystemExit):
        real_batch.main()
