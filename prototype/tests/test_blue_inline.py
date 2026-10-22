"""Opt-in BLUE_INLINE=1: the keyword rule runs inside the gateway; the Blue service never receives Red's prompt."""
import asyncio

from test_gateway import auth, client_for, configure, generic, settings, submit  # noqa: F401 (fixture)


def decisions(config, tag):
    calls, result = [], []

    async def scenario():
        async with client_for(config, calls) as (app, client):
            await configure(client, config)
            for index, prompt in enumerate(("hello orchard", "a PineApple here", "pineapple", "mango")):
                response, _ = await submit(client, config, prompt, f"{tag}{index}")
                generic(response)
            with app.state.store.connect() as db:
                result.extend(row[0] for row in db.execute("SELECT safe FROM attempts WHERE run_id LIKE ? ORDER BY id", (tag + "%",)))
    asyncio.run(scenario())
    return calls, result


def test_inline_decisions_equal_the_service_and_the_service_is_never_called(settings):
    service_calls, service_result = decisions(dict(settings), "s")
    inline_calls, inline_result = decisions(dict(settings, BLUE_INLINE="1"), "i")
    assert inline_result == service_result == [1, 0, 0, 1]  # casefolded substring: same decisions
    assert any(host == "blue-defense" for host, _ in service_calls)
    assert not any(host == "blue-defense" for host, _ in inline_calls)  # no Blue-side request at all
    assert any(host == "model-mock" for host, _ in inline_calls)  # allowed prompts still reach the model
