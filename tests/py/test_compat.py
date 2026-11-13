"""Regressões genéricas medidas em recortes neutros de prática."""
from fx import BrowserCase, REPO
from dracaena.adapters.heuristic import HeuristicAdapter
from dracaena.core import contract
from dracaena.core.model import DROPDOWN, SINGLE, UNKNOWN
from dracaena.guard import Guard, Refused


class CompatibilityTests(BrowserCase):
    def setUp(self):
        self.page = self.browser.new_page()
        self.adapter = HeuristicAdapter()

    def tearDown(self):
        self.page.close()

    def fixture(self, name):
        self.page.set_content((REPO / 'tests/fixtures/compat' / name).read_text())

    def test_dropdown_is_recognized_but_dry_run_never_changes_the_dom(self):
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

    def test_mcq_single_is_explicitly_not_supported(self):
        self.fixture('mcq_single.html')
        before = self.page.content()
        self.assertEqual(self.adapter.locate(self.page.main_frame), [])
        self.assertEqual(self.page.content(), before)

    def test_text_kinds_propose_no_actions(self):
        for name in ['fill_blank.html', 'essay.html']:
            with self.subTest(name=name):
                self.fixture(name)
                before = self.page.content()
                self.assertEqual(self.adapter.locate(self.page.main_frame), [])
                self.assertEqual(self.page.content(), before)

    def test_quiz_result_is_only_a_result_screen(self):
        self.fixture('quiz_result.html')
        self.assertEqual(self.adapter.locate(self.page.main_frame), [])
        self.assertTrue(Guard(lambda _: None).result_visible(self.page.main_frame))

    def test_quiz_mcq_single_ignores_navigation_and_clear_controls(self):
        self.fixture('quiz_mcq_single.html')
        hosts = self.adapter.locate(self.page.main_frame)
        self.assertEqual(len(hosts), 1)
        host = hosts[0]
        question = self.adapter.extract(host)
        self.assertEqual(question.kind, SINGLE)
        self.assertEqual(len(question.options), 4)
        self.assertTrue(question.stem)
        self.assertNotIn('Limpar escolha', question.stem)
        self.assertNotIn('Limpar escolha', question.instruction)
        self.assertIsNone(self.adapter.submit_target(host))
        self.assertIsNone(self.adapter.reset_target(host))

    def test_hidden_control_labels_are_absent_from_question_text(self):
        self.page.set_content('''<style>.qz-sr{position:absolute;width:1px;height:1px;clip:rect(0,0,0,0);overflow:hidden}</style>
        <form><h2>Enunciado sintético</h2><fieldset>
          <label><input type="radio" name="qz"> Alternativa visível</label>
          <label><input type="radio" name="qz"> Alternativa legítima</label>
          <label aria-hidden="true"><input type="radio" name="qz"> Controle aria</label>
          <label style="display:none"><input type="radio" name="qz"> Controle display</label>
          <label class="qz-sr"><input type="radio" name="qz"> Controle recortado</label>
        </fieldset></form>''')
        host = self.adapter.locate(self.page.main_frame)[0]
        question = self.adapter.extract(host)
        text = contract.question_text(question)
        self.assertEqual([option.text for option in question.options], ['Alternativa visível', 'Alternativa legítima'])
        for hidden in ('Controle aria', 'Controle display', 'Controle recortado'):
            self.assertNotIn(hidden, question.stem)
            self.assertNotIn(hidden, question.instruction)
            self.assertNotIn(hidden, text)
