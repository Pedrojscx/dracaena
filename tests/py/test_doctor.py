"""Doctor usa somente leituras e status; página, conta e CDP são simulados."""
import contextlib
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from quizhelper import doctor


class DoctorTest(unittest.TestCase):
    def run_doctor(self, logged=True, cdp_error=False):
        secret = 'fake-' + 'private-doctor-value'
        with tempfile.TemporaryDirectory() as tmp, contextlib.ExitStack() as stack:
            root = Path(tmp)
            for folder in ('bin', 'prompts', 'home/.local/bin', 'data/vivaldi-profile'):
                (root / folder).mkdir(parents=True)
            shutil.copytree(doctor.config.REPO / 'bin', root / 'bin', dirs_exist_ok=True)
            for target in (root / 'bin').iterdir():
                if not target.is_file():
                    continue
                name = target.name
                target.write_text('synthetic command')
                target.chmod(0o700)
                (root / 'home/.local/bin' / name).symlink_to(target)
            for name in ('system', 'answer', 'retry', 'invalid'):
                (root / 'prompts' / f'{name}.txt').write_text('synthetic prompt')
            stack.enter_context(mock.patch.object(doctor.config, 'REPO', root))
            stack.enter_context(mock.patch.object(doctor.config, 'load', return_value={}))
            stack.enter_context(mock.patch.object(doctor.config, 'data_dir', return_value=root / 'data'))
            stack.enter_context(mock.patch.object(doctor.Path, 'home', return_value=root / 'home'))
            stack.enter_context(mock.patch.object(doctor.Path, 'glob', return_value=[mock.Mock(read_bytes=mock.Mock(
                return_value=f'fake\0--user-data-dir={root / "data/vivaldi-profile"}\0--remote-debugging-port=9222\0'.encode()))]))
            stack.enter_context(mock.patch.object(doctor.sys, 'prefix', 'fake-venv'))
            stack.enter_context(mock.patch.object(doctor.claude, 'claude_bin', return_value='fake-claude'))
            run = stack.enter_context(mock.patch.object(doctor.subprocess, 'run', side_effect=[
                SimpleNamespace(returncode=0, stdout=json.dumps({'loggedIn': logged, 'token': secret})),
                SimpleNamespace(returncode=0)]))
            stack.enter_context(mock.patch.object(doctor.cdp, 'version', side_effect=ValueError(secret) if cdp_error else None))
            pw = stack.enter_context(mock.patch('playwright.sync_api.sync_playwright'))
            browser = mock.Mock()
            stack.enter_context(mock.patch.object(doctor.browser, 'connect', return_value=browser))
            stack.enter_context(mock.patch.object(doctor.browser, 'find_tab', return_value=mock.Mock()))
            stack.enter_context(mock.patch.object(doctor.browser, 'revalidate', return_value=SimpleNamespace(frame=mock.Mock(), item='Synthetic')))
            stack.enter_context(mock.patch.object(doctor.dom, 'locate', return_value=SimpleNamespace(host=mock.Mock())))
            stack.enter_context(mock.patch.object(doctor.dom, 'extract', return_value={'kind': 'SINGLE', 'stem': 'Synthetic private question'}))
            terminal = io.StringIO()
            with contextlib.redirect_stdout(terminal):
                result = doctor.run()
            self.assertNotIn(secret, terminal.getvalue())
            self.assertNotIn('Synthetic private question', terminal.getvalue())
            browser.close.assert_not_called()
            self.assertEqual(run.call_args_list[0].args[0], ['fake-claude', 'auth', 'status', '--json'])
            return result, terminal.getvalue()

    def test_read_only_success(self):
        result, text = self.run_doctor()
        self.assertEqual(result, 0, text)
        self.assertIn('leitura da questão atual', text)

    def test_login_required(self):
        result, text = self.run_doctor(logged=False)
        self.assertEqual(result, 1)
        self.assertIn('claude auth login', text)

    def test_connection_failure_omits_details(self):
        self.assertEqual(self.run_doctor(cdp_error=True)[0], 1)


class CmdlineMatchesTest(unittest.TestCase):
    profile = Path('/x/vivaldi-profile')

    def cmdline(self, separator, profile=None, port=9222, extra=()):
        args = ['vivaldi', f'--user-data-dir={profile or self.profile}',
                f'--remote-debugging-port={port}', *extra]
        return (separator.join(args) + '\0').encode()

    def test_nul_separated(self):
        self.assertTrue(doctor.cmdline_matches(self.cmdline('\0'), self.profile, 9222))

    def test_space_separated(self):
        raw = self.cmdline(' ')
        for value in (raw, raw.rstrip(b'\0')):
            with self.subTest(raw=value):
                self.assertTrue(doctor.cmdline_matches(value, self.profile, 9222))

    def test_different_port(self):
        for separator in ('\0', ' '):
            with self.subTest(separator=separator):
                self.assertFalse(doctor.cmdline_matches(self.cmdline(separator, port=9223), self.profile, 9222))

    def test_different_profile(self):
        for separator in ('\0', ' '):
            with self.subTest(separator=separator):
                self.assertFalse(doctor.cmdline_matches(self.cmdline(separator, profile='/other/profile'),
                                                       self.profile, 9222))

    def test_flag_value_prefix_does_not_match(self):
        for separator in ('\0', ' '):
            for raw in (self.cmdline(separator, profile=str(self.profile) + '-2'),
                        self.cmdline(separator, port=92220)):
                with self.subTest(raw=raw):
                    self.assertFalse(doctor.cmdline_matches(raw, self.profile, 9222))

    def test_child_process_is_rejected(self):
        for separator in ('\0', ' '):
            with self.subTest(separator=separator):
                self.assertFalse(doctor.cmdline_matches(self.cmdline(separator, extra=['--type=renderer']),
                                                       self.profile, 9222))

    def test_nul_preserves_spaces_and_regex_characters_in_profile(self):
        profile = Path('/x/profile [1].dir')
        self.assertTrue(doctor.cmdline_matches(self.cmdline('\0', profile=profile), profile, 9222))
        self.assertFalse(doctor.cmdline_matches(self.cmdline('\0', profile=str(profile) + ' other'), profile, 9222))

    def test_nul_argument_containing_flags_is_not_a_match(self):
        raw = b'vivaldi\0--title= --user-data-dir=/x/vivaldi-profile --remote-debugging-port=9222\0'
        self.assertFalse(doctor.cmdline_matches(raw, self.profile, 9222))
