"""O motor JS só LÊ: o invariante "só a guarda age na página" vale para o JavaScript também."""

from __future__ import annotations

import re
import unittest

from corpus import CorpusServer, manifest
from fx import REPO, launch
from playwright.sync_api import sync_playwright

from dracaena.adapters.general import GeneralAdapter

ENGINE = REPO / "lib" / "dracaena" / "adapters" / "engine.js"
FORBIDDEN = {
    "clique": r"\.click\s*\(",
    "evento": r"dispatchEvent|\bnew\s+(?:\w+)?Event\b|addEventListener|\bon[a-z]+\s*=(?!=)",
    "envio": r"requestSubmit|\.submit\s*\(",
    "foco": r"\.focus\s*\(|\.blur\s*\(",
    "escrita em campo": r"\.(?:value|checked|selected|selectedIndex|disabled|hidden)\s*=(?!=)",
    "escrita no DOM": r"(?:inner|outer)HTML\s*=(?!=)|textContent\s*=(?!=)|innerText\s*=(?!=)|setAttribute\s*\(|"
                      r"removeAttribute\s*\(|toggleAttribute\s*\(|classList\.|\.style\.|appendChild|insertBefore|"
                      r"\.append\s*\(|\.prepend\s*\(|\.remove\s*\(|replaceWith|createElement|insertAdjacent|attachShadow",
    "rolagem": r"scrollIntoView|scrollTo|scrollBy",
    "rede": r"\bfetch\s*\(|XMLHttpRequest|WebSocket|sendBeacon|EventSource|\bimport\s*\(",
    "armazenamento": r"localStorage|sessionStorage|indexedDB|document\.cookie",
    "código dinâmico": r"\beval\s*\(|new\s+Function|setTimeout|setInterval",
    "navegação": r"location\.(?:href|assign|replace|reload)|history\.|window\.open",
}


class EngineSourceTests(unittest.TestCase):
    def test_engine_has_no_action_or_write(self):
        source = ENGINE.read_text(encoding="utf-8")
        code = "\n".join(line.split("//", 1)[0] if line.lstrip().startswith("//") else line for line in source.splitlines())
        found = []
        for what, pattern in FORBIDDEN.items():
            for match in re.finditer(pattern, code):
                found.append(f"{what}: {match.group(0)!r} na linha {code.count(chr(10), 0, match.start()) + 1}")
        self.assertEqual(found, [])

    def test_engine_is_one_dependency_free_module(self):
        source = ENGINE.read_text(encoding="utf-8")
        self.assertNotRegex(source, r"(?m)^\s*(import|export)\b|\brequire\s*\(")
        self.assertEqual(len(re.findall(r"(?m)^const DracaenaEngine = ", source)), 1)

    def test_the_scan_catches_a_planted_action(self):
        for bad in ("el.click()", "s.selectedIndex = 2", "e.value = 'x'", "x.setAttribute('a', 1)",
                    "fetch('/x')", "e.dispatchEvent(ev)", "n.scrollIntoView()", "document.cookie", "form.requestSubmit()"):
            with self.subTest(bad=bad):
                self.assertTrue(any(re.search(p, bad) for p in FORBIDDEN.values()))


class EngineBehaviourTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = CorpusServer()
        cls.pw = sync_playwright().start()
        cls.browser = launch(cls.pw)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()
        cls.server.close()

    def test_reading_leaves_every_fixture_untouched(self):
        """Ler (localizar, extrair, propor alvos, diagnosticar, recortar) não muda o DOM nem dispara eventos."""
        spy = """() => { window.__eventos = [];
            for (const t of ['click', 'input', 'change', 'focus', 'submit', 'keydown', 'scroll'])
                document.addEventListener(t, () => window.__eventos.push(t), true); }"""
        snapshot = """() => { const walk = (r) => Array.from(r.querySelectorAll('*')).map((e) => e.outerHTML.length + ':' +
            (e.checked ? 1 : 0) + (e.selectedIndex || 0) + (e.shadowRoot ? walk(e.shadowRoot) : '')).join('|');
            return walk(document) + '@' + scrollY; }"""
        adapter = GeneralAdapter()
        for entry in manifest():
            with self.subTest(fixture=entry["file"]):
                page = self.browser.new_page()
                try:
                    page.goto(self.server.url(entry))
                    for frame in page.frames:
                        frame.evaluate(spy)
                    before = [frame.evaluate(snapshot) for frame in page.frames]
                    adapter.diagnose(page.main_frame)
                    adapter.region(page.main_frame)
                    adapter.structure(page.main_frame)
                    for host in adapter.locate(page.main_frame):
                        question = adapter.extract(host)
                        adapter.verdict(host)
                        adapter.submit_target(host)
                        adapter.reset_target(host)
                        if question.options:
                            adapter.target(host, "option", 0)
                        if question.items:
                            adapter.target(host, "dropdown", (0, 0))
                        if question.right:
                            adapter.target(host, "match", (0, "A"))
                    self.assertEqual([frame.evaluate(snapshot) for frame in page.frames], before)
                    self.assertEqual([frame.evaluate("window.__eventos") for frame in page.frames],
                                     [[] for _ in page.frames])
                finally:
                    page.close()


if __name__ == "__main__":
    unittest.main()
