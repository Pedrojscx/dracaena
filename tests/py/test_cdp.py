"""Valida respostas CDP sem sockets ou rede."""
import json
import unittest
from unittest import mock
from quizhelper import cdp


class CDPTest(unittest.TestCase):
    def validate(self, data):
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps(data).encode()
        with mock.patch.object(cdp, 'build_opener') as opener:
            opener.return_value.open.return_value = response
            return cdp.version(9222)

    def test_valid(self):
        data = {'Browser': 'Synthetic/1', 'Protocol-Version': '1.3', 'webSocketDebuggerUrl': 'ws://127.0.0.1:9222/devtools/browser/fake'}
        self.assertEqual(self.validate(data), data)

    def test_rejects_invalid_or_remote_endpoints(self):
        for data in ({}, {'Browser': 'http server'},
                     {'Browser': 'Synthetic', 'Protocol-Version': '1.3', 'webSocketDebuggerUrl': 'ws://example.invalid:9222/devtools/browser/fake'}):
            with self.subTest(data=data), self.assertRaises(ValueError):
                self.validate(data)
