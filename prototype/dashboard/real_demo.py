"""Secure terminal launcher for the real-model operator demo."""
import argparse
import asyncio
import getpass
import os
from pathlib import Path
import subprocess
import sys

from .story_demo import serve


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port",type=int,default=8091)
    parser.add_argument("--docker",action="store_true",help="Also build/start the real-provider Docker stack; Engine must already be running")
    args=parser.parse_args()
    if args.docker:
        result=subprocess.run(["docker","info","--format","{{.ServerVersion}}"],capture_output=True,timeout=15)
        if result.returncode:
            raise SystemExit("Docker Linux Engine unavailable. Start Docker Desktop/service from an elevated Windows session, then retry.")
    if not os.environ.get("DEEPSEEK_API_KEY"):
        os.environ["DEEPSEEK_API_KEY"]=getpass.getpass("DeepSeek API key (hidden, this process only): ").strip()
    if not os.environ.get("DEEPSEEK_API_KEY"):
        raise SystemExit("Key missing. No model call or mock fallback.")
    if args.docker:
        root=Path(__file__).resolve().parents[1]
        # Generate only local role/audit credentials; never write the provider key.
        initializer=[sys.executable,"init_env.py"] + (["--add-audit"] if (root/".env").exists() else [])
        subprocess.run(initializer,cwd=root,check=True)
        result=subprocess.run(["docker","compose","-f","docker-compose.yml","-f","docker-compose.real.yml","up","-d","--build"],cwd=root)
        if result.returncode:
            raise SystemExit("Docker startup failed; no isolation result asserted.")
        from manage import env_file
        from .real_run import configure_docker
        config=env_file()
        port=int(os.getenv("GATEWAY_PORT",config.get("GATEWAY_PORT","8000")))
        configure_docker(f"http://127.0.0.1:{port}",{k:config[k] for k in ("RED_TOKEN","BLUE_TOKEN","EVALUATOR_TOKEN")})
    print("Select Live DeepSeek, then Run test now. " + ("Uses the Docker gateway; isolation is a separate test." if args.docker else "Uses localhost subprocesses; not Docker isolation."),flush=True)
    try:
        asyncio.run(serve(args.port,Path(__file__).parent/"runtime/real-operator"))
    except KeyboardInterrupt:
        pass


if __name__=="__main__":
    main()
