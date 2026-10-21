"""Every request is saved: public metadata (no prompt/answer text) and a private answers file; the join and duplicate-finish safety."""
import asyncio
import json

from eval import real_records
from eval.live import Lab


def test_harvest_saves_public_metadata_and_private_answers_without_a_second_finish(tmp_path, monkeypatch):
    monkeypatch.setattr(real_records, "PUBLIC_DIR", tmp_path / "public")
    monkeypatch.setattr(real_records, "PRIVATE_DIR", tmp_path / "private")

    async def scenario():
        async with Lab(tmp_path / "lab", 0.05, "window_hard", audit=True, window_continue=True, window_seconds=0.45) as lab:
            world, run_id, requests = lab.worlds[0], "rec-run", []
            for index, prompt in enumerate(["pineapple orchard", "neutral river", "neutral stone"]):
                observation = await world.observe(run_id, prompt)
                requests.append(dict(role="timing", world=0, run_id=run_id, index=index, case="x", client=observation))
            await world.finish(run_id)
            summary = await real_records.harvest(lab, requests, "unit", save=True)
            audit = await lab.audit_check({0: [run_id]}, drain_seconds=10)
            return summary, audit
    summary, audit = asyncio.run(scenario())
    assert summary["requests"] == 3 and summary["joined_with_evaluator"] == 3 and summary["runs_unavailable"] == 0
    assert audit["valid"] == 1  # harvest without finish leaves the audit chain valid
    public = [json.loads(line) for line in (tmp_path / "public/unit.jsonl").read_text().splitlines()]
    private = [json.loads(line) for line in (tmp_path / "private/unit-answers.jsonl").read_text().splitlines()]
    assert [p["evaluator"]["blue_allowed"] for p in public] == [False, True, True]  # the first prompt contains world 0's keyword
    text = json.dumps(public)
    assert "orchard" not in text and "Dummy answer" not in text and "prompt" not in text and "answer\"" not in text  # no text in the public file
    assert all(p["evaluator"]["answer_sha256"] for p in public[1:]) and public[0]["evaluator"]["answer_sha256"] is None
    assert [p["prompt"] for p in private] == ["pineapple orchard", "neutral river", "neutral stone"] and private[1]["answer"] == "Dummy answer."
    assert set(public[0]["client"]) >= {"status", "body_length", "header_fingerprint", "total", "started_at"}


def test_a_run_whose_record_count_does_not_match_is_flagged_not_guessed(tmp_path, monkeypatch):
    monkeypatch.setattr(real_records, "PUBLIC_DIR", tmp_path / "public")
    monkeypatch.setattr(real_records, "PRIVATE_DIR", tmp_path / "private")

    async def scenario():
        async with Lab(tmp_path / "lab", 0.05, "window_hard", audit=False, window_continue=True, window_seconds=0.45) as lab:
            world, run_id = lab.worlds[0], "mismatch-run"
            observation = await world.observe(run_id, "neutral river")
            await world.finish(run_id)
            ghost = dict(role="timing", world=0, run_id=run_id, index=1, case="x", client=observation)  # a request the gateway never recorded
            real = dict(role="timing", world=0, run_id=run_id, index=0, case="x", client=observation)
            return await real_records.harvest(lab, [real, ghost], "mismatch", save=False)
    summary = asyncio.run(scenario())
    assert summary["runs_with_count_mismatch"] == 1 and summary["joined_with_evaluator"] == 0
