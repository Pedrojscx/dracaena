"""Runner offline: Chromium local, CDP local e Claude injetado."""

from __future__ import annotations

import threading
import json
import stat
import tempfile
from pathlib import Path
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

from fx import REPO, BrowserCase

from dracaena.core import runner


class RunnerTests(BrowserCase):
    def test_review_cli_does_not_require_connection_flags(self):
        calls = []
        original = runner.review
        runner.review = lambda path: calls.append(path) or 0
        try:
            self.assertEqual(runner.main(["--revisar"]), 0)
            self.assertEqual(runner.main(["--revisar", "/tmp/revisao.jsonl"]), 0)
            self.assertEqual(str(calls[1]), "/tmp/revisao.jsonl")
        finally:
            runner.review = original

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

    def test_repeated_question_stops_after_one_dry_run_action(self):
        page = self.browser.new_page()
        try:
            page.goto(self.serve("quiz_mcq_single.html"))
            logs = []
            class PW:
                chromium = type("Chromium", (), {"connect_over_cdp": lambda _, __: type("B", (), {"contexts": self.browser.contexts, "close": lambda _: None})()})()
                def __enter__(_): return _
                def __exit__(_, *a): return None
            answer = lambda *_a, **_k: ('{"type":"SINGLE","answers":[0]}', 0.0)
            self.assertEqual(runner.run(1, "quiz_mcq_single.html", max_questions=3, wait_seconds=0, ask=answer,
                                        log=logs.append, playwright_factory=lambda: PW()), 0)
            self.assertEqual(sum("(dry-run) faria:" in line for line in logs), 1)
            self.assertIn("parada: sem avanço (a navegação entre questões é do humano)", logs)
        finally:
            page.close()

    def test_waits_for_human_navigation_without_another_claude_call(self):
        page = self.browser.new_page()
        try:
            page.goto(self.serve("quiz_mcq_single.html"))
            calls = []
            class PW:
                chromium = type("Chromium", (), {"connect_over_cdp": lambda _, __: type("B", (), {"contexts": self.browser.contexts, "close": lambda _: None})()})()
                def __enter__(_): return _
                def __exit__(_, *a): return None
            def answer(*_a, **_k):
                calls.append(1)
                return '{"type":"SINGLE","answers":[0]}', 0.0
            def advance(_seconds):
                page.evaluate("document.querySelector('.qz-c2').textContent = 'Texto sintético seguinte'")
            self.assertEqual(runner.run(1, "quiz_mcq_single.html", max_questions=2, ask=answer,
                                        playwright_factory=lambda: PW(), wait_seconds=1, sleep=advance), 0)
            self.assertEqual(len(calls), 2)
        finally:
            page.close()

    def test_dry_run_records_private_review_without_duplicates(self):
        page = self.browser.new_page()
        with tempfile.TemporaryDirectory() as tmp:
            record = Path(tmp) / "revisao" / "registro.jsonl"
            try:
                page.goto(self.serve("quiz_mcq_single.html"))
                class PW:
                    chromium = type("Chromium", (), {"connect_over_cdp": lambda _, __: type("B", (), {"contexts": self.browser.contexts, "close": lambda _: None})()})()
                    def __enter__(_): return _
                    def __exit__(_, *a): return None
                answer = lambda *_a, **_k: ('{"type":"SINGLE","answers":[0]}', 0.0)
                for _ in range(2):
                    self.assertEqual(runner.run(1, "quiz_mcq_single.html", ask=answer,
                                                playwright_factory=lambda: PW(), record_path=record), 0)
                rows = [json.loads(line) for line in record.read_text().splitlines()]
                self.assertEqual(len(rows), 1)
                self.assertTrue(rows[0]["dry_run"])
                self.assertEqual(rows[0]["chosen"], [{"index": 0, "text": "Alternativa sintética 1"}])
                self.assertEqual(stat.S_IMODE(record.stat().st_mode), 0o600)
                self.assertEqual(stat.S_IMODE(record.parent.stat().st_mode), 0o700)
            finally:
                page.close()

    def test_real_does_not_write_review(self):
        page = self.browser.new_page()
        with tempfile.TemporaryDirectory() as tmp:
            record = Path(tmp) / "revisao.jsonl"
            try:
                page.goto(self.serve("quiz_mcq_single.html"))
                class PW:
                    chromium = type("Chromium", (), {"connect_over_cdp": lambda _, __: type("B", (), {"contexts": self.browser.contexts, "close": lambda _: None})()})()
                    def __enter__(_): return _
                    def __exit__(_, *a): return None
                answer = lambda *_a, **_k: ('{"type":"SINGLE","answers":[0]}', 0.0)
                self.assertEqual(runner.run(1, "quiz_mcq_single.html", dry_run=False, ask=answer,
                                            playwright_factory=lambda: PW(), record_path=record), 0)
                self.assertFalse(record.exists())
            finally:
                page.close()

    def test_result_summary_stops_without_claude_or_click(self):
        page = self.browser.new_page()
        try:
            page.goto(self.serve("quiz_result.html"))
            logs = []
            class PW:
                chromium = type("Chromium", (), {"connect_over_cdp": lambda _, __: type("B", (), {"contexts": self.browser.contexts, "close": lambda _: None})()})()
                def __enter__(_): return _
                def __exit__(_, *a): return None
            def no_claude(*_a, **_k):
                self.fail("o resumo não consulta o Claude")
            self.assertEqual(runner.run(1, "quiz_result.html", ask=no_claude, log=logs.append,
                                        playwright_factory=lambda: PW()), 0)
            self.assertIn("parada: fim da atividade", logs)
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
