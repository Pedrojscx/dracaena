"""`autoprofile.learn` com o mapa estrutural: rascunho sem consulta externa, [meta], pausa e privacidade."""

from __future__ import annotations

import json
import unittest

from corpus import CorpusServer, FakeClaude, manifest
from fx import launch
from playwright.sync_api import sync_playwright

from dracaena.adapters import autoprofile, profile as profiles
from dracaena.adapters.general import GeneralAdapter

CANARY = "CANARIOZULU"
BASE = """[site]
name = "sintetico"
version = 0
match = ["*"]
[question]
container = "main"
stem = "h2"
[options]
item = "label"
"""
EXTRAS = ("status", "candidates", "fields", "fingerprint", "notes")


class MetaTableTests(unittest.TestCase):
    def test_meta_is_optional_and_round_trips(self):
        self.assertEqual(profiles.parse(BASE).meta, {})
        text = BASE + '[meta]\nconfidence = 0.9\nstatus = "verified"\nfingerprint = "f1abc"\ngenerator = "structure 1"\ngenerated = "2026-01-02"\n'
        parsed = profiles.parse(text)
        self.assertEqual(parsed.meta, {"confidence": 0.9, "status": "verified", "fingerprint": "f1abc",
                                       "generator": "structure 1", "generated": "2026-01-02"})
        self.assertNotIn("meta", parsed.to_engine())
        self.assertEqual(profiles.parse(profiles.dump(parsed.tables)).meta, parsed.meta)

    def test_meta_rejects_bad_values_with_the_line(self):
        bad = {'confidence = 1.5': 11, 'confidence = true': 11, 'status = "pronto"': 11, 'generated = "ontem"': 11,
               'fingerprint = "a@b.invalid"': 11, 'generator = "' + "x" * 60 + '"': 11, 'extra = 1': 11}
        for line, number in bad.items():
            with self.subTest(line=line[:30]):
                with self.assertRaises(profiles.ProfileError) as ctx:
                    profiles.parse(BASE + "[meta]\n" + line + "\n")
                self.assertEqual(ctx.exception.line, number)


class LearnTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = CorpusServer()
        cls.pw = sync_playwright().start()
        cls.browser = launch(cls.pw)
        cls.entries = {e["file"]: e for e in manifest()}

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()
        cls.server.close()

    def open(self, name: str):
        page = self.browser.new_page()
        self.addCleanup(page.close)
        page.goto(self.server.url(self.entries[name]))
        return page

    def test_confident_structure_gives_a_draft_without_asking(self):
        page = self.open("botoes_grandes.html")
        got = autoprofile.learn(page.main_frame, page.url, FakeClaude([]), force=True)
        self.assertEqual((got["status"], got["layer"], got["needed"]), ("verified", "profile", True))
        parsed = profiles.parse(got["draft_toml"])
        self.assertEqual((parsed.meta["status"], parsed.meta["generator"], parsed.meta["fingerprint"]),
                         ("verified", "structure 1", got["fingerprint"]))
        self.assertGreaterEqual(parsed.meta["confidence"], 0.85)
        self.assertEqual(GeneralAdapter(profile=parsed).diagnose(page.main_frame)["layer"], "profile")
        self.assertEqual(set(autoprofile.probe(page.main_frame, page.url, FakeClaude([]))),
                         {"matches", "questions", "draft_toml", *EXTRAS})

    def test_heuristic_is_enough_still_reports_the_structure(self):
        page = self.open("botoes_grandes.html")
        got = autoprofile.learn(page.main_frame, page.url, FakeClaude([]))
        self.assertEqual((got["needed"], got["draft_toml"]), (False, ""))
        self.assertTrue(all(key in got for key in EXTRAS))

    def test_pause_asks_and_a_failure_carries_the_candidates(self):
        page = self.open("tabela_sem_rotulos.html")
        teacher = FakeClaude([{"toml": "[hooks]\nrun = 1\n"}, {"toml": "[hooks]\nrun = 1\n"}])
        with self.assertRaises(autoprofile.AutoprofileError) as ctx:
            autoprofile.learn(page.main_frame, page.url, teacher)
        self.assertEqual(len(teacher.prompts), 2)
        details = ctx.exception.details
        self.assertEqual(details["status"], "pause")
        self.assertIn("question.container", details["candidates"])
        self.assertTrue(all(len(found) <= 3 for found in details["candidates"].values()))

    def test_canary_in_the_page_never_reaches_the_draft_or_the_result(self):
        page = self.open("botoes_grandes.html")
        # Só a montagem do teste escreve no DOM; o aprendizado apenas lê.
        page.evaluate("""(c) => { for (const e of document.querySelectorAll('main, main *')) {
                e.setAttribute('title', c); e.setAttribute('data-x', c); if (!e.id) e.id = c + Math.random().toString(36).slice(2); }
            const walk = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
            const nodes = []; while (walk.nextNode()) nodes.push(walk.currentNode);
            for (const n of nodes) if (n.textContent.trim() && !n.parentElement.closest('button:not([role])')) n.textContent = c + ' ' + n.textContent;
            const extra = document.createElement('input'); extra.type = 'hidden'; extra.value = c; document.querySelector('main').append(extra); }""", CANARY)
        got = autoprofile.learn(page.main_frame, page.url, FakeClaude([]), force=True)
        self.assertTrue(got["draft_toml"])
        self.assertNotIn(CANARY.lower(), json.dumps(got, ensure_ascii=False).lower())


if __name__ == "__main__":
    unittest.main()
