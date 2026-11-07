"""Guarda validada exclusivamente com fixtures sintéticas locais."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from web import REPO, BrowserFixtureCase

from quizhelper import dom
from quizhelper.guard import FinalScreen, Guard, Refused

CFG = {"SUBMIT_WORDS_BLOCKLIST": ["all", "assessment", "exam", "finish", "end"],
       "RESET_WORDS": ["Reset", "Try again", "Retry"], "ACTION_TIMEOUT_MS": 2000}

FINAL_PAGES = ["assessment_final.html"]

FS_JS = dom.js(r"""const fs = QH.first(document, e => e.tagName === 'FINALSCREEN-VIEW'); return fs ? fs.shadowRoot : null;""")


class GuardTests(BrowserFixtureCase):
    def setUp(self):
        self.page = self.browser.new_page()
        self.log: list[str] = []
        self.guard = Guard(self.page.main_frame, CFG, self.log.append)

    def tearDown(self):
        self.page.close()

    def open(self, name: str):
        self.page.goto(self.server.url(name))
        self.page.wait_for_function("() => window.__SIM_CLICKS !== undefined")

    def clicks(self) -> list[str]:
        return self.page.evaluate("window.__SIM_CLICKS")

    def final_el(self, selector: str):
        root = self.page.main_frame.evaluate_handle(FS_JS)
        return root.evaluate_handle(f"r => r.querySelector({selector!r})").as_element()

    def assert_blocked(self, el, host=None):
        with self.assertRaises((Refused, FinalScreen)):
            self.guard.click(el, host, "teste")
        self.assertEqual(self.clicks(), [], "a guarda deixou um clique passar")
        self.assertFalse(self.page.evaluate("window.__SIM_FINAL_SUBMITTED"))

    # ---------------------------------------------------------------- tela de envio

    def test_adaptive_submit_refused_disabled_enabled_and_relabeled(self):
        for name in FINAL_PAGES:
            with self.subTest(fixture=name):
                self.open(name)
                btn = self.final_el(".adaptive-assessment-submit")
                self.assertIsNotNone(btn)
                self.assert_blocked(btn)                                  # desabilitado
                btn.evaluate("b => { b.disabled = false; b.classList.remove('disabled', 'is-disabled'); }")
                self.assert_blocked(btn)                                  # habilitado
                for label in ("Submit", "submit", "Submit Your answer will be submitted", ""):
                    btn.evaluate("(b, l) => b.setAttribute('aria-label', l)", label)
                    self.assert_blocked(btn)                              # aria-label alterado
                # Mesmo fora da finalscreen visível e sem a classe, dentro dela é recusado.
                btn.evaluate("b => b.className = 'btn-text btn__action js-btn-action'")
                self.assert_blocked(btn)

    def test_adaptive_submit_refused_even_if_finalscreen_hidden(self):
        """A trava estrutural não depende só da visibilidade da tela."""
        self.open("assessment.html")
        root = self.page.main_frame.evaluate_handle(FS_JS)
        btn = root.evaluate_handle("r => r.querySelector('.adaptive-assessment-submit')").as_element()
        btn.evaluate("b => { b.classList.remove('disabled', 'is-disabled'); b.setAttribute('aria-label', 'submit'); }")
        with self.assertRaises(Refused) as ctx:
            self.guard.click(btn, None, "teste")
        self.assertEqual(ctx.exception.reason, "dentro de finalscreen-view")
        self.assertEqual(self.clicks(), [])

    def test_confirm_checkbox_never_checked(self):
        for name in FINAL_PAGES:
            with self.subTest(fixture=name):
                self.open(name)
                for sel in ("#confirm-exam", "#confirm-label"):
                    self.assert_blocked(self.final_el(sel))
                checked = self.page.main_frame.evaluate_handle(FS_JS).evaluate(
                    "r => r.querySelector('#confirm-exam').checked")
                self.assertFalse(checked)

    def test_injected_submit_outside_allowed_containers_is_refused(self):
        self.open("assessment.html")
        loc = dom.locate(self.page.main_frame)
        self.assertEqual(loc.mode, "assessment")
        for html in ('<button class="js-btn-action" aria-label="Submit Your answer will be submitted">Submit</button>',
                     '<button class="submit-button" aria-label="submit">Submit</button>',
                     '<div role="button" aria-label="Submit">Submit</div>',
                     '<button>Submit</button>'):
            with self.subTest(html=html):
                el = self.page.evaluate_handle(
                    "h => { const d = document.createElement('div'); d.innerHTML = h; document.body.appendChild(d); return d.firstChild; }",
                    html).as_element()
                self.assert_blocked(el, loc.host)

    def test_skip_links_and_strip_are_refused(self):
        self.open("assessment.html")
        loc = dom.locate(self.page.main_frame)
        tb = self.page.main_frame.evaluate_handle(dom.js(
            "return QH.first(document, e => e.tagName === 'ASSESSMENT-TOOLBAR-VIEW').shadowRoot;"))
        for sel in ("#skip-all-question", "#skip-question", "label[for=skip-question]", "label[for=skip-all-question]"):
            with self.subTest(sel=sel):
                self.assert_blocked(tb.evaluate_handle(f"r => r.querySelector({sel!r})").as_element(), loc.host)
        st = self.page.main_frame.evaluate_handle(dom.js(
            "return QH.first(document, e => e.tagName === 'ASSESSMENT-BLOCK-STRIP-VIEW').shadowRoot;"))
        for sel in ("[data-blockstrip-slider=right]", "[data-blockstrip-slider=left]", ".block-button"):
            with self.subTest(sel=sel):
                self.assert_blocked(st.evaluate_handle(f"r => r.querySelector({sel!r})").as_element(), loc.host)

    def test_other_component_on_page_is_refused(self):
        """Seção do curso: só o componente da questão atual é permitido."""
        self.open("cyu_single.html")
        loc = dom.locate(self.page.main_frame, "9.9.1.1 Check Your Understanding - Single")
        other = self.page.main_frame.evaluate_handle(dom.js(
            "const h = QH.all(document, QH.isQuestionHost).find(h => QH.q(h).dataset.socialgoodpulseId === 'other');"
            "return QH.q(h).querySelector('.mcq__item');")).as_element()
        self.assert_blocked(other, loc.host)

    # ---------------------------------------------------------------- última questão

    def test_last_question_submit_leads_to_finalscreen_and_stops(self):
        self.open("assessment.html")
        frame = self.page.main_frame
        for expected in (1, 2, 3):
            loc = dom.locate(frame)
            self.assertFalse(loc.final)
            self.assertEqual(loc.number, (expected, 3))
            item = dom.element(frame, loc.host, "mcq", index=0)
            self.guard.click(item, loc.host, f"alternativa da questão {expected}")
            if expected == 2:
                self.guard.click(dom.element(frame, loc.host, "mcq", index=1), loc.host, "segunda alternativa")
            self.guard.click(dom.element(frame, loc.host, "toolbar-submit"), loc.host, "Submit da barra")
            self.page.wait_for_function(dom.js(
                "const a = QH.first(document, e => e.classList && e.classList.contains('active-block'));"
                f"return !!a && (a.classList.contains('review-screen-button') || a.dataset.index === '{expected + 1}');"))
        before = len(self.clicks())
        self.assertTrue(dom.finalscreen_visible(frame))
        self.assertTrue(dom.locate(frame).final)
        # Qualquer ação depois disso: nenhuma passa.
        with self.assertRaises(FinalScreen):
            self.guard.click(dom.element(frame, loc.host, "toolbar-submit"), loc.host, "Submit de novo")
        with self.assertRaises(FinalScreen):
            self.guard.click(self.final_el(".adaptive-assessment-submit"), None, "envio")
        self.assertEqual(len(self.clicks()), before)
        self.assertFalse(self.page.evaluate("window.__SIM_FINAL_SUBMITTED"))
        self.assertEqual(dom.unanswered_count(frame), 0)


class SourceTests(unittest.TestCase):
    def test_only_guard_acts_on_the_page(self):
        """Nenhum módulo além de guard.py chama métodos de ação do Playwright."""
        pattern = re.compile(r"(?<!guard)\.(click|dblclick|check|uncheck|set_checked|select_option|drag_to|tap|press|"
                             r"press_sequentially|type|fill|dispatch_event|hover)\(|\.mouse\.|\.keyboard\.")
        pkg = REPO / "lib" / "quizhelper"
        offenders = []
        for path in sorted(pkg.glob("*.py")):
            if path.name == "guard.py":
                continue
            for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if pattern.search(line):
                    offenders.append(f"{path.name}:{n}: {line.strip()}")
        self.assertEqual(offenders, [])
        guard_src = (pkg / "guard.py").read_text(encoding="utf-8")
        self.assertEqual(guard_src.count("hit.click()"), 1, "guard.py deve ter um único ponto de clique")
        self.assertNotIn(".click(timeout", guard_src, "guard.py não usa o clique do Playwright")


if __name__ == "__main__":
    unittest.main()
