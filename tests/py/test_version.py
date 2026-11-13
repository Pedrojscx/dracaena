import contextlib
import io
import os
from pathlib import Path
import re
import subprocess
import sys
import unittest
from unittest.mock import patch

from dracaena import cli

REPO = Path(__file__).resolve().parents[2]


class VersionTests(unittest.TestCase):
    def run_main(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            with self.assertRaises(SystemExit) as caught:
                cli.main(argv)
        return caught.exception.code, out.getvalue(), err.getvalue()

    def test_long_and_short_flags_exit_zero_without_subcommand(self):
        for flag in ("--version", "-V"):
            with self.subTest(flag=flag):
                code, out, err = self.run_main([flag])
                self.assertIn(code, (0, None))
                self.assertEqual(out.strip(), f"dracaena {cli.package_version()}")
                self.assertEqual(err, "")

    def test_installed_metadata_has_priority(self):
        with patch("importlib.metadata.version", return_value="9.8.7"):
            self.assertEqual(cli.package_version(), "9.8.7")

    def test_fallback_when_not_installed(self):
        from importlib.metadata import PackageNotFoundError
        with patch("importlib.metadata.version", side_effect=PackageNotFoundError("dracaena")):
            self.assertEqual(cli.package_version(), cli.__version__)

    def test_fallback_matches_pyproject(self):
        text = (REPO / "pyproject.toml").read_text(encoding="utf-8")
        declared = re.search(r'^version\s*=\s*"([^"]+)"', text, re.M).group(1)
        self.assertEqual(cli.__version__, declared)

    def test_module_entry_point(self):
        env = {**os.environ, "PYTHONPATH": str(REPO / "lib")}
        result = subprocess.run([sys.executable, "-m", "dracaena", "-V"], capture_output=True, text=True,
                                env=env, timeout=30, stdin=subprocess.DEVNULL)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertRegex(result.stdout.strip(), r"^dracaena \S+$")


if __name__ == "__main__":
    unittest.main()
