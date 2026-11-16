"""Contrato JSON do comando de leitura, sem conexão externa."""
import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
import fx
from dracaena.adapters import aprender, autoprofile


class CommandTests(unittest.TestCase):
    def run_command(self, **kwargs):
        page = SimpleNamespace(url='http://127.0.0.1/pratica', main_frame=object())
        browser = Mock(contexts=[SimpleNamespace(pages=[page])])
        pw = Mock()
        pw.chromium.connect_over_cdp.return_value = browser
        context = Mock()
        context.__enter__ = Mock(return_value=pw)
        context.__exit__ = Mock(return_value=False)
        output = []
        code = aprender.run(9, 'pratica', playwright_factory=lambda: context, out=output.append, **kwargs)
        self.assertEqual(len(output), 1)
        browser.close.assert_called_once()
        return code, json.loads(output[0])

    def test_read_does_not_save_without_explicit_request(self):
        data = dict(matches={}, questions=1, draft_toml='rascunho', layer='profile', confidence=1)
        with patch.object(autoprofile, 'learn', return_value=data), patch('dracaena.platform.sites.save') as save:
            code, got = self.run_command()
        self.assertEqual(code, 0)
        self.assertIsNone(got['data']['saved'])
        save.assert_not_called()

    def test_explicit_save_uses_sites(self):
        data = dict(matches={}, questions=1, draft_toml='rascunho', layer='profile', confidence=1)
        with patch.object(autoprofile, 'learn', return_value=data), \
                patch('dracaena.platform.sites.save', return_value={'path': '/tmp/perfil.toml'}) as save:
            code, got = self.run_command(save='sintetico')
        self.assertEqual(code, 0)
        save.assert_called_once_with('sintetico', 'rascunho', False)
        self.assertEqual(got['data']['saved'], '/tmp/perfil.toml')

    def test_unexpected_failure_is_json_without_page_details(self):
        with patch.object(autoprofile, 'learn', side_effect=RuntimeError('conteudo privado')):
            code, got = self.run_command()
        self.assertEqual(code, 1)
        self.assertEqual(got['code'], 'internal')
        self.assertNotIn('conteudo privado', got['error'])
