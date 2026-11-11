"""Watcher do StatusNotifierWatcher e aviso de bandeja ausente.

O teste D-Bus roda num processo filho com um barramento de sessão privado (dbus-daemon);
sem dbus-daemon ele é PULADO. Não valida nenhum shell real (GNOME/KDE/Hyprland).
"""
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication
from dracaena.ui.tray import NOTICE_GNOME, NOTICE_HYPRLAND, NOTICE_NO_TRAY, TrayController, tray_notice

APP = QApplication.instance() or QApplication([])


class Client(QObject):
    availability_changed = Signal(bool, str)
    protocol_error = Signal(str)
    is_connected = False
    def connect_to_daemon(self): pass
    def request(self, *args, **kwargs): pass
    def close(self): pass


class Host:
    def open_settings(self): pass
    def open_add_site(self): pass
    def open_shortcut_wizard(self): pass
    def quit_app(self): pass


class NoticeTests(unittest.TestCase):
    def test_notice_texts_by_desktop(self):
        self.assertEqual(tray_notice('KDE'), NOTICE_NO_TRAY)
        self.assertTrue(tray_notice('ubuntu:GNOME').startswith(NOTICE_GNOME))
        self.assertTrue(tray_notice('Hyprland').startswith(NOTICE_HYPRLAND))
        self.assertTrue(tray_notice('Hyprland').endswith(NOTICE_NO_TRAY))

    def test_missing_tray_warns_once_hides_icon_and_keeps_app_usable(self):
        with tempfile.TemporaryDirectory() as temp:
            tray = TrayController(Client(), Host(), notifications=False, watch_dbus=False,
                                  lock_path=os.path.join(temp, 'ui.lock'))
            seen = []
            tray.tray_availability.connect(lambda ok, text: seen.append((ok, text)))
            try:
                tray._shown = True
                tray._set_tray_available(False)
                tray._set_tray_available(False)
                self.assertEqual(len(seen), 1)
                self.assertFalse(seen[0][0])
                self.assertIn('continua funcionando', seen[0][1])
                self.assertTrue(tray.settings.isEnabled())
                tray._set_tray_available(True)
                self.assertEqual(seen[-1], (True, ''))
            finally:
                tray.close()


CHILD = textwrap.dedent('''
    import os, sys, tempfile, time
    os.environ['QT_QPA_PLATFORM'] = 'offscreen'
    from PySide6.QtCore import QObject, Signal
    from PySide6.QtDBus import QDBusConnection
    from PySide6.QtWidgets import QApplication
    from dracaena.ui.tray import TrayController, WATCHER_SERVICE
    app = QApplication([])
    class Client(QObject):
        availability_changed = Signal(bool, str)
        protocol_error = Signal(str)
        is_connected = False
        def connect_to_daemon(self): pass
        def request(self, *a, **k): pass
        def close(self): pass
    class Host:
        def open_settings(self): pass
        def open_add_site(self): pass
        def open_shortcut_wizard(self): pass
        def quit_app(self): pass
    def until(pred, timeout=3):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            app.processEvents()
            if pred():
                return
            time.sleep(0.005)
        raise SystemExit('timeout')
    temp = tempfile.mkdtemp()
    tray = TrayController(Client(), Host(), notifications=False, lock_path=temp + '/ui.lock')
    seen = []
    tray.tray_availability.connect(lambda ok, text: seen.append(ok))
    assert tray.show()
    assert tray._watcher is not None, 'watcher não criado'
    assert tray.tray_available is False and seen == [False], (tray.tray_available, seen)
    first = tray.tray
    bus = QDBusConnection.sessionBus()
    assert bus.registerService(WATCHER_SERVICE)
    until(lambda: tray.tray_available is True)
    assert tray.tray is not first, 'ícone não foi recriado'
    assert tray.tray.contextMenu() is tray.menu
    bus.unregisterService(WATCHER_SERVICE)
    until(lambda: tray.tray_available is False)
    assert seen == [False, True, False], seen
    tray.close()
    print('ok')
''')


@unittest.skipUnless(sys.platform.startswith('linux') and shutil.which('dbus-daemon'),
                     'Precisa de Linux e dbus-daemon para um barramento de sessão privado')
class WatcherDbusTests(unittest.TestCase):
    def test_icon_is_recreated_when_watcher_appears(self):
        bus = subprocess.Popen(['dbus-daemon', '--session', '--nofork', '--print-address=1'],
                               stdout=subprocess.PIPE, text=True)
        try:
            address = bus.stdout.readline().strip()
            if not address:
                self.skipTest('dbus-daemon não informou endereço')
            env = dict(os.environ, DBUS_SESSION_BUS_ADDRESS=address, QT_QPA_PLATFORM='offscreen',
                       XDG_CURRENT_DESKTOP='')
            done = subprocess.run([sys.executable, '-c', CHILD], env=env, capture_output=True,
                                  text=True, timeout=30)
            self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
            self.assertIn('ok', done.stdout)
        finally:
            bus.terminate()
            bus.wait(timeout=5)
            bus.stdout.close()


if __name__ == '__main__':
    unittest.main()
