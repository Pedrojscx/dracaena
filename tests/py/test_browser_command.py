"""quiz-browser exercitado com ss/curl/navegador/Playwright simulados."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

MOCK = r'''
import json, os, pathlib, sys
root = pathlib.Path(os.environ['MOCK_ROOT'])
name = pathlib.Path(sys.argv[0]).name
args = sys.argv[1:]
with (root / 'calls').open('a') as f: f.write(json.dumps([name, *args]) + '\n')
state = root / 'listening'
if name == 'ss':
    print('LISTEN 0 128 ' + state.read_text() + ' 0.0.0.0:*' if state.exists() else '')
elif name == 'python':
    if 'quizhelper.cdp' in args: sys.exit(int(os.environ.get('MOCK_BAD_CDP', '0')))
    print('{}')
elif name == 'setsid':
    if os.environ.get('MOCK_NO_START') != '1': state.write_text('127.0.0.1:9222')
'''


class BrowserCommandTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        mocks = self.root / 'bin'
        mocks.mkdir()
        for name in ('ss', 'python', 'curl', 'setsid', 'sleep', 'fake-browser'):
            p = mocks / name
            p.write_text('#!' + sys.executable + '\n' + MOCK)
            p.chmod(0o700)
        self.env = {**os.environ, 'HOME': str(self.root), 'XDG_CONFIG_HOME': str(self.root / 'config'),
                    'XDG_DATA_HOME': str(self.root / 'data'), 'XDG_RUNTIME_DIR': str(self.root),
                    'QH_PYTHON': str(mocks / 'python'), 'PATH': str(mocks) + ':' + os.environ['PATH'],
                    'MOCK_ROOT': str(self.root)}
        config = self.root / 'config/quiz-helper'
        config.mkdir(parents=True)
        (config / 'config').write_text(f'BROWSER_BIN={mocks / "fake-browser"}\n')

    def run_browser(self, *args):
        return subprocess.run([str(REPO / 'bin/quiz-browser'), *args], env=self.env, capture_output=True, text=True, timeout=15)

    def listening(self, address='127.0.0.1:9222'):
        (self.root / 'listening').write_text(address)

    def calls(self):
        return (self.root / 'calls').read_text()

    def test_free_port_starts_dedicated_browser(self):
        r = self.run_browser()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('--user-data-dir=', self.calls())
        self.assertIn('--remote-debugging-address=127.0.0.1', self.calls())
        self.assertEqual((self.root / 'data/quiz-helper/vivaldi-profile').stat().st_mode & 0o777, 0o700)

    def test_closed_port_status(self):
        self.assertEqual(self.run_browser('--status').returncode, 1)
        self.assertNotIn('setsid', self.calls())

    def test_other_service_refused(self):
        self.listening()
        self.env['MOCK_BAD_CDP'] = '1'
        self.assertNotEqual(self.run_browser().returncode, 0)
        self.assertNotIn('setsid', self.calls())
        self.assertNotIn('curl', self.calls())

    def test_non_loopback_refused(self):
        self.listening('0.0.0.0:9222')
        self.assertNotEqual(self.run_browser().returncode, 0)
        self.assertNotIn('setsid', self.calls())

    def test_valid_endpoint_status(self):
        self.listening()
        self.assertEqual(self.run_browser('--status').returncode, 0)

    def test_non_cdp_endpoint_status(self):
        self.listening()
        self.env['MOCK_BAD_CDP'] = '1'
        self.assertNotEqual(self.run_browser('--status').returncode, 0)

    def test_missing_browser(self):
        (self.root / 'config/quiz-helper/config').write_text('BROWSER_BIN=/nonexistent/synthetic-browser\n')
        self.assertIn('navegador não encontrado', self.run_browser().stderr)

    def test_browser_does_not_open_port(self):
        self.env['MOCK_NO_START'] = '1'
        r = self.run_browser()
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('não abriu a porta', r.stderr)

    def test_reuse_browser(self):
        self.listening()
        self.assertEqual(self.run_browser('https://example.invalid/').returncode, 0)
        self.assertNotIn('setsid', self.calls())
        self.assertIn('curl', self.calls())
