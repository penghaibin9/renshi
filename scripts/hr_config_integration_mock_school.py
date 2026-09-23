#!/usr/bin/env python3
"""Tiny local school-side mock used only by the V1 acceptance gate.

It deliberately exposes no production credential logic.  The goal is to prove
that Integration Hub performs a real network probe against an allow-listed host
while keeping all HR01-HR18 business modules untouched.
"""
from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOST = os.getenv("HR_V1_MOCK_HOST", "127.0.0.1")
PORT = int(os.getenv("HR_V1_MOCK_PORT", "9011"))


class Handler(BaseHTTPRequestHandler):
    server_version = "YuekeHRMock/1.0"

    def _write(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - stdlib callback name
        if self.path in {"/health", "/masterdata/health"}:
            self._write(200, {"status": "ok", "service": "mock-master-data"})
            return
        self._write(404, {"error": "not_found"})

    def do_POST(self) -> None:  # noqa: N802 - stdlib callback name
        if self.path != "/masterdata/staff/echo":
            self._write(404, {"error": "not_found"})
            return
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8"))
        except Exception:
            self._write(400, {"error": "invalid_json"})
            return
        self._write(200, {"status": "ok", "echo": payload})

    def log_message(self, fmt: str, *args) -> None:
        print(f"mock-school {self.address_string()} {fmt % args}", flush=True)


if __name__ == "__main__":
    print(f"mock school endpoint listening on http://{HOST}:{PORT}", flush=True)
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
