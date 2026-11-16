"""Cobertura offline do motor, do autoperfil e das ações limitadas pela guarda."""
import unittest
from playwright.sync_api import sync_playwright
from corpus import CorpusServer, FakeClaude, manifest, measure
from fx import launch
from dracaena.adapters import autoprofile
from dracaena.adapters.flow import answer_visible
from dracaena.adapters.general import GeneralAdapter


class CorpusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = CorpusServer()
        cls.pw = sync_playwright().start()
        cls.browser = launch(cls.pw)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()
        cls.server.close()

    def page(self, filename):
        page = self.browser.new_page()
        self.addCleanup(page.close)
        page.goto(self.server.url(next(e for e in manifest() if e['file'] == filename)))
        return page

    def test_manifest_results_and_types(self):
        for entry in manifest():
            with self.subTest(fixture=entry['file']):
                page = self.browser.new_page()
                try:
                    row = measure(page, self.server, entry)
                    self.assertEqual(row['result'], entry['expect']['result'], row['detail'])
                    self.assertEqual(row['layer'], entry['expect']['layer'])
                    self.assertEqual(row['kinds'], entry['expect']['kinds'])
                    if 'code' in entry['expect']:
                        self.assertEqual(row['code'], entry['expect']['code'])
                finally:
                    page.close()

    def test_default_flow_is_dry_run(self):
        page = self.page('botoes_grandes.html')
        before = page.content()
        result = answer_visible(page.main_frame, GeneralAdapter(), FakeClaude([{'type': 'SINGLE', 'answers': [1]}]),
                                log=lambda _: None)
        self.assertEqual([r.status for r in result], ['answered'])
        self.assertEqual(page.content(), before)

    def test_autoprofile_retries_invalid_response_without_changing_dom(self):
        entry = next(e for e in manifest() if e['file'] == 'tabela_sem_rotulos.html')
        page = self.page(entry['file'])
        before = page.content()
        teacher = FakeClaude([{'toml': '[hooks]\nrun="x"'}, {'toml': entry['profile']}])
        result = autoprofile.learn(page.main_frame, page.url, teacher)
        self.assertEqual(result['layer'], 'profile')
        self.assertEqual(len(teacher.prompts), 2)
        self.assertEqual(page.content(), before)
        self.assertNotIn('texto(', result['draft_toml'])

    def test_autoprofile_cancellation_after_query_discards_draft(self):
        entry = next(e for e in manifest() if e['file'] == 'tabela_sem_rotulos.html')
        page = self.page(entry['file'])
        cancelled = [False]
        teacher = FakeClaude([{'toml': entry['profile']}])
        def ask(*args, **kwargs):
            result = teacher(*args, **kwargs)
            cancelled[0] = True
            return result
        events = []
        with self.assertRaises(autoprofile.AutoprofileError) as ctx:
            autoprofile.learn(page.main_frame, page.url, ask, cancelled=lambda: cancelled[0], emit=events.append)
        self.assertEqual(ctx.exception.code, 'cancelled')
        self.assertEqual(events[-1]['phase'], 'cancelled')

    def test_recognized_page_does_not_query_model(self):
        page = self.page('botoes_grandes.html')
        result = autoprofile.learn(page.main_frame, page.url, FakeClaude([]))
        self.assertFalse(result['needed'])
        self.assertEqual(result['draft_toml'], '')

    def test_profile_frame_filter_does_not_fall_back_to_other_frames(self):
        from dracaena.adapters.profile import parse
        page = self.page('botoes_grandes.html')
        spec = parse('[site]\nname="sintetico"\nversion=0\nmatch=["*"]\nframe="quadro-ausente"\n'
                     '[question]\ncontainer="section"\nstem="h2"\n[options]\nitem="button"\n')
        adapter = GeneralAdapter(profile=spec)
        self.assertEqual(adapter.locate(page.main_frame), [])
        self.assertFalse(adapter.diagnose(page.main_frame)['supported'])
