import unittest

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence

from dracaena.ui.settings.testsupport import ContractFake, app, screenshot_dir, wait_for
from dracaena.ui.shortcuts_wizard import ShortcutWizardPage, ShortcutWizardWindow, gnome, instructions
from dracaena.ui.shortcuts_wizard.commands import ToggleCommand, toggle_command
from dracaena.ui.shortcuts_wizard.env import detect
from dracaena.ui.shortcuts_wizard.page import key_from_sequence
from dracaena.ui.state import AppState

app()
ITEM = f"{gnome.ITEM_SCHEMA}:{gnome.ITEM_PATH}"


class FakeGsettings:
    """gsettings simulado: guarda a lista; nunca toca o gsettings real."""
    def __init__(self, listing="@as []", fail_on=None):
        self.listing, self.calls, self.fail_on = listing, [], fail_on

    def __call__(self, argv):
        self.calls.append(list(argv))
        if argv[:2] == ["gsettings", "get"]:
            return 0, self.listing
        if self.fail_on and self.fail_on in argv:
            return 1, "falhou"
        if argv[:2] == ["gsettings", "set"] and argv[2] == gnome.SCHEMA and argv[3] == gnome.LIST_KEY:
            self.listing = argv[4]
        return 0, ""


class EnvTests(unittest.TestCase):
    def test_detection_matrix(self):
        cases = [
            (dict(XDG_SESSION_TYPE="x11", XDG_CURRENT_DESKTOP="ubuntu:GNOME"), "x11", "gnome", True),
            (dict(XDG_SESSION_TYPE="wayland", XDG_CURRENT_DESKTOP="GNOME"), "wayland", "gnome", False),
            (dict(XDG_SESSION_TYPE="wayland", XDG_CURRENT_DESKTOP="KDE"), "wayland", "kde", False),
            (dict(XDG_SESSION_TYPE="wayland", XDG_CURRENT_DESKTOP="Hyprland"), "wayland", "hyprland", False),
            (dict(XDG_SESSION_TYPE="wayland", XDG_CURRENT_DESKTOP="sway"), "wayland", "sway", False),
            (dict(XDG_SESSION_TYPE="x11", XDG_CURRENT_DESKTOP="i3"), "x11", "i3", True),
            (dict(WAYLAND_DISPLAY="wayland-1", SWAYSOCK="/x"), "wayland", "sway", False),
            (dict(DISPLAY=":0", XDG_CURRENT_DESKTOP="XFCE"), "x11", "other", True),
            ({}, "unknown", "other", False),
        ]
        for environ, sess, comp, reg in cases:
            e = detect(environ, "linux")
            self.assertEqual((e.session, e.compositor, e.app_can_register), (sess, comp, reg), environ)
        w = detect({}, "win32")
        self.assertEqual((w.session, w.app_can_register), ("windows", True))


class CommandTests(unittest.TestCase):
    def test_text_quotes_safely(self):
        c = ToggleCommand(("/opt/meu app/D.AppImage", "toggle"), "daemon")
        self.assertEqual(c.text(), "'/opt/meu app/D.AppImage' toggle")
        self.assertEqual(c.text(windows=True), '"/opt/meu app/D.AppImage" toggle')
        self.assertEqual(toggle_command().text(), "dracaena toggle")


class GnomeTests(unittest.TestCase):
    def test_parse_list(self):
        self.assertEqual(gnome.parse_list("@as []"), [])
        self.assertEqual(gnome.parse_list("['/a/', '/b/']"), ["/a/", "/b/"])
        for bad in ("nao-lista", "[1]", "{'a':1}", "[]]"):
            with self.assertRaises(ValueError):
                gnome.parse_list(bad)

    def test_plan_appends_never_overwrites_and_never_duplicates(self):
        user = ["/org/x/custom0/", "/org/x/custom1/"]
        p = gnome.build_plan(user, "dracaena toggle")
        self.assertEqual(list(p.new_list), user + [gnome.ITEM_PATH])
        self.assertIn("'/org/x/custom0/', '/org/x/custom1/', '" + gnome.ITEM_PATH + "'", p.steps[-1][4])
        again = gnome.build_plan(user + [gnome.ITEM_PATH], "dracaena toggle")
        self.assertTrue(again.already_listed)
        self.assertEqual(list(again.new_list), user + [gnome.ITEM_PATH])
        self.assertFalse([s for s in again.steps if s[3:4] == [gnome.LIST_KEY]])   # lista não regravada

    def test_copyable_text_round_trips_through_a_shell_parser(self):
        import shlex
        for command in ("dracaena toggle", "'/opt/a b/App.AppImage' toggle", "/x/it's $HOME/a\"b toggle"):
            plan = gnome.build_plan(["/org/x/custom0/"], command)
            lines = plan.text().splitlines()
            self.assertEqual([tuple(shlex.split(l)) for l in lines], [tuple(st) for st in plan.steps])
        self.assertIn("name \"'DRACAENA'\"", gnome.build_plan([], "dracaena toggle").text())

    def test_apply_sets_item_before_list_and_preserves_user_entries(self):
        fake = FakeGsettings("['/org/x/custom0/']")
        plan = gnome.build_plan(gnome.read_list(fake), "'/opt/a b/App.AppImage' toggle")
        gnome.apply_plan(plan, fake)
        sets = [c for c in fake.calls if c[1] == "set"]
        self.assertEqual([c[3] if c[2] == gnome.SCHEMA else c[3] for c in sets],
                         ["name", "command", "binding", gnome.LIST_KEY])
        self.assertEqual(gnome.parse_list(fake.listing), ["/org/x/custom0/", gnome.ITEM_PATH])
        cmd = [c for c in sets if c[3] == "command"][0][4]
        self.assertEqual(cmd, "'\\'/opt/a b/App.AppImage\\' toggle'")   # aspas escapadas no GVariant

    def test_apply_refuses_if_list_changed_since_plan(self):
        fake = FakeGsettings("['/a/']")
        plan = gnome.build_plan(gnome.read_list(fake), "dracaena toggle")
        fake.listing = "['/a/', '/novo/']"
        with self.assertRaises(RuntimeError):
            gnome.apply_plan(plan, fake)
        self.assertFalse([c for c in fake.calls if c[1] == "set"])

    def test_failure_stops_and_reports(self):
        fake = FakeGsettings("@as []", fail_on="binding")
        with self.assertRaises(OSError):
            gnome.apply_plan(gnome.build_plan([], "dracaena toggle"), fake)
        self.assertNotEqual(gnome.parse_list(fake.listing), [gnome.ITEM_PATH])   # lista não alterada


YES = [True]


def make(environ, *, answers=None, **kw):
    client = ContractFake(toggle_cmd=kw.pop("toggle_cmd", None))
    state = AppState()
    state.set_connected(kw.pop("connected", True))
    asked = [] if answers is None else answers

    def confirm(parent, text):
        asked.append(text)
        return YES[0]
    page = ShortcutWizardPage(client, state, environ=environ, platform="linux", confirm=confirm,
                              portal_probe=kw.pop("portal_probe", lambda: False), **kw)
    return client, state, page


YES = [True]
WAYLAND_GNOME = dict(XDG_SESSION_TYPE="wayland", XDG_CURRENT_DESKTOP="GNOME")


class PageTests(unittest.TestCase):
    def setUp(self):
        YES[0] = True

    def test_command_comes_from_hello_with_safe_quoting(self):
        client, state, page = make(WAYLAND_GNOME, toggle_cmd=["/tmp/x y/App.AppImage", "toggle"], runner=FakeGsettings())
        page.show()
        self.assertTrue(wait_for(lambda: page.command.source == "daemon"))
        self.assertEqual(page.command_view.text(), "'/tmp/x y/App.AppImage' toggle")

    def test_fallback_only_when_hello_has_no_toggle_cmd(self):
        client, state, page = make(WAYLAND_GNOME, runner=FakeGsettings())
        page.show()
        wait_for(lambda: client.calls)
        wait_for(lambda: False, 0.1)
        self.assertEqual((page.command.source, page.command_view.text()), ("fallback", "dracaena toggle"))

    def test_hyprland_and_sway_lines_use_daemon_command(self):
        for desk, expected in (("Hyprland", "bind = SUPER_ALT, D, exec, /opt/App toggle"),
                               ("sway", "bindsym Mod4+Mod1+d exec /opt/App toggle")):
            client, state, page = make(dict(XDG_SESSION_TYPE="wayland", XDG_CURRENT_DESKTOP=desk),
                                       toggle_cmd=["/opt/App", "toggle"])
            page.show()
            wait_for(lambda: page.command.source == "daemon")
            self.assertEqual(page.snippet_view.toPlainText(), expected)

    def test_kde_shows_manual_path_only(self):
        client, state, page = make(dict(XDG_SESSION_TYPE="wayland", XDG_CURRENT_DESKTOP="KDE"))
        page.show()
        texts = " ".join(l.text() for l in page.findChildren(type(page.env_label)))
        self.assertIn("Configurações do sistema → Atalhos → Adicionar comando", texts)
        self.assertFalse(hasattr(page, "snippet_view"))
        self.assertNotIn("X-KDE", texts)

    def test_x11_and_windows_register_in_app(self):
        calls = []
        client, state, page = make(dict(XDG_SESSION_TYPE="x11"), register_hotkey=lambda k, m: calls.append((k, m)))
        page.show()
        self.assertTrue(hasattr(page, "key_edit") and not hasattr(page, "command_view"))
        page.key_edit.setKeySequence(QKeySequence(Qt.META | Qt.ALT | Qt.Key_D))
        page.btn_register.click()
        self.assertEqual(calls, [("D", ("super", "alt"))])

    def test_register_conflict_message(self):
        def boom(k, m):
            raise OSError("Atalho já está em uso.")
        client, state, page = make(dict(XDG_SESSION_TYPE="x11"), register_hotkey=boom)
        page.key_edit.setKeySequence(QKeySequence(Qt.CTRL | Qt.Key_P))
        page.btn_register.click()
        self.assertEqual(page.info.text(), "Esse atalho já está em uso por outro programa. Escolha outro.")

    def test_key_conversion_rejects_bad_combos(self):
        self.assertEqual(key_from_sequence(QKeySequence(Qt.CTRL | Qt.Key_P)), ("P", ("ctrl",)))
        for bad in (QKeySequence(Qt.Key_P), QKeySequence(Qt.CTRL | Qt.Key_F5), QKeySequence()):
            with self.assertRaises(ValueError):
                key_from_sequence(bad)

    def test_gnome_preview_confirm_and_apply(self):
        fake = FakeGsettings("['/org/x/custom0/']")
        asked = []
        client, state, page = make(WAYLAND_GNOME, answers=asked, runner=fake, toggle_cmd=["/opt/App", "toggle"])
        page.show()
        wait_for(lambda: page.command.source == "daemon")
        page.btn_preview.click()
        self.assertIn("['/org/x/custom0/', '" + gnome.ITEM_PATH + "']", page.plan_view.toPlainText())   # mantém e acrescenta
        self.assertFalse([c for c in fake.calls if c[1] == "set"])           # prévia nunca grava
        YES[0] = False
        page.btn_apply.click()
        self.assertEqual(len(asked), 1)
        self.assertIn("gsettings set", asked[0])
        self.assertFalse([c for c in fake.calls if c[1] == "set"])           # recusou: nada gravado
        YES[0] = True
        page.btn_apply.click()
        self.assertEqual(gnome.parse_list(fake.listing), ["/org/x/custom0/", gnome.ITEM_PATH])
        self.assertIn("Atalho criado no GNOME", page.info.text())

    def test_portal_note_only_when_detected_on_kde_or_hyprland(self):
        for desk, found, visible in (("KDE", True, True), ("KDE", False, False), ("Hyprland", None, False),
                                     ("GNOME", True, False)):
            client, state, page = make(dict(XDG_SESSION_TYPE="wayland", XDG_CURRENT_DESKTOP=desk),
                                       portal_probe=lambda f=found: f, runner=FakeGsettings())
            page.show()
            self.assertEqual(page.portal_label.isVisible(), visible, (desk, found))

    def test_test_button_arms_and_confirms_only_on_shortcut_test_event(self):
        client, state, page = make(WAYLAND_GNOME, runner=FakeGsettings())
        page.show()
        done = []
        page.verified.connect(lambda: done.append(1))
        client.event_received.emit({"event": "shortcut_test", "ok": True})   # antes de armar: ignora
        self.assertFalse(page.is_verified)
        page.start_test()
        self.assertTrue(wait_for(lambda: page.test_status.text().startswith("Pressione o atalho agora")))
        self.assertEqual(client.calls[-1], ("shortcut.test", {"arm": True}))
        state.apply_state_event({"state": "running"})               # mudança de estado NÃO vale mais
        client.event_received.emit({"event": "shortcut_test", "ok": False})
        self.assertFalse(page.is_verified)
        client.fire_shortcut_test()                                  # o toggle do compositor chegou
        self.assertTrue(page.is_verified and done == [1])
        self.assertIn("Atalho confirmado", page.test_status.text())
        self.assertFalse([c for c in client.calls if c[0] in ("toggle", "stop")])   # nunca age no daemon

    def test_test_button_accepts_eventmsg_shape(self):
        class Ev:  # EventMsg do B1
            event, data = "shortcut_test", {"ok": True}
        client, state, page = make(WAYLAND_GNOME, runner=FakeGsettings())
        page.start_test()
        wait_for(lambda: page.test_status.text().startswith("Pressione"))
        client.event_received.emit(Ev())
        self.assertTrue(page.is_verified)

    def test_arm_failure_is_shown_and_does_not_verify(self):
        client, state, page = make(WAYLAND_GNOME, runner=FakeGsettings())
        client.shortcut_test_error = "Comando desconhecido"
        page.start_test()
        self.assertTrue(wait_for(lambda: "Comando desconhecido" in page.test_status.text()))
        self.assertTrue(page.btn_test.isEnabled())
        client.fire_shortcut_test()
        self.assertFalse(page.is_verified)

    def test_test_button_timeout_does_not_verify(self):
        client, state, page = make(WAYLAND_GNOME, runner=FakeGsettings(), test_timeout_ms=60)
        page.show()
        page.start_test()
        self.assertTrue(wait_for(lambda: "Não recebi o comando" in page.test_status.text()))
        self.assertFalse(page.is_verified)
        client.fire_shortcut_test()                                  # tarde demais: desarmado
        self.assertFalse(page.is_verified)

    def test_test_button_offline(self):
        client, state, page = make(WAYLAND_GNOME, runner=FakeGsettings(), connected=False)
        page.start_test()
        self.assertIn("Sem conexão", page.test_status.text())
        self.assertEqual([c for c in client.calls if c[0] == "shortcut.test"], [])

    def test_screenshots_per_environment(self):
        for tag, environ in (("gnome_wayland", WAYLAND_GNOME),
                             ("hyprland", dict(XDG_SESSION_TYPE="wayland", XDG_CURRENT_DESKTOP="Hyprland")),
                             ("kde_wayland", dict(XDG_SESSION_TYPE="wayland", XDG_CURRENT_DESKTOP="KDE")),
                             ("x11", dict(XDG_SESSION_TYPE="x11"))):
            client = ContractFake(toggle_cmd=["/opt/DRACAENA.AppImage", "toggle"])
            state = AppState()
            state.set_connected(True)
            win = ShortcutWizardWindow(client, state, environ=environ, platform="linux",
                                       portal_probe=lambda: False, runner=FakeGsettings())
            win.show()
            wait_for(lambda: win.page.command.source == "daemon" or win.page.env.app_can_register)
            if tag == "gnome_wayland":
                win.page.btn_preview.click()
            win.grab().save(str(screenshot_dir() / f"shortcut_wizard_{tag}.png"))


if __name__ == "__main__":
    unittest.main()
