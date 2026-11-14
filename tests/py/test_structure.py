"""Mapa estrutural do motor (`structure`): perfil candidato, confiança por campo e privacidade."""

from __future__ import annotations

import json
import unittest

from corpus import CorpusServer, manifest
from fx import launch
from playwright.sync_api import sync_playwright

from dracaena.adapters import profile as profiles
from dracaena.adapters.general import GeneralAdapter

CANARY = "CANARIOZULU"
RADIOS = """<main><section class="cartao"><h2>{c} enunciado sintético</h2>
<div role="radiogroup"><div role="radio" aria-checked="false" tabindex="0">{c} alfa</div>
<div role="radio" aria-checked="false" tabindex="0">{c} beta</div>
<div role="radio" aria-checked="false" tabindex="0">{c} gama</div></div>
<input type="hidden" value="{c}-oculto"><button type="button">Submit</button></section></main>"""
MIXED = """<main><div class="bloco"><p>Enunciado sintético de teste</p>
<label><input type="radio" name="a"> um</label><label><input type="radio" name="a"> dois</label>
<label><input type="checkbox"> três</label><label><input type="checkbox"> quatro</label>
<button type="button">Verificar</button></div></main>"""
FIELDS = ("question.container", "question.stem", "options.item", "dropdown.item", "submit.button", "reset.button")
KEYS = {"version", "status", "kind", "kinds", "ambiguous", "truncated", "elements", "shadow_depth", "interactive", "groups",
        "controls", "candidates", "profile", "confidence", "check", "notes", "fingerprint", "frame", "frames"}


def as_profile(tables: dict) -> profiles.Profile:
    body = dict(tables)
    body["site"] = {"name": "sintetico", "version": 0, "match": ("*",)}
    return profiles.parse(profiles.dump(body))


class StructureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = CorpusServer()
        cls.pw = sync_playwright().start()
        cls.browser = launch(cls.pw)
        cls.adapter = GeneralAdapter()

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()
        cls.server.close()

    def read(self, html: str) -> tuple:
        page = self.browser.new_page()
        self.addCleanup(page.close)
        page.set_content(f"<!doctype html><html><body>{html}</body></html>")
        return page, self.adapter.structure(page.main_frame)

    def test_frozen_shape(self):
        _, got = self.read(RADIOS.format(c="x"))
        self.assertEqual(set(got), KEYS)
        self.assertEqual(got["version"], 1)
        self.assertEqual(set(got["interactive"]), {"total", "tag", "role", "signal", "listeners"})
        self.assertEqual(set(got["controls"]), {"submit", "reset", "next", "feedback"})
        self.assertEqual(set(got["confidence"]), {"fields", "global"})
        for group in got["groups"]:
            self.assertEqual(set(group), {"key", "selector", "parent", "tag", "role", "type", "via", "count", "visible",
                                          "shadow_depth", "label", "group_label"})

    def test_aria_radios_with_submit_are_learned_without_help(self):
        page, got = self.read(RADIOS.format(c="x"))
        self.assertEqual((got["status"], got["kind"], got["ambiguous"]), ("verified", "SINGLE", False))
        self.assertGreaterEqual(got["confidence"]["global"], 0.85)
        self.assertEqual(got["check"], {"hosts": 1, "agree": True})
        self.assertEqual(got["controls"]["submit"][0]["hint"], "submit")
        learned = GeneralAdapter(profile=as_profile(got["profile"]))
        diag = learned.diagnose(page.main_frame)
        self.assertEqual((diag["layer"], len(diag["questions"])), ("profile", 1))
        plain = self.adapter.extract(self.adapter.locate(page.main_frame)[0])
        mine = learned.extract(learned.locate(page.main_frame)[0])
        self.assertEqual((mine.kind, mine.stem, [o.text for o in mine.options]),
                         (plain.kind, plain.stem, [o.text for o in plain.options]))

    def test_two_answer_groups_in_one_region_pause(self):
        _, got = self.read(MIXED)
        self.assertTrue(got["ambiguous"])
        self.assertEqual(got["status"], "pause")
        self.assertLess(got["confidence"]["global"], 0.5)
        self.assertEqual(sorted(got["kinds"]), ["MULTI", "SINGLE"])
        for name, found in got["candidates"].items():
            self.assertIn(name, FIELDS)
            self.assertLessEqual(len(found), 3)

    def test_no_page_text_or_field_value_leaves_the_engine(self):
        html = RADIOS.format(c=CANARY).replace("<section", f'<section id="{CANARY}" data-x="{CANARY}" title="{CANARY}"')
        html += f'<a href="/{CANARY}?k={CANARY}">{CANARY}</a><textarea>{CANARY}</textarea><img src="/{CANARY}.png" alt="{CANARY}">'
        _, got = self.read(html)
        self.assertNotIn(CANARY.lower(), json.dumps(got, ensure_ascii=False).lower())

    def test_corpus_text_never_appears_and_verified_profiles_read_the_page(self):
        for entry in manifest():
            with self.subTest(fixture=entry["file"]):
                page = self.browser.new_page()
                try:
                    page.goto(self.server.url(entry))
                    got = self.adapter.structure(page.main_frame)
                    dump = json.dumps(got, ensure_ascii=False)
                    for host in self.adapter.locate(page.main_frame):
                        question = self.adapter.extract(host)
                        texts = [question.stem] + [o.text for o in question.options] + [i.label for i in question.items]
                        for text in texts:
                            if len(text) >= 12:
                                self.assertNotIn(text, dump)
                    self.assertIn(got["status"], ("verified", "unverified", "pause", "experimental", "none", "limit"))
                    if got["status"] in ("verified", "unverified"):
                        self.assertTrue(got["check"]["agree"])
                        diag = GeneralAdapter(profile=as_profile(got["profile"])).diagnose(page.main_frame)
                        self.assertEqual(diag["layer"], "profile")
                        self.assertTrue(all(n > 0 for n in diag["matches"].values()), diag["matches"])
                    else:
                        self.assertLess(got["confidence"]["global"], 0.5)
                finally:
                    page.close()

    def test_hidden_alternatives_are_not_options(self):
        """Oculto por atributo, estilo ou bloco de leitor de tela: fora das opções, na heurística e no perfil."""
        hidden = ('<label aria-hidden="true"><input type="radio" name="a"> oculta um</label>'
                  '<label hidden><input type="radio" name="a"> oculta dois</label>'
                  '<label style="display:none"><input type="radio" name="a"> oculta três</label>'
                  '<label style="visibility:hidden"><input type="radio" name="a"> oculta quatro</label>'
                  '<label style="position:absolute;width:1px;height:1px;overflow:hidden"><input type="radio" name="a"> oculta cinco</label>'
                  '<div style="position:absolute;width:1px;height:1px;overflow:hidden"><label><input type="radio" name="a"> oculta seis</label></div>')
        page, got = self.read('<main><div class="bloco"><p>Enunciado sintético de teste</p>'
                              '<label><input type="radio" name="a"> um</label><label><input type="radio" name="a"> dois</label>'
                              '<label><input type="radio" name="a"> três</label>' + hidden + '</div></main>')
        self.assertEqual(got["check"], {"hosts": 1, "agree": True})
        self.assertEqual(got["candidates"]["options.item"][0]["count"], 3)
        learned = GeneralAdapter(profile=as_profile(got["profile"]))
        for adapter in (self.adapter, learned):
            question = adapter.extract(adapter.locate(page.main_frame)[0])
            self.assertEqual([o.text for o in question.options], ["um", "dois", "três"])

    def test_pages_the_heuristic_reads_well_get_a_matching_profile(self):
        wanted = {"lms_paginado.html", "quiz_mcq_single.html", "botoes_estado.html"}
        seen = set()
        for entry in manifest():
            if entry["file"] not in wanted:
                continue
            with self.subTest(fixture=entry["file"]):
                page = self.browser.new_page()
                try:
                    page.goto(self.server.url(entry))
                    got = self.adapter.structure(page.main_frame)
                    self.assertTrue(got["check"]["agree"])
                    self.assertIn(got["status"], ("verified", "unverified"))
                    seen.add(entry["file"])
                finally:
                    page.close()
        self.assertEqual(seen, wanted)

    def test_typed_answer_is_experimental_and_has_no_profile(self):
        _, got = self.read('<main><p>Enunciado sintético</p><textarea></textarea><button type="button">Enviar</button></main>')
        self.assertEqual((got["status"], got["kind"], got["profile"]), ("experimental", "TEXT", None))
        self.assertEqual(got["confidence"]["global"], 0)

    def test_fingerprint_follows_structure_not_text(self):
        _, one = self.read(RADIOS.format(c="um"))
        _, two = self.read(RADIOS.format(c="outro texto"))
        _, other = self.read(MIXED)
        self.assertEqual(one["fingerprint"], two["fingerprint"])
        self.assertNotEqual(one["fingerprint"], other["fingerprint"])

    def test_shadow_depth_limit_stops_the_capture(self):
        page = self.browser.new_page()
        self.addCleanup(page.close)
        page.set_content("<!doctype html><html><body><div id='raiz'></div></body></html>")
        page.evaluate("""() => { let host = document.getElementById('raiz');
            for (let i = 0; i < 22; i++) { const root = host.attachShadow({ mode: 'open' });
                host = document.createElement('div'); root.appendChild(host); } }""")
        got = self.adapter.structure(page.main_frame)
        self.assertEqual((got["status"], got["truncated"], got["profile"]), ("limit", True, None))

    def test_generated_class_names_stay_out_of_selectors(self):
        html = RADIOS.format(c="x").replace('class="cartao"', 'class="css-1a2b3c9 cartao sc-88213477 selected"')
        _, got = self.read(html)
        self.assertEqual(got["profile"]["question"]["container"], "section.cartao")


if __name__ == "__main__":
    unittest.main()
