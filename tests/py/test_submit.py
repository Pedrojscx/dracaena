"""Detecção do Submit: desabilitado, habilitado depois, habilitado e ausente (fixture assessment.html)."""
from quizhelper import dom
from quizhelper.actions import Actor, Pause
from quizhelper.guard import Guard
from web import BrowserFixtureCase

BTN = "QH.first(document, e => e.tagName === 'ASSESSMENT-TOOLBAR-VIEW').shadowRoot.querySelector('button.submit-button')"


class SubmitDetectionTest(BrowserFixtureCase):
    def setUp(self):
        self.page = self.browser.new_page()
        self.addCleanup(self.page.close)
        self.page.goto(self.server.url("assessment.html"))
        self.page.wait_for_function("() => window.__SIM_CLICKS !== undefined")
        self.frame = self.page.main_frame
        self.host = dom.locate(self.frame).host
        self.log: list[str] = []
        cfg = {"ACTION_TIMEOUT_MS": 2000, "VERIFY_TIMEOUT_MS": 100, "SUBMIT_TIMEOUT_MS": 600}
        self.actor = Actor(self.frame, Guard(self.frame, cfg, self.log.append), cfg, lambda: False)

    def js(self, body: str):
        return self.frame.evaluate(dom.js(f"const b = {BTN}; {body}"))

    def enable(self):
        self.js("b.disabled = false; b.classList.remove('is-disabled');")

    def test_fixture_starts_disabled(self):
        self.assertTrue(self.js("return b.disabled && b.classList.contains('is-disabled');"))
        info = dom.submit_info(self.frame, self.host, "toolbar-submit")
        self.assertEqual((info["candidates"], info["disabled"]), (1, 1))

    def test_enabled_is_found_and_clicked(self):
        dom.element(self.frame, self.host, "mcq", index=0).click()
        self.enable()
        self.assertEqual(self.actor.submit(self.host, "assessment"), "Submit")
        self.assertTrue(any("Submit" in c for c in self.page.evaluate("window.__SIM_CLICKS")))

    def test_waits_for_button_to_become_enabled(self):
        self.js("setTimeout(() => { b.disabled = false; b.classList.remove('is-disabled'); }, 250);")
        self.assertEqual(self.actor.submit(self.host, "assessment"), "Submit")

    def test_still_disabled_pauses_with_diagnostics(self):
        with self.assertRaisesRegex(Pause, "continua desabilitado"):
            self.actor.submit(self.host, "assessment")
        self.assertIn("candidatos=1 desabilitados=1 existia=True", self.log[-1])
        self.assertIn("(assessment|secure)-toolbar-view >> button.submit-button", self.log[-1])

    def test_missing_button_keeps_original_pause_message(self):
        self.js("b.remove();")
        with self.assertRaisesRegex(Pause, "^botão Submit não encontrado$"):
            self.actor.submit(self.host, "assessment")
        self.assertIn("candidatos=0", self.log[-1])
        self.assertIn("existia=False", self.log[-1])


class SecureToolbarTest(BrowserFixtureCase):
    """Exame final: barra `secure-toolbar-view`. Antes caía no modo `section` e pegava a Q1."""

    def setUp(self):
        self.page = self.browser.new_page()
        self.addCleanup(self.page.close)
        self.page.goto(self.server.url("assessment_secure.html"))
        self.page.wait_for_function("() => window.__SIM_CLICKS !== undefined")
        self.frame = self.page.main_frame

    def test_locates_assessment_mode_and_toolbar_submit(self):
        loc = dom.locate(self.frame)
        self.assertEqual(loc.mode, "assessment")
        self.assertEqual(loc.number, (1, 3))
        info = dom.submit_info(self.frame, loc.host, "toolbar-submit")
        self.assertEqual((info["candidates"], info["disabled"]), (1, 1))
        self.assertIsNotNone(dom.element(self.frame, loc.host, "toolbar-submit"))

    def test_guard_allows_secure_toolbar_submit_when_enabled(self):
        loc = dom.locate(self.frame)
        cfg = {"ACTION_TIMEOUT_MS": 2000}
        guard = Guard(self.frame, cfg, lambda m: None)
        self.frame.evaluate(dom.js("const b = QH.toolbar(document).shadowRoot.querySelector('button.submit-button');"
                                   "b.disabled = false; b.classList.remove('is-disabled');"))
        self.assertEqual(guard.check(dom.element(self.frame, loc.host, "toolbar-submit"), loc.host)["kind"], "submit")
