"""Demo telemetry is explicit, private, bounded and absent by default."""
import asyncio
import json

from test_gateway import settings, client_for, configure, submit, generic


def test_trace_flag_alone_cannot_enable_private_telemetry(settings,tmp_path):
    async def scenario():
        async with client_for(dict(settings,DEMO_TRACE="1")) as (_,client):
            await configure(client,settings)
            response,_=await submit(client,settings,"pineapple")
            generic(response)
        assert not (tmp_path/'demo-trace.jsonl').exists()
    asyncio.run(scenario())


def test_opt_in_trace_records_actual_decision_and_only_known_mock_answer(settings,tmp_path):
    async def scenario():
        async with client_for(dict(settings,EVAL_MODE="1",DEMO_TRACE="1")) as (_,client):
            await configure(client,settings)
            for prompt in ('pineapple','hello'):
                response,_=await submit(client,settings,prompt)
                generic(response)
                assert b'keyword' not in response.content
        text=(tmp_path/'demo-trace.jsonl').read_text(encoding='utf-8')
        assert 'pineapple' not in text and 'hello' not in text
        a,b=[json.loads(line) for line in text.splitlines()]
        assert a['blue_allowed'] is False and a['reason']=='keyword_matched'
        assert a['model_called'] is False and a['model_answer'] is None
        assert b['blue_allowed'] is True and b['model_completed'] is True
        assert b['model_answer']=='Dummy answer.'
        assert a['compute_seconds']>=0 and a['released_seconds']>=a['scheduled_release_seconds']
    asyncio.run(scenario())
