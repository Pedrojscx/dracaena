"""Integração X11 isolada em Xvfb, sem capturar o teclado da sessão real."""
import importlib.util
import os
import select
import shutil
import subprocess
import threading
import unittest
from unittest.mock import patch
from dracaena.ui.hotkeys import GlobalHotkey


@unittest.skipUnless(shutil.which('Xvfb'), 'Xvfb indisponível')
@unittest.skipUnless(importlib.util.find_spec('Xlib'), 'python-xlib indisponível (dependência opcional do atalho X11)')
class X11Tests(unittest.TestCase):
    def test_register_trigger_conflict_and_release(self):
        from Xlib import X, XK, display
        from Xlib.ext import xtest
        process = subprocess.Popen(['Xvfb', '-displayfd', '1', '-screen', '0', '640x480x24'],
                                   stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        first = second = connection = None
        try:
            self.assertTrue(select.select([process.stdout], [], [], 3)[0])
            name = ':' + process.stdout.readline().strip()
            with patch.dict(os.environ, {'DISPLAY': name, 'XDG_SESSION_TYPE': 'x11', 'WAYLAND_DISPLAY': ''}):
                registered, triggered, conflict = threading.Event(), threading.Event(), threading.Event()
                first = GlobalHotkey(triggered.set, on_status=lambda text: registered.set())
                first.start()
                self.assertTrue(registered.wait(2))
                self.assertTrue(first._thread.is_alive())
                connection = display.Display(name)
                super_key = connection.keysym_to_keycode(XK.string_to_keysym('Super_L'))
                p_key = connection.keysym_to_keycode(XK.string_to_keysym('p'))
                for kind, key in ((X.KeyPress, super_key), (X.KeyPress, p_key),
                                  (X.KeyRelease, p_key), (X.KeyRelease, super_key)):
                    xtest.fake_input(connection, kind, key)
                connection.sync()
                self.assertTrue(triggered.wait(2))
                messages = []
                def status(text):
                    messages.append(text)
                    conflict.set()
                second = GlobalHotkey(lambda: None, on_status=status)
                second.start()
                self.assertTrue(conflict.wait(2))
                self.assertIn('Não foi possível', messages[-1])
                first.close()
                first._thread.join(2)
                self.assertFalse(first._thread.is_alive())
        finally:
            for hotkey in (first, second):
                if hotkey:
                    hotkey.close()
                    hotkey._thread.join(2)
            if connection:
                connection.close()
            process.terminate()
            process.wait(timeout=3)
            process.stdout.close()


if __name__ == '__main__':
    unittest.main()
