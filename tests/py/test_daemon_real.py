"""Daemon real: Service do núcleo atrás do IPC, troca de modo (DRY_RUN) e Chromium local.

Três blocos:
- ModeSwapTests: a troca de serviço em config.set DRY_RUN, com um serviço falso que tem close();
- RealIpcTests: daemon em thread + cliente IPC real + Service do núcleo, sem navegador;
- LiveTests: o mesmo, com o Chromium do Playwright e as fixtures sintéticas (pulado sem Chromium).

O Service só aceita abas http(s); por isso as fixtures são servidas em 127.0.0.1 e a
aba file:// aparece só no caso no_site. Em Windows o pipe tem nome fixo por usuário
(caminho NÃO VALIDADO em Windows real): os blocos com IPC real são pulados lá.
"""
import json
import os
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import socket
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from dracaena.core.service import Service
from dracaena.daemon import Daemon
from dracaena.platform import config, ipc

REPO = Path(__file__).resolve().parents[2]
COMPAT = REPO / "tests" / "fixtures" / "compat"
SINGLE = '{"type":"SINGLE","answers":[0]}'


def wait_for(pred, timeout=10.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(.02)
    return bool(pred())


def service_threads():
    """Threads vivas do Service do núcleo (laço e entrega de eventos)."""
    return {thread for thread in threading.enumerate() if thread.name.startswith("dracaena-")}


class Asker:
    """Claude falso: conta as consultas; com `gate`, só responde quando liberado."""

    def __init__(self):
        self.calls = 0
        self.gate = threading.Event()
        self.gate.set()
        self.entered = threading.Event()

    def __call__(self, cfg, text, abort=None, schema=None, **_):
        self.calls += 1
        self.entered.set()
        self.gate.wait(10)
        return SINGLE, 0.0


class FakeService:
    """Serviço mínimo com a mesma API pública do núcleo, incluindo close()."""

    def __init__(self, dry_run=True, state="idle"):
        self.dry_run, self.state = bool(dry_run), state
        self.subs, self.closed, self.stopped, self.close_error = [], 0, 0, None

    def subscribe(self, callback):
        self.subs.append(callback)

        def unsubscribe():
            if callback in self.subs:
                self.subs.remove(callback)
        return unsubscribe

    def fire(self, event):
        for callback in list(self.subs):
            callback(event)

    def handle(self, cmd, args):
        if cmd == "stop":
            self.stopped += 1
            self.state = "idle"
        return {"state": self.state, "site": "", "question": 0, "max": 0, "error": "", "dry_run": self.dry_run}

    def close(self, timeout=5.0):
        self.closed += 1
        if self.close_error:
            raise self.close_error


class FakeConn:
    def __init__(self):
        self.sent = []

    def send(self, value):
        self.sent.append(value)


class ConfigCase(unittest.TestCase):
    """Configuração, dados e runtime em pasta temporária."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="dr-")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        env = {"XDG_CONFIG_HOME": str(self.root / "xdg"), "XDG_DATA_HOME": str(self.root / "data"),
               "XDG_RUNTIME_DIR": str(self.root / "run"), "APPDATA": str(self.root / "data")}
        (self.root / "run").mkdir(mode=0o700)
        for item in (patch.object(config, "config_dir", return_value=self.root / "config"), patch.dict(os.environ, env)):
            item.start()
            self.addCleanup(item.stop)

    def stored(self):
        """DRY_RUN gravado em disco (None se nada foi gravado)."""
        path = self.root / "config" / "config.json"
        return json.loads(path.read_text(encoding="utf-8"))["DRY_RUN"] if path.exists() else None


class ModeSwapTests(ConfigCase):
    def make(self, dry_run=True, state="idle", factory=None):
        self.created = []

        def default_factory(value):
            self.created.append(FakeService(value))
            return self.created[-1]
        self.old = FakeService(dry_run, state)
        self.daemon = Daemon(self.old, service_factory=factory or default_factory)
        self.conns = [FakeConn(), FakeConn()]
        for index, conn in enumerate(self.conns):
            self.assertTrue(self.daemon.dispatch({"id": index, "cmd": "subscribe", "args": {"events": ["state", "log"]}}, conn)["ok"])
            self.daemon.initial_state(self.daemon.clients[conn])
            conn.sent.clear()
        return self.daemon

    def set_mode(self, value):
        return self.daemon.dispatch({"id": 9, "cmd": "config.set", "args": {"key": "DRY_RUN", "value": value}}, None)

    def test_swap_in_idle_is_atomic_with_one_state_event_for_every_subscriber(self):
        daemon = self.make()
        late = self.old.subs[0]
        with self.assertLogs("dracaena", "WARNING") as logs:
            response = self.set_mode(False)
        self.assertTrue(response["ok"], response)
        self.assertIs(response["data"]["DRY_RUN"], False)
        self.assertIn("Modo real ativado por config.set", logs.output[0])
        new = self.created[0]
        self.assertEqual(len(self.created), 1)
        self.assertIs(daemon.service, new)
        self.assertIs(self.stored(), False)
        self.assertIs(daemon.dispatch({"id": 1, "cmd": "status"}, None)["data"]["dry_run"], False)
        for conn in self.conns:  # as assinaturas das conexões abertas continuam valendo
            self.assertEqual(conn.sent, [{"event": "state", "state": "idle", "site": "", "question": 0, "max": 0,
                                          "error": "", "dry_run": False}])
        # o serviço antigo foi encerrado de verdade e ficou mudo
        self.assertEqual((self.old.closed, self.old.subs), (1, []))
        late({"event": "state", "state": "running", "dry_run": True})
        late({"event": "log", "level": "info", "msg": "atrasado"})
        self.assertEqual([len(conn.sent) for conn in self.conns], [1, 1])
        # o serviço novo é o único que fala
        new.fire({"event": "log", "level": "info", "msg": "novo"})
        self.assertEqual([conn.sent[-1]["msg"] for conn in self.conns], ["novo", "novo"])
        self.assertEqual(new.closed, 0)

    def test_swap_is_allowed_in_error_state_and_back_to_dry_run(self):
        self.make(dry_run=False, state="error")
        self.assertTrue(self.set_mode(True)["ok"])
        self.assertIs(self.daemon.service.dry_run, True)
        self.assertIs(self.stored(), True)
        self.assertEqual(self.old.closed, 1)
        self.assertEqual([conn.sent[-1]["dry_run"] for conn in self.conns], [True, True])

    def test_running_or_paused_refuses_both_directions_in_portuguese(self):
        for dry_run in (True, False):
            for state in ("running", "paused"):
                with self.subTest(dry_run=dry_run, state=state):
                    self.make(dry_run=dry_run, state=state)
                    before = self.stored()
                    response = self.set_mode(not dry_run)
                    self.assertEqual((response["ok"], response["code"]), (False, "bad_state"))
                    self.assertEqual(response["error"], "Pare o laço (stop) antes de mudar o modo simulação.")
                    self.assertIs(self.daemon.service, self.old)
                    self.assertEqual((self.created, self.old.closed, self.stored()), ([], 0, before))
                    self.assertEqual([conn.sent for conn in self.conns], [[], []])

    def test_same_mode_only_confirms_the_config(self):
        self.make(state="running")
        self.assertTrue(self.set_mode(True)["ok"])
        self.assertIs(self.daemon.service, self.old)
        self.assertEqual((self.created, self.old.closed, self.stored()), ([], 0, True))
        self.assertEqual([conn.sent for conn in self.conns], [[], []])

    def test_other_keys_and_invalid_values_never_swap(self):
        self.make()
        self.assertTrue(self.daemon.dispatch({"id": 1, "cmd": "config.set", "args": {"key": "MAX_QUESTIONS", "value": 5}}, None)["ok"])
        for value in (0, "false", None):
            self.assertEqual(self.set_mode(value)["code"], "bad_request")
        self.assertIs(self.daemon.service, self.old)
        self.assertEqual((self.created, self.old.closed, self.stored()), ([], 0, True))

    def test_failed_factory_keeps_previous_mode_in_config_and_service(self):
        def broken(_value):
            raise RuntimeError("não deu para criar")
        self.make(factory=broken)
        with self.assertLogs("dracaena", "ERROR"):
            response = self.set_mode(False)
        self.assertEqual((response["ok"], response["code"]), (False, "internal"))
        self.assertIs(self.daemon.service, self.old)
        self.assertEqual((self.old.closed, len(self.old.subs), self.stored()), (0, 1, None))
        self.assertIs(config.load()["DRY_RUN"], True)
        self.assertIs(self.daemon.dispatch({"id": 1, "cmd": "status"}, None)["data"]["dry_run"], True)
        self.assertEqual([conn.sent for conn in self.conns], [[], []])

    def test_new_service_in_the_wrong_mode_is_closed_and_refused(self):
        wrong = FakeService(dry_run=True)
        self.make(factory=lambda _value: wrong)
        with self.assertLogs("dracaena", "ERROR"):
            self.assertFalse(self.set_mode(False)["ok"])
        self.assertIs(self.daemon.service, self.old)
        self.assertEqual((wrong.closed, wrong.subs, self.old.closed, self.stored()), (1, [], 0, None))

    def test_failed_save_keeps_previous_mode_and_closes_the_new_service(self):
        for start in (True, False):
            with self.subTest(start=start):
                config.set_value("DRY_RUN", start)
                self.make(dry_run=start)
                with patch.object(config, "save", side_effect=OSError("disco cheio")), self.assertLogs("dracaena", "ERROR"):
                    response = self.set_mode(not start)
                self.assertFalse(response["ok"])
                new = self.created[0]
                self.assertEqual((new.closed, new.subs), (1, []))
                self.assertIs(self.daemon.service, self.old)
                self.assertEqual((self.old.closed, len(self.old.subs), self.stored()), (0, 1, start))
                self.assertEqual([conn.sent for conn in self.conns], [[], []])
                self.old.fire({"event": "log", "level": "info", "msg": "segue vivo"})
                self.assertEqual([len(conn.sent) for conn in self.conns], [1, 1])

    def test_old_service_failing_to_close_does_not_undo_the_swap(self):
        self.make(dry_run=False)
        self.old.close_error = RuntimeError("não encerrou")
        with self.assertLogs("dracaena", "ERROR"):
            self.assertTrue(self.set_mode(True)["ok"])
        self.assertIs(self.daemon.service.dry_run, True)
        self.assertIs(self.stored(), True)
        self.assertEqual(self.old.subs, [])

    def test_shutdown_stops_the_loop_and_closes_the_service(self):
        self.make(state="running")
        self.daemon.shutdown()
        self.assertEqual((self.old.stopped, self.old.closed, self.old.subs), (1, 1, []))

    def start_log(self, daemon):
        """Roda Daemon.run() com trava e socket falsos; devolve o que a partida registrou."""
        import contextlib
        import logging
        listener = type("Fechado", (), {"closed": True, "close": lambda self: None})()
        with patch("dracaena.daemon.InstanceLock", return_value=contextlib.nullcontext()), \
                patch("dracaena.daemon.Listener", return_value=listener), \
                self.assertLogs("dracaena", "INFO") as logs:
            logging.getLogger("dracaena").info("início")   # assertLogs exige ao menos um registro
            daemon.run()
        return [(record.levelname, record.getMessage()) for record in logs.records[1:]]

    def test_real_daemon_logs_its_mode_at_startup(self):
        self.make(dry_run=True)
        self.assertEqual(self.start_log(self.daemon), [("INFO", "Daemon real em modo simulação (DRY_RUN=true)")])
        self.make(dry_run=False)
        self.assertEqual(self.start_log(self.daemon), [("WARNING", "Daemon real em MODO REAL (DRY_RUN=false)")])

    def test_simulator_does_not_log_a_real_mode_at_startup(self):
        from dracaena.daemon import Simulator
        self.assertEqual(self.start_log(Daemon(Simulator(dry_run=False), simulate=True)), [])

    def test_simulator_and_services_without_factory_are_not_closed(self):
        from dracaena.daemon import Simulator
        simulator = Simulator(dry_run=True)
        daemon = Daemon(simulator, simulate=True)
        self.assertTrue(daemon.dispatch({"id": 1, "cmd": "config.set", "args": {"key": "DRY_RUN", "value": False}}, None)["ok"])
        self.assertIs(daemon.service, simulator)
        self.assertIs(simulator.dry_run, False)
        daemon.shutdown()  # o simulador não tem close(); nada a encerrar
        self.assertEqual(simulator.callbacks, [])


class Subscriber:
    """Cliente IPC real inscrito em eventos; uma thread guarda tudo o que chega."""

    def __init__(self, events):
        self.conn = ipc.connect(timeout=None)
        self.events = []
        self.conn.send({"v": 0, "id": 1, "cmd": "subscribe", "args": {"events": events}})
        self.reply = self.conn.receive()
        self.thread = threading.Thread(target=self.read, daemon=True)
        self.thread.start()

    def read(self):
        try:
            while True:
                message = self.conn.receive()
                if message is None:
                    return
                self.events.append(message)
        except (OSError, ValueError):
            return

    def kind(self, name):
        return [event for event in list(self.events) if event.get("event") == name]

    def settle(self, quiet=.3, timeout=5.0):
        """Espera a fila de eventos parar de crescer por `quiet` segundos."""
        end = time.monotonic() + timeout
        count, since = len(self.events), time.monotonic()
        while time.monotonic() < end and time.monotonic() - since < quiet:
            time.sleep(.02)
            if len(self.events) != count:
                count, since = len(self.events), time.monotonic()

    def close(self):
        try:
            self.conn.handle.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.conn.close()
        self.thread.join(2)


@unittest.skipIf(os.name == "nt", "pipe com nome fixo por usuário: IPC real NÃO VALIDADO em Windows real")
class RealIpcCase(ConfigCase):
    """Daemon real numa thread, atrás do socket IPC de verdade."""

    service_options = {}

    def setUp(self):
        super().setUp()
        self.asker = Asker()
        self.created = []
        self.baseline = service_threads()   # sobras de outros testes não contam
        self.daemon = Daemon(self.factory(config.load()["DRY_RUN"]), service_factory=self.factory)
        self.listener = ipc.Listener()
        self.server = threading.Thread(target=self.daemon.serve, args=(self.listener,), daemon=True)
        self.server.start()
        self.addCleanup(self.stop_daemon)

    def factory(self, dry_run):
        service = Service(dry_run=dry_run, ask=self.asker, record_path=self.root / "revisao.jsonl",
                                  once_wait=1.0, **self.service_options)
        self.created.append(service)
        return service

    def close_listener(self):
        """Fecha o socket e espera o serve() sair.

        Listener.close() não é seguro entre threads: o serve() acorda e fecha o mesmo socket
        no seu finally. Em produção só uma thread fecha; aqui a segunda chamada pode perder
        a corrida, e isso não é o que estes testes medem.
        """
        try:
            self.listener.close()
        except AttributeError:
            pass
        self.server.join(10)
        self.assertFalse(self.server.is_alive())

    def stop_daemon(self):
        self.asker.gate.set()
        self.close_listener()

    def own_threads(self):
        """Threads do Service criadas por este teste que ainda estão vivas."""
        return {thread for thread in service_threads() - self.baseline if thread.is_alive()}

    def assert_swap_ends_the_old_service(self, client, old):
        """Troca o modo e prova: threads do antigo encerradas em 5 s e nenhum evento dele nas conexões."""
        self.assertTrue(old.flush(), "eventos do serviço antigo entregues antes da troca")
        client.settle()   # tudo o que o antigo disse antes da troca já chegou ao cliente
        old_threads = self.own_threads()
        self.assertTrue(old_threads, "o serviço antigo tinha threads vivas antes da troca")
        mark = len(client.events)
        self.assertTrue(self.call("config.set", key="DRY_RUN", value=False)["ok"])
        self.assertIsNot(self.daemon.service, old)
        self.assertTrue(wait_for(lambda: not any(thread.is_alive() for thread in old_threads), 5),
                        [thread.name for thread in old_threads if thread.is_alive()])
        self.assertTrue(self.call("shortcut.test", arm=True)["ok"])   # marcador: evento seguinte conhecido
        self.assertEqual(self.call("toggle")["data"], {"shortcut_test": True})
        self.assertTrue(wait_for(lambda: client.kind("shortcut_test")), client.events)
        time.sleep(.2)
        # o close() do antigo emite um state próprio (dry_run true): ele não pode chegar a ninguém
        self.assertEqual(client.events[mark:], [
            {"event": "state", "state": "idle", "site": "", "question": 0, "max": 0, "error": "", "dry_run": False},
            {"event": "shortcut_test", "ok": True}])
        self.assertEqual(self.own_threads(), set(), "nenhuma thread órfã depois da troca")

    def subscriber(self, events=("state", "log", "question", "verdict", "shortcut_test")):
        client = Subscriber(list(events))
        self.addCleanup(client.close)
        self.assertTrue(client.reply["ok"], client.reply)
        self.assertTrue(wait_for(lambda: client.kind("state")), "estado inicial")
        return client

    def call(self, cmd, **args):
        return ipc.request(cmd, args)

    def state(self):
        return self.call("status")["data"]


class RealIpcTests(RealIpcCase):
    def test_hello_status_subscribe_and_nothing_starts_by_itself(self):
        with patch("dracaena.platform.browser.read_port", side_effect=AssertionError("não deve procurar navegador")), \
                patch("dracaena.platform.browser.launch", side_effect=AssertionError("não deve abrir navegador")):
            hello = self.call("hello")
            self.assertTrue(hello["ok"])
            self.assertEqual(hello["data"]["v"], 0)
            self.assertLessEqual({"status", "toggle", "stop", "ask", "once", "config.set", "subscribe"}, set(hello["data"]["caps"]))
            expected = {"state": "idle", "site": "", "question": 0, "max": 0, "error": "", "dry_run": True}
            self.assertEqual(self.state(), expected)
            client = self.subscriber()
            self.assertEqual(client.events[0], {**expected, "event": "state"})
            time.sleep(.2)
        self.assertEqual(self.state(), expected)
        self.assertEqual((len(client.events), self.asker.calls, len(self.created)), (1, 0, 1))
        self.assertIsNone(self.stored(), "o daemon não grava configuração sozinho")

    def test_no_browser_arrives_as_state_error(self):
        client = self.subscriber()
        response = self.call("toggle")
        self.assertTrue(response["ok"], response)
        self.assertEqual(response["data"]["state"], "running")
        self.assertTrue(wait_for(lambda: any(e["state"] == "error" for e in client.kind("state"))), client.events)
        error = [e for e in client.kind("state") if e["state"] == "error"][-1]
        self.assertIn("Nenhum navegador dedicado aberto", error["error"])
        self.assertIs(error["dry_run"], True)
        self.assertEqual(self.asker.calls, 0)
        self.assertEqual(self.call("stop")["data"]["state"], "idle")

    def test_swap_after_error_leaves_no_thread_of_the_old_service(self):
        client = self.subscriber()
        old = self.daemon.service
        self.assertEqual(self.call("toggle")["data"]["state"], "running")
        self.assertTrue(wait_for(lambda: self.state()["state"] == "error"))
        self.assert_swap_ends_the_old_service(client, old)

    def test_daemon_shutdown_leaves_no_service_thread(self):
        client = self.subscriber()
        self.assertEqual(self.call("toggle")["data"]["state"], "running")
        self.assertTrue(wait_for(lambda: self.state()["state"] == "error"))
        self.assertTrue(self.own_threads(), "havia threads do serviço antes do encerramento")
        self.assertTrue(self.daemon.service.flush())
        client.settle()   # o que foi dito antes do encerramento já chegou ao cliente
        mark = len(client.events)
        self.close_listener()
        self.assertTrue(wait_for(lambda: not self.own_threads(), 5), [thread.name for thread in self.own_threads()])
        time.sleep(.2)
        self.assertEqual(client.events[mark:], [], "o serviço encerrado não fala com as conexões")

    def test_two_subscribers_keep_their_subscriptions_and_get_one_state_event(self):
        first, second = self.subscriber(), self.subscriber()
        old = self.daemon.service
        response = self.call("config.set", key="DRY_RUN", value=False)
        self.assertTrue(response["ok"], response)
        self.assertIsNot(self.daemon.service, old)
        self.assertTrue(self.call("shortcut.test", arm=True)["ok"])   # marcador: evento seguinte conhecido
        self.assertEqual(self.call("toggle")["data"], {"shortcut_test": True})
        for client in (first, second):
            self.assertTrue(wait_for(lambda: client.kind("shortcut_test")), client.events)
            after = [e for e in client.events[1:] if e["event"] != "log"]
            self.assertEqual(after, [{"event": "state", "state": "idle", "site": "", "question": 0, "max": 0,
                                      "error": "", "dry_run": False}, {"event": "shortcut_test", "ok": True}])
        self.assertIs(self.state()["dry_run"], False)
        self.assertIs(self.stored(), False)
        self.assertEqual(len(self.created), 2)


class RunningIpcTests(RealIpcCase):
    """Laço preso na descoberta (endpoint e abas injetados), para pedir a troca com ele ativo."""

    def setUp(self):
        self.release, self.entered = threading.Event(), threading.Event()
        self.addCleanup(self.release.set)

        def tabs(_port):
            self.entered.set()
            self.release.wait(10)
            return []
        self.service_options = {"endpoint": lambda: 9, "tabs": tabs}
        super().setUp()

    def test_mode_change_is_refused_while_the_loop_runs_or_is_paused(self):
        client = self.subscriber()
        self.assertEqual(self.call("toggle")["data"]["state"], "running")
        response = self.call("config.set", key="DRY_RUN", value=False)
        self.assertEqual((response["ok"], response["code"]), (False, "bad_state"))
        self.assertEqual(response["error"], "Pare o laço (stop) antes de mudar o modo simulação.")
        self.assertEqual(self.call("toggle")["data"]["state"], "paused")
        self.assertEqual(self.call("config.set", key="DRY_RUN", value=False)["code"], "bad_state")
        self.assertEqual((self.state()["dry_run"], self.stored(), len(self.created)), (True, None, 1))
        self.assertEqual(self.call("stop")["data"]["state"], "idle")
        self.release.set()
        self.assertTrue(self.call("config.set", key="DRY_RUN", value=False)["ok"], "parado, a troca é aceita")
        self.assertTrue(wait_for(lambda: client.kind("state")[-1]["dry_run"] is False), client.events)
        self.assertTrue(all(e["dry_run"] is True for e in client.kind("state")[:-1]))

    def test_swap_after_start_and_stop_leaves_no_thread_of_the_old_service(self):
        client = self.subscriber()
        old = self.daemon.service
        self.assertEqual(self.call("toggle")["data"]["state"], "running")
        self.assertTrue(self.entered.wait(10), "laço iniciado e preso na descoberta")
        self.assertTrue(self.own_threads())
        self.assertEqual(self.call("stop")["data"]["state"], "idle")
        self.release.set()   # a descoberta presa volta; o laço parado encerra sem agir
        self.assertTrue(wait_for(lambda: any(e["msg"].startswith("erro:") for e in client.kind("log"))), client.events)
        self.assertEqual(self.state()["state"], "idle", "laço parado não muda mais o estado")
        self.assert_swap_ends_the_old_service(client, old)
        self.assertEqual(self.asker.calls, 0)

    def test_shutdown_with_the_loop_running_leaves_no_service_thread(self):
        self.assertEqual(self.call("toggle")["data"]["state"], "running")
        self.assertTrue(self.entered.wait(10), "laço iniciado e preso na descoberta")
        self.assertTrue(self.own_threads())
        self.release.set()
        self.close_listener()
        self.assertTrue(wait_for(lambda: not self.own_threads(), 5), [thread.name for thread in self.own_threads()])
        self.assertEqual(self.asker.calls, 0)


def free_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


class LiveTests(RealIpcCase):
    """Chromium do Playwright com CDP local; o Service conecta nele pelo endpoint injetado."""

    @classmethod
    def setUpClass(cls):
        cls.profile = tempfile.TemporaryDirectory(prefix="dr-perfil-")
        cls.port = free_port()
        try:
            from playwright.sync_api import sync_playwright
            cls.playwright = sync_playwright().start()
        except Exception as exc:  # noqa: BLE001 - sem Playwright utilizável o bloco é pulado
            cls.profile.cleanup()
            raise unittest.SkipTest(f"Playwright indisponível: {type(exc).__name__}") from None
        try:
            root = hasattr(os, "geteuid") and os.geteuid() == 0
            cls.context = cls.playwright.chromium.launch_persistent_context(
                cls.profile.name, headless=True,
                args=[f"--remote-debugging-port={cls.port}", "--remote-debugging-address=127.0.0.1"] + (["--no-sandbox"] if root else []))
        except Exception as exc:  # noqa: BLE001
            cls.playwright.stop()
            cls.profile.cleanup()
            raise unittest.SkipTest(f"Chromium do Playwright indisponível: {type(exc).__name__}") from None
        cls.page = cls.context.pages[0] if cls.context.pages else cls.context.new_page()
        cls.http = ThreadingHTTPServer(("127.0.0.1", 0), partial(QuietHandler, directory=str(COMPAT)))
        threading.Thread(target=cls.http.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown()
        cls.http.server_close()
        cls.context.close()
        cls.playwright.stop()
        cls.profile.cleanup()

    def setUp(self):
        self.service_options = {"endpoint": lambda: self.port}
        super().setUp()

    def open(self, name):
        self.page.goto(f"http://127.0.0.1:{self.http.server_address[1]}/{name}")
        return self.page.content()

    def checked(self):
        return self.page.evaluate("[...document.querySelectorAll('input:checked')].map(e => e.value)")

    def wait_state(self, client, value, after=0):
        ok = wait_for(lambda: any(e["state"] == value for e in client.kind("state")[after:]), 60)
        self.assertTrue(ok, client.events)

    def test_toggle_in_dry_run_does_not_change_the_dom(self):
        before = self.open("quiz_mcq_single.html")
        client = self.subscriber()
        self.assertEqual(self.call("toggle")["data"]["state"], "running")
        self.assertTrue(wait_for(lambda: client.kind("verdict"), 60), client.events)
        self.assertTrue(wait_for(lambda: any("(dry-run) faria:" in e["msg"] for e in client.kind("log"))), client.events)
        time.sleep(.5)   # o laço fica à espera do humano: não responde de novo nem navega
        self.assertEqual(self.call("stop")["data"]["state"], "idle")
        self.assertEqual(self.asker.calls, 1)
        self.assertEqual(self.page.content(), before)
        self.assertEqual(self.checked(), [])
        self.assertTrue(self.page.url.endswith("/quiz_mcq_single.html"))
        self.assertTrue(all(e["dry_run"] is True for e in client.kind("state")))
        self.assertEqual(client.kind("question")[0]["kind"], "SINGLE")
        self.assertEqual(sum("(dry-run) faria:" in e["msg"] for e in client.kind("log")), 1)

    def test_real_mode_only_when_asked_and_state_shows_it(self):
        before = self.open("quiz_mcq_single.html")
        client = self.subscriber()
        self.assertTrue(self.call("config.set", key="MAX_QUESTIONS", value=3)["ok"])
        self.assertTrue(self.call("ask")["ok"])
        self.wait_state(client, "idle", after=1)
        self.assertEqual((self.checked(), self.page.content() == before), ([], True))
        self.assertEqual(len(self.created), 1, "nenhuma troca de modo sem pedido")
        mark = len(client.kind("state"))
        self.assertTrue(self.call("config.set", key="DRY_RUN", value=False)["ok"])
        self.assertTrue(wait_for(lambda: len(client.kind("state")) > mark))
        self.assertEqual((client.kind("state")[mark]["state"], client.kind("state")[mark]["dry_run"]), ("idle", False))
        self.assertIs(self.state()["dry_run"], False)
        self.assertEqual(self.checked(), [], "mudar o modo não age na página")
        mark = len(client.kind("state"))
        self.assertTrue(self.call("ask")["ok"])
        self.wait_state(client, "idle", after=mark)
        self.assertEqual(self.checked(), ["0"], "modo real marca só a alternativa, pela guarda")
        self.assertTrue(self.page.url.endswith("/quiz_mcq_single.html"), "não navega nem envia")
        self.assertTrue(all(e["dry_run"] is False for e in client.kind("state")[mark:]))
        self.assertEqual(self.asker.calls, 2)
        self.assertTrue(self.call("config.set", key="DRY_RUN", value=True)["ok"])
        self.assertIs(self.state()["dry_run"], True)
        self.assertIs(self.stored(), True)

    def test_unsupported_kind_takes_no_action(self):
        before = self.open("essay.html")
        client = self.subscriber()
        self.assertTrue(self.call("ask")["ok"])
        self.assertTrue(wait_for(lambda: any(e["state"] in ("idle", "error") for e in client.kind("state")[1:]), 60), client.events)
        self.assertEqual(self.asker.calls, 0)
        self.assertEqual(self.page.content(), before)
        self.assertEqual(client.kind("verdict"), [])
        self.assertFalse(any("faria:" in e["msg"] for e in client.kind("log")))
        final = self.state()
        self.assertEqual(final["state"], "error")
        self.assertIn("Nenhuma questão", final["error"])

    def test_no_site_arrives_as_state_error(self):
        self.page.goto((COMPAT / "quiz_mcq_single.html").as_uri())   # aba file:// não é página compatível
        client = self.subscriber()
        response = self.call("toggle")
        self.assertEqual((response["ok"], response["data"]["state"]), (True, "running"))
        self.wait_state(client, "error", after=1)
        error = [e for e in client.kind("state") if e["state"] == "error"][-1]
        self.assertIn("Nenhuma aba com uma página compatível", error["error"])
        self.assertEqual((self.asker.calls, self.checked()), (0, []))
        self.assertEqual(self.call("stop")["data"]["state"], "idle")


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


if __name__ == "__main__":
    unittest.main()
