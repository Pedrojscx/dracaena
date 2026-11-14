"""`dracaena daemon`: Service real por padrão em modo simulação; --simulate continua com o simulador."""
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from dracaena import cli
from dracaena import daemon as daemon_module
from dracaena.platform import config


class DaemonCommandTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        for item in (patch.object(config, "config_dir", return_value=root / "config"),
                     patch.dict(os.environ, {"XDG_CONFIG_HOME": str(root / "xdg")})):
            item.start()
            self.addCleanup(item.stop)

    def run_daemon(self, argv):
        """Roda `dracaena daemon` sem abrir socket: captura o Daemon montado."""
        built = []

        def fake_run(server):
            built.append(server)
        out, err = io.StringIO(), io.StringIO()
        with patch.object(daemon_module.Daemon, "run", fake_run), patch.object(cli.signal, "signal"), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(argv)
        return code, built, out.getvalue(), err.getvalue()

    def test_real_daemon_uses_core_service_in_dry_run_and_starts_nothing(self):
        from dracaena.core.service import Service
        with patch("dracaena.platform.browser.read_port", side_effect=AssertionError("não deve procurar navegador")), \
                patch("dracaena.platform.browser.launch", side_effect=AssertionError("não deve abrir navegador")), \
                patch("playwright.sync_api.sync_playwright", side_effect=AssertionError("não deve conectar")), \
                patch("subprocess.Popen", side_effect=AssertionError("não deve iniciar processo")):
            code, built, out, err = self.run_daemon(["daemon"])
            self.assertEqual((code, out, err), (0, "", ""))
            server = built[0]
            self.assertIsInstance(server.service, Service)
            self.assertFalse(server.simulate)
            self.assertIs(server.service_factory, daemon_module.real_service)
            self.assertEqual(server.service.handle("status", {}),
                             {"state": "idle", "site": "", "question": 0, "max": 0, "error": "", "dry_run": True})

    def test_real_mode_comes_only_from_the_stored_key(self):
        config.set_value("DRY_RUN", False)
        self.assertIs(self.run_daemon(["daemon"])[1][0].service.handle("status", {})["dry_run"], False)
        (Path(self.directory.name) / "config" / "config.json").write_text("{quebrado", encoding="utf-8")
        self.assertIs(self.run_daemon(["daemon"])[1][0].service.handle("status", {})["dry_run"], True,
                      "configuração ilegível cai no modo simulação")

    def test_no_argument_turns_real_mode_on(self):
        for flag in ("--real", "--no-dry-run", "--dry-run=false"):
            with self.subTest(flag=flag), self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
                cli.main(["daemon", flag])

    def test_simulate_still_uses_the_simulator(self):
        code, built, _, _ = self.run_daemon(["daemon", "--simulate"])
        self.assertEqual(code, 0)
        self.assertIsInstance(built[0].service, daemon_module.Simulator)
        self.assertTrue(built[0].simulate)
        self.assertIsNone(built[0].service_factory)

    def test_missing_core_module_is_a_json_error_without_traceback(self):
        with patch.object(daemon_module, "real_service", side_effect=ModuleNotFoundError("módulo ausente")):
            code, built, out, err = self.run_daemon(["daemon"])
        self.assertEqual((code, built), (1, []))
        result = json.loads(out)
        self.assertFalse(result["ok"])
        self.assertIn("não está disponível neste executável", result["error"])
        self.assertNotIn("Traceback", out + err)


if __name__ == "__main__":
    unittest.main()
