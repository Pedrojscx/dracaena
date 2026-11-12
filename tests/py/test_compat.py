"""Regressões genéricas medidas em recortes neutros de prática."""
from fx import BrowserCase, REPO
from dracaena.adapters.heuristic import HeuristicAdapter
from dracaena.core.model import DROPDOWN, UNKNOWN
from dracaena.guard import Guard, Refused


class CompatibilityTests(BrowserCase):
    def setUp(self):
        self.page = self.browser.new_page()
        self.adapter = HeuristicAdapter()

    def tearDown(self):
        self.page.close()

    def fixture(self, name):
        self.page.set_content((REPO / 'tests/fixtures/compat' / name).read_text())

    def test_semantic_region_groups_selects_and_keeps_disabled_submit(self):
        self.fixture('dropdown.html')
        hosts = self.adapter.locate(self.page.main_frame)
        self.assertEqual(len(hosts), 1)
        host = hosts[0]
        question = self.adapter.extract(host)
        self.assertEqual(question.kind, DROPDOWN)
        self.assertEqual(len(question.items), 3)
        self.assertTrue(question.stem)
        self.assertEqual([len(i.options) for i in question.items], [10, 9, 6])
        self.assertEqual(self.adapter.verdict(host).result, UNKNOWN)
        logs = []
        guard = Guard(logs.append, dry_run=True)
        guard.bind(self.page.main_frame, host, question.id)
        before = self.page.content()
        for i in range(3):
            target = self.adapter.target(host, 'dropdown', (i, 0))
            self.assertEqual(target.value, 1)
            self.assertEqual(guard.perform(target), 'dropdown nativo')
        submit = self.adapter.submit_target(host)
        self.assertIsNotNone(submit)
        with self.assertRaisesRegex(Refused, 'desabilitado'):
            guard.perform(submit)
        self.assertEqual(guard.perform(self.adapter.reset_target(host)), 'reset')
        self.assertEqual(self.page.content(), before)
        self.assertEqual(guard.clicks, 0)

    def test_enabled_submit_is_accepted_without_clicking(self):
        self.fixture('dropdown.html')
        host = self.adapter.locate(self.page.main_frame)[0]
        question = self.adapter.extract(host)
        # Simulação neutra exclusivamente no teste: as escolhas habilitam o envio.
        self.page.evaluate("""() => {
            const selects = [...document.querySelectorAll('select')];
            const submit = [...document.querySelectorAll('button')]
                .find(b => b.textContent.trim() === 'Confirmar resposta');
            const refresh = () => { submit.disabled = !selects.every(s => s.selectedIndex > 0); };
            for (const select of selects) select.addEventListener('change', refresh);
            window.syntheticSubmits = 0;
            submit.addEventListener('click', () => { window.syntheticSubmits += 1; });
        }""")
        setup_guard = Guard(lambda _: None)
        setup_guard.bind(self.page.main_frame, host, question.id)
        for item in range(3):
            setup_guard.perform(self.adapter.target(host, 'dropdown', (item, 0)))
            self.assertEqual(self.adapter.submit_target(host).element.is_disabled(), item < 2)
        target = self.adapter.submit_target(host)
        self.assertEqual(target.label, 'Confirmar resposta')
        guard = Guard(lambda _: None, dry_run=True)
        guard.bind(self.page.main_frame, host, question.id)
        before = self.page.content()
        self.assertEqual(guard.perform(target), 'submit')
        self.assertEqual(self.page.content(), before)
        self.assertEqual(self.page.evaluate('window.syntheticSubmits'), 0)
        self.assertEqual(guard.clicks, 0)

    def test_separate_regions_do_not_merge(self):
        region = '<article><h2>Questão sintética</h2><label>Item<select><option>A</option><option>B</option></select></label><button>Confirmar resposta</button></article>'
        self.page.set_content(region + region)
        hosts = self.adapter.locate(self.page.main_frame)
        self.assertEqual(len(hosts), 2)
        self.assertEqual([len(self.adapter.extract(h).items) for h in hosts], [1, 1])

    def test_untyped_buttons_and_text_kinds_propose_no_actions(self):
        for name in ['mcq_single.html', 'fill_blank.html', 'essay.html']:
            with self.subTest(name=name):
                self.fixture(name)
                before = self.page.content()
                self.assertEqual(self.adapter.locate(self.page.main_frame), [])
                self.assertEqual(self.page.content(), before)
