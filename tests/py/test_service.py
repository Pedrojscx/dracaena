"""Service do núcleo: navegador/adaptador falsos e um caso com Chromium local e fixture sintética."""

from __future__ import annotations

import os
import tempfile
import threading
import time
import unittest
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from fx import REPO, launch

from dracaena.adapters.base import Registry
from dracaena.core.errors import ServiceError
from dracaena.core.model import Option, Question, Target, Verdict
from dracaena.core.service import Service, default_endpoint
from dracaena.platform.browser import BrowserSandboxUnavailable

SINGLE = '{"type":"SINGLE","answers":[0]}'


def wait_for(pred, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(.01)
    return pred()


class Element:
    def __init__(self, site):
        self.site = site

    def evaluate(self, _script, _arg=None):
        self.site.acted += 1
        return {"ok": True}


class Site:
    """Página falsa: uma questão por vez; o humano avança mudando `index`."""

    def __init__(self, kind="SINGLE"):
        self.index, self.kind, self.result, self.gone, self.acted = 0, kind, False, False, 0
        self.check = {"ok": True, "kind": "alternativa", "desc": "falso"}


class Frame:
    def __init__(self, site):
        self.site = site

    def evaluate(self, _script, arg=None):
        if isinstance(arg, list):          # frases de resultado
            return self.site.result
        return dict(self.site.check)       # conferência da guarda


class Page:
    def __init__(self, site, url="http://127.0.0.1/pratica"):
        self.url, self.main_frame = url, Frame(site)

    def title(self):
        return "Prática sintética"

    def evaluate(self, _script):
        return "visible"


class Adapter:
    name, figure_dir, extra_block = "falso", None, ()

    def __init__(self, site, score=10):
        self.site, self.score = site, score

    def matches(self, url, title=""):
        return self.score

    def locate(self, frame):
        return [] if self.site.result or self.site.gone else [self.site]

    def extract(self, host):
        return Question(id=f"q{host.index}", kind=host.kind, stem=f"Enunciado sintético {host.index}",
                        options=(Option(0, "Alternativa A"), Option(1, "Alternativa B")))

    def target(self, host, kind, index):
        return Target("option", "click", Element(host), f"alternativa {index}", f"q{host.index}")

    def verdict(self, host):
        return Verdict()


class PW:
    def __init__(self, pages):
        browser = type("B", (), {"contexts": [type("C", (), {"pages": pages})()], "close": lambda _: None})()
        self.chromium = type("Ch", (), {"connect_over_cdp": lambda _, __: browser})()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None


class Asker:
    """Claude falso; com `gate`, a consulta só volta quando liberada."""

    def __init__(self, raw=SINGLE, gate=False):
        self.raw, self.calls = raw, 0
        self.gate = threading.Event()
        if not gate:
            self.gate.set()
        self.entered = threading.Event()

    def __call__(self, cfg, text, abort=None, schema=None, **_):
        self.calls += 1
        self.entered.set()
        self.gate.wait(5)
        return self.raw, 0.0


class ServiceCase(unittest.TestCase):
    def make(self, site=None, asker=None, **kw):
        self.site = site or Site()
        self.asker = asker or Asker()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.record = Path(tmp.name) / "revisao.jsonl"
        pages = kw.pop("pages", None) or [Page(self.site)]
        options = dict(registry=Registry([Adapter(self.site)]), config=lambda: {"MAX_QUESTIONS": 80},
                       endpoint=lambda: 9, tabs=lambda _port: [{"type": "page", "url": p.url} for p in pages],
                       playwright_factory=lambda: PW(pages), ask=self.asker, record_path=self.record,
                       sleep=lambda s: time.sleep(min(s, .01)))
        options.update(kw)
        self.svc = Service(**options)
        self.events = []
        self.svc.subscribe(self.events.append)
        svc, asker = self.svc, self.asker
        self.addCleanup(svc.close)
        self.addCleanup(asker.gate.set)
        return self.svc

    def state(self, value):
        return wait_for(lambda: self.svc.state == value)

    def logs(self):
        self.svc.flush()
        return [e["msg"] for e in self.events if e["event"] == "log"]

    def kinds(self, name):
        self.svc.flush()
        return [e for e in self.events if e["event"] == name]

    def acted(self):
        return sum("(dry-run) faria:" in line for line in self.logs())


class StateTests(ServiceCase):
    def test_status_snapshot(self):
        svc = self.make()
        self.assertEqual(svc.handle("status", {}), {"state": "idle", "site": "", "question": 0, "max": 0,
                                                    "error": "", "dry_run": True})

    def test_dry_run_is_the_default(self):
        self.assertTrue(Service(registry=Registry()).dry_run)

    def test_toggle_does_not_block_and_loop_waits_for_human(self):
        svc = self.make(asker=Asker(gate=True))
        started = time.monotonic()
        snap = svc.handle("toggle", {})
        self.assertLess(time.monotonic() - started, 1)
        self.assertEqual(snap["state"], "running")
        self.assertTrue(self.asker.entered.wait(5))
        self.assertEqual(svc.handle("status", {})["state"], "running")   # handle responde com o laço preso
        self.asker.gate.set()
        self.assertTrue(wait_for(lambda: svc.count == 1))
        time.sleep(.1)
        self.assertEqual(self.asker.calls, 1, "a mesma questão não é respondida de novo")
        self.site.index = 1                                              # o humano avançou
        self.assertTrue(wait_for(lambda: svc.count == 2))
        self.assertEqual(self.acted(), 2)
        self.assertEqual(svc.handle("stop", {})["state"], "idle")
        self.assertEqual(self.site.acted, 0, "dry-run não age na página")

    def test_slow_discovery_does_not_block_commands_or_act_after_stop(self):
        entered, release = threading.Event(), threading.Event()
        def tabs(_port):
            entered.set()
            release.wait(5)
            return [{"type": "page", "url": "http://127.0.0.1/pratica"}]
        svc = self.make(tabs=tabs)
        self.addCleanup(release.set)
        started = time.monotonic()
        svc.handle("toggle", {})
        self.assertLess(time.monotonic() - started, .5)
        self.assertTrue(entered.wait(2))
        self.assertEqual(svc.handle("status", {})["state"], "running")
        svc.handle("stop", {})
        release.set()
        svc._thread.join(2)
        self.assertFalse(svc._thread.is_alive())
        self.assertEqual(self.asker.calls, 0)
        self.assertEqual(svc.state, "idle")

    def test_events_in_order(self):
        svc = self.make()
        svc.handle("ask", {})
        self.assertTrue(self.state("idle"))
        svc.flush()
        names = [e["event"] for e in self.events if e["event"] != "log"]
        self.assertEqual(names, ["state", "state", "question", "verdict", "state", "state"])
        question = self.kinds("question")[0]
        self.assertEqual((question["id"], question["kind"]), ("q0", "SINGLE"))
        verdict = self.kinds("verdict")[0]
        self.assertEqual((verdict["id"], verdict["result"]), ("q0", "UNKNOWN"))
        states = [e["state"] for e in self.kinds("state")]
        self.assertEqual((states[0], states[-1]), ("running", "idle"))
        self.assertTrue(all("dry_run" in e for e in self.kinds("state")))

    def test_pause_between_questions(self):
        svc = self.make(asker=Asker(gate=True))
        svc.handle("toggle", {})
        self.assertTrue(self.asker.entered.wait(5))
        self.assertEqual(svc.handle("toggle", {})["state"], "paused")    # pausa no meio da consulta
        self.asker.gate.set()
        self.assertTrue(wait_for(lambda: svc.count == 1), "a questão atual termina")
        self.assertEqual(self.acted(), 1)
        self.site.index = 1
        time.sleep(.2)
        self.assertEqual(self.asker.calls, 1, "pausado não começa outra questão")
        self.assertEqual(svc.handle("toggle", {})["state"], "running")
        self.assertTrue(wait_for(lambda: svc.count == 2))

    def test_stop_before_acting(self):
        svc = self.make(asker=Asker(gate=True))
        svc.handle("toggle", {})
        self.assertTrue(self.asker.entered.wait(5))
        self.assertEqual(svc.handle("stop", {})["state"], "idle")
        self.asker.gate.set()
        svc._thread.join(5)
        self.assertEqual(self.acted(), 0)
        self.assertEqual(svc.state, "idle")
        self.assertFalse(self.record.exists())

    def test_ask_answers_current_only_and_stops(self):
        svc = self.make()
        svc.handle("ask", {})
        self.assertTrue(self.state("idle"))
        self.assertEqual(self.asker.calls, 1)
        svc.handle("ask", {})                       # mesma questão: ask responde de novo e para
        self.assertTrue(wait_for(lambda: self.asker.calls == 2))
        self.assertTrue(self.state("idle"))
        self.assertEqual(self.acted(), 2)

    def test_once_is_one_short_round(self):
        svc = self.make()
        self.assertEqual(svc.handle("once", {})["max"], 1)
        self.assertTrue(self.state("idle"))
        self.assertEqual((self.asker.calls, self.acted()), (1, 1))

    def test_ask_while_paused_returns_to_paused(self):
        svc = self.make()
        svc.handle("toggle", {})
        self.assertTrue(wait_for(lambda: svc.count == 1))
        svc.handle("toggle", {})
        self.assertEqual(svc.state, "paused")
        svc.handle("ask", {})
        self.assertTrue(wait_for(lambda: self.asker.calls == 2))
        self.assertTrue(self.state("paused"))
        self.assertEqual(self.acted(), 2)

    def test_max_questions_stops(self):
        svc = self.make(max_questions=1)
        svc.handle("toggle", {})
        self.assertTrue(self.state("idle"))
        self.assertIn("parada: limite de questões", self.logs())

    def test_result_screen_stops_without_claude(self):
        site = Site()
        site.result = True
        svc = self.make(site=site)
        svc.handle("toggle", {})
        self.assertTrue(self.state("idle"))
        self.assertEqual(self.asker.calls, 0)
        self.assertIn("parada: fim da atividade", self.logs())

    def test_unsupported_kind_takes_no_action(self):
        svc = self.make(site=Site(kind="MATCH"))
        svc.handle("ask", {})
        self.assertTrue(self.state("idle"))
        self.assertEqual((self.asker.calls, self.acted()), (0, 0))
        self.assertEqual(self.kinds("verdict")[0]["feedback"], "não suportado")

    def test_guard_refusal_is_error_state(self):
        site = Site()
        site.check = {"ok": False, "reason": "invisível", "desc": "falso"}
        svc = self.make(site=site)
        svc.handle("toggle", {})
        self.assertTrue(self.state("error"))
        self.assertIn("guarda recusou", svc.snapshot()["error"])
        self.assertEqual(svc.handle("stop", {})["state"], "idle")

    def test_invalid_answer_is_error_state(self):
        svc = self.make(asker=Asker(raw='{"type":"SINGLE","answers":[9]}'))
        svc.handle("toggle", {})
        self.assertTrue(self.state("error"))
        self.assertEqual(self.acted(), 0)

    def test_real_mode_acts_only_through_guard(self):
        svc = self.make(dry_run=False)
        svc.handle("ask", {})
        self.assertTrue(self.state("idle"))
        self.assertEqual(self.site.acted, 1)
        self.assertFalse(self.record.exists(), "modo real não grava revisão")


class ErrorTests(ServiceCase):
    def code(self, cmd, args=None):
        with self.assertRaises(ServiceError) as ctx:
            self.svc.handle(cmd, {} if args is None else args)
        return ctx.exception.code

    def test_typed_errors(self):
        self.make(asker=Asker(gate=True))
        self.assertEqual(self.code("nada"), "unknown_cmd")
        self.assertEqual(self.code("status", []), "bad_request")
        self.assertEqual(self.code("toggle", {"url_contains": 3}), "bad_request")
        self.assertEqual(self.code("stop"), "bad_state")
        self.svc.handle("toggle", {})
        self.assertEqual(self.code("ask"), "bad_state")
        self.assertEqual(self.code("once"), "bad_state")

    def test_no_browser(self):
        def missing():
            raise ServiceError("no_browser", "sem navegador")
        self.make(endpoint=missing)
        self.svc.handle("toggle", {})
        self.assertTrue(self.state("error"))
        self.assertEqual(self.svc.error, "sem navegador")

    def test_sandbox_failure_reaches_state_with_its_condition(self):
        def blocked():
            raise BrowserSandboxUnavailable("sandbox indisponível")
        self.make(endpoint=blocked)
        self.svc.handle("toggle", {})
        self.assertTrue(self.state("error"))
        event = self.kinds("state")[-1]
        self.assertEqual((event["error"], event["condition"]),
                         ("sandbox indisponível", "sandbox_unavailable"))

    def test_default_endpoint_without_profile(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"XDG_DATA_HOME": tmp, "APPDATA": tmp}):
            with self.assertRaises(ServiceError) as ctx:
                default_endpoint()
        self.assertEqual(ctx.exception.code, "no_browser")

    def test_no_site(self):
        self.make(tabs=lambda _p: [{"type": "page", "url": "about:blank"}])
        self.svc.handle("toggle", {})
        self.assertTrue(self.state("error"))
        site = Site()
        self.make(site=site, registry=Registry([Adapter(site, score=0)]))
        self.svc.handle("ask", {})
        self.assertTrue(self.state("error"))

    def test_no_question_in_tab_is_error_state(self):
        site = Site()
        site.gone = True
        svc = self.make(site=site, pages=[Page(site, "http://127.0.0.1/a"), Page(site, "http://127.0.0.1/b")])
        svc.handle("toggle", {})
        self.assertTrue(self.state("error"))
        self.assertIn("Nenhuma questão", svc.snapshot()["error"])


class SubscriptionTests(ServiceCase):
    def test_unsubscribe(self):
        svc = self.make()
        got = []
        off = svc.subscribe(got.append)
        svc.handle("ask", {})
        self.assertTrue(self.state("idle"))
        svc.flush()
        count = len(got)
        self.assertGreater(count, 0)
        off()
        svc.handle("ask", {})
        self.assertTrue(wait_for(lambda: self.asker.calls == 2))
        self.assertTrue(self.state("idle"))
        svc.flush()
        self.assertEqual(len(got), count)

    def test_raising_callback_does_not_break_loop(self):
        svc = self.make()

        def bad(_event):
            raise RuntimeError("assinante com defeito")
        svc.subscribe(bad)
        with self.assertLogs("dracaena", "ERROR"):
            svc.handle("ask", {})
            self.assertTrue(self.state("idle"))
            svc.flush()
        self.assertEqual(self.acted(), 1)
        self.assertEqual(self.kinds("state")[-1]["state"], "idle")


class CloseTests(ServiceCase):
    def assert_stopped(self, svc):
        self.assertFalse(any(t.is_alive() for t in (svc._thread, svc._dispatcher) if t))
        self.assertFalse(any(t.name.startswith("dracaena-") for t in threading.enumerate()))

    def test_close_drains_events_and_is_idempotent(self):
        svc = self.make()
        entered, release = threading.Event(), threading.Event()
        delivered = []
        def callback(event):
            if event.get("number") == 0:
                entered.set()
                release.wait(2)
            if "number" in event:
                delivered.append(event["number"])
        svc.subscribe(callback)
        self.addCleanup(release.set)
        for number in range(4):
            svc._emit({"event": "log", "number": number})
        self.assertTrue(entered.wait(2))
        closer = threading.Thread(target=svc.close)
        closer.start()
        self.assertTrue(wait_for(lambda: svc._closed))
        release.set()
        closer.join(2)
        self.assertFalse(closer.is_alive())
        self.assertEqual(delivered, [0, 1, 2, 3])
        svc.close()
        self.assertTrue(svc.flush(.1))
        self.assert_stopped(svc)

    def test_closed_service_cannot_restart(self):
        svc = self.make(dry_run=False)
        svc.close()
        dispatcher = svc._dispatcher
        for command in ("toggle", "stop", "ask", "once"):
            with self.assertRaises(ServiceError) as ctx:
                svc.handle(command, {})
            self.assertEqual(ctx.exception.code, "bad_state")
            self.assertIn("fechado", ctx.exception.msg)
        with self.assertRaises(ServiceError):
            svc.subscribe(lambda _: None)
        svc._emit({"event": "log", "msg": "ignorado"})
        self.assertIs(svc._dispatcher, dispatcher)
        self.assertEqual(svc.handle("status", {})["state"], "idle")
        self.assertEqual(self.site.acted, 0)
        self.assert_stopped(svc)

    def test_close_from_subscriber_drains_without_self_join(self):
        svc = self.make()
        returned = threading.Event()
        delivered = []
        def callback(event):
            if event.get("msg") == "fechar":
                svc.close()
                returned.set()
            delivered.append(event)
        svc.subscribe(callback)
        with svc._lock:
            svc._emit({"event": "log", "msg": "fechar"})
            svc._emit({"event": "log", "msg": "pendente"})
        self.assertTrue(returned.wait(2))
        svc.close()
        self.assertTrue(any(e.get("msg") == "pendente" for e in delivered))
        self.assert_stopped(svc)

    def test_close_during_round_never_calls_guard_after_close(self):
        from dracaena.core import claude
        entered = threading.Event()
        def ask(_cfg, _text, abort, **_):
            entered.set()
            while not abort():
                time.sleep(.001)
            raise claude.Aborted()
        svc = self.make(ask=ask, dry_run=False)
        with mock.patch("dracaena.core.service.Guard") as guard:
            guard.return_value.result_visible.return_value = False
            svc.handle("toggle", {})
            self.assertTrue(entered.wait(2))
            svc.close()
            guard.return_value.perform.assert_not_called()
        self.assert_stopped(svc)

    def test_timed_out_round_cannot_act_when_it_returns(self):
        svc = self.make(asker=Asker(gate=True), dry_run=False)
        with mock.patch("dracaena.core.service.Guard") as guard:
            guard.return_value.result_visible.return_value = False
            svc.handle("toggle", {})
            self.assertTrue(self.asker.entered.wait(2))
            start = time.monotonic()
            svc.close(timeout=.02)
            self.assertLess(time.monotonic() - start, .5)
            self.asker.gate.set()
            svc.close()
            guard.return_value.perform.assert_not_called()
        self.assert_stopped(svc)

    def test_close_wakes_paused_worker(self):
        svc = self.make()
        svc.handle("toggle", {})
        self.assertTrue(wait_for(lambda: svc.count == 1))
        svc.handle("toggle", {})
        svc.close()
        self.assert_stopped(svc)


class LiveTests(unittest.TestCase):
    """Chromium local criado na thread do laço, fixture compat servida por HTTP."""

    def test_dry_run_on_fixture_keeps_dom(self):
        from playwright.sync_api import sync_playwright
        root = REPO / "tests" / "fixtures" / "compat"
        server = ThreadingHTTPServer(("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=str(root)))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        url = f"http://127.0.0.1:{server.server_address[1]}/quiz_mcq_single.html"
        seen = {}

        class Live:
            def __enter__(self):
                self.cm = sync_playwright()
                pw = self.cm.__enter__()

                class Chromium:
                    def connect_over_cdp(_, _endpoint):
                        browser = launch(pw)
                        page = browser.new_page()
                        page.goto(url)
                        seen["before"] = page.content()

                        class Wrapped:
                            contexts = browser.contexts

                            def close(_):
                                seen["after"] = page.content()
                                browser.close()
                        return Wrapped()
                self.chromium = Chromium()
                return self

            def __exit__(self, *exc):
                return self.cm.__exit__(*exc)

        with tempfile.TemporaryDirectory() as tmp:
            svc = Service(config=lambda: {}, endpoint=lambda: 9, tabs=lambda _p: [{"type": "page", "url": url}],
                          playwright_factory=Live, ask=lambda *_a, **_k: (SINGLE, 0.0),
                          record_path=Path(tmp) / "revisao.jsonl")
            self.addCleanup(svc.close)
            events = []
            svc.subscribe(events.append)
            svc.handle("ask", {})
            self.assertTrue(wait_for(lambda: svc.state != "running" and "after" in seen, 60))
            svc.flush()
            self.assertEqual(svc.state, "idle", [e for e in events if e["event"] == "log"])
            self.assertEqual(seen["before"], seen["after"])
            logs = [e["msg"] for e in events if e["event"] == "log"]
            self.assertEqual(sum("(dry-run) faria:" in line for line in logs), 1)
            self.assertEqual([e["event"] for e in events if e["event"] in ("question", "verdict")],
                             ["question", "verdict"])


if __name__ == "__main__":
    unittest.main()
