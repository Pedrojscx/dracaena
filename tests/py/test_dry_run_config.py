"""Chave DRY_RUN (modo simulação por padrão) e dry_run no estado do simulador."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from dracaena import daemon as daemon_module
from dracaena.daemon import Daemon, Simulator
from dracaena.platform import config


class FakeConn:
    def __init__(self):
        self.sent = []

    def send(self, value):
        self.sent.append(value)


class DryRunConfigTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.patches = [patch.object(config, "config_dir", return_value=self.root / "config"),
                        patch.dict(os.environ, {"XDG_CONFIG_HOME": str(self.root / "xdg")})]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.directory.cleanup()

    def test_default_is_safe_and_schema_is_boolean_in_portuguese(self):
        self.assertIs(config.DEFAULTS["DRY_RUN"], True)
        self.assertIs(config.load()["DRY_RUN"], True)
        entry = {e["key"]: e for e in config.schema()}["DRY_RUN"]
        self.assertEqual(entry["type"], "boolean")
        self.assertIs(entry["default"], True)
        self.assertEqual(entry["label"], "Modo simulação")
        self.assertEqual(entry["description"], "Modo simulação: valida e registra sem clicar na página.")
        schema = Daemon(Simulator(), simulate=True).dispatch({"id": 1, "cmd": "config.schema"}, None)["data"]
        self.assertIn("DRY_RUN", [e["key"] for e in schema])

    def test_only_real_booleans_are_accepted(self):
        self.assertIs(config.validate("DRY_RUN", False), False)
        for value in (0, 1, "true", "false", None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                config.validate("DRY_RUN", value)

    def test_legacy_import_never_turns_real_mode_on(self):
        legacy = self.root / "xdg" / "quiz-helper" / "config"
        legacy.parent.mkdir(parents=True)
        for text in ("DRY_RUN=0\n", "DRY_RUN=false\n", "DRY_RUN=talvez\n"):
            with self.subTest(text=text):
                legacy.write_text(text + "MAX_QUESTIONS=7\n", encoding="utf-8")
                values = config.load()
                self.assertIs(values["DRY_RUN"], True, "migração não ativa o modo real")
                self.assertEqual(values["MAX_QUESTIONS"], 7)
                self.assertIs(json.loads((self.root / "config" / "config.json").read_text())["DRY_RUN"], True)
                (self.root / "config" / "config.json").unlink()

    def test_simulator_state_carries_dry_run_from_config(self):
        self.assertIs(Simulator().snapshot()["dry_run"], True)
        config.set_value("DRY_RUN", False)
        self.assertIs(Simulator().snapshot()["dry_run"], False)
        self.assertIs(Simulator(dry_run=True).handle("status", {})["dry_run"], True)

    def test_unreadable_config_falls_back_to_dry_run(self):
        (self.root / "config").mkdir(mode=0o700)
        (self.root / "config" / "config.json").write_text("{quebrado", encoding="utf-8")
        self.assertIs(daemon_module.configured_dry_run(), True)
        self.assertIs(Simulator().snapshot()["dry_run"], True)

    def test_config_set_changes_dry_run_and_emits_state(self):
        daemon = Daemon(Simulator(), simulate=True)
        conn = FakeConn()
        self.assertTrue(daemon.dispatch({"id": 1, "cmd": "subscribe", "args": {"events": ["state"]}}, conn)["ok"])
        daemon.initial_state(daemon.clients[conn])
        self.assertIs(conn.sent[-1]["dry_run"], True)
        response = daemon.dispatch({"id": 2, "cmd": "config.set", "args": {"key": "DRY_RUN", "value": False}}, conn)
        self.assertTrue(response["ok"])
        self.assertIs(response["data"]["DRY_RUN"], False)
        self.assertEqual(conn.sent[-1]["event"], "state")
        self.assertIs(conn.sent[-1]["dry_run"], False)
        self.assertIs(json.loads((self.root / "config" / "config.json").read_text())["DRY_RUN"], False)
        self.assertIs(daemon.dispatch({"id": 3, "cmd": "status"}, conn)["data"]["dry_run"], False)
        before = len(conn.sent)
        self.assertTrue(daemon.dispatch({"id": 4, "cmd": "config.set", "args": {"key": "MAX_QUESTIONS", "value": 10}}, conn)["ok"])
        self.assertEqual(len(conn.sent), before)
        bad = daemon.dispatch({"id": 5, "cmd": "config.set", "args": {"key": "DRY_RUN", "value": 1}}, conn)
        self.assertEqual(bad["code"], "bad_request")

    def test_service_without_set_dry_run_still_saves(self):
        class Service:
            def handle(self, cmd, args):
                raise AssertionError("não deveria chegar ao núcleo")
        response = Daemon(Service()).dispatch({"id": 1, "cmd": "config.set", "args": {"key": "DRY_RUN", "value": False}}, None)
        self.assertTrue(response["ok"])
        self.assertIs(config.load()["DRY_RUN"], False)


if __name__ == "__main__":
    unittest.main()
