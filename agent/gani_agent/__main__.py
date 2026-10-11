import argparse
import asyncio
import logging

from .server import build_router, serve


def main():
    ap = argparse.ArgumentParser(prog="gani-agent")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("-v", action="store_true")
    a = ap.parse_args()
    logging.basicConfig(level=logging.DEBUG if a.v else logging.INFO)
    asyncio.run(serve(build_router(), a.host, a.port))


if __name__ == "__main__":
    main()
