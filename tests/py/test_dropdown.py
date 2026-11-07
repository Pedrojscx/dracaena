"""Dropdowns com ordem visual diferente dos índices internos, em Chromium local."""
from quizhelper import dom
from quizhelper.actions import Actor
from quizhelper.guard import Guard
from web import BrowserFixtureCase


class DropdownTest(BrowserFixtureCase):
    def setUp(self):
        self.page = self.browser.new_page()
        self.addCleanup(self.page.close)
        self.page.goto(self.server.url('cyu_dropdown_reversed.html'))
        self.page.wait_for_function('() => window.__SIM_CLICKS !== undefined')
        self.host = dom.locate(self.page.main_frame, '9.9.2 Cloud Services').host
        cfg = {'ACTION_TIMEOUT_MS': 2000, 'VERIFY_TIMEOUT_MS': 100}
        self.guard = Guard(self.page.main_frame, cfg, lambda message: None)
        self.actor = Actor(self.page.main_frame, self.guard, cfg, lambda: False)

    def test_extract_sorts_options_by_data_index(self):
        order = self.host.evaluate('''h => Array.from(h.shadowRoot
            .querySelector('matching-dropdown-view').shadowRoot.querySelectorAll('li[role=option]'))
            .map(li => +li.dataset.index)''')
        self.assertEqual(order, [3, 2, 1, 0])
        for item in dom.extract(self.host)['items']:
            self.assertEqual([o['index'] for o in item['options']], [0, 1, 2, 3])
            self.assertEqual([o['text'] for o in item['options']], ['Red', 'Blue', 'Green', 'Yellow'])

    def apply_and_check(self):
        done = self.actor.apply(self.host, dom.extract(self.host), {
            'type': 'DROPDOWN', 'items': [{'item': i, 'option': i} for i in range(4)]})
        self.assertEqual(len(done), 4)
        state = dom.extract(self.host)
        self.assertEqual([item['shown'] for item in state['items']], ['Red', 'Blue', 'Green', 'Yellow'])
        self.assertEqual(done, [f'item [{i}] → [{i}] {text}'
                                for i, text in enumerate(['Red', 'Blue', 'Green', 'Yellow'])])
        return state

    def test_apply_selects_correct_option_without_pause(self):
        state = self.apply_and_check()
        for i, item in enumerate(state['items']):
            self.assertEqual([o['index'] for o in item['options'] if o['selected']], [i])

    def test_apply_accepts_shown_text_without_aria_selected(self):
        # O simulador atualiza o botão; depois, simula aria-selected desatualizado.
        self.page.evaluate('''() => document.addEventListener('click', event => {
            const li = event.composedPath().find(e => e instanceof Element && e.matches('li[role=option]'));
            if (li) li.setAttribute('aria-selected', 'false');
        })''')
        state = self.apply_and_check()
        self.assertFalse(any(o['selected'] for item in state['items'] for o in item['options']))
