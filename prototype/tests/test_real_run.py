"""Control-flow fixtures only, no real API request or real-model result claim."""
import asyncio
from contextlib import asynccontextmanager
import json

import httpx
import pytest

from common import HEADERS, PENDING
from dashboard import real_run


@pytest.mark.parametrize('decision',[False,None])
def test_real_demo_only_persists_hashes_and_never_calls_unknown_decision_blocked(tmp_path, monkeypatch, decision):
    from types import SimpleNamespace
    key="test-key-not-real"
    text="private-upstream-fixture-not-a-real-generation"
    monkeypatch.setenv("DEEPSEEK_API_KEY",key)
    monkeypatch.setattr(real_run,"_view",None)
    calls=[]
    @asynccontextmanager
    async def fixture_deployment(directory):
        def dispatch(request):
            calls.append(request.url.path)
            if request.url.path.endswith('/artifacts'):
                return httpx.Response(202,json={"records":[{"blue_allowed":decision,"output":None},{"blue_allowed":True,"output":{"backend":"DeepSeek","model":"deepseek-flash","answer":text}}]})
            return httpx.Response(202,content=PENDING,headers=HEADERS)
        async with httpx.AsyncClient(base_url='http://fixture',transport=httpx.MockTransport(dispatch)) as client:
            async def finish(rid):
                await client.post(f'/v1/run/{rid}/finish')
            async def checked(rid):
                return True
            yield SimpleNamespace(client=client,auth=lambda role:{},finish=finish),checked,'localhost subprocesses; not Docker isolation'
    monkeypatch.setattr(real_run,'deployment',fixture_deployment)
    path=tmp_path/'real.json'
    private=tmp_path/'private'
    if decision is False:
        result=asyncio.run(real_run.run_real(path,private))
        assert result['status']=='complete' and result['requests'][1]['answer']==text
    else:
        with pytest.raises(ValueError,match='defense setup not asserted'):
            asyncio.run(real_run.run_real(path))
        assert real_run.current_view()['status']=='failed'
    persisted=path.read_text()
    assert text not in persisted and key not in persisted
    assert len(json.loads(persisted)['requests'][1]['answer_sha256'])==64
    assert calls[-2].endswith('/finish') and calls[-1].endswith('/artifacts')
    # Dated hashes-only archive always; raw text only in the explicit private record (successful run).
    archives=list((tmp_path/'history').glob('real-*.json'))
    assert len(archives)==1 and text not in archives[0].read_text() and key not in archives[0].read_text()
    if decision is False:
        record=json.loads(next(private.glob('real-*.json')).read_text())
        assert record['requests'][1]['answer']==text and record['requests'][1]['prompt']=="Write one short greeting."
        assert key not in json.dumps(record) and record['run_id'].startswith('real-')


def test_real_lab_rejects_missing_key_before_starting_servers(tmp_path,monkeypatch):
    from eval.live import Lab
    monkeypatch.delenv('DEEPSEEK_API_KEY',raising=False)
    lab=Lab(tmp_path,backend='deepseek')
    with pytest.raises(ValueError,match='no mock fallback'):
        asyncio.run(lab.__aenter__())
    assert lab.servers==[]
