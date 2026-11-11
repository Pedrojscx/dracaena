"""Testes de ciclo de vida sem alterar a sessão real do usuário."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from dracaena.ui.tray import lifecycle
from dracaena.ui.tray.lifecycle import (SingleInstance, autostart_argv, autostart_command,
                                         is_autostart_enabled, set_autostart)
from dracaena.ui.hotkeys import GlobalHotkey, WAYLAND_HELP


class LifecycleTests(unittest.TestCase):
    def test_single_instance_release(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'ui.lock'
            first, second = SingleInstance(path), SingleInstance(path)
            self.assertTrue(first.acquire())
            self.assertFalse(second.acquire())
            first.close()
            self.assertTrue(second.acquire())
            second.close()

    @unittest.skipUnless(sys.platform.startswith('linux'), 'Autostart Linux')
    def test_autostart_opt_in_and_remove(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.assertFalse(is_autostart_enabled(config_home=root))
            set_autostart(False, ['dracaena', 'ui'], config_home=root)
            self.assertFalse((root / 'autostart').exists())
            argv = ['/pasta com espaço/python', '-m', 'dracaena', 'ui', '--background']
            set_autostart(True, argv, config_home=root)
            path = root / 'autostart/dracaena.desktop'
            self.assertIn('Exec="/pasta com espaço/python" "-m" "dracaena" "ui" "--background"', path.read_text())
            self.assertTrue(is_autostart_enabled(config_home=root))
            self.assertEqual(autostart_argv(config_home=root), argv)
            set_autostart(False, argv, config_home=root)
            self.assertFalse(path.exists())
            self.assertFalse(is_autostart_enabled(config_home=root))

    @unittest.skipUnless(sys.platform.startswith('linux'), 'Autostart Linux')
    def test_autostart_writes_exactly_the_given_argv(self):
        argv = ['/opt/App Dir/Dracaena.AppImage', 'a"b', 'c`d', '$HOME', r'back\slash', '100%', '--background']
        with tempfile.TemporaryDirectory() as temp:
            set_autostart(True, argv, config_home=Path(temp))
            self.assertEqual(autostart_argv(config_home=Path(temp)), argv)
            text = (Path(temp) / 'autostart/dracaena.desktop').read_text()
            self.assertEqual(text.count('Exec='), 1)
            self.assertNotIn('\n\n', text)

    @unittest.skipUnless(sys.platform.startswith('linux'), 'Autostart Linux')
    def test_autostart_disabled_markers_and_invalid_argv(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            set_autostart(True, ['dracaena'], config_home=root)
            path = root / 'autostart/dracaena.desktop'
            path.write_text(path.read_text() + 'Hidden=true\n')
            self.assertFalse(is_autostart_enabled(config_home=root))
            path.write_text('lixo sem seção\n')
            self.assertFalse(is_autostart_enabled(config_home=root))
            for bad in ([], ['a\nExec=evil'], ['a\0b']):
                with self.assertRaises(ValueError):
                    set_autostart(True, bad, config_home=root)

    def test_autostart_command_adds_background_once(self):
        self.assertEqual(autostart_command(['app', 'ui']), ['app', 'ui', '--background'])
        self.assertEqual(autostart_command(['app', '--background']), ['app', '--background'])

    def test_windows_run_key_with_fake_registry(self):
        store = {}

        class Key:
            def __enter__(self): return self
            def __exit__(self, *exc): return False

        fake = types.SimpleNamespace(
            HKEY_CURRENT_USER='HKCU', REG_SZ=1,
            CreateKey=lambda root, path: Key(), OpenKey=lambda root, path: Key(),
            SetValueEx=lambda key, name, reserved, kind, value: store.__setitem__(name, value),
            QueryValueEx=lambda key, name: (store[name], 1) if name in store else (_ for _ in ()).throw(FileNotFoundError()),
            DeleteValue=lambda key, name: store.pop(name) if name in store else (_ for _ in ()).throw(FileNotFoundError()))
        with patch.object(sys, 'platform', 'win32'), patch.dict(sys.modules, {'winreg': fake}):
            self.assertFalse(is_autostart_enabled())
            set_autostart(True, [r'C:\Program Files\Dracaena\dracaena.exe', '--background'])
            self.assertEqual(store['DracaenaUI'], subprocess.list2cmdline(
                [r'C:\Program Files\Dracaena\dracaena.exe', '--background']))
            self.assertTrue(is_autostart_enabled())
            set_autostart(False, ['x'])
            set_autostart(False, ['x'])  # idempotente
            self.assertFalse(is_autostart_enabled())

    def test_wayland_does_not_start_worker_even_with_xwayland(self):
        status = []
        with patch.dict(os.environ, {'XDG_SESSION_TYPE': 'wayland', 'DISPLAY': ':99'}):
            hotkey = GlobalHotkey(lambda: self.fail('Captura proibida'), on_status=status.append)
            hotkey.start()
            self.assertIsNone(hotkey._thread)
            self.assertEqual(status, [WAYLAND_HELP])

    def test_hotkey_rejects_unknown_modifier(self):
        with self.assertRaises(ValueError):
            GlobalHotkey(lambda: None, modifiers=('meta-invalido',))


if __name__ == '__main__':
    unittest.main()
