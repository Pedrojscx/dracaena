"""A simulação passa pela guarda sem clicar, repetir ações ou esperar mudanças."""
from unittest import mock

from quizhelper import actions, dom
from quizhelper.actions import Actor
from quizhelper.guard import Guard
from web import BrowserFixtureCase


class DryRunTest(BrowserFixtureCase):
    def check_apply(self, fixture, item, answer, action_count, component=None):
        page = self.browser.new_page()
        self.addCleanup(page.close)
        page.goto(self.server.url(fixture))
        page.wait_for_function('() => window.__SIM_CLICKS !== undefined')
        if component:
            host = page.main_frame.evaluate_handle(dom.js(
                f"return QH.first(document, e => QH.isQuestionHost(e) && "
                f"QH.q(e).dataset.socialgoodpulseId === '{component}');")).as_element()
        else:
            host = dom.locate(page.main_frame, item).host
        before = dom.extract(host)
        self.assertEqual(before['kind'], answer['type'])
        log = []
        cfg = {'VERIFY_TIMEOUT_MS': 100, 'ACTION_TIMEOUT_MS': 2000}
        guard = Guard(page.main_frame, cfg, log.append, dry_run=True)
        actor = Actor(page.main_frame, guard, cfg, lambda: False)
        with mock.patch.object(actions, 'wait_for', wraps=actions.wait_for) as wait:
            done = actor.apply(host, before, answer)
            wait.assert_not_called()
        self.assertEqual(dom.extract(host), before)
        self.assertEqual(page.evaluate('window.__SIM_CLICKS'), [])
        self.assertEqual(guard.clicks, 0)
        simulated = [line for line in log if line.startswith('(dry-run) clicaria:')]
        self.assertEqual(len(simulated), action_count)
        self.assertEqual(len(set(simulated)), action_count)
        self.assertEqual(log, simulated)
        for label in done:
            expected = 2 if answer['type'] == 'MATCH' else 1
            self.assertEqual(sum(f'clicaria: {label}' in line for line in simulated), expected)

    def test_single(self):
        self.check_apply('cyu_single.html', '9.9.1.1 Check Your Understanding - Single',
                         {'type': 'SINGLE', 'answers': [0]}, 1)

    def test_multi(self):
        self.check_apply('assessment.html', None, {'type': 'MULTI', 'answers': [0, 1]}, 2, component='q2')

    def test_dropdown(self):
        self.check_apply('cyu_dropdown.html', '9.9.2 Cloud Services',
                         {'type': 'DROPDOWN', 'items': [{'item': i, 'option': i} for i in range(4)]}, 8)

    def test_match(self):
        self.check_apply('cyu_match.html', '9.9.1.4 Check Your Understanding - Terminology',
                         {'type': 'MATCH', 'pairs': [{'right': i, 'left': letter}
                                                    for i, letter in enumerate('CAB')]}, 6)
