import unittest

from dracaena.ui.settings.testsupport import (FakeClient, Resp, SimulatedDaemon, app, daemon_python,
                                             screenshot_dir, wait_for)
from dracaena.ui.settings import SettingsWindow
from dracaena.ui.state import AppState
from PySide6.QtWidgets import QCheckBox, QComboBox, QLineEdit, QSpinBox

app()

SCHEMA = [
    {"key": "MODEL", "type": "string", "default": "haiku", "description": "model"},
    {"key": "CLAUDE_TIMEOUT", "type": "integer", "default": 45, "description": "claude timeout", "min": 1, "max": 3600},
    {"key": "BROWSER_FALLBACK", "type": "string", "default": "playwright", "description": "browser fallback",
     "choices": ["", "playwright"]},
    {"key": "CLICK_SUBMIT", "type": "integer", "default": 1, "description": "click submit", "min": 0, "max": 1},
    {"key": "FLAG", "type": "boolean", "default": False, "description": "flag"},
]
VALUES = {"MODEL": "haiku", "CLAUDE_TIMEOUT": 45, "BROWSER_FALLBACK": "playwright", "CLICK_SUBMIT": 1, "FLAG": False}


def make(answers=None, connected=True):
    client = FakeClient({"config.schema": SCHEMA, "config.get": dict(VALUES), **(answers or {})})
    state = AppState()
    state.set_connected(connected)
    win = SettingsWindow(client, state)
    return client, state, win


class SettingsFormTests(unittest.TestCase):
    def test_widgets_generated_from_schema_types(self):
        client, state, win = make()
        win.show()
        self.assertTrue(wait_for(lambda: win._form is not None))
        f = win._form.fields
        self.assertIsInstance(f["MODEL"].widget, QLineEdit)
        self.assertIsInstance(f["CLAUDE_TIMEOUT"].widget, QSpinBox)
        self.assertEqual((f["CLAUDE_TIMEOUT"].widget.minimum(), f["CLAUDE_TIMEOUT"].widget.maximum()), (1, 3600))
        self.assertIsInstance(f["BROWSER_FALLBACK"].widget, QComboBox)
        self.assertIsInstance(f["CLICK_SUBMIT"].widget, QCheckBox)
        self.assertIsInstance(f["FLAG"].widget, QCheckBox)
        self.assertEqual(win._form.values(), VALUES)
        self.assertEqual([c[0] for c in client.calls], ["config.schema", "config.get"])

    def test_save_sends_only_changed_keys_with_typed_values(self):
        client, state, win = make()
        win.show()
        wait_for(lambda: win._form is not None)
        self.assertFalse(win.btn_save.isEnabled())
        win._form.fields["CLAUDE_TIMEOUT"].set(90)
        win._form.fields["CLICK_SUBMIT"].set(0)
        win._form.fields["BROWSER_FALLBACK"].set("")
        self.assertTrue(win.btn_save.isEnabled())
        win.save()
        self.assertTrue(wait_for(lambda: win.status.text() == "Configurações salvas."))
        sets = {a["key"]: a["value"] for c, a in client.calls if c == "config.set"}
        self.assertEqual(sets, {"CLAUDE_TIMEOUT": 90, "CLICK_SUBMIT": 0, "BROWSER_FALLBACK": ""})
        self.assertIs(type(sets["CLICK_SUBMIT"]), int)
        self.assertFalse(win.btn_save.isEnabled())

    def test_daemon_rejection_is_shown_and_keeps_pending(self):
        err = Resp(1, False, error="Value outside supported range", code="bad_request")
        client, state, win = make({"config.set": err})
        win.show()
        wait_for(lambda: win._form is not None)
        win._form.fields["MODEL"].set("opus")
        win.save()
        self.assertTrue(wait_for(lambda: "Value outside supported range" in win.status.text()))
        self.assertIn("MODEL", win.status.text())
        self.assertEqual(win._form.changed(), {"MODEL": "opus"})

    def test_defaults_restored_on_screen_only(self):
        client, state, win = make()
        win.show()
        wait_for(lambda: win._form is not None)
        win._form.fields["MODEL"].set("opus")
        win._defaults()
        self.assertEqual(win._form.values()["MODEL"], "haiku")
        self.assertFalse([c for c in client.calls if c[0] == "config.set"])

    def test_offline_banner_and_load_on_reconnect(self):
        client, state, win = make(connected=False)
        win.show()
        self.assertFalse(win.banner.isHidden())
        self.assertFalse(win.btn_save.isEnabled())
        self.assertIsNone(win._form)
        state.set_connected(True)
        self.assertTrue(wait_for(lambda: win._form is not None))
        self.assertTrue(win.banner.isHidden())

    def test_load_failure_message(self):
        client, state, win = make({"config.schema": Resp(1, False, error="Falha ao executar comando")})
        win.show()
        self.assertTrue(wait_for(lambda: "Falha ao executar comando" in win.status.text()))

    def test_unknown_current_choice_is_not_hidden(self):
        client, state, win = make({"config.get": {**VALUES, "BROWSER_FALLBACK": "outro"}})
        win.show()
        wait_for(lambda: win._form is not None)
        self.assertEqual(win._form.values()["BROWSER_FALLBACK"], "outro")


class SettingsAgainstSimulatedDaemon(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.daemon = SimulatedDaemon()
        cls.tr = cls.daemon.transport()

    @classmethod
    def tearDownClass(cls):
        cls.tr.close()
        cls.daemon.stop()

    def test_form_from_real_schema_save_and_persist(self):
        state = AppState()
        state.set_connected(True)
        win = SettingsWindow(self.tr, state)
        win.show()
        self.assertTrue(wait_for(lambda: win._form is not None))
        keys = set(win._form.fields)
        self.assertTrue({"MODEL", "CLAUDE_TIMEOUT", "BROWSER_BIN", "BROWSER_FALLBACK", "KEEP_DAYS"} <= keys)
        from PySide6.QtWidgets import QLabel
        texts = [l.text() for l in win._form.findChildren(QLabel)]
        self.assertIn("Modelo", texts)                      # label em português vindo do schema real
        self.assertNotIn("MODEL", texts)
        win._form.fields["CLAUDE_TIMEOUT"].set(60)
        win.save()
        self.assertTrue(wait_for(lambda: win.status.text() == "Configurações salvas."))
        got = []
        self.tr.request("config.get", {}, got.append)
        wait_for(lambda: bool(got))
        self.assertEqual(got[0].data["CLAUDE_TIMEOUT"], 60)
        win.grab().save(str(screenshot_dir() / "settings.png"))
        win.close()


class LabelTests(unittest.TestCase):
    def test_label_is_field_text_and_description_is_the_hint(self):
        schema = [{"key": "KEEP_DAYS", "type": "integer", "default": 7, "min": 1, "max": 3650,
                   "label": "Dias de retenção", "description": "Dias em que os registros são mantidos."}]
        client, state, win = make({"config.schema": schema, "config.get": {"KEEP_DAYS": 7}})
        win.show()
        wait_for(lambda: win._form is not None)
        from PySide6.QtWidgets import QLabel
        texts = [l.text() for l in win._form.findChildren(QLabel)]
        self.assertIn("Dias de retenção", texts)
        self.assertIn("Dias em que os registros são mantidos.", texts)
        self.assertNotIn("KEEP_DAYS", texts)
        self.assertIn("Dias em que os registros são mantidos.", win._form.fields["KEEP_DAYS"].widget.toolTip())

    def test_without_label_falls_back_to_description_then_key(self):
        schema = [{"key": "A", "type": "string", "default": "", "description": "texto a"},
                  {"key": "B", "type": "string", "default": ""}]
        client, state, win = make({"config.schema": schema, "config.get": {}})
        win.show()
        wait_for(lambda: win._form is not None)
        from PySide6.QtWidgets import QLabel
        texts = [l.text() for l in win._form.findChildren(QLabel)]
        self.assertIn("Texto a", texts)
        self.assertIn("B", texts)


class DaemonSelectionTests(unittest.TestCase):
    def test_python_choice_falls_back_to_system_python(self):
        ok = {"/usr/bin/python3"}
        self.assertEqual(daemon_python(["/venv/bin/python", "/usr/bin/python3"], probe=lambda c: c in ok),
                         "/usr/bin/python3")
        self.assertIsNone(daemon_python(["/venv/bin/python", ""], probe=lambda c: False))

    def test_missing_backend_or_python_means_skip_not_error(self):
        import os
        from dracaena.ui.settings import testsupport as ts
        old = ts.BACKEND
        try:
            ts.BACKEND = ts.Path("/nao/existe/b2-backend")
            with self.assertRaises(unittest.SkipTest):
                ts.SimulatedDaemon()
            ts.BACKEND = old
            real = ts.daemon_python
            ts.daemon_python = lambda *a, **k: None
            with self.assertRaises(unittest.SkipTest):
                ts.SimulatedDaemon()
        finally:
            ts.BACKEND = old
            ts.daemon_python = real


if __name__ == "__main__":
    unittest.main()
