import contextlib
import io
import unittest
from unittest.mock import patch

from dracaena import cli

SUBCOMMANDS = ("daemon", "loop", "ask", "toggle", "stop", "status", "doctor", "probe", "once", "install-browser")


class HelpTests(unittest.TestCase):
    def test_help_lists_all_ten_subcommands(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(SystemExit) as caught:
            cli.main(["--help"])
        self.assertIn(caught.exception.code, (0, None))
        text = out.getvalue()
        listed = [line.split()[0] for line in text.splitlines() if line.startswith("    ") and line.split()]
        for name in SUBCOMMANDS:
            with self.subTest(name=name):
                self.assertIn(name, listed)

    def test_ipc_subcommands_keep_their_requests(self):
        expected = {"loop": "toggle", "probe": "probe.start", "ask": "ask", "toggle": "toggle", "stop": "stop",
                    "status": "status", "once": "once"}
        for name, cmd in expected.items():
            with self.subTest(name=name), patch.object(cli, "request", return_value={"ok": True}) as request, \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(cli.main([name]), 0)
            request.assert_called_once_with(cmd)


if __name__ == "__main__":
    unittest.main()
