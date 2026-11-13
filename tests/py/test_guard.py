"""Guarda validada exclusivamente com páginas sintéticas locais."""

from __future__ import annotations

import re
import unittest

from fx import REPO, BrowserCase

from dracaena.core.model import Target
from dracaena.guard import BLOCK_WORDS, Guard, Refused, ResultScreen


class GuardCase(BrowserCase):
    def setUp(self):
        self.page = self.browser.new_page()
        self.log: list[str] = []
        self.guard = Guard(self.log.append)

    def tearDown(self):
        self.page.close()

    def open(self, name: str, qid: str = "r1", guard: Guard | None = None):
        self.page.goto(self.server.url(name))
        self.page.wait_for_function("() => window.__SIM_CLICKS !== undefined")
        self.guard = guard or self.guard
        self.host = self.page.query_selector(f"#{qid}")
        self.guard.bind(self.page.main_frame, self.host, qid)
        return self.host

    def el(self, selector: str):
        return self.page.query_selector(selector)

    def t(self, role: str, selector: str, action: str = "click", qid: str | None = None, value=None) -> Target:
        return Target(role, action, self.el(selector), selector, qid or self.guard.qid, value)

    def clicks(self) -> list[str]:
        return self.page.evaluate("window.__SIM_CLICKS")

    def assert_refused(self, target: Target, reason: str | None = None):
        with self.assertRaises(Refused) as ctx:
            self.guard.perform(target, "teste")
        if reason:
            self.assertIn(reason, ctx.exception.reason)
        self.assertEqual(self.clicks(), [], "a guarda deixou uma ação passar")
        self.assertFalse(self.page.evaluate("window.__SIM_GLOBAL"))

    def inject(self, html: str):
        return self.page.evaluate_handle(
            "([sel, h]) => { const d = document.createElement('div'); d.innerHTML = h;"
            " document.querySelector(sel).appendChild(d); return d.firstChild; }", [f"#{self.guard.qid}", html]).as_element()


class ActionTests(GuardCase):
    def test_radio_option_click(self):
        self.open("radio.html")
        kind = self.guard.perform(self.t("option", "#r1 input[value='1']"), "Dog")
        self.assertEqual(kind, "alternativa")
        self.assertTrue(self.page.evaluate("document.querySelector(\"#r1 input[value='1']\").checked"))
        self.assertEqual(len(self.clicks()), 1)

    def test_checkbox_two(self):
        self.open("checkbox.html", "c1")
        for v in (1, 3):
            self.guard.perform(self.t("option", f"#c1 input[value='{v}']"))
        self.assertEqual(self.page.evaluate("[...document.querySelectorAll('#c1 input:checked')].map(i => i.value)"), ["1", "3"])

    def test_select_native(self):
        self.open("select.html", "d1")
        kind = self.guard.perform(self.t("option", "#d1-s0", "select", value=2))
        self.assertEqual(kind, "dropdown nativo")
        self.assertEqual(self.page.evaluate("document.querySelector('#d1-s0').selectedIndex"), 2)
        self.assertEqual(self.clicks(), [])                           # escolha, não clique

    def test_select_placeholder_and_missing_option_refused(self):
        self.open("select.html", "d1")
        self.assert_refused(self.t("option", "#d1-s0", "select", value=0), "opção desabilitada")
        self.assert_refused(self.t("option", "#d1-s0", "select", value=9), "opção inexistente")
        self.assertEqual(self.page.evaluate("document.querySelector('#d1-s0').selectedIndex"), 0)

    def test_aria_in_shadow_dom(self):
        host = self.open("aria.html", "a1")
        self.assertIsNotNone(host)
        radios = self.page.evaluate_handle("document.querySelector('quiz-item').shadowRoot.querySelectorAll('[role=radio]')")
        mars = radios.evaluate_handle("l => l[1]").as_element()
        self.guard.perform(Target("option", "click", mars, "Mars", "a1"))
        self.assertEqual(mars.get_attribute("aria-checked"), "true")

    def test_submit_shows_feedback_and_reset_undoes(self):
        self.open("radio.html")
        self.guard.perform(self.t("option", "#r1 input[value='0']"))          # errada de propósito
        self.guard.perform(self.t("submit", "#r1 [data-sim=submit]"), "Submit")
        self.assertEqual(self.page.evaluate("document.querySelector('#r1').dataset.result"), "incorrect")
        self.guard.perform(self.t("reset", "#r1 [data-sim=reset]"), "Try again")
        self.assertEqual(self.page.evaluate("document.querySelector('#r1').dataset.result"), None)

    def test_dry_run_does_nothing(self):
        self.open("radio.html", guard=Guard(self.log.append, dry_run=True))
        self.guard.perform(self.t("option", "#r1 input[value='1']"))
        self.guard.perform(self.t("submit", "#r1 [data-sim=submit]"))
        self.assertEqual(self.clicks(), [])
        self.assertTrue(any("dry-run" in line for line in self.log))

    def test_opener_runs_first(self):
        self.open("radio.html")
        opener = self.inject('<button type="button" aria-haspopup="listbox" aria-expanded="false" id="op" '
                             'onclick="document.getElementById(\'lst\').hidden=false">Open</button>'
                             '<div id="lst" hidden><div role="option" id="o1" aria-selected="false">Item</div></div>')
        self.assertIsNotNone(opener)
        option = self.el("#o1")
        target = Target("option", "click", option, "Item", "r1", opener=Target("option", "click", self.el("#op"), "abrir", "r1"))
        self.guard.perform(target, "Item")
        self.assertEqual(self.el("#o1").get_attribute("aria-selected"), "true")
        self.assertEqual(len(self.clicks()), 2)


class InvariantTests(GuardCase):
    def test_global_buttons_outside_question_refused(self):
        self.open("radio.html")
        for btn in self.page.query_selector_all("#globals button"):
            self.assert_refused(Target("submit", "click", btn, "x", "r1"), "fora da questão atual")

    def test_global_labels_inside_question_refused(self):
        self.open("radio.html")
        for label in ("Finish quiz", "Submit all answers", "Submit page", "Submit My Assessment", "End", "Finish",
                      "Submit exam", "Enviar tudo", "Skip All"):
            with self.subTest(label=label):
                btn = self.inject(f'<button type="button" id="x">{label}</button>')
                self.assert_refused(Target("submit", "click", btn, label, "r1"))
                self.assert_refused(Target("reset", "click", btn, label, "r1"))

    def test_final_attempt_button_is_refused(self):
        self.open("radio.html")
        label = "Finalizar tentativa ..."
        btn = self.inject(f'<button type="submit">{label}</button>')
        self.assert_refused(Target("submit", "click", btn, label, "r1"), "texto bloqueado (finalizar)")

    def test_final_submission_and_confirmation_are_refused_for_their_reason(self):
        self.open("radio.html")
        label = "Enviar tudo e terminar"
        btn = self.inject(f'<button type="submit">{label}</button>')
        self.assert_refused(Target("submit", "click", btn, label, "r1"), "texto bloqueado (enviar tudo)")
        dialog = self.page.evaluate_handle(f"""() => {{ const d = document.createElement('dialog'); d.open = true;
            d.innerHTML = '<button type=\"submit\">{label}</button>'; document.body.appendChild(d); return d; }}""").as_element()
        self.assertIsNotNone(dialog)
        confirmation = dialog.query_selector("button")
        self.assert_refused(Target("submit", "click", confirmation, label, "r1"), "fora da questão atual")

    def test_aria_label_cannot_hide_a_global_submit(self):
        self.open("radio.html")
        btn = self.inject('<button type="button" aria-label="Submit all answers">OK</button>')
        self.assert_refused(Target("submit", "click", btn, "Submit", "r1"), "texto bloqueado")
        btn = self.inject('<button type="button" aria-label="Finish">Submit</button>')
        self.assert_refused(Target("submit", "click", btn, "Submit", "r1"), "blocklist")

    def test_adapter_label_is_not_trusted(self):
        self.open("radio.html")
        btn = self.inject('<button type="button">Finish quiz</button>')
        self.assert_refused(Target("submit", "click", btn, "Submit", "r1"))

    def test_submit_without_label_refused(self):
        self.open("radio.html")
        btn = self.inject('<button type="button"></button>')
        self.assert_refused(Target("submit", "click", btn, "Submit", "r1"), "sem rótulo")

    def test_option_text_may_contain_block_words(self):
        """“Todas as anteriores” é resposta legítima; a blocklist vale para botões."""
        self.open("radio.html")
        label = self.inject('<label><input type="radio" name="r1" value="9" id="all"> All of the above, to the end</label>')
        self.assertIsNotNone(label)
        self.guard.perform(Target("option", "click", self.el("#all"), "All of the above", "r1"))
        self.assertTrue(self.el("#all").is_checked())

    def test_confirmation_checkbox_refused(self):
        self.open("radio.html")
        cb = self.inject('<label><input type="checkbox" id="cf"> Yes, confirm my submission.</label>')
        self.assertIsNotNone(cb)
        self.assert_refused(Target("option", "click", self.el("#cf"), "confirm", "r1"))

    def test_other_question_refused(self):
        self.open("radio.html")
        other = self.el("#r2 input[value='1']")
        self.assert_refused(Target("option", "click", other, "x", "r2"), "outra questão")          # qid diferente
        self.assert_refused(Target("option", "click", other, "x", "r1"), "fora da questão atual")  # qid mentido
        self.assertFalse(self.el("#r2 input[value='1']").is_checked())

    def test_unbound_guard_refuses(self):
        self.page.goto(self.server.url("radio.html"))
        with self.assertRaises(Refused):
            Guard(self.log.append).perform(Target("option", "click", self.el("#r1 input"), "x", "r1"))

    def test_invalid_role_action_and_element_types(self):
        self.open("radio.html")
        radio = "#r1 input[value='1']"
        self.assert_refused(self.t("submit", radio), "não permitido")                  # rádio não é Submit
        self.assert_refused(self.t("option", radio, "select", value=0), "não permitido")
        self.assert_refused(Target("hack", "click", self.el(radio), "x", "r1"), "inválido")
        self.assert_refused(Target("option", "type", self.el(radio), "x", "r1"), "inválido")
        link = self.inject('<a href="#end" id="lk">Go</a>')
        self.assert_refused(Target("option", "click", link, "x", "r1"), "não permitido")
        resetter = self.inject('<input type="reset" value="Clear" id="rs">')
        self.assert_refused(Target("reset", "click", resetter, "x", "r1"), "não permitido")
        legend = self.el("#r1 legend")
        self.assert_refused(Target("option", "click", legend, "x", "r1"), "não permitido")

    def test_disabled_and_hidden_refused(self):
        self.open("radio.html")
        self.page.evaluate("document.querySelector(\"#r1 input[value='2']\").disabled = true")
        self.assert_refused(self.t("option", "#r1 input[value='2']"), "desabilitado")
        self.page.evaluate("document.querySelector(\"#r1 input[value='3']\").parentElement.style.display = 'none'")
        self.assert_refused(self.t("option", "#r1 input[value='3']"), "invisível")
        self.page.evaluate("document.querySelector('#r1 fieldset').disabled = true")
        self.assert_refused(self.t("option", "#r1 input[value='0']"), "desabilitado")

    def test_submit_that_would_send_other_questions_refused(self):
        self.open("oneform.html", "f1")
        btn = self.page.evaluate_handle("""() => { const b = document.querySelector('#f button[type=submit]');
            document.querySelector('#f1').appendChild(b); return b; }""").as_element()
        self.assert_refused(Target("submit", "click", btn, "Submit", "f1"), "outras questões")

    def test_element_covered_by_another_is_refused(self):
        self.open("radio.html")
        self.page.evaluate("""() => { const d = document.createElement('div'); d.id = 'cover';
            const r = document.querySelector("#r1 input[value='1']").getBoundingClientRect();
            d.style.cssText = `position:fixed;left:${r.left - 5}px;top:${r.top - 5}px;width:${r.width + 10}px;height:${r.height + 10}px;background:red`;
            document.body.appendChild(d); }""")
        self.assert_refused(self.t("option", "#r1 input[value='1']"), "por cima")
        self.assertFalse(self.el("#r1 input[value='1']").is_checked())

    def test_extra_block_terms_only_add(self):
        g = Guard(self.log.append, extra_block=["Check answer", "recomeçar"])
        for word in ("all", "assessment", "exam", "finish", "end"):
            self.assertIn(word, g.block)
        self.assertTrue(set(BLOCK_WORDS) <= set(g.block))
        self.assertIn("recomecar", g.block)
        self.assertIn("check answer", g.phrases)
        self.open("aria.html", "a1", guard=g)
        btn = self.page.evaluate_handle("document.querySelector('quiz-item').shadowRoot.querySelector('[data-sim=submit]')").as_element()
        self.assert_refused(Target("submit", "click", btn, "Check answer", "a1"), "texto bloqueado")

    def test_result_screen_stops_without_acting(self):
        self.open("radio.html")
        target = self.t("option", "#r1 input[value='1']")
        self.page.evaluate("""() => { document.querySelector('#r1').style.display = 'none';
            const h = document.createElement('h2'); h.textContent = 'Quiz complete'; document.body.appendChild(h); }""")
        with self.assertRaises(ResultScreen):
            self.guard.perform(target, "Dog")
        self.assertEqual(self.clicks(), [])
        self.assertTrue(self.guard.result_visible())

    def test_result_variants_stop_only_when_question_is_hidden(self):
        variants = ("Revisão da atividade", "Revisão da tentativa", "Resumo da tentativa",
                    "Attempt summary", "Attempt review")
        for text in variants:
            with self.subTest(text=text):
                self.open("radio.html")
                target = self.t("option", "#r1 input[value='1']")
                self.page.evaluate("([text]) => { document.querySelector('#r1').style.display = 'none';"
                                   " const h = document.createElement('h2'); h.textContent = text; document.body.appendChild(h); }", [text])
                with self.assertRaises(ResultScreen):
                    self.guard.perform(target, "teste")
                self.assertEqual(self.clicks(), [])
        self.open("radio.html")
        self.inject('<span>Revisão da tentativa</span>')
        self.guard.perform(self.t("option", "#r1 input[value='1']"))
        self.assertTrue(self.el("#r1 input[value='1']").is_checked())

    def test_result_page_is_detected_and_question_page_is_not(self):
        self.page.goto(self.server.url("result.html"))
        self.assertTrue(Guard(self.log.append).result_visible(self.page.main_frame))
        self.page.goto(self.server.url("radio.html"))
        self.assertFalse(Guard(self.log.append).result_visible(self.page.main_frame))

    def test_hidden_question_without_result_text_is_a_plain_refusal(self):
        self.open("radio.html")
        target = self.t("option", "#r1 input[value='1']")
        self.page.evaluate("document.querySelector('#r1').style.display = 'none'")
        self.assert_refused(target, "não está visível")


class SourceTests(unittest.TestCase):
    def test_only_guard_acts_on_the_page(self):
        """Nenhum módulo além de guard.py chama métodos de ação do Playwright."""
        pattern = re.compile(r"\.(click|dblclick|check|uncheck|set_checked|select_option|drag_to|tap|press|"
                             r"press_sequentially|type|fill|dispatch_event|dispatchEvent|requestSubmit|submit|hover|focus|set_input_files)\s*\(|\.(?:checked|selectedIndex|value)\s*=(?!=)|\.mouse\.|\.keyboard\.")
        # O legado mantém a auditoria anterior até sua remoção coordenada.
        legacy_pattern = re.compile(r"(?<!guard)\.(click|dblclick|check|uncheck|set_checked|select_option|drag_to|tap|press|"
                                    r"press_sequentially|type|fill|dispatch_event|hover|focus|set_input_files)\(|\.mouse\.|\.keyboard\.")
        offenders = []
        for pkg in (REPO / "lib" / "dracaena", REPO / "lib" / "quizhelper"):
            for path in sorted(pkg.rglob("*.py")):
                legacy = pkg.name == "quizhelper"
                if (legacy and path.name == "guard.py") or path == REPO / "lib" / "dracaena" / "guard.py":
                    continue
                for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                    if (legacy_pattern if legacy else pattern).search(line):
                        offenders.append(f"{path.relative_to(REPO)}:{n}: {line.strip()}")
        self.assertEqual(offenders, [])
        guard_src = (REPO / "lib" / "dracaena" / "guard.py").read_text(encoding="utf-8")
        self.assertEqual(guard_src.count("hit.click()"), 1, "guard.py deve ter um único ponto de clique")
        self.assertNotIn(".click(timeout", guard_src, "guard.py não usa o clique do Playwright")
        self.assertEqual(len(re.findall(r"\.selectedIndex\s*=", guard_src)), 1, "um único ponto de escolha")

    def test_blocklist_is_a_code_constant(self):
        for word in ("all", "assessment", "exam", "finish", "end"):
            self.assertIn(word, BLOCK_WORDS)
        self.assertIsInstance(BLOCK_WORDS, frozenset)


if __name__ == "__main__":
    unittest.main()
