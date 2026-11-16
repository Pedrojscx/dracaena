"""Contrato declarativo em páginas sintéticas, sem ações do adaptador."""
from dataclasses import FrozenInstanceError
from pathlib import Path
import unittest

from playwright.sync_api import sync_playwright
from fx import launch
from dracaena.adapters.base import Adapter, Ambiguous, NotFound, Registry
from dracaena.adapters.declarative import DeclarativeAdapter
from dracaena.adapters.general import GeneralAdapter
from dracaena.adapters.profile import ProfileError, parse
from dracaena.guard import Guard, Refused

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "compat"
SINGLE = '''
[site]
name = "sintetico"
version = 0
match = ["*quiz_mcq_single.html"]
title = "Prática"
[question]
container = ".qz-c1"
stem = ".qz-c1 h4"
instruction = "div.qz-c2"
[options]
item = ".qz-c2 label:not(.qz-sr-only)"
text = "label"
input = "input"
selected_attr = "checked"
[submit]
button = "input[value^='Finalizar']"
[reset]
button = "button"
[guard]
block_labels = ["reservado"]
'''
DROPDOWN = '''
[site]
name = "sintetico"
version = 0
match = ["*"]
[question]
container = "article.qz-c0"
stem = ".qz-c2 h2"
instruction = ".qz-c2 p"
[dropdown]
item = ".qz-c7"
native = true
[submit]
button = ".qz-c14"
[reset]
button = ".qz-c13"
[feedback]
correct = ".qz-good"
incorrect = ".qz-bad"
text = ".qz-message"
'''


class DeclarativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pw = sync_playwright().start()
        cls.browser = launch(cls.pw)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()

    def page(self, name):
        page = self.browser.new_page()
        self.addCleanup(page.close)
        page.goto((FIXTURES / name).as_uri())
        return page

    def test_single_read_only_and_guard_refuses_final(self):
        page = self.page("quiz_mcq_single.html")
        before = page.content()
        adapter = DeclarativeAdapter(SINGLE)
        self.assertIsInstance(adapter, Adapter)
        hosts = adapter.locate(page.main_frame)
        self.assertEqual(len(hosts), 1)
        host = hosts[0]
        question = adapter.extract(host)
        self.assertEqual(question.kind, "SINGLE")
        self.assertEqual(len(question.options), 4)
        self.assertEqual(question.stem, "Texto sintético 1")
        self.assertNotIn("Limpar", question.stem)
        self.assertEqual(question.instruction, "Texto sintético 2")
        with self.assertRaises(FrozenInstanceError):
            question.stem = "outro"
        for i in range(4):
            target = adapter.target(host, "option", i)
            self.assertEqual((target.role, target.action, target.qid), ("option", "click", question.id))
        self.assertEqual(adapter.reset_target(host).role, "reset")
        self.assertEqual(adapter.verdict(host).result, "UNKNOWN")
        guard = Guard(lambda _: None, dry_run=True, extra_block=adapter.extra_block)
        guard.bind(page.main_frame, host, question.id)
        with self.assertRaisesRegex(Refused, "texto bloqueado.*finalizar"):
            guard.perform(adapter.submit_target(host))
        self.assertEqual(page.content(), before)
        self.assertEqual(adapter.extra_block, ("reservado",))

    def test_dropdown_read_only_and_native_index(self):
        page = self.page("dropdown.html")
        before = page.content()
        adapter = DeclarativeAdapter(parse(DROPDOWN))
        hosts = adapter.locate(page.main_frame)
        self.assertEqual(len(hosts), 1)
        question = adapter.extract(hosts[0])
        self.assertEqual(question.kind, "DROPDOWN")
        self.assertEqual([len(i.options) for i in question.items], [10, 9, 6])
        for i in range(3):
            target = adapter.target(hosts[0], "dropdown", (i, 0))
            self.assertEqual((target.action, target.value, target.qid), ("select", 1, question.id))
        self.assertEqual(adapter.submit_target(hosts[0]).role, "submit")
        self.assertEqual(adapter.reset_target(hosts[0]).role, "reset")
        self.assertEqual(page.content(), before)

    def test_matches_and_no_fallback(self):
        page = self.page("quiz_mcq_single.html")
        adapter = DeclarativeAdapter(SINGLE)
        self.assertEqual(adapter.matches(page.url, page.title()), 80)
        self.assertEqual(adapter.matches(page.url, "outro"), 0)
        self.assertEqual(adapter.matches("about:blank", page.title()), 0)
        self.assertIs(Registry([GeneralAdapter(), adapter]).pick(page.url, page.title()), adapter)
        missing = DeclarativeAdapter(SINGLE.replace('container = ".qz-c1"', 'container = ".qz-missing"'))
        self.assertEqual(missing.locate(page.main_frame), [])
        host = adapter.locate(page.main_frame)[0]
        for call in (missing.extract, missing.submit_target, missing.reset_target, missing.verdict):
            with self.assertRaises(NotFound):
                call(host)
        with self.assertRaises(NotFound):
            missing.target(host, "option", 0)

    def test_shadow_feedback_selected_and_ambiguity(self):
        page = self.page("quiz_mcq_single.html")
        # Só a montagem da fixture escreve no DOM; o adaptador apenas lê.
        page.evaluate("""() => {
            const host = document.querySelector('.qz-c1');
            const wrapper = document.createElement('div');
            document.body.append(wrapper);
            wrapper.attachShadow({mode:'open'}).append(host);
            host.querySelector('input[type=radio]').setAttribute('checked', '');
            host.insertAdjacentHTML('beforeend', '<p class="qz-good qz-message">Certo</p>');
        }""")
        adapter = DeclarativeAdapter(SINGLE + '\n[feedback]\ncorrect=".qz-good"\nincorrect=".qz-bad"\ntext=".qz-message"\n')
        host = adapter.locate(page.main_frame)[0]
        question = adapter.extract(host)
        self.assertTrue(question.options[0].checked)
        self.assertEqual(question.feedback, "Certo")
        self.assertEqual(adapter.verdict(host).result, "CORRECT")
        page.evaluate("() => document.querySelector('body > div').shadowRoot.querySelector('.qz-good').classList.replace('qz-good', 'qz-bad')")
        self.assertEqual(adapter.verdict(host).result, "INCORRECT")
        without = DeclarativeAdapter(SINGLE)
        self.assertEqual(without.verdict(host).result, "UNKNOWN")
        self.assertIsNone(without.extract(host).feedback)
        ambiguous = DeclarativeAdapter(SINGLE.replace("input[value^='Finalizar']", "input[type='submit']"))
        with self.assertRaises(Ambiguous):
            ambiguous.submit_target(host)
        with self.assertRaises(NotFound):
            adapter.target(host, "option", 99)

    def test_invalid_profile(self):
        with self.assertRaises(ProfileError):
            DeclarativeAdapter(SINGLE + '\n[hooks]\nrun="x"\n')
