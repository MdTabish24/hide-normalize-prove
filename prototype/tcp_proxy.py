"""Host -> gateway TCP forwarder. Holds no tokens or keys; lets the gateway stay internal-only.

Docker publishes no ports for containers attached only to internal networks, so
this sidecar owns the host binding and the gateway keeps zero internet egress.
"""
import asyncio
import os


TARGET = os.getenv("PROXY_TARGET", "gateway:8000")


async def pipe(reader, writer):
    try:
        while data := await reader.read(65536):
            writer.write(data)
            await writer.drain()
    except (ConnectionError, OSError):
        pass
    finally:
        writer.close()


async def handle(client_reader, client_writer):
    host, port = TARGET.rsplit(":", 1)
    try:
        upstream_reader, upstream_writer = await asyncio.open_connection(host, int(port))
    except OSError:
        client_writer.close()
        return
    await asyncio.gather(pipe(client_reader, upstream_writer), pipe(upstream_reader, client_writer))


async def main():
    server = await asyncio.start_server(handle, "0.0.0.0", 8000)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
