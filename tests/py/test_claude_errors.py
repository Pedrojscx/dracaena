"""Erros do Claude com subprocesso simulado; nenhuma chamada externa."""
import unittest
from unittest import mock
from quizhelper import claude


class ClaudeErrorsTest(unittest.TestCase):
    def check_error(self, out, err, expected):
        proc = mock.Mock(returncode=7)
        proc.poll.return_value = 7
        proc.communicate.return_value = (out, err)
        with mock.patch.object(claude, "claude_env", return_value=({}, "/tmp", "/tmp")), \
             mock.patch.object(claude, "build_cmd", return_value=["fake-claude"]), \
             mock.patch.object(claude.subprocess, "Popen", return_value=proc):
            with self.assertRaises(claude.ClaudeError) as ctx:
                claude.ask({}, "exemplo sintético")
        message = str(ctx.exception)
        self.assertIn("código 7", message)
        self.assertIn(expected, message)
        self.assertLess(len(message), 1000)
        return message

    def test_short_error(self):
        self.check_error("", "Error: failed", "Error: failed")

    def test_long_warning_then_error(self):
        self.check_error("", "Warning: " + "context " * 1000 + "\nError: network connection failed", "network connection failed")

    def test_warning_stderr_error_stdout(self):
        self.check_error("Error: rate limit exceeded", "Warning: notice", "rate limit exceeded")

    def test_warning_only(self):
        self.check_error("", "Warning: deprecated option", "Warning: deprecated option")

    def test_empty_output(self):
        self.check_error("  ", "\n", "sem saída em stdout ou stderr")

    def test_repeated_lines(self):
        message = self.check_error("", "Warning: notice\n" * 100 + "Error: failed\n" * 4, "repetida 4 vezes")
        self.assertIn("100 linhas", message)

    def test_expired_session(self):
        self.check_error("Authentication session expired. Please log in again", "Warning: notice", "session expired")

    def test_not_logged_in(self):
        self.check_error("Not logged in. Please run /login", "", "Not logged in")

    def test_actionable_cause_survives_many_generic_errors(self):
        self.check_error("Error: cleanup failed\nError: failed again\nError: stopped", "Authentication expired", "Authentication expired")
