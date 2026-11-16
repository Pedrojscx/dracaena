"""Carregamento, leitura e seleção restrita de fixtures genéricas."""
import unittest
from playwright.sync_api import sync_playwright
from web import launch
from generic_coverage import ADAPTERS, ROOT, GenericServer, inspect, manifest, report
from dracaena.adapters.general import GeneralAdapter
from dracaena.guard import Guard


class GenericTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = GenericServer()
        cls.pw = sync_playwright().start()
        cls.browser = launch(cls.pw)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()
        cls.server.close()

    def test_measured_coverage_and_read_only(self):
        page = self.browser.new_page()
        self.addCleanup(page.close)
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        entries = manifest()
        self.assertEqual({e["file"] for e in entries}, {p.name for p in ROOT.glob("*.html")})
        for entry in entries:
            for name in ADAPTERS:
                with self.subTest(fixture=entry["file"], adapter=name):
                    self.assertEqual(inspect(page, self.server, entry, name), entry["observed"][name])
        self.assertEqual(errors, [])
        self.assertEqual((ROOT / "COBERTURA.md").read_text(encoding="utf-8"), report(entries))

    def test_aria_selection_through_guard(self):
        for filename in ("lista_aninhada.html", "radio_aria.html"):
            with self.subTest(fixture=filename):
                page = self.browser.new_page()
                try:
                    entry = next(e for e in manifest() if e["file"] == filename)
                    page.goto(self.server.url(entry))
                    adapter = GeneralAdapter()
                    host, = adapter.locate(page.main_frame)
                    guard = Guard(lambda _: None)
                    guard.bind(page.main_frame, host, adapter.extract(host).id)
                    for index in (1, 2):
                        guard.perform(adapter.target(host, "option", index))
                        self.assertEqual([o.index for o in adapter.extract(host).options if o.checked], [index])
                finally:
                    page.close()

    def test_neutral_standalone_markup(self):
        from html.parser import HTMLParser
        class Check(HTMLParser):
            def handle_starttag(self, tag, attrs):
                for key, value in attrs:
                    if key in ("id", "class", "name") and value:
                        assert all(part.startswith("gx-") for part in value.split()), (tag, key)
                    if key.startswith("data-"):
                        assert key.startswith("data-gx-"), key
                    assert key not in ("src", "href", "action"), key
                    if key == "srcdoc":
                        Check().feed(value)
            def handle_comment(self, data):
                raise AssertionError("comentário não permitido")
        for entry in manifest():
            with self.subTest(fixture=entry["file"]):
                Check().feed((ROOT / entry["file"]).read_text(encoding="utf-8"))
