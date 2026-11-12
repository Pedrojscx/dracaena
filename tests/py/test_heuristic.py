"""Contrato heurístico exercitado em páginas sintéticas com a guarda real."""
from fx import BrowserCase
from dracaena.adapters.heuristic import HeuristicAdapter
from dracaena.core.model import SINGLE, MULTI, DROPDOWN, CORRECT, INCORRECT, UNKNOWN
from dracaena.core.errors import NotFound, Ambiguous
from dracaena.guard import Guard


class HeuristicTests(BrowserCase):
    def test_round_trips(self):
        cases = [('radio.html', [SINGLE, SINGLE], [[1], [1]]),
                 ('checkbox.html', [MULTI], [[1, 3]]),
                 ('select.html', [DROPDOWN], [[1, 1, 1]]),
                 ('aria.html', [SINGLE, MULTI, SINGLE], [[1], [0, 2], [1]]),
                 ('styled.html', [SINGLE], [[2]])]
        for filename, kinds, answers in cases:
            with self.subTest(filename=filename):
                page = self.browser.new_page()
                try:
                    page.goto(self.server.url(filename))
                    adapter = HeuristicAdapter()
                    self.assertEqual(adapter.matches(page.url, page.title()), 10)
                    hosts = adapter.locate(page.main_frame)
                    self.assertEqual([adapter.extract(h).kind for h in hosts], kinds)
                    for host, kind, answer in zip(hosts, kinds, answers):
                        q = adapter.extract(host)
                        self.assertTrue(q.stem)
                        self.assertEqual(adapter.extract(host).id, q.id)
                        if kind == MULTI:
                            self.assertEqual(q.expected, 2)
                        self.assertEqual(adapter.verdict(host).result, UNKNOWN)
                        self.assertIsNone(adapter.reset_target(host))
                        guard = Guard(lambda _: None)
                        guard.bind(page.main_frame, host, q.id)
                        # Uma tentativa vazia produz feedback e disponibiliza reset.
                        guard.perform(adapter.submit_target(host))
                        self.assertEqual(adapter.verdict(host).result, INCORRECT)
                        self.assertTrue(adapter.extract(host).feedback)
                        guard.perform(adapter.reset_target(host))
                        self.assertEqual(adapter.verdict(host).result, UNKNOWN)
                        for item, index in enumerate(answer):
                            target = adapter.target(host, 'dropdown' if kind == DROPDOWN else 'option',
                                                    (item, index) if kind == DROPDOWN else index)
                            self.assertEqual(target.qid, q.id)
                            if kind == DROPDOWN:
                                self.assertEqual(target.value, index + 1)
                            dry = Guard(lambda _: None, dry_run=True)
                            dry.bind(page.main_frame, host, q.id)
                            before = adapter.extract(host)
                            dry.perform(target)
                            self.assertEqual(adapter.extract(host), before)
                            guard.perform(target)
                        guard.perform(adapter.submit_target(host))
                        self.assertEqual(adapter.verdict(host).result, CORRECT)
                    self.assertFalse(page.evaluate('window.__SIM_GLOBAL'))
                finally:
                    page.close()

    def test_missing_and_ambiguous_targets(self):
        page = self.browser.new_page()
        try:
            adapter = HeuristicAdapter()
            for filename in ['nosubmit.html', 'oneform.html']:
                page.goto(self.server.url(filename))
                for host in adapter.locate(page.main_frame):
                    self.assertIsNone(adapter.submit_target(host))
            page.goto(self.server.url('radio.html'))
            host = adapter.locate(page.main_frame)[0]
            with self.assertRaises(NotFound):
                adapter.target(host, 'option', 999)
            host.evaluate("h => h.appendChild(h.querySelector('button').cloneNode(true))")
            with self.assertRaises(Ambiguous):
                adapter.submit_target(host)
            page.goto(self.server.url('result.html'))
            self.assertEqual(adapter.locate(page.main_frame), [])
        finally:
            page.close()
