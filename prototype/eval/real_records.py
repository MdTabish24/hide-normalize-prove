"""Save EVERY request of a step so the final report can show all of it (PARAMS.md v6).

Public file (committable): one JSON line per request with what Red saw (status, size, header fingerprint, release times, start time) and what the evaluator knows
(Blue's decision, cancelled, backend, model, token usage, the length and SHA-256 of the answer). No prompt text, no answer text, no keys.
Private file (git-ignored, under dashboard/runtime/private): the prompt and the full model answer for the same request.
The join uses the order of requests inside a run (every run sends sequentially); if the evaluator returns a different number of records the run is flagged, not guessed.
"""
import asyncio
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PUBLIC_DIR = ROOT / "eval/output/real_overnight/requests"
PRIVATE_DIR = ROOT / "dashboard/runtime/private/real_overnight"


def client_view(observation):
    return {k: (round(v, 4) if isinstance(v, float) else v) for k, v in observation.items()
            if k in ("status", "body_length", "header_fingerprint", "ttfb", "total", "started_at")}


async def fetch_records(world, run_id, finish):
    """Read the evaluator's decrypted records of a run; None if unavailable.

    finish=True first finishes the run (waits for background work in continue mode). NEVER finish a run twice: a second finish
    appends a duplicate run_finished event to its audit chain."""
    from common import PENDING
    if finish:
        await world.finish(run_id)
    response = await world.client.get(f"/v1/run/{run_id}/artifacts", headers=world.auth("evaluator"))
    if response.content == PENDING:
        return None
    try:
        return response.json().get("records")
    except ValueError:
        return None


async def harvest(lab, requests, tag, save=True, concurrency=16, finish=False):
    """requests: dicts with world, run_id, index, role, case, client (an observation dict) and optional extra fields.

    Returns a summary; writes <tag>.jsonl publicly and <tag>-answers.jsonl privately when save is true."""
    by_run = {}
    for request in requests:
        by_run.setdefault((request["world"], request["run_id"]), []).append(request)
    semaphore = asyncio.Semaphore(concurrency)
    fetched = {}

    async def one(world, run_id):
        async with semaphore:
            try:
                fetched[(world, run_id)] = await fetch_records(lab.worlds[world], run_id, finish)
            except Exception:  # A failed fetch is recorded as unavailable for that run, never hidden.
                fetched[(world, run_id)] = None
    await asyncio.gather(*(one(world, run_id) for world, run_id in by_run))
    public, private, joined, mismatched, unavailable = [], [], 0, 0, 0
    for (world, run_id), items in by_run.items():
        items.sort(key=lambda r: r["index"])
        records = fetched.get((world, run_id))
        ok = records is not None and len(records) == len(items)
        mismatched += int(records is not None and not ok)
        unavailable += int(records is None)
        for position, item in enumerate(items):
            line = {k: v for k, v in item.items() if k != "client"}
            line["client"] = client_view(item["client"])
            if ok:
                record = records[position]
                output = record.get("output") or {}
                answer = output.get("answer")
                line["evaluator"] = dict(blue_allowed=record.get("blue_allowed"), cancelled=record.get("cancelled"), backend=output.get("backend"),
                                         model=output.get("model"), usage=output.get("usage"), answer_chars=len(answer) if isinstance(answer, str) else None,
                                         answer_sha256=hashlib.sha256(answer.encode()).hexdigest() if isinstance(answer, str) else None)
                private.append(dict(run_id=run_id, index=item["index"], prompt=record.get("prompt"), answer=answer))
                joined += 1
            else:
                line["evaluator"] = None
            public.append(line)
    if save:
        PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
        PRIVATE_DIR.mkdir(parents=True, exist_ok=True)
        (PUBLIC_DIR / f"{tag}.jsonl").write_text("".join(json.dumps(line, separators=(",", ":")) + "\n" for line in public), encoding="utf-8")
        (PRIVATE_DIR / f"{tag}-answers.jsonl").write_text("".join(json.dumps(line, separators=(",", ":")) + "\n" for line in private), encoding="utf-8")
    answers = [p["answer"] for p in private if isinstance(p.get("answer"), str)]
    return dict(requests=len(public), joined_with_evaluator=joined, runs=len(by_run), runs_unavailable=unavailable, runs_with_count_mismatch=mismatched,
                answers=len(answers), public_file=f"eval/output/real_overnight/requests/{tag}.jsonl" if save else None,
                private_file=f"dashboard/runtime/private/real_overnight/{tag}-answers.jsonl (git-ignored)" if save else None)
