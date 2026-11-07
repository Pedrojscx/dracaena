"""Segredos fictícios nunca saem do diagnóstico, nem por exceções/saída do subprocesso."""
import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from quizhelper import claude, cli, redact


class CredentialsTest(unittest.TestCase):
    def test_presence_only_and_redaction(self):
        secret = "fictitious-" + "private-value-123"
        env = {name: secret for name in ("ANTHROPIC_API_KEY", "CUSTOM_TOKEN", "DB_PASSWORD", "COOKIE", "CREDENTIAL", "OTHER_SECRET")}
        with mock.patch.dict(os.environ, env, clear=True):
            report = redact.environment(["HOME", "MISSING_TOKEN"])
            self.assertEqual(report["MISSING_TOKEN"], "ausente")
            self.assertEqual(redact.data(report)["MISSING_TOKEN"], "ausente")
            self.assertTrue(all(report[name] == "definida" for name in env))
            self.assertNotIn(secret, json.dumps(report))
            self.assertNotIn(secret, claude.error_message(1, secret, "password=" + secret))

    def test_envquery_files_and_terminal_never_contain_secret(self):
        secret = "fictitious-" + "private-value-456"
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": secret, "CUSTOM_TOKEN": secret}), \
             mock.patch.object(cli.configmod, "load", return_value={}), \
             mock.patch.object(claude, "claude_env", return_value=({"CLAUDE_CODE_TMPDIR": tmp}, Path(tmp), Path(tmp))), \
             mock.patch.object(claude, "build_cmd", return_value=["fake", "-p", "text"]):
            terminal = io.StringIO()
            for index, result in enumerate((secret, claude.ClaudeError(secret))):
                with mock.patch.object(claude, "ask", **({"side_effect": result} if isinstance(result, Exception)
                                                        else {"return_value": (result, 0.1)})), contextlib.redirect_stdout(terminal), contextlib.redirect_stderr(terminal):
                    cli.cmd_envquery(SimpleNamespace(sample="conceitual", out=str(Path(tmp) / f"report{index}.json")))
            for path in Path(tmp).rglob('*'):
                if path.is_file():
                    self.assertNotIn(secret, path.read_text())
                    self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertNotIn(secret, terminal.getvalue())

    def test_envcheck_redacts_subprocess_output(self):
        secret = "fictitious-" + "private-value-789"
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.dict(os.environ, {"CUSTOM_PASSWORD": secret}), \
             mock.patch.object(cli.configmod, "load", return_value={}), \
             mock.patch("tempfile.mkdtemp", return_value=tmp), \
             mock.patch.object(cli.subprocess, "run", return_value=SimpleNamespace(returncode=1, stdout=secret, stderr=secret)):
            terminal = io.StringIO()
            with contextlib.redirect_stdout(terminal), contextlib.redirect_stderr(terminal):
                self.assertEqual(cli.cmd_envcheck(SimpleNamespace()), 1)
            self.assertNotIn(secret, terminal.getvalue())
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_config_failure_never_prints_invalid_secret(self):
        secret = "fictitious-" + "config-private-value"
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(cli.configmod, "load", side_effect=ValueError(secret)):
            terminal = io.StringIO()
            with contextlib.redirect_stdout(terminal), contextlib.redirect_stderr(terminal):
                cli.cmd_envquery(SimpleNamespace(sample="conceitual", out=str(Path(tmp) / "report.json")))
                cli.cmd_envcheck(SimpleNamespace())
            self.assertNotIn(secret, terminal.getvalue())
            self.assertNotIn(secret, (Path(tmp) / "report.json").read_text())

    def test_embedded_json_and_cookie_headers_are_redacted(self):
        secret = "fictitious-" + "output-private-value"
        output = json.dumps({"access_token": secret}) + "\nCookie: first=" + secret + "; second=" + secret
        self.assertNotIn(secret, redact.text(output, env={}))
