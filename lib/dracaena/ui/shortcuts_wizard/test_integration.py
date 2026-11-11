"""Assistente de atalhos contra o daemon simulado real (SKIP se ele não subir)."""
import shlex
import unittest

from dracaena.ui.settings.testsupport import SimulatedDaemon, app, wait_for
from dracaena.ui.shortcuts_wizard import ShortcutWizardPage
from dracaena.ui.state import AppState

app()
HYPRLAND = dict(XDG_SESSION_TYPE="wayland", XDG_CURRENT_DESKTOP="Hyprland")


class ShortcutsAgainstSimulatedDaemon(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.daemon = SimulatedDaemon()
        cls.tr = cls.daemon.transport()

    @classmethod
    def tearDownClass(cls):
        cls.tr.close()
        cls.daemon.stop()

    def make(self):
        state = AppState()
        state.set_connected(True)
        page = ShortcutWizardPage(self.tr, state, environ=HYPRLAND, platform="linux", portal_probe=lambda: False)
        page.show()
        return state, page

    def test_toggle_cmd_from_hello_is_shown_quoted_not_exact_value(self):
        state, page = self.make()
        got = []
        self.tr.request("hello", {}, got.append)
        wait_for(lambda: bool(got))
        argv = got[0].data["toggle_cmd"]                       # valor pode herdar APPIMAGE em dev: não comparo literal
        self.assertTrue(isinstance(argv, list) and argv and all(isinstance(a, str) for a in argv))
        self.assertTrue(wait_for(lambda: page.command.source == "daemon"))
        self.assertEqual(shlex.split(page.command_view.text()), argv)
        self.assertTrue(page.snippet_view.toPlainText().startswith("bind = SUPER_ALT, D, exec, "))

    def test_arm_then_compositor_toggle_emits_event_and_does_not_act(self):
        state, page = self.make()
        before = self.tr.raw("status")["data"]["state"]
        page.start_test()
        self.assertTrue(wait_for(lambda: page.test_status.text().startswith("Pressione o atalho agora"), 3))
        self.assertFalse(page.is_verified)
        reply = self.tr.raw("toggle")                           # o compositor dispara `dracaena toggle`
        self.assertEqual(reply["data"], {"shortcut_test": True})
        self.assertTrue(wait_for(lambda: page.is_verified, 3))
        self.assertEqual(self.tr.raw("status")["data"]["state"], before)     # o toggle NÃO agiu
        self.assertIn("Atalho confirmado", page.test_status.text())

    def test_toggle_without_arm_does_not_verify(self):
        state, page = self.make()
        self.tr.raw("toggle")                                   # desarmado: age normalmente
        self.tr.raw("stop")
        wait_for(lambda: False, 0.3)
        self.assertFalse(page.is_verified)

    def test_second_toggle_after_test_acts_again(self):
        state, page = self.make()
        page.start_test()
        wait_for(lambda: page.test_status.text().startswith("Pressione"), 3)
        self.tr.raw("toggle")                                   # consumido pelo teste
        wait_for(lambda: page.is_verified, 3)
        before = self.tr.raw("status")["data"]["state"]
        self.tr.raw("toggle")                                   # desarmou: agora age
        after = self.tr.raw("status")["data"]["state"]
        self.assertNotEqual(before, after)
        self.tr.raw("stop")


if __name__ == "__main__":
    unittest.main()
