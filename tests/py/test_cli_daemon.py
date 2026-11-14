import contextlib
import io
import unittest
from unittest.mock import patch

from dracaena import cli


class DaemonRefusalTests(unittest.TestCase):
    def test_real_daemon_refuses_in_portuguese_without_usage(self):
        out, err = io.StringIO(), io.StringIO()
        with patch("dracaena.daemon.Daemon") as daemon, \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(["daemon"])
        self.assertEqual(code, 2)
        daemon.assert_not_called()
        self.assertEqual(out.getvalue(), "")
        self.assertEqual(err.getvalue(),
                         "Dracaena: a integração com o núcleo ainda não está disponível; use --simulate\n")
        self.assertNotIn("usage", err.getvalue().lower())
        self.assertNotIn("error", err.getvalue().lower())


if __name__ == "__main__":
    unittest.main()
