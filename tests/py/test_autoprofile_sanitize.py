"""Recortes para aprendizado não transportam valores sensíveis conhecidos."""
import unittest
import fx
from dracaena.adapters.autoprofile import sanitize


class SanitizeTests(unittest.TestCase):
    def test_removes_contacts_addresses_tokens_and_long_identifiers(self):
        source = 'usuario@exemplo.invalid https://exemplo.invalid/a?segredo=1 123456789 abcdef123456789xyz'
        cleaned = sanitize(source, {})
        for value in source.split():
            self.assertNotIn(value, cleaned)
        self.assertIn('[email]', cleaned)
        self.assertIn('[url]', cleaned)
        self.assertIn('[n]', cleaned)

    def test_preserves_structural_selectors(self):
        source = '<section class="bloco"><input type="radio" name="q1">texto(12)'
        self.assertEqual(sanitize(source, {}), source)
