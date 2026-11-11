import json
import os
from pathlib import Path
import socket
import tempfile
import threading
import unittest
from unittest.mock import patch

from dracaena.daemon import Daemon, Simulator
from dracaena.platform import browser, config
from dracaena.platform.instance import InstanceLock, LoopControl
from dracaena.platform.ipc import Connection
from dracaena.platform.resources import default_config


class PlatformTests(unittest.TestCase):
    def test_jsonl_fragmentation_and_unicode(self):
        left, right = socket.socketpair()
        try:
            conn = Connection(right)
            left.sendall(b'{"cmd":')
            left.sendall('"olá"}\n{"id":2}\n'.encode())
            self.assertEqual(conn.receive(), {"cmd": "olá"})
            self.assertEqual(conn.receive(), {"id": 2})
        finally:
            left.close()
            right.close()

    def test_invalid_requests_do_not_change_state(self):
        server = Daemon(Simulator())
        for request in ([], {"v": 1, "cmd": "toggle"}, {"cmd": "toggle", "args": []}):
            self.assertFalse(server.dispatch(request, None)["ok"])
        self.assertEqual(server.service.state, "idle")
        self.assertEqual(server.dispatch({"cmd": "unknown", "id": 7}, None)["code"], "unknown_cmd")

    def test_config_validation_and_resources(self):
        with self.assertRaises(ValueError):
            config.validate("MAX_QUESTIONS", True)
        with self.assertRaises(ValueError):
            config.validate("BROWSER_FALLBACK", "firefox")
        self.assertEqual(json.loads(default_config()), config.DEFAULTS)

    def test_prompts_are_not_duplicated_in_platform(self):
        names = {entry.name for entry in (Path(config.__file__).parent / "resources").iterdir()}
        self.assertFalse({"answer.txt", "invalid.txt", "retry.txt", "system.txt"} & names)

    def test_user_messages_are_portuguese(self):
        with self.assertRaisesRegex(ValueError, "Chave desconhecida"):
            config.validate("NOPE", 1)
        with self.assertRaisesRegex(ValueError, "intervalo"):
            config.validate("MAX_QUESTIONS", 0)
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "config.json").write_text("{", encoding="utf-8")
            with patch.object(config, "config_dir", return_value=Path(directory)):
                with self.assertRaisesRegex(ValueError, "corrompido"):
                    config.load()

    def test_persistence_and_legacy_migration(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            old = base / "quiz-helper/config"
            old.parent.mkdir()
            old.write_text("MODEL=sonnet\nMAX_QUESTIONS=12\nUNKNOWN=ignored\n", encoding="utf-8")
            with patch.dict(os.environ, {"XDG_CONFIG_HOME": directory}), patch.object(config, "config_dir", return_value=base / "dracaena"):
                self.assertEqual(config.load()["MAX_QUESTIONS"], 12)
                config.set_value("MAX_QUESTIONS", 15)
                self.assertEqual(config.load()["MAX_QUESTIONS"], 15)
                self.assertIn("MAX_QUESTIONS=12", old.read_text())
                if os.name != "nt":
                    self.assertEqual((base / "dracaena/config.json").stat().st_mode & 0o777, 0o600)

    def test_lock_excludes_second_instance(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch("dracaena.platform.instance.runtime_dir", return_value=Path(directory)):
                with InstanceLock():
                    with self.assertRaises(RuntimeError):
                        with InstanceLock():
                            pass
                with InstanceLock():
                    pass

    def test_control_does_not_need_signals(self):
        control = LoopControl()
        self.assertTrue(control.toggle())
        self.assertFalse(control.toggle())
        control.stop.set()
        self.assertTrue(control.stop.is_set())

    def test_dynamic_port_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / "DevToolsActivePort"
            file.write_text("49123\n/devtools/browser/test\n")
            self.assertEqual(browser.read_port(directory), 49123)
            for value in ("0\n/devtools/browser/a", "9222\ninvalid", "bad"):
                file.write_text(value)
                with self.assertRaises(browser.BrowserError):
                    browser.read_port(directory)

    def test_no_implicit_fallback(self):
        with patch.object(browser, "default_browser", return_value="firefox"), patch.object(browser, "is_chromium", return_value=False):
            with self.assertRaises(browser.BrowserError):
                browser.resolve()

    def test_explicit_browser_precedes_detection(self):
        with patch.object(browser, "default_browser") as detect, patch.object(browser, "is_chromium", return_value=True):
            self.assertEqual(browser.resolve("configured"), "configured")
            detect.assert_not_called()

    def test_invalid_explicit_browser_does_not_fallback(self):
        with patch.object(browser, "default_browser") as detect, patch.object(browser, "is_chromium", return_value=False):
            with self.assertRaises(browser.BrowserError):
                browser.resolve("configured")
            detect.assert_not_called()

    def test_detected_browser_precedes_fallback(self):
        with patch.object(browser, "default_browser", return_value="detected"), patch.object(browser, "is_chromium", return_value=True):
            self.assertEqual(browser.resolve(), "detected")

    def test_playwright_fallback_only_when_no_browser(self):
        from unittest.mock import MagicMock
        context = MagicMock()
        context.__enter__.return_value.chromium.executable_path = __file__
        with patch.object(browser, "default_browser", side_effect=browser.BrowserError("absent")), patch("playwright.sync_api.sync_playwright", return_value=context):
            self.assertEqual(browser.resolve(), __file__)

    def test_detected_sandbox_browser_does_not_silently_fallback(self):
        with patch.object(browser, "default_browser", side_effect=browser.BrowserUnsupported("Flatpak")):
            with self.assertRaises(browser.BrowserUnsupported):
                browser.resolve()


if __name__ == "__main__":
    unittest.main()
