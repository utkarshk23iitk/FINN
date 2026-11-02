"""Vercel function: promised vs delivered for any NSE ticker, on demand.

GET /api/research?symbol=TITAN -> the same JSON the CLI writes. The CDN
keeps each answer for a day, so a second visitor costs nothing.
"""
import json
import os
import re
import sys
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

os.environ.setdefault("FINN_DATA_DIR", "/tmp/finn-data")  # the only writable place
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from finn import research  # noqa: E402

SYMBOL = re.compile(r"^[A-Z0-9&-]{1,20}$")


class handler(BaseHTTPRequestHandler):
    def _send(self, status: int, body: dict, cache: bool = False):
        data = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "public, s-maxage=86400, stale-while-revalidate=604800" if cache else "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        sym = (parse_qs(urlparse(self.path).query).get("symbol", [""])[0]).strip().upper().removesuffix(".NS")
        if not SYMBOL.match(sym):
            return self._send(400, {"error": "Give an NSE symbol, e.g. ?symbol=TITAN"})
        try:
            return self._send(200, research.review(sym), cache=True)
        except ValueError as exc:  # no such company, or no transcripts on screener.in
            return self._send(404, {"error": str(exc)})
        except Exception as exc:  # a source or the model is down: say so, don't cache it
            return self._send(502, {"error": f"{type(exc).__name__}: {str(exc)[:200]}"})
