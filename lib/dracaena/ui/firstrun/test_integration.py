"""Primeira execução contra o daemon simulado real (SKIP se ele não subir)."""
import unittest

from dracaena.ui.add_site import AddSitePage
from dracaena.ui.firstrun import FirstRunWindow
from dracaena.ui.settings.testsupport import SimulatedDaemon, app, wait_for
from dracaena.ui.shortcuts_wizard import ShortcutWizardPage
from dracaena.ui.state import AppState

app()


class FirstRunAgainstSimulatedDaemon(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.daemon = SimulatedDaemon()
        cls.tr = cls.daemon.transport()

    @classmethod
    def tearDownClass(cls):
        cls.tr.close()
        cls.daemon.stop()

    def test_doctor_result_shown_with_real_format(self):
        state = AppState()
        state.set_connected(True)
        pages = (AddSitePage(self.tr, state),
                 ShortcutWizardPage(self.tr, state, environ=dict(XDG_SESSION_TYPE="wayland"), platform="linux",
                                    portal_probe=lambda: False))
        win = FirstRunWindow(self.tr, state, pages=pages)
        win.show()
        got = []
        self.tr.request("doctor", {}, got.append)
        wait_for(lambda: bool(got))
        real = got[0].data
        self.assertIsInstance(real["ok"], bool)
        self.assertTrue(wait_for(lambda: win.doctor_label.text().startswith("Verificação do ambiente"), 5))
        for c in real["checks"]:
            self.assertIn(c["name"], win.doctor_label.text())
            if not c["ok"] and c.get("hint"):
                self.assertIn(c["hint"], win.doctor_label.text())
        win.close()


if __name__ == "__main__":
    unittest.main()
