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

    def test_incompatible_default_without_fallback_enabled_is_error(self):
        with patch.object(browser, "default_browser", return_value="firefox"), patch.object(browser, "is_chromium", return_value=False), \
                patch.object(browser, "fallback_executable") as reserve:
            with self.assertRaises(browser.BrowserError) as caught:
                browser.resolve("", "")
            self.assertNotIsInstance(caught.exception, (browser.NoBrowser, browser.FallbackMissing))
            reserve.assert_not_called()

    def test_incompatible_default_uses_fallback_when_present(self):
        with patch.object(browser, "default_browser", return_value="firefox"), patch.object(browser, "is_chromium", return_value=False), \
                patch.object(browser, "fallback_executable", return_value="/reserva/chrome"):
            self.assertEqual(browser.resolve(), "/reserva/chrome")
            self.assertEqual(browser.resolve("", "playwright"), "/reserva/chrome")

    def test_incompatible_default_with_fallback_absent_is_fallback_missing(self):
        with patch.object(browser, "default_browser", return_value="firefox"), patch.object(browser, "is_chromium", return_value=False), \
                patch.object(browser, "fallback_executable", return_value=None):
            with self.assertRaises(browser.FallbackMissing):
                browser.resolve()

    def test_chromium_default_ignores_fallback(self):
        with patch.object(browser, "default_browser", return_value="chromium"), patch.object(browser, "is_chromium", return_value=True), \
                patch.object(browser, "fallback_executable", return_value="/reserva/chrome") as reserve:
            self.assertEqual(browser.resolve(), "chromium")
            reserve.assert_not_called()

    def test_invalid_explicit_browser_ignores_fallback(self):
        with patch.object(browser, "is_chromium", return_value=False), patch.object(browser, "fallback_executable", return_value="/reserva/chrome") as reserve:
            with self.assertRaises(browser.BrowserError):
                browser.resolve("configured", "playwright")
            reserve.assert_not_called()

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

    def test_unsupported_sandbox_browser_uses_fallback_only_when_enabled(self):
        with patch.object(browser, "default_browser", side_effect=browser.BrowserUnsupported("Flatpak")), \
                patch.object(browser, "fallback_executable", return_value="/reserva/chrome"):
            with self.assertRaises(browser.BrowserUnsupported):
                browser.resolve("", "")
            self.assertEqual(browser.resolve(), "/reserva/chrome")

    def test_sandboxed_default_without_cdp_uses_fallback(self):
        with patch.object(browser, "default_browser", return_value="/var/lib/flatpak/exports/bin/org.mozilla.firefox"), \
                patch.object(browser, "sandboxed", return_value=True), patch.object(browser, "supports_cdp", return_value=False), \
                patch.object(browser, "fallback_executable", return_value="/reserva/chrome"):
            self.assertEqual(browser.resolve(), "/reserva/chrome")
            with self.assertRaises(browser.BrowserUnsupported):
                browser.resolve("", "")


class FallbackDownloadTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.data = Path(self.directory.name) / "data"
        self.patch = patch.object(browser, "data_dir", return_value=self.data)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.directory.cleanup()

    def fake_playwright(self, executable, seen=None):
        from unittest.mock import MagicMock
        context = MagicMock()
        def path_property():
            if seen is not None:
                seen.append(os.environ.get(browser.BROWSERS_KEY))
            return executable
        type(context.__enter__.return_value.chromium).executable_path = property(lambda self: path_property())
        return patch("playwright.sync_api.sync_playwright", return_value=context)

    def test_missing_fallback_is_a_distinct_error_and_uses_our_directory(self):
        seen = []
        before = os.environ.get(browser.BROWSERS_KEY)
        with patch.object(browser, "default_browser", side_effect=browser.BrowserError("ausente")), \
                self.fake_playwright(str(self.data / "nao-existe"), seen):
            with self.assertRaisesRegex(browser.FallbackMissing, "ainda não foi baixado"):
                browser.resolve()
        self.assertEqual(seen, [str(self.data / "browsers")])
        self.assertEqual(os.environ.get(browser.BROWSERS_KEY), before)

    def test_no_browser_error_type_when_fallback_disabled(self):
        with patch.object(browser, "default_browser", side_effect=browser.BrowserError("ausente")):
            with self.assertRaises(browser.NoBrowser):
                browser.resolve("", "")

    def test_install_runs_embedded_driver_into_private_directory(self):
        calls = []
        def fake_run(command, **kwargs):
            calls.append((command, kwargs))
            from types import SimpleNamespace
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        with patch.object(browser.subprocess, "run", fake_run), patch.object(browser, "fallback_executable", return_value="/x/chrome"):
            self.assertEqual(browser.install_fallback(), "/x/chrome")
        command, kwargs = calls[0]
        self.assertEqual(command[2:], ["install", "chromium", "--no-shell", "--no-progress"])
        self.assertTrue(command[1].endswith("cli.js"))
        self.assertEqual(kwargs["env"][browser.BROWSERS_KEY], str(self.data / "browsers"))
        if os.name != "nt":
            self.assertEqual((self.data / "browsers").stat().st_mode & 0o777, 0o700)

    def test_download_failures_are_explained_in_portuguese(self):
        from types import SimpleNamespace
        cases = {"getaddrinfo ENOTFOUND cdn.playwright.dev": "Sem conexão",
                 "Error: EACCES: permission denied, mkdir": "Sem permissão",
                 "ENOSPC: no space left on device": "Sem espaço",
                 "algo estranho": "Falha ao baixar"}
        for output, expected in cases.items():
            with self.subTest(output=output), patch.object(browser.subprocess, "run",
                    return_value=SimpleNamespace(returncode=1, stdout="", stderr=output)):
                with self.assertRaisesRegex(browser.BrowserError, expected):
                    browser.install_fallback()
        with patch.object(browser.subprocess, "run", side_effect=browser.subprocess.TimeoutExpired("x", 1)):
            with self.assertRaisesRegex(browser.BrowserError, "Tempo esgotado"):
                browser.install_fallback()
        with patch.object(browser.subprocess, "run", side_effect=FileNotFoundError()):
            with self.assertRaisesRegex(browser.BrowserError, "instalador"):
                browser.install_fallback()

    def test_unwritable_directory_is_reported(self):
        with patch.object(browser, "private_dir", side_effect=PermissionError()):
            with self.assertRaisesRegex(browser.BrowserError, "Sem permissão"):
                browser.install_fallback()

    def test_doctor_never_downloads_and_shows_hint(self):
        from dracaena.platform import doctor
        with patch.object(browser, "resolve", side_effect=browser.FallbackMissing("O Chromium reserva ainda não foi baixado")), \
                patch.object(browser, "install_fallback") as install:
            checks = {c["name"]: c for c in doctor.run()["checks"]}
        install.assert_not_called()
        self.assertFalse(checks["browser"]["ok"])
        self.assertIn("dracaena install-browser", checks["browser"]["hint"])


class InstallBrowserCommandTests(unittest.TestCase):
    def run_command(self, assume_yes=False, answer="n", interactive=True, cfg=None, resolve=None, existing=None):
        import contextlib
        import io
        from dracaena import cli
        cfg = {"BROWSER_BIN": "", "BROWSER_FALLBACK": "playwright", **(cfg or {})}
        out, prompts = io.StringIO(), []
        resolve = resolve or browser.NoBrowser("Nenhum navegador")
        with patch("dracaena.platform.config.load", return_value=cfg), \
                patch.object(browser, "resolve", side_effect=resolve if isinstance(resolve, Exception) else None,
                             return_value=None if isinstance(resolve, Exception) else resolve), \
                patch.object(browser, "fallback_executable", return_value=existing), \
                patch.object(browser, "install_fallback", return_value="/dados/chrome") as install, \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = cli.install_browser(assume_yes, ask=lambda text: prompts.append(text) or answer, interactive=interactive)
        return code, json.loads(out.getvalue()), install, prompts

    def test_asks_and_downloads_only_after_explicit_yes(self):
        code, result, install, prompts = self.run_command(answer="s")
        self.assertEqual((code, result["ok"]), (0, True))
        install.assert_called_once()
        self.assertIn("400 MB", prompts[0])

    def test_declined_or_noninteractive_does_not_download(self):
        for kwargs in (dict(answer=""), dict(answer="n"), dict(interactive=False)):
            code, result, install, _ = self.run_command(**kwargs)
            self.assertEqual(code, 1)
            install.assert_not_called()
        self.assertIn("--yes", self.run_command(interactive=False)[1]["error"])

    def test_yes_flag_skips_prompt(self):
        code, result, install, prompts = self.run_command(assume_yes=True, interactive=False)
        self.assertEqual(code, 0)
        install.assert_called_once()
        self.assertEqual(prompts, [])

    def test_existing_or_configured_browser_has_priority(self):
        code, result, install, _ = self.run_command(assume_yes=True, resolve="/usr/bin/chromium")
        self.assertEqual(code, 0)
        install.assert_not_called()
        code, result, install, _ = self.run_command(assume_yes=True, cfg={"BROWSER_BIN": "/x/firefox"},
                                                    resolve=browser.BrowserError("Navegador configurado não é Chromium válido"))
        self.assertEqual(code, 1)
        install.assert_not_called()

    def test_incompatible_default_proceeds_to_reserve_but_explicit_does_not(self):
        incompatible = browser.BrowserError("Navegador padrão detectado não é Chromium")
        code, result, install, _ = self.run_command(assume_yes=True, resolve=incompatible, existing="/dados/chrome")
        self.assertEqual(code, 0)
        self.assertIn("incompatível", result["message"])
        install.assert_not_called()
        code, result, install, prompts = self.run_command(answer="s", resolve=incompatible)
        self.assertEqual(code, 0)
        install.assert_called_once()
        self.assertIn("incompatível", prompts[0])
        code, result, install, _ = self.run_command(assume_yes=True, resolve=incompatible, cfg={"BROWSER_BIN": "/x/firefox"}, existing="/dados/chrome")
        self.assertEqual(code, 1)
        install.assert_not_called()
        code, result, install, _ = self.run_command(assume_yes=True, resolve=incompatible, cfg={"BROWSER_FALLBACK": ""})
        self.assertEqual(code, 1)
        install.assert_not_called()

    def test_disabled_fallback_and_already_installed(self):
        code, result, install, _ = self.run_command(assume_yes=True, cfg={"BROWSER_FALLBACK": ""})
        self.assertEqual(code, 1)
        install.assert_not_called()
        code, result, install, _ = self.run_command(assume_yes=True, existing="/dados/chrome")
        self.assertEqual(code, 0)
        install.assert_not_called()

    def test_download_error_is_reported(self):
        from dracaena import cli
        import contextlib
        import io
        out = io.StringIO()
        with patch("dracaena.platform.config.load", return_value={"BROWSER_BIN": "", "BROWSER_FALLBACK": "playwright"}), \
                patch.object(browser, "resolve", side_effect=browser.NoBrowser("x")), \
                patch.object(browser, "fallback_executable", return_value=None), \
                patch.object(browser, "install_fallback", side_effect=browser.BrowserError("Sem conexão com a internet")), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(cli.install_browser(True), 1)
        self.assertIn("Sem conexão", json.loads(out.getvalue())["error"])


class FallbackModuleAbsentTests(unittest.TestCase):
    """Executável sem o módulo do Chromium reserva: erro em português, sem traceback e sem download."""

    ABSENT = {name: None for name in ("playwright", "playwright.sync_api", "playwright._impl", "playwright._impl._driver")}

    def run_main(self, argv):
        import contextlib
        import io
        import sys
        from dracaena import cli
        out, err = io.StringIO(), io.StringIO()
        with patch.dict(sys.modules, self.ABSENT), \
                patch("dracaena.platform.config.load", return_value={"BROWSER_BIN": "", "BROWSER_FALLBACK": "playwright"}), \
                patch.object(browser, "default_browser", side_effect=browser.BrowserError("ausente")), \
                patch.object(browser.subprocess, "run") as run, patch.object(browser.subprocess, "Popen") as popen, \
                patch("builtins.input", side_effect=AssertionError("não deve perguntar")), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(argv)
        run.assert_not_called()
        popen.assert_not_called()
        return code, out.getvalue(), err.getvalue()

    def test_install_browser_reports_json_error_without_traceback_or_download(self):
        for argv in (["install-browser"], ["install-browser", "--yes"]):
            with self.subTest(argv=argv):
                code, out, err = self.run_main(argv)
                self.assertNotEqual(code, 0)
                result = json.loads(out)
                self.assertEqual(set(result), {"ok", "error"})
                self.assertFalse(result["ok"])
                self.assertIn("Chromium reserva não está disponível neste executável", result["error"])
                self.assertNotIn("Traceback", out + err)
                self.assertNotIn("Baixando", err)

    def test_library_calls_raise_browser_error(self):
        import sys
        with patch.dict(sys.modules, self.ABSENT), patch.object(browser.subprocess, "run") as run:
            for call in (browser.fallback_executable, browser.install_fallback):
                with self.subTest(call=call.__name__), self.assertRaisesRegex(browser.FallbackUnavailable, "não está disponível"):
                    call()
            with patch.object(browser, "default_browser", side_effect=browser.BrowserError("ausente")), \
                    self.assertRaises(browser.FallbackUnavailable):
                browser.resolve()
        run.assert_not_called()

    def test_doctor_does_not_suggest_download_when_module_is_absent(self):
        import sys
        from dracaena.platform import doctor
        with patch.dict(sys.modules, self.ABSENT), \
                patch("dracaena.platform.config.load", return_value={"BROWSER_BIN": "", "BROWSER_FALLBACK": "playwright"}), \
                patch.object(browser, "default_browser", side_effect=browser.BrowserError("ausente")):
            checks = {c["name"]: c for c in doctor.run()["checks"]}
        self.assertFalse(checks["browser"]["ok"])
        self.assertIn("não está disponível neste executável", checks["browser"]["message"])
        self.assertNotIn("install-browser", checks["browser"].get("hint", ""))


if __name__ == "__main__":
    unittest.main()
