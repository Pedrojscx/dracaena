"""Permissões testadas sob umask permissiva; arquivos existentes não são alterados."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from quizhelper import claude, loop, private


class PrivateTest(unittest.TestCase):
    def test_new_logs_answers_figures_and_parents(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = os.umask(0)
            self.addCleanup(os.umask, old)
            run = Path(tmp) / "data/runs/example"
            lp = loop.Loop({}, run_dir=run)
            lp.log("synthetic log")
            lp._claude_log("synthetic prompt and answer")
            lp._record({"q": 0, "verdict": {}}, loop.Timer())
            private.write_bytes(run / "claude/figure.png", b"synthetic image")
            private.write_text(run / "answers.json", "[]")
            for path in Path(tmp).rglob('*'):
                self.assertEqual(path.stat().st_mode & 0o777, 0o700 if path.is_dir() else 0o600, str(path))

    def test_existing_permissions_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "existing"
            path.mkdir(mode=0o755)
            path.chmod(0o755)
            file = path / "existing.txt"
            file.write_text("existing")
            file.chmod(0o644)
            private.mkdir(path)
            with private.open_file(file, "a") as fh:
                fh.write(" appended")
            with mock.patch.dict(os.environ, {"CLAUDE_CODE_TMPDIR": str(path)}), \
                 mock.patch.object(claude.configmod, "runtime_dir", return_value=Path(tmp)):
                claude.claude_env({})
            self.assertEqual(path.stat().st_mode & 0o777, 0o755)
            self.assertEqual(file.stat().st_mode & 0o777, 0o644)

    def test_refuses_file_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "target"
            target.write_text("untouched")
            link = Path(tmp) / "link"
            link.symlink_to(target)
            with self.assertRaises(OSError):
                private.write_text(link, "overwrite")
            self.assertEqual(target.read_text(), "untouched")
