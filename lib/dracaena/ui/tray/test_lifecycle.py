"""Testes de ciclo de vida sem alterar a sessão real do usuário."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from dracaena.ui.tray.lifecycle import SingleInstance, set_autostart
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
            set_autostart(False, ['dracaena', 'ui'], config_home=root)
            self.assertFalse((root / 'autostart').exists())
            set_autostart(True, ['/pasta com espaço/python', '-m', 'dracaena', 'ui'], config_home=root)
            path = root / 'autostart/dracaena-ui.desktop'
            self.assertIn('Exec="/pasta com espaço/python" "-m" "dracaena" "ui"', path.read_text())
            set_autostart(False, ['dracaena', 'ui'], config_home=root)
            self.assertFalse(path.exists())

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
