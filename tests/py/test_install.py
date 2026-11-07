"""Instalador em HOME/repositório temporários; pip e comandos do sistema simulados."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PYTHON = r'''
import json, os, pathlib, subprocess, sys
args = sys.argv[1:]
with open(os.environ['INSTALL_CALLS'], 'a') as f: f.write(json.dumps(args) + '\n')
if args[:2] == ['-m', 'venv']:
    subprocess.run([sys.executable, '-m', 'venv', '--without-pip', args[2]], check=True)
    site = pathlib.Path(args[2]) / 'lib' / f'python{sys.version_info.major}.{sys.version_info.minor}' / 'site-packages/pip'
    site.mkdir()
    (site / '__init__.py').write_text('')
    (site / '__main__.py').write_text(
        "import json, os, sys\n"
        "with open(os.environ['INSTALL_CALLS'], 'a') as f: f.write(json.dumps(['-m', 'pip', *sys.argv[1:]]) + '\\n')\n"
        "sys.exit(int(os.environ.get('FAIL_PIP', '0')))\n")
elif args[:3] == ['-m', 'pip', 'install']:
    sys.exit(int(os.environ.get('FAIL_PIP', '0')))
'''


class InstallTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.repo = self.root / 'repo'
        self.repo.mkdir()
        for directory in ('bin', 'config'):
            shutil.copytree(REPO / directory, self.repo / directory)
        for file in ('install.sh', 'requirements.txt'):
            shutil.copy2(REPO / file, self.repo / file)
        mocks = self.root / 'mocks'
        mocks.mkdir()
        p = mocks / 'python3'
        p.write_text('#!' + sys.executable + '\n' + PYTHON)
        p.chmod(0o700)
        for name in ('curl', 'ss', 'flock', 'claude'):
            p = mocks / name
            p.write_text('#!/bin/sh\nexit 0\n')
            p.chmod(0o700)
        self.env = {**os.environ, 'HOME': str(self.root / 'home'), 'XDG_CONFIG_HOME': str(self.root / 'config'),
                    'XDG_DATA_HOME': str(self.root / 'data'), 'PATH': str(mocks) + ':' + os.environ['PATH'],
                    'INSTALL_CALLS': str(self.root / 'calls')}

    def install(self, *args):
        return subprocess.run([shutil.which('bash'), str(self.repo / 'install.sh'), *args], env=self.env, capture_output=True, text=True)

    def test_clean_and_idempotent(self):
        for attempt in range(2):
            result = self.install()
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            cfg = self.root / 'config/quiz-helper/config'
            if attempt == 0:
                cfg.write_text('MODEL=personal-model\n')
            else:
                self.assertEqual(cfg.read_text(), 'MODEL=personal-model\n')
        for target in (self.repo / 'bin').iterdir():
            if not target.is_file() or not os.access(target, os.X_OK):
                continue
            name = target.name
            self.assertEqual((self.root / 'home/.local/bin' / name).resolve(), self.repo / 'bin' / name)
        calls = [json.loads(line) for line in (self.root / 'calls').read_text().splitlines()]
        self.assertEqual(sum(args[:2] == ['-m', 'venv'] for args in calls), 1)
        pip = [args for args in calls if args[:2] == ['-m', 'pip']]
        self.assertEqual(len(pip), 2)
        self.assertTrue(all(args[-2:] == ['-r', str(self.repo / 'requirements.txt')] for args in pip))
        self.assertNotIn('playwright install', json.dumps(calls))
        self.assertTrue((self.root / 'data/quiz-helper/venv/pyvenv.cfg').is_file())
        self.assertEqual((self.root / 'data/quiz-helper/venv').stat().st_mode & 0o777, 0o700)
        self.assertEqual((self.root / 'config/quiz-helper/config').stat().st_mode & 0o777, 0o600)

    def test_dependency_failure_is_clear(self):
        self.env['FAIL_PIP'] = '1'
        result = self.install()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Falha ao instalar dependências declaradas', result.stdout)
        self.assertFalse((self.root / 'home/.local/bin/quiz-loop').exists())


    def check_path(self, optional=(), missing=None):
        directory = self.root / 'check-bin'
        directory.mkdir()
        for name in ('dirname', 'readlink', 'python3', 'curl', 'ss', 'flock', 'setsid'):
            if name == missing:
                continue
            if name in ('dirname', 'readlink', 'python3'):
                (directory / name).symlink_to(sys.executable if name == 'python3' else shutil.which(name))
            else:
                self.optional_command(directory / name)
        for name in optional:
            self.optional_command(directory / name)
        self.env['PATH'] = str(directory)

    def optional_command(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('#!/bin/sh\nexit 0\n')
        path.chmod(0o700)

    def test_check_optional_missing_is_informational(self):
        self.check_path()
        result = self.install('--check')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for name in ('claude', 'vivaldi-stable', 'notify-send', 'wl-copy'):
            self.assertIn(f'[OPCIONAL] {name} ausente', result.stdout)
        self.assertFalse((self.root / 'data').exists())

    def test_check_optional_present_and_browser_from_default_config(self):
        cfg = self.repo / 'config/quiz-helper.conf'
        cfg.write_text(cfg.read_text().replace('BROWSER_BIN=vivaldi-stable', 'BROWSER_BIN=test-browser'))
        self.check_path(('claude', 'test-browser', 'notify-send', 'wl-copy'))
        result = self.install('--check')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for name in ('claude', 'test-browser', 'notify-send', 'wl-copy'):
            self.assertIn(f'[OK] {name}', result.stdout)
        self.assertNotIn('[OPCIONAL]', result.stdout)

    def test_check_finds_claude_in_usual_locations(self):
        self.check_path()
        for relative in ('.local/bin/claude', '.claude/local/claude'):
            with self.subTest(location=relative):
                path = self.root / 'home' / relative
                self.optional_command(path)
                result = self.install('--check')
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn('[OK] claude', result.stdout)
                path.unlink()

    def test_check_required_dependency_missing_fails(self):
        self.check_path(missing='curl')
        result = self.install('--check')
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn('Dependências DOM ausentes: curl.', result.stdout)
        self.assertFalse((self.root / 'data').exists())
