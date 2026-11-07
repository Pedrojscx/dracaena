"""Servidor local das fixtures HTML + Chromium headless do Playwright.

As fixtures são servidas por HTTP (o shadow DOM declarativo só é montado
quando a página é carregada por URL) e recebem `sim.js` injetado antes de
`</body>`: o simulador do comportamento do NetAcad. Nada depende do NetAcad.
"""

from __future__ import annotations

import functools
import os
import subprocess
import sys
import threading
import unittest

from playwright.sync_api import sync_playwright
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
HTML = REPO / "tests" / "fixtures" / "html"
DERIVED = REPO / "tests" / "fixtures" / "out"
sys.path.insert(0, str(REPO / "lib"))


def build_derived() -> Path:
    script = REPO / "tests" / "fixtures" / "derived.py"
    stamp = DERIVED / "assessment.html"
    if not stamp.exists() or script.stat().st_mtime > stamp.stat().st_mtime:
        subprocess.run([sys.executable, str(script), str(DERIVED)], check=True, capture_output=True)
    return DERIVED


class _Handler(SimpleHTTPRequestHandler):
    roots: list[Path] = []

    def log_message(self, *args):  # silencioso
        pass

    def translate_path(self, path: str) -> str:
        name = path.split("?", 1)[0].lstrip("/")
        for root in self.roots:
            cand = root / name
            if cand.is_file():
                return str(cand)
        return str(self.roots[0] / name)

    def send_head(self):
        path = Path(self.translate_path(self.path))
        if path.suffix != ".html" or not path.is_file():
            return super().send_head()
        body = path.read_text(encoding="utf-8").replace("</body>", '<script src="/sim.js"></script></body>')
        data = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        import io
        return io.BytesIO(data)


class FixtureServer:
    def __init__(self):
        build_derived()
        handler = type("H", (_Handler,), {"roots": [HTML, DERIVED]})
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(handler))
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def url(self, name: str) -> str:
        return f"http://127.0.0.1:{self.port}/{name}"

    def close(self):
        self.httpd.shutdown()


def launch(p):
    """Chromium headless do Playwright (`playwright install --only-shell chromium`)."""
    return p.chromium.launch(headless=True, args=["--no-sandbox"] if os.geteuid() == 0 else [])


class BrowserFixtureCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = FixtureServer()
        cls.pw = sync_playwright().start()
        cls.browser = launch(cls.pw)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()
        cls.server.close()
