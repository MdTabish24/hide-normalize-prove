"""Authenticated CONNECT tunnel: only api.deepseek.com:443, public IPs only.

The model container stays on internal model-net. Only this small broker joins
the external provider network. TLS and provider authentication remain end to end.
"""
import asyncio
import base64
import ipaddress
import os
import secrets
import socket

TARGET = "api.deepseek.com:443"


def public_address(address):
    return ipaddress.ip_address(address).is_global


async def handle(reader, writer, token):
    upstream = None
    accepted = False
    try:
        headers = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 3)
        if len(headers) > 8192:
            raise ValueError("Oversized headers")
        lines = headers.decode("ascii").split("\r\n")
        if lines[0] != "CONNECT " + TARGET + " HTTP/1.1":
            raise ValueError("Forbidden target")
        auth = [line.split(":", 1)[1].strip() for line in lines[1:] if line.lower().startswith("proxy-authorization:")]
        expected = "Basic " + base64.b64encode(("model:" + token).encode()).decode()
        if len(auth) != 1 or not secrets.compare_digest(auth[0], expected):
            raise ValueError("Unauthorized")
        addresses = await asyncio.get_running_loop().getaddrinfo("api.deepseek.com", 443, type=socket.SOCK_STREAM)
        if not addresses or any(not public_address(item[4][0]) for item in addresses):
            raise ValueError("Non-public destination")
        remote, upstream = await asyncio.wait_for(asyncio.open_connection(addresses[0][4][0], 443), 5)
        writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        await writer.drain()
        accepted = True

        async def pipe(source, destination):
            while data := await source.read(16384):
                destination.write(data)
                await destination.drain()

        tasks = [asyncio.create_task(pipe(reader, upstream)), asyncio.create_task(pipe(remote, writer))]
        try:
            await asyncio.wait(tasks, timeout=60, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
    except Exception:
        if not accepted:
            writer.write(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
            try:
                await writer.drain()
            except ConnectionError:
                pass
    finally:
        if upstream:
            upstream.close()
        writer.close()
        try:
            await writer.wait_closed()
        except ConnectionError:
            pass


async def main():
    token = os.environ["SERVICE_TOKEN"]
    if len(token) < 16:
        raise ValueError("Private SERVICE_TOKEN required")
    semaphore = asyncio.Semaphore(16)

    async def bounded(reader, writer):
        if semaphore.locked():
            writer.close()
            return
        async with semaphore:
            await handle(reader, writer, token)

    server = await asyncio.start_server(bounded, "0.0.0.0", 3128, limit=8192)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
