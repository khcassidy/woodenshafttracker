#!/usr/bin/env python
"""Entry point: `python run.py [--reload] [--port 8765]`.

Prints the LAN URL on startup, so a phone or tablet on the same home
network can reach the entry grid at the bench.
"""

from __future__ import annotations

import argparse
import socket

import uvicorn

from app import settings


def _lan_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reload", action="store_true")
    parser.add_argument("--port", type=int, default=settings.PORT)
    parser.add_argument("--host", default=settings.HOST)
    args = parser.parse_args()

    url_host = _lan_ip() if args.host == "0.0.0.0" else args.host
    print(f"Shaft Tracker: http://{url_host}:{args.port}")

    uvicorn.run("app.main:app", host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
