"""Paridade: o perfil APRENDIDO propõe as mesmas ações que um perfil escrito à mão (fixtures sintéticas)."""

from __future__ import annotations

import unittest

from corpus import CorpusServer, FakeClaude, manifest
from fx import launch
from playwright.sync_api import sync_playwright

from dracaena.adapters import autoprofile
from dracaena.adapters.declarative import DeclarativeAdapter

SITE = '[site]\nname = "sintetico"\nversion = 0\nmatch = ["*"]\n'
HAND = {
    "botoes_grandes.html": SITE + '[question]\ncontainer = "main"\nstem = "h2"\n[options]\nitem = "[role=radio]"\n',
    "pagina_unica.html": SITE + '[question]\ncontainer = "fieldset"\nstem = "legend"\n[options]\nitem = "label"\n'
                                '[dropdown]\nitem = "select"\nnative = true\n',
    "select_em_frase.html": SITE + '[question]\ncontainer = "main"\nstem = "h2"\n[dropdown]\nitem = "select"\nnative = true\n',
    "componentes_shadow.html": SITE + '[question]\ncontainer = "section.cartao"\nstem = "legend"\n[options]\nitem = "label"\n'
                                      '[submit]\nbutton = "button"\n',
}
SAME = "(a, b) => a === b"


class ParityTests(unittest.TestCase):
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

    def same(self, mine, theirs):
        """Dois alvos propostos são a mesma ação no mesmo elemento."""
        if mine is None or theirs is None:
            self.assertEqual(mine, theirs)
            return
        self.assertEqual((mine.role, mine.action, mine.value, mine.label), (theirs.role, theirs.action, theirs.value, theirs.label))
        self.assertTrue(mine.element.evaluate(SAME, theirs.element))

    def test_learned_profile_proposes_the_same_actions_as_a_hand_written_one(self):
        for name, text in HAND.items():
            with self.subTest(fixture=name):
                page = self.browser.new_page()
                try:
                    page.goto(self.server.url(self.entries[name]))
                    before = page.content()
                    got = autoprofile.learn(page.main_frame, page.url, FakeClaude([]), force=True)
                    learned, hand = DeclarativeAdapter(got["draft_toml"]), DeclarativeAdapter(text)
                    mine, theirs = learned.locate(page.main_frame), hand.locate(page.main_frame)
                    self.assertEqual(len(mine), len(theirs))
                    self.assertGreater(len(mine), 0)
                    for a, b in zip(mine, theirs):
                        self.assertTrue(a.evaluate(SAME, b))
                        qa, qb = learned.extract(a), hand.extract(b)
                        self.assertEqual((qa.kind, [o.text for o in qa.options], [[c.text for c in i.options] for i in qa.items]),
                                         (qb.kind, [o.text for o in qb.options], [[c.text for c in i.options] for i in qb.items]))
                        for index in range(len(qa.options)):
                            self.same(learned.target(a, "option", index), hand.target(b, "option", index))
                        for i, item in enumerate(qa.items):
                            for j in range(len(item.options)):
                                self.same(learned.target(a, "dropdown", (i, j)), hand.target(b, "dropdown", (i, j)))
                        self.same(learned.submit_target(a), hand.submit_target(b))
                    self.assertEqual(page.content(), before)
                finally:
                    page.close()


if __name__ == "__main__":
    unittest.main()
