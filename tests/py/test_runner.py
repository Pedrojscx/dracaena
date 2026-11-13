"""Runner offline: Chromium local, CDP local e Claude injetado."""

from __future__ import annotations

import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

from fx import REPO, BrowserCase

from dracaena.core import runner


class RunnerTests(BrowserCase):
    def serve(self, name):
        root = REPO / "tests" / "fixtures" / "compat"
        handler = lambda *a, **kw: SimpleHTTPRequestHandler(*a, directory=str(root), **kw)
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.shutdown)
        self.addCleanup(server.server_close)
        return f"http://127.0.0.1:{server.server_address[1]}/{name}"

    def cdp(self):
        server = self.browser.new_browser_cdp_session()
        info = server.send("Browser.getVersion")
        # O endpoint do navegador de testes é exposto pelo servidor HTTP CDP interno.
        return self.browser.contexts[0].pages[0]

    def test_dry_run_keeps_dom_and_uses_guard(self):
        page = self.browser.new_page()
        try:
            page.goto(self.serve("dropdown.html"))
            before = page.content()
            logs = []
            # O navegador lançado pela fixture não oferece porta CDP pública; testamos o laço
            # com uma fábrica mínima que entrega a conexão existente.
            class PW:
                chromium = type("Chromium", (), {"connect_over_cdp": lambda _, __: type("B", (), {"contexts": self.browser.contexts, "close": lambda _: None})()})()
                def __enter__(_): return _
                def __exit__(_, *a): return None
            answer = lambda *_a, **_k: ('{"type":"DROPDOWN","items":[{"item":0,"option":0},{"item":1,"option":0},{"item":2,"option":0}]}', 0.0)
            self.assertEqual(runner.run(1, "dropdown.html", ask=answer, log=logs.append, playwright_factory=lambda: PW()), 0)
            self.assertEqual(page.content(), before)
            self.assertTrue(any("(dry-run) faria:" in line for line in logs))
        finally:
            page.close()

    def test_unsupported_exits_cleanly(self):
        page = self.browser.new_page()
        try:
            page.goto(self.serve("mcq_single.html"))
            logs = []
            class PW:
                chromium = type("Chromium", (), {"connect_over_cdp": lambda _, __: type("B", (), {"contexts": self.browser.contexts, "close": lambda _: None})()})()
                def __enter__(_): return _
                def __exit__(_, *a): return None
            self.assertEqual(runner.run(1, "mcq_single.html", log=logs.append, playwright_factory=lambda: PW()), 0)
            self.assertIn("parada: não suportado", logs)
        finally:
            page.close()

    def test_real_requires_explicit_cli_flag(self):
        calls = []
        original = runner.run
        runner.run = lambda *args, **kwargs: calls.append((args, kwargs)) or 0
        try:
            self.assertEqual(runner.main(["--port", "1", "--url-contains", "x"]), 0)
            self.assertTrue(calls[0][1]["dry_run"])
            self.assertEqual(runner.main(["--port", "1", "--url-contains", "x", "--real"]), 0)
            self.assertFalse(calls[1][1]["dry_run"])
        finally:
            runner.run = original
