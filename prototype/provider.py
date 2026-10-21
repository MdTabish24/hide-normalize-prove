"""Private, stateless DeepSeek adapter. No credentials or model text in logs."""
import asyncio
from contextlib import asynccontextmanager
import os
import secrets

import httpx
from fastapi import FastAPI, HTTPException, Request

from model import Generate

DEFAULT_MODEL = "deepseek-flash"
ENDPOINT = "https://api.deepseek.com/chat/completions"


def create_app(settings=None, transport=None):
    config = dict(os.environ if settings is None else settings)
    api_key = config.get("DEEPSEEK_API_KEY", "")
    token = config.get("SERVICE_TOKEN", "")
    if not api_key or len(token) < 16:
        raise ValueError("DEEPSEEK_API_KEY and private SERVICE_TOKEN required")
    model_name = config.get("DEEPSEEK_MODEL", DEFAULT_MODEL)
    if model_name not in ("deepseek-flash", "deepseek-v4-pro"):
        raise ValueError("Unsupported DeepSeek model")
    max_tokens = int(config.get("MAX_OUTPUT_TOKENS", "128"))
    timeout = float(config.get("PROVIDER_TIMEOUT_SECONDS", "6"))
    if not 1 <= max_tokens <= 512 or not 0 < timeout <= 60:
        raise ValueError("Invalid provider limits")
    proxy = None
    if config.get("PROVIDER_PROXY_URL"):
        proxy = httpx.Proxy(config["PROVIDER_PROXY_URL"], auth=("model", token))

    @asynccontextmanager
    async def lifespan(app):
        async with httpx.AsyncClient(transport=transport, proxy=proxy, trust_env=False,
                                     follow_redirects=False, timeout=timeout) as client:
            app.state.client = client
            yield

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    @app.post("/generate")
    async def generate(body: Generate, request: Request):
        if not secrets.compare_digest(request.headers.get("authorization", ""), "Bearer " + token):
            raise HTTPException(403, "Unavailable")
        # No shared conversation/history, no tools, no user-controlled system role.
        # Random first-message salt reduces prefix reuse; it is NOT a hosted KV reset.
        payload = dict(model=model_name, max_tokens=max_tokens, stream=False,
                       thinking={"type": "disabled"}, messages=[
                           {"role": "system", "content": secrets.token_hex(32) + "\nAnswer the user's request briefly. This is an independent test."},
                           {"role": "user", "content": body.prompt}])
        try:
            async with asyncio.timeout(timeout):
                for attempt in range(2):
                    async with app.state.client.stream("POST", ENDPOINT,
                            headers={"authorization": "Bearer " + api_key}, json=payload) as response:
                        if response.status_code in (429, 503) and attempt == 0:
                            retry = True
                        else:
                            response.raise_for_status()
                            content = bytearray()
                            async for chunk in response.aiter_bytes():
                                content.extend(chunk)
                                if len(content) > 131072:
                                    raise ValueError("Provider response too large")
                            import json
                            data = json.loads(content)
                            answer = data["choices"][0]["message"]["content"]
                            if not isinstance(answer, str) or not answer.strip() or len(answer.encode()) > 20000:
                                raise ValueError("Invalid provider output")
                            usage = data.get("usage", {})
                            usage = {k: v for k, v in usage.items() if k in (
                                "prompt_tokens", "completion_tokens", "prompt_cache_hit_tokens", "prompt_cache_miss_tokens") and type(v) is int and v >= 0}
                            return dict(answer=answer, backend="DeepSeek", model=model_name, usage=usage)
                    if retry:
                        await asyncio.sleep(.15 + secrets.randbelow(100)/1000)
        except (Exception, asyncio.TimeoutError):
            # Never reflect upstream error bodies, URLs or exceptions to callers.
            raise HTTPException(502, "Model unavailable") from None
        raise HTTPException(502, "Model unavailable")

    return app


def factory():
    return create_app()
