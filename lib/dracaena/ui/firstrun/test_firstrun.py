import unittest

from dracaena.ui.firstrun import FirstRunWindow
from dracaena.ui.firstrun.window import format_checks
from dracaena.ui.settings.testsupport import ContractFake, Resp, app, screenshot_dir, wait_for
from dracaena.ui.state import AppState

app()
WAYLAND_GNOME = dict(XDG_SESSION_TYPE="wayland", XDG_CURRENT_DESKTOP="GNOME")


_WINDOWS = []


def make(connected=True):
    from dracaena.ui.add_site import AddSitePage
    from dracaena.ui.shortcuts_wizard import ShortcutWizardPage
    client = ContractFake(toggle_cmd=["/opt/DRACAENA.AppImage", "toggle"])
    state = AppState()
    state.set_connected(connected)
    pages = (AddSitePage(client, state, confirm=lambda p, t: True),
             ShortcutWizardPage(client, state, environ=WAYLAND_GNOME, platform="linux",
                                portal_probe=lambda: False, runner=lambda argv: (0, "@as []")))
    win = FirstRunWindow(client, state, pages=pages)
    _WINDOWS.append(win)
    return client, state, win


class FirstRunTests(unittest.TestCase):
    def tearDown(self):
        # destrói as janelas em ordem previsível: evita aviso de QObject no encerramento do Python
        while _WINDOWS:
            w = _WINDOWS.pop()
            w.close()
            w.deleteLater()
        from PySide6.QtCore import QCoreApplication, QEvent
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)

    def test_welcome_text_and_doctor(self):
        client, state, win = make()
        win.show()
        self.assertIn("Bem-vindo ao DRACAENA", win.findChild(type(win.steps), "welcome").text())
        self.assertTrue(wait_for(lambda: "tudo certo" in win.doctor_label.text()))
        self.assertIn("✔ Claude Code — autenticado", win.doctor_label.text())

    def test_doctor_waits_for_connection(self):
        client, state, win = make(connected=False)
        win.show()
        self.assertEqual([c for c in client.calls if c[0] == "doctor"], [])
        state.set_connected(True)
        self.assertTrue(wait_for(lambda: "tudo certo" in win.doctor_label.text()))

    def test_doctor_failure_lists_items_and_hint(self):
        ok, lines = format_checks({"ok": False, "checks": [
            {"name": "navegador", "ok": False, "message": "não achei", "hint": "instale um navegador"},
            {"name": "Claude Code", "ok": True, "hint": "não aparece quando ok"}]})
        self.assertEqual((ok, lines), (False, ["✘ navegador — não achei", "    Dica: instale um navegador",
                                               "✔ Claude Code"]))

    def test_full_flow_finishes_with_real_signals(self):
        client, state, win = make()
        win.show()
        out, auto = [], []
        win.finished.connect(out.append)
        win.autostart_requested.connect(auto.append)
        win.btn_next.click()                                   # início -> adicionar site
        self.assertIn("Passo 1 de 2", win.steps.text())
        self.assertTrue(win.btn_skip.isVisible())
        page = win.add_page
        page.verify()
        wait_for(lambda: page.result is not None)
        page.name.setText("pratica-1")
        page.save()
        self.assertTrue(wait_for(lambda: win._site_saved))
        self.assertFalse(win.btn_skip.isVisible())
        win.btn_next.click()                                   # -> atalho
        self.assertIn("Passo 2 de 2", win.steps.text())
        win.shortcut_page.start_test()
        wait_for(lambda: client.armed)
        client.fire_shortcut_test()                            # o toggle do compositor chegou ao daemon
        self.assertTrue(win._shortcut_ok)
        win.btn_next.click()                                   # -> fim
        self.assertIn("Pronto. O DRACAENA fica na bandeja.", win.done_label.text())
        self.assertIn("✔ Site salvo.", win.summary.text())
        self.assertFalse(win.autostart.isChecked())            # desligado por padrão
        win.btn_next.click()                                   # Concluir
        self.assertEqual(out, [{"site_saved": True, "shortcut_verified": True, "autostart": False}])
        self.assertEqual(auto, [False])

    def test_skipping_does_not_mark_anything_done(self):
        client, state, win = make()
        win.show()
        out = []
        win.finished.connect(out.append)
        win.btn_next.click()
        win.btn_skip.click()
        win.btn_skip.click()
        self.assertIn("Nenhum site salvo", win.summary.text())
        self.assertIn("Atalho não confirmado", win.summary.text())
        win.autostart.setChecked(True)
        win.btn_next.click()
        self.assertEqual(out, [{"site_saved": False, "shortcut_verified": False, "autostart": True}])

    def test_closing_early_emits_dismissed_and_not_finished(self):
        client, state, win = make()
        win.show()
        out, gone = [], []
        win.finished.connect(out.append)
        win.dismissed.connect(lambda: gone.append(1))
        win.close()
        self.assertEqual((out, gone), ([], [1]))

    def test_concluding_does_not_emit_dismissed(self):
        client, state, win = make()
        win.show()
        gone = []
        win.dismissed.connect(lambda: gone.append(1))
        for _ in range(4):
            win.btn_next.click()
        self.assertEqual(gone, [])

    def test_screenshots_each_step(self):
        client, state, win = make()
        win.show()
        wait_for(lambda: "tudo certo" in win.doctor_label.text())
        for i, tag in enumerate(("1_inicio", "2_site", "3_atalho", "4_fim")):
            win._go(i)
            if i == 1:
                win.add_page.url.setText("https://exemplo.test/pratica")
                win.add_page.verify()
                wait_for(lambda: win.add_page.result is not None)
                win.add_page.name.setText("pratica-1")
            if i == 2:
                wait_for(lambda: win.shortcut_page.command.source == "daemon")
            win.grab().save(str(screenshot_dir() / f"first_run_{tag}.png"))


if __name__ == "__main__":
    unittest.main()
