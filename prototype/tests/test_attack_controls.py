"""Evaluation-only negative controls must be inert outside EVAL_MODE."""
import asyncio
import time

import httpx

import model


def test_cache_namespace_off_requires_eval_mode(monkeypatch):
    monkeypatch.setenv("SERVICE_TOKEN", "test-model-service-token")
    monkeypatch.setenv("MISS_SECONDS", "0.05")
    monkeypatch.setenv("HIT_SECONDS", "0")
    monkeypatch.setenv("JITTER_SECONDS", "0")
    monkeypatch.setenv("CACHE_NAMESPACE", "off")

    async def second_run_time():
        model.cache.clear()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=model.app), base_url="http://model") as client:
            headers = {"authorization": "Bearer test-model-service-token"}
            for run_id in ("victim", "attacker"):
                start = time.perf_counter()
                await client.post("/generate", json={"prompt": "shared secret prefix", "run_id": run_id, "role": "red"},
                                  headers=headers)
            return time.perf_counter() - start

    monkeypatch.delenv("EVAL_MODE", raising=False)
    assert asyncio.run(second_run_time()) >= 0.045  # Namespaced: the other run's prefix is a miss.
    monkeypatch.setenv("EVAL_MODE", "1")
    assert asyncio.run(second_run_time()) < 0.04  # Control: shared cache, cross-run hit.
