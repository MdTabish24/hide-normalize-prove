"""One-command local launcher for /story and its explicit operator worker."""
import argparse
import asyncio
from pathlib import Path

import uvicorn

from .worker import Worker, matrix_active


async def serve(port):
    if await asyncio.to_thread(matrix_active):
        raise SystemExit("Timing matrix active or status unavailable. Story server NOT STARTED.")
    worker = Worker(Path(__file__).parent / "runtime")
    server = uvicorn.Server(uvicorn.Config("dashboard.app:app", host="127.0.0.1", port=port,
                                         access_log=False, log_level="warning"))
    operator = asyncio.create_task(worker.serve())
    web = asyncio.create_task(server.serve())
    print(f"Story: http://127.0.0.1:{port}/story  |  Original dashboard: /", flush=True)
    try:
        done, _ = await asyncio.wait([web, operator], return_when=asyncio.FIRST_COMPLETED)
        if operator in done and not operator.cancelled():
            print("Operator stopped; closing the UI. Check local file access.", flush=True)
    finally:
        server.should_exit = True
        operator.cancel()
        await asyncio.gather(web, operator, return_exceptions=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8090)
    try:
        asyncio.run(serve(parser.parse_args().port))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
