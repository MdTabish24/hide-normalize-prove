"""Side-by-side view: projection from a recorded run only, no prompt text or keyword, NOT RUN / PARTIAL honesty, routes, recorder."""
import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from dashboard import duel, duel_run
from dashboard.app import create_app

SECRET_WORD = "pineapple"


def request(index, seconds, allowed, late=False):
    return dict(index=index, red=dict(status=202, body_length=64, release_seconds=seconds, envelope_exact=True),
                evaluator=dict(blue_allowed=allowed, model_called=allowed, model_completed=allowed, cancelled=False, late=late))


def recording(complete=True, with_ours=True):
    sequence = [dict(index=0, probe="Probe 1", case="blocked", group="keyword rule A type", prompt=f"{SECRET_WORD} orchard cloud", slow_compute=None),
                dict(index=1, probe="Probe 2", case="allowed", group="neutral", prompt="neutral orchard cloud", slow_compute=None)]
    raw = dict(name="raw", title="Bina defense", policy="raw", window_continue=False, feedback_mode="none", meter=None,
               requests=[request(0, 0.04, False), request(1, 0.27, True)], audit=dict(status="VALID", count=9))
    ours = dict(name="ours", title="Hamare solution", policy="window_hard", window_continue=True, feedback_mode="meter",
                requests=[request(0, 0.93, False), request(1, 0.92, True, late=True)], audit=dict(status="VALID", count=9),
                meter=dict(reads=[dict(after_probe=2, state="IMPROVING")], reads_used=1, reads_budget=3,
                           batches=[dict(batch=0, score=0.5, published="STABLE", true_state="STABLE")]))
    arms = dict(raw=raw, **(dict(ours=ours) if with_ours else {}))
    return dict(status="complete" if complete else "running", recorded_at=1792500000, sequence=sequence, arms=arms)


def saved_dir(tmp_path, **kwargs):
    observations = tmp_path / "obs"
    observations.mkdir(parents=True, exist_ok=True)
    (observations / "duel.json").write_text(json.dumps(recording(**kwargs)))
    return observations


def test_projection_has_no_prompt_text_or_rule_keyword_and_keeps_red_text_neutral(tmp_path):
    snapshot = duel.snapshot(tmp_path, saved_dir(tmp_path))
    assert snapshot["status"] == "RECORDED" and set(snapshot["arms"]) == {"raw", "ours"}
    dump = json.dumps(snapshot).lower()
    assert SECRET_WORD not in dump and "orchard" not in dump and "prompt" not in dump
    for arm in snapshot["arms"].values():
        for r in arm["requests"]:  # Red-visible fields never say which Blue decision happened
            assert "block" not in r["red"]["text"].lower() and "allow" not in r["red"]["text"].lower()
            assert r["red"]["text"].startswith("Red ko dikha: HTTP 202 pending")
    why = snapshot["arms"]["raw"]["requests"][0]["evaluator"]["why"]
    assert why == "Blocked: Blue ke keyword rule A match hua, model tak gaya hi nahi"


def test_timing_note_is_computed_from_the_recording_and_meter_reads_left_from_the_budget(tmp_path):
    snapshot = duel.snapshot(tmp_path, saved_dir(tmp_path))
    assert "gap 230 ms" in snapshot["arms"]["raw"]["timing"]
    assert "0.92-0.93 s" in snapshot["arms"]["ours"]["timing"]
    assert snapshot["arms"]["raw"]["meter"] is None
    meter = snapshot["arms"]["ours"]["meter"]
    assert meter["reads_left"] == 2 and meter["batches"][0]["score"] == 0.5
    late = snapshot["arms"]["ours"]["requests"][1]["evaluator"]
    assert "baad" in late["why"] and late["late"] is True


def test_missing_recording_is_not_run_and_partial_recording_hides_both_panels(tmp_path):
    empty = duel.snapshot(tmp_path, tmp_path / "nothing")
    assert empty["status"] == "NOT RUN" and empty["arms"] == {} and empty["sequence"] == []
    assert empty["accuracy"]["raw"]["status"] == "NOT RUN" and "NOT RUN" in empty["accuracy"]["ours"]["text"]
    partial = duel.snapshot(tmp_path, saved_dir(tmp_path, complete=False, with_ours=False))
    assert partial["status"] == "PARTIAL" and partial["arms"] == {}  # never fills the missing arm


def test_accuracy_comes_only_from_saved_matrix_cells(tmp_path):
    (tmp_path / "eval/output/round2").mkdir(parents=True)
    cells = [dict(cohort="ordinary", policy="raw", test_accuracy=0.985, wilson_95=[0.957, 0.995], test_runs=200, train_accuracy=1, train_test_gap=0)]
    (tmp_path / "eval/output/round2/results.json").write_text(json.dumps(dict(cells=cells, status="in_progress")))
    snapshot = duel.snapshot(tmp_path, tmp_path / "obs")
    assert snapshot["accuracy"]["raw"]["status"] == "SAVED" and "98%" in snapshot["accuracy"]["raw"]["text"]
    assert snapshot["accuracy"]["ours"]["status"] == "NOT RUN"
    assert [r["status"] for r in snapshot["chart"] if r["policy"] == "window_hard"] == ["NOT RUN"] * 5


def test_routes_serve_the_page_and_the_api_and_the_job_schema_accepts_duel(tmp_path):
    client = TestClient(create_app(saved=tmp_path, runtime=tmp_path / "runtime", audit=tmp_path / "a", eval_mode=False), base_url="http://127.0.0.1")
    page = client.get("/duel")
    assert page.status_code == 200 and "sbs.js" in page.text
    assert client.get("/api/duel").json()["status"] == "NOT RUN"
    # No worker is connected here: a valid "duel" job is refused as NOT RUN (409), not rejected as invalid input (400).
    response = client.post("/api/jobs", json={"action": "duel"}, headers={"x-demo-ui": "1"})
    assert response.status_code == 409


def test_sequence_is_fixed_and_the_meter_batches_have_different_outcomes():
    items = duel_run.sequence()
    assert len(items) == 20 and items[10]["prompt"] == items[2]["prompt"] and items[12]["slow_compute"]
    first = sum(i["case"] != "blocked" for i in items[:10]) / 10
    second = sum(i["case"] != "blocked" for i in items[10:]) / 10
    assert (first, second) == (0.2, 0.9)  # batch scores 0.2 then 0.9: STABLE, then IMPROVING


@pytest.mark.timing
def test_recorder_end_to_end_same_sequence_two_policies(tmp_path):
    path = tmp_path / "duel.json"
    result = asyncio.run(duel_run.run_duel(path))
    assert result["status"] == "complete" and set(result["arms"]) == {"raw", "ours"}
    raw, ours = (result["arms"][k] for k in ("raw", "ours"))
    assert len(raw["requests"]) == len(ours["requests"]) == 20 and raw["audit"]["status"] == "VALID" == ours["audit"]["status"]
    spread = lambda arm: max(r["red"]["release_seconds"] for r in arm["requests"]) - min(r["red"]["release_seconds"] for r in arm["requests"])  # noqa: E731
    assert spread(ours) < 0.15 < spread(raw)  # fixed window vs. leaking times
    assert all(r["red"]["envelope_exact"] for r in raw["requests"] + ours["requests"])
    assert [m["state"] for m in ours["meter"]["reads"]] == ["STABLE", "IMPROVING"] and raw["meter"] is None
    assert [r["evaluator"]["blue_allowed"] for r in raw["requests"]] == [r["evaluator"]["blue_allowed"] for r in ours["requests"]]
