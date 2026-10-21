"""Contract tests use MockTransport; they do NOT claim a successful real API call."""
import asyncio
import json

import httpx
import pytest

from provider import create_app, ENDPOINT
from provider_proxy import handle, public_address

CONFIG = {"DEEPSEEK_API_KEY":"test-provider-credential-not-real", "SERVICE_TOKEN":"private-adapter-test-token"}


def test_provider_contract_fresh_context_token_cap_and_ignored_delay():
    calls=[]
    async def upstream(request):
        assert str(request.url)==ENDPOINT
        assert request.headers["authorization"]=="Bearer "+CONFIG["DEEPSEEK_API_KEY"]
        calls.append(json.loads(request.content))
        return httpx.Response(200,json={"choices":[{"message":{"content":"actual upstream response fixture"}}],
                                       "usage":{"prompt_tokens":20,"completion_tokens":5,"private":"discard"}})
    async def scenario():
        app=create_app(CONFIG,httpx.MockTransport(upstream))
        async with app.router.lifespan_context(app),httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://adapter") as client:
            for _ in range(2):
                response=await client.post("/generate",headers={"authorization":"Bearer "+CONFIG["SERVICE_TOKEN"]},
                    json={"role":"red","run_id":"r","prompt":"Hello","sim_delay":30})
                assert response.json()==dict(answer="actual upstream response fixture",backend="DeepSeek",model="deepseek-flash",usage={"prompt_tokens":20,"completion_tokens":5})
            assert (await client.post("/generate",json={"role":"red","run_id":"r","prompt":"Hello"})).status_code==403
    asyncio.run(scenario())
    assert len(calls)==2
    for call in calls:
        assert call["max_tokens"]==128 and call["stream"] is False and call["thinking"]=={"type":"disabled"}
        assert [m["role"] for m in call["messages"]]==["system","user"]
        assert "sim_delay" not in call and CONFIG["DEEPSEEK_API_KEY"] not in json.dumps(call)
    assert calls[0]["messages"][0] != calls[1]["messages"][0]


@pytest.mark.parametrize("status",[401,429,503,302])
def test_provider_errors_are_generic_and_retry_is_bounded(status):
    calls=[]
    def upstream(request):
        calls.append(1)
        return httpx.Response(status,text="private upstream diagnostic "+CONFIG["DEEPSEEK_API_KEY"])
    async def scenario():
        app=create_app(CONFIG,httpx.MockTransport(upstream))
        async with app.router.lifespan_context(app),httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://adapter") as client:
            response=await client.post("/generate",headers={"authorization":"Bearer "+CONFIG["SERVICE_TOKEN"]},
                                       json={"role":"red","run_id":"r","prompt":"Hello"})
            assert response.status_code==502 and response.json()=={"detail":"Model unavailable"}
    asyncio.run(scenario())
    assert len(calls)==(2 if status in (429,503) else 1)


def test_missing_key_fails_instead_of_falling_back_to_mock():
    with pytest.raises(ValueError):
        create_app({"SERVICE_TOKEN":"private-adapter-test-token"})


@pytest.mark.parametrize("address",["127.0.0.1","10.1.2.3","169.254.169.254","192.168.1.2","::1","fc00::1"])
def test_proxy_forbids_private_destinations(address):
    assert not public_address(address)


def test_proxy_rejects_arbitrary_targets_and_missing_auth_without_network():
    async def scenario():
        tasks=[]
        def accept(reader,writer):
            tasks.append(asyncio.create_task(handle(reader,writer,"private-proxy-test-token")))
        server=await asyncio.start_server(accept,"127.0.0.1",0)
        try:
            for target in ("example.com:443","127.0.0.1:8000","api.deepseek.com:443"):
                reader,writer=await asyncio.open_connection("127.0.0.1",server.sockets[0].getsockname()[1])
                writer.write(("CONNECT "+target+" HTTP/1.1\r\nHost: "+target+"\r\n\r\n").encode());await writer.drain()
                assert (await reader.read()).startswith(b"HTTP/1.1 403")
                writer.close();await writer.wait_closed()
        finally:
            server.close();await server.wait_closed()
            await asyncio.gather(*tasks)
    asyncio.run(scenario())


def test_proxy_relays_https_with_authenticated_connect_and_end_to_end_tls(tmp_path,monkeypatch):
    """Local TLS fixture only. Neither DNS nor traffic leaves the machine."""
    import datetime
    import ssl
    import socket
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes,serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    import provider_proxy
    key=ec.generate_private_key(ec.SECP256R1())
    name=x509.Name([x509.NameAttribute(x509.NameOID.COMMON_NAME,'api.deepseek.com')])
    now=datetime.datetime.now(datetime.timezone.utc)
    cert=(x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
          .serial_number(x509.random_serial_number()).not_valid_before(now-datetime.timedelta(minutes=1))
          .not_valid_after(now+datetime.timedelta(days=1))
          .add_extension(x509.SubjectAlternativeName([x509.DNSName('api.deepseek.com')]),False)
          .add_extension(x509.BasicConstraints(ca=True,path_length=None),True).sign(key,hashes.SHA256()))
    cert_path,key_path=tmp_path/'fixture.pem',tmp_path/'fixture-key.pem'
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
    server_tls=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);server_tls.load_cert_chain(cert_path,key_path)
    client_tls=ssl.create_default_context(cafile=str(cert_path))
    async def scenario():
        observed=[];tasks=[]
        async def api(reader,writer):
            headers=await reader.readuntil(b'\r\n\r\n')
            observed.append(headers)
            body=b'{"fixture":"https tunnel works"}'
            writer.write(b'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: '+str(len(body)).encode()+b'\r\nConnection: close\r\n\r\n'+body)
            await writer.drain();writer.close();await writer.wait_closed()
        api_server=await asyncio.start_server(api,'127.0.0.1',0,ssl=server_tls)
        api_port=api_server.sockets[0].getsockname()[1]
        original_open=asyncio.open_connection
        original_resolve=asyncio.get_running_loop().getaddrinfo
        async def resolve(host,port,*args,**kwargs):
            if host=='api.deepseek.com':
                return [(socket.AF_INET,socket.SOCK_STREAM,6,'',('93.184.216.34',443))]
            return await original_resolve(host,port,*args,**kwargs)
        async def connect(host,port,*args,**kwargs):
            if host=='93.184.216.34' and port==443:
                return await original_open('127.0.0.1',api_port)
            assert host=='127.0.0.1', 'No external network in this contract test'
            return await original_open(host,port,*args,**kwargs)
        monkeypatch.setattr(asyncio.get_running_loop(),'getaddrinfo',resolve)
        monkeypatch.setattr(provider_proxy.asyncio,'open_connection',connect)
        def accept(reader,writer):
            tasks.append(asyncio.create_task(handle(reader,writer,'private-proxy-test-token')))
        proxy_server=await asyncio.start_server(accept,'127.0.0.1',0)
        proxy_port=proxy_server.sockets[0].getsockname()[1]
        try:
            proxy=httpx.Proxy(f'http://127.0.0.1:{proxy_port}',auth=('model','private-proxy-test-token'))
            async with httpx.AsyncClient(proxy=proxy,verify=client_tls,trust_env=False,timeout=3) as client:
                response=await client.get(ENDPOINT,headers={'authorization':'Bearer fixture-not-a-real-provider-key'})
                assert response.json()=={'fixture':'https tunnel works'}
            assert observed[0].startswith(b'GET /chat/completions HTTP/1.1')
            assert b'fixture-not-a-real-provider-key' in observed[0]
            assert b'proxy-authorization' not in observed[0].lower()
        finally:
            proxy_server.close();api_server.close()
            await proxy_server.wait_closed();await api_server.wait_closed()
            await asyncio.wait_for(asyncio.gather(*tasks),3)
    asyncio.run(scenario())
