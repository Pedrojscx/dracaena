"""Explorador CDP só leitura (adapters/explorer.py): lista branca, limites, quadros de outra origem, canário."""

from __future__ import annotations

import ast
import functools
import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from fx import launch
from playwright.sync_api import sync_playwright

from dracaena.adapters import explorer

SOURCE = Path(explorer.__file__).read_text(encoding="utf-8")
CANARY = "CANARIOZULU"


class FakeCDP:
    """Sessão falsa: `answers[método]` é o dict de resposta ou uma função(params) -> dict."""

    def __init__(self, answers):
        self.answers, self.calls = answers, []

    def send(self, method, params=None):
        self.calls.append(method)
        value = self.answers.get(method, {})
        return value(params) if callable(value) else value


def tree(children=(), **extra):
    return {"nodeType": 1, "localName": "div", "attributes": [], "children": list(children), **extra}


def frame_tree(origin="http://a.test"):
    return {"frameTree": {"frame": {"id": "top", "securityOrigin": origin}}}


class SourceTests(unittest.TestCase):
    def test_every_cdp_call_is_on_the_allowlist(self):
        methods = set()
        for node in ast.walk(ast.parse(SOURCE)):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "send":
                if node.args and isinstance(node.args[0], ast.Constant):
                    methods.add(node.args[0].value)
        self.assertTrue(methods, "o módulo deveria chamar CDP por literais")
        self.assertLessEqual(methods, explorer.ALLOWED_METHODS)

    def test_allowlist_has_no_forbidden_method(self):
        for name in explorer.ALLOWED_METHODS:
            self.assertFalse(name.startswith(explorer.FORBIDDEN_PREFIXES), name)
            self.assertNotIn(name, explorer.FORBIDDEN_METHODS)
        for name in ("Input.dispatchMouseEvent", "Page.navigate", "Page.reload", "Runtime.evaluate",
                     "DOM.setAttributeValue", "Emulation.setDeviceMetricsOverride"):
            self.assertNotIn(name, explorer.ALLOWED_METHODS)

    def test_session_refuses_a_method_outside_the_allowlist(self):
        fake = FakeCDP({})
        session = explorer._Session(fake, lambda: 0.0, 10.0)
        for name in ("Input.dispatchMouseEvent", "Page.navigate", "Runtime.evaluate", "DOM.setOuterHTML"):
            with self.subTest(method=name), self.assertRaises(explorer.ForbiddenMethod):
                session.send(name, {})
        self.assertEqual(fake.calls, [])

    def test_no_disk_access(self):
        self.assertNotIn("open(", SOURCE)
        self.assertNotIn("write_text", SOURCE)


class LimitTests(unittest.TestCase):
    def test_node_limit_is_an_overflow(self):
        big = tree(children=[tree() for _ in range(explorer.MAX_NODES)])
        fake = FakeCDP({"Page.getFrameTree": frame_tree(), "DOM.getDocument": {"root": big}})
        with self.assertRaises(explorer.CaptureLimitExceeded):
            explorer.capture(fake)

    def test_shadow_depth_limit(self):
        def chain(levels):
            inner = tree()
            for _ in range(levels):
                inner = tree(shadowRoots=[{"nodeType": 11, "shadowRootType": "open", "children": [inner]}])
            return inner

        ok = FakeCDP({"Page.getFrameTree": frame_tree(), "DOM.getDocument": {"root": chain(explorer.MAX_SHADOW)}})
        self.assertEqual(explorer.capture(ok)["shadow"]["max_depth"], explorer.MAX_SHADOW)
        over = FakeCDP({"Page.getFrameTree": frame_tree(), "DOM.getDocument": {"root": chain(explorer.MAX_SHADOW + 1)}})
        with self.assertRaises(explorer.CaptureLimitExceeded):
            explorer.capture(over)

    def test_time_limit(self):
        ticks = [0.0]

        def clock():
            ticks[0] += 4.0
            return ticks[0]

        fake = FakeCDP({"Page.getFrameTree": frame_tree(), "DOM.getDocument": {"root": tree(children=[tree()] * 5)}})
        with self.assertRaises(explorer.CaptureLimitExceeded):
            explorer.capture(fake, clock=clock)


class StructureTests(unittest.TestCase):
    def test_closed_shadow_and_frame_origin_from_the_tree(self):
        closed = tree(shadowRoots=[{"nodeType": 11, "shadowRootType": "closed", "children": [
            tree(localName="button", attributes=["role", "button", "id", "dentro"])]}])
        other = tree(localName="iframe", attributes=["id", "quadro"], frameId="f2",
                     contentDocument={"nodeType": 9, "children": [
                         tree(localName="div", attributes=["role", "option", "id", "alt-1"])]})
        fake = FakeCDP({
            "Page.getFrameTree": {"frameTree": {"frame": {"id": "top", "securityOrigin": "http://a.test"},
                                                "childFrames": [{"frame": {"id": "f2",
                                                                           "securityOrigin": "http://b.test"}}]}},
            "DOM.getDocument": {"root": tree(children=[closed, other])},
            "DOMSnapshot.captureSnapshot": {"documents": []},
            "DOM.resolveNode": {"object": {"objectId": "o"}},
            "DOMDebugger.getEventListeners": {"listeners": [{"type": "click"}, {"type": "evento-do-autor"}]},
            "Runtime.releaseObjectGroup": {},
        })
        out = explorer.capture(fake)
        self.assertEqual(out["shadow"]["closed_roots"], 1)
        self.assertEqual(out["frames"], [{"selector": "iframe#quadro", "same_origin": False, "readable": True, "depth": 1}])
        by_id = {n["selector"]: n for n in out["nodes"]}
        self.assertEqual(by_id["button#dentro"]["shadow_depth"], 1)
        self.assertEqual(by_id["div#alt-1"]["frame_path"], ["iframe#quadro"])
        self.assertFalse(by_id["div#alt-1"]["same_origin"])
        self.assertEqual(by_id["div#alt-1"]["listeners"], ["click"])
        self.assertEqual(out["listeners"]["other_types"], 2)
        self.assertNotIn("evento-do-autor", json.dumps(out))


class BrowserTests(unittest.TestCase):
    """Duas origens em 127.0.0.1 (portas diferentes): a página de cima tem um iframe da outra."""

    @classmethod
    def setUpClass(cls):
        cls.pages = {}
        cls.servers = []
        cls.urls = {}
        for name in ("a", "b"):
            server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(_Pages, cls.pages))
            cls.servers.append(server)
            cls.urls[name] = f"http://127.0.0.1:{server.server_address[1]}"
            threading.Thread(target=server.serve_forever, daemon=True).start()
        cls.pages["/topo.html"] = (
            '<!doctype html><html><body><main><p>' + CANARY + ' enunciado de topo</p>'
            '<input value="' + CANARY + '" aria-label="' + CANARY + '">'
            f'<iframe id="quadro-pratica" src="{cls.urls["b"]}/quadro.html"></iframe>'
            '<button id="conferir">Conferir</button></main></body></html>')
        cls.pages["/quadro.html"] = (
            '<!doctype html><html><body><div class="bloco">'
            '<div role="option" id="alt-1">Alfa ' + CANARY + '</div>'
            '<div role="option" id="alt-2" onclick="void 0">Beta</div>'
            '<button id="enviar">Enviar</button><span data-x="' + CANARY + '">x</span></div>'
            '<div id="casca"></div><script>'
            "document.getElementById('alt-1').addEventListener('click', () => {});"
            "const sr = document.getElementById('casca').attachShadow({mode: 'closed'});"
            "sr.innerHTML = '<button role=\"button\" id=\"fechado\">Ok</button>';"
            "sr.querySelector('#fechado').addEventListener('click', () => {});"
            '</script></body></html>')
        cls.pw = sync_playwright().start()
        cls.browser = launch(cls.pw)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()
        for server in cls.servers:
            server.shutdown()

    def capture_page(self):
        context = self.browser.new_context()
        try:
            context.add_cookies([{"name": "c", "value": CANARY, "url": self.urls["a"]}])
            page = context.new_page()
            page.goto(self.urls["a"] + "/topo.html")
            page.wait_for_load_state("load")
            page.evaluate(f"localStorage.setItem('k', '{CANARY}')")
            page.frames[1].wait_for_load_state("load")
            cdp = context.new_cdp_session(page)
            seen = set()

            class Recording:
                def send(self, method, params=None):
                    seen.add(method)
                    return cdp.send(method, params)

            out = explorer.capture(Recording())
            return out, seen
        finally:
            context.close()

    def test_frame_of_other_origin_and_its_path(self):
        out, _ = self.capture_page()
        self.assertEqual(len(out["frames"]), 1)
        self.assertEqual(out["frames"][0]["selector"], "iframe#quadro-pratica")
        self.assertFalse(out["frames"][0]["same_origin"])
        self.assertTrue(out["frames"][0]["readable"])
        by_sel = {n["selector"]: n for n in out["nodes"]}
        self.assertEqual(by_sel["div#alt-1"]["frame"], "iframe#quadro-pratica")
        self.assertEqual(by_sel["div#alt-1"]["frame_path"], ["iframe#quadro-pratica"])
        self.assertEqual(by_sel["button#conferir"]["frame_path"], [])

    def test_listeners_only_on_buttons_and_options(self):
        out, _ = self.capture_page()
        by_sel = {n["selector"]: n for n in out["nodes"]}
        self.assertEqual(by_sel["div#alt-1"]["listeners"], ["click"])
        self.assertIn("click", by_sel["div#alt-2"]["listeners"])
        self.assertEqual(by_sel["button#enviar"]["listeners"], [])
        self.assertGreaterEqual(out["listeners"]["with_click"], 2)
        for node in out["nodes"]:
            self.assertEqual(node["role"] in ("button", "option"), True, node)

    def test_closed_shadow_root_is_read(self):
        out, _ = self.capture_page()
        self.assertGreaterEqual(out["shadow"]["closed_roots"], 1)
        fechado = [n for n in out["nodes"] if n["selector"] == "button#fechado"]
        self.assertEqual(len(fechado), 1)
        self.assertEqual(fechado[0]["shadow_depth"], 1)
        self.assertEqual(fechado[0]["listeners"], ["click"])

    def test_bbox_is_integer_geometry(self):
        out, _ = self.capture_page()
        by_sel = {n["selector"]: n for n in out["nodes"]}
        box = by_sel["div#alt-1"]["bbox"]
        self.assertIsNotNone(box)
        self.assertEqual(len(box), 4)
        self.assertTrue(all(isinstance(v, int) for v in box))
        self.assertGreater(box[2], 0)

    def test_only_allowlisted_methods_were_called(self):
        _, seen = self.capture_page()
        self.assertTrue(seen)
        self.assertLessEqual(seen, explorer.ALLOWED_METHODS)

    def test_canary_never_reaches_the_output(self):
        out, _ = self.capture_page()
        self.assertNotIn(CANARY, json.dumps(out, ensure_ascii=False))


class _Pages(BaseHTTPRequestHandler):
    def __init__(self, pages, *args, **kwargs):
        self.pages = pages
        super().__init__(*args, **kwargs)

    def do_GET(self):
        body = self.pages.get(self.path.split("?", 1)[0])
        if body is None:
            self.send_error(404)
            return
        data = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    unittest.main()
