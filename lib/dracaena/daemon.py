"""Servidor IPC v0 local e simulador determinístico do núcleo."""
import logging
import threading
import time
from urllib.parse import urlsplit
from .platform.ipc import Listener
from .platform.instance import InstanceLock

COMMANDS = ("hello", "subscribe", "status", "toggle", "stop", "ask", "once", "config.get",
            "config.set", "config.schema", "sites.list", "sites.save", "probe.start", "probe.cancel",
            "doctor", "shortcut.test")
SHORTCUT_TEST_SECONDS = 30
# Sites do simulador: "existente" provoca o código exists; "invalido" aparece com valid=false.
SIMULATED_SITES = (
    {"name": "Prática simulada", "slug": "existente", "valid": True},
    {"name": "invalido", "slug": "invalido", "valid": False},
)


class ProbeError(Exception):
    """Falha de probe com código IPC (no_browser|no_site|bad_request|cancelled|internal)."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


ServiceUnavailable = ProbeError  # nome antigo, mantido por compatibilidade


def configured_dry_run():
    """DRY_RUN da configuração; na dúvida, modo seguro (simulação)."""
    from .platform import config
    try:
        return bool(config.load().get("DRY_RUN", True))
    except (OSError, ValueError):
        return True


class Simulator:
    def __init__(self, dry_run=None):
        self.callbacks = []
        self.state = "idle"
        self.question = 0
        self.maximum = 80
        self.dry_run = configured_dry_run() if dry_run is None else bool(dry_run)

    def set_dry_run(self, value):
        self.dry_run = bool(value)
        self.emit()

    def subscribe(self, callback):
        self.callbacks.append(callback)

        def unsubscribe():
            if callback in self.callbacks:
                self.callbacks.remove(callback)
        return unsubscribe

    def emit(self):
        for callback in list(self.callbacks):
            callback(self.snapshot())

    def snapshot(self):
        return dict(event="state", state=self.state, site="Prática simulada", question=self.question,
                    max=self.maximum, error="", dry_run=self.dry_run)

    def handle(self, cmd, args):
        if cmd == "status":
            return self.snapshot()
        if cmd == "toggle":
            self.state = "paused" if self.state == "running" else "running"
        elif cmd == "stop":
            self.state = "idle"
        elif cmd in ("ask", "once"):
            self.question += 1
            self.emit()
            return {"simulated": True, "answer": "Resposta simulada", "question": self.question}
        self.emit()
        return self.snapshot()


EVENTS = ("state", "log", "question", "verdict", "probe", "shortcut_test")
LOG = logging.getLogger("dracaena")


DRAFT_TOML = """# Rascunho gerado pela sondagem simulada.
[site]
name = "Prática simulada"
version = 0

[selectors]
question = "[data-question]"
option = "[data-option]"
"""


class ProbeRunner:
    """Sondagem somente leitura (simulada): emite progresso e permite cancelar.

    Fases: connect, scan, match, draft e, ao fim, done. `done` conta as etapas já
    concluídas quando a fase começa; em erro/cancelamento a fase final é error/cancelled.
    """

    PHASES = ("connect", "scan", "match", "draft")
    FAILURES = {
        "no_browser": ("connect", "Nenhum navegador com a prática aberta foi encontrado."),
        "no_site": ("scan", "Nenhum site compatível foi reconhecido nesta página."),
        "bad_request": ("connect", "O pedido de sondagem é inválido."),
        "internal": ("match", "Falha interna durante a sondagem."),
    }

    def __init__(self, emit, step=0.2):
        self.emit, self.step = emit, step
        self.lock = threading.Lock()
        self.cancel_event = None  # definido enquanto uma sondagem está ativa

    @staticmethod
    def validate(args):
        url, failure = args.get("url"), args.get("simulate_error")
        if url is not None:
            parsed = urlsplit(url) if isinstance(url, str) and len(url) <= 2048 else None
            if not parsed or parsed.scheme not in ("http", "https") or not parsed.netloc:
                raise ValueError("URL inválida: use um endereço http ou https de até 2048 caracteres")
        if failure is not None and failure not in (*ProbeRunner.FAILURES, "cancelled"):
            raise ValueError("simulate_error inválido: use no_browser, no_site, bad_request, internal ou cancelled")
        return failure

    def _event(self, phase, done):
        self.emit({"event": "probe", "phase": phase, "done": done, "total": len(self.PHASES)})

    def start(self, args):
        failure = self.validate(args)
        with self.lock:
            if self.cancel_event is not None:
                raise ProbeError("bad_request", "Já existe uma sondagem em andamento")
            cancel = self.cancel_event = threading.Event()
        completed = 0
        try:
            for index, phase in enumerate(self.PHASES):
                completed = index
                self._event(phase, completed)
                if failure == "cancelled" and phase == "scan":
                    cancel.set()
                if cancel.wait(self.step):
                    break
                if failure in self.FAILURES and self.FAILURES[failure][0] == phase:
                    self._event("error", completed)
                    raise ProbeError(failure, self.FAILURES[failure][1])
            else:
                with self.lock:  # decide sob o lock: cancel() só vale enquanto ativa
                    if not cancel.is_set():
                        self.cancel_event = None
                        completed = len(self.PHASES)
                if completed == len(self.PHASES):
                    self._event("done", completed)
                    return {"matches": {"[data-question]": 1, "[data-option]": 4}, "questions": 1,
                            "draft_toml": DRAFT_TOML}
            self._event("cancelled", completed)
            raise ProbeError("cancelled", "Sondagem cancelada")
        finally:
            with self.lock:
                self.cancel_event = None

    def cancel(self):
        with self.lock:
            if self.cancel_event is None or self.cancel_event.is_set():
                return False
            self.cancel_event.set()
            return True


class Subscription:
    """Assinante de eventos. Eventos chegam de qualquer thread; a ordem é preservada.

    Até `release`, os eventos ficam retidos para que a resposta de `subscribe` e o
    estado inicial sempre precedam os eventos seguintes.
    """

    def __init__(self, conn, events):
        self.conn, self.events = conn, set(events)
        self.backlog = []
        self.lock = threading.Lock()

    def deliver(self, event):
        if event.get("event") not in self.events:
            return
        with self.lock:
            if self.backlog is not None:
                self.backlog.append(event)
                return
            self.conn.send(event)

    def mark(self):
        with self.lock:
            return len(self.backlog or ())

    def release(self, snapshot, mark):
        """Envia o estado inicial e libera os eventos retidos.

        Estados retidos antes do instantâneo (índice < mark) são mais antigos que ele.
        """
        with self.lock:
            if snapshot and "state" in self.events:
                self.conn.send({**snapshot, "event": "state"})
            pending, self.backlog = self.backlog, None
            for index, event in enumerate(pending):
                if index < mark and event.get("event") == "state":
                    continue
                self.conn.send(event)


class Daemon:
    def __init__(self, service, simulate=False, clock=time.monotonic, probe_step=0.2):
        self.simulate = simulate
        self.service = service
        self.clock = clock
        self.armed_until = None
        self.shortcut_lock = threading.Lock()
        self.probe = ProbeRunner(self.emit, probe_step)
        self.clients = {}
        self.lock = threading.RLock()
        self.client_lock = threading.RLock()
        self.unsubscribe = service.subscribe(self.emit) if hasattr(service, "subscribe") else None

    def emit(self, event):
        with self.client_lock:
            subscriptions = list(self.clients.items())
        for conn, subscription in subscriptions:
            try:
                subscription.deliver(event)
            except OSError:
                with self.client_lock:
                    self.clients.pop(conn, None)
            except Exception:
                LOG.exception("Falha ao entregar evento IPC")

    def platform_command(self, cmd, args):
        from .platform import config
        if cmd == "config.schema":
            return config.schema()
        if cmd == "config.get":
            return config.load()
        if cmd == "config.set":
            values = config.set_value(args.get("key"), args.get("value"))
            if args.get("key") == "DRY_RUN" and hasattr(self.service, "set_dry_run"):
                self.service.set_dry_run(values["DRY_RUN"])  # o serviço emite o novo state
            return values
        if cmd == "doctor":
            from .platform.doctor import run
            return run()
        if cmd == "sites.list":
            if self.simulate:
                return [dict(SIMULATED_SITES[0]), dict(SIMULATED_SITES[1])]
            from .platform.sites import list_sites
            return list_sites()
        if cmd == "sites.save":
            from .platform.sites import save
            # Simulado: valida e responde o caminho, sem gravar nada.
            return save(args.get("name"), args.get("toml"), args.get("overwrite", False), write=not self.simulate,
                        existing=[site["slug"] for site in SIMULATED_SITES])
        raise ValueError("Comando de plataforma desconhecido")

    def dispatch(self, request, conn):
        if not isinstance(request, dict):
            return {"ok": False, "error": "Esperado um objeto JSON", "code": "bad_request"}
        ident = request.get("id")
        cmd, args = request.get("cmd"), request.get("args", {})
        if request.get("v", 0) != 0 or not isinstance(cmd, str) or not isinstance(args, dict):
            return dict(id=ident, ok=False, error="Pedido IPC v0 inválido", code="bad_request")
        if cmd not in COMMANDS:
            return dict(id=ident, ok=False, error="Comando desconhecido", code="unknown_cmd")
        try:
            if cmd == "hello":
                from .platform.launcher import toggle_command
                data = {"v": 0, "app_version": "0.1.0", "caps": list(COMMANDS), "toggle_cmd": toggle_command()}
            elif cmd == "subscribe":
                events = args.get("events", ["state"])
                if not isinstance(events, list) or any(e not in EVENTS for e in events):
                    raise ValueError("Assinatura de eventos inválida")
                with self.client_lock:
                    self.clients[conn] = Subscription(conn, events)
                data = {"events": events}
            elif cmd == "probe.start":
                data = self.start_probe(args)
            elif cmd == "probe.cancel":
                data = {"cancelled": self.probe.cancel()}
            elif cmd == "shortcut.test":
                data = self.shortcut_test(args)
            elif cmd == "toggle" and self.consume_shortcut_test():
                self.emit({"event": "shortcut_test", "ok": True})
                data = {"shortcut_test": True}
            else:
                with self.lock:
                    if cmd in ("status", "toggle", "stop", "ask", "once"):
                        data = self.service.handle(cmd, args)
                    else:
                        data = self.platform_command(cmd, args)
            return dict(id=ident, ok=True, data=data)
        except ValueError as exc:
            return dict(id=ident, ok=False, error=str(exc), code="bad_request")
        except ProbeError as exc:
            return dict(id=ident, ok=False, error=str(exc), code=exc.code)
        except Exception as exc:
            code = getattr(exc, "code", "internal")
            allowed = ("bad_request", "unknown_cmd", "bad_state", "no_browser", "no_site", "refused", "cancelled", "exists")
            if code not in allowed:
                LOG.exception("Falha interna ao executar %s", cmd)
            return dict(id=ident, ok=False, error=str(exc) if code in allowed else "Falha ao executar comando",
                        code=code if code in allowed else "internal")

    def start_probe(self, args):
        if not self.simulate:
            raise ProbeError("no_site", "A sondagem aguarda a integração com o adaptador")
        return self.probe.start(args)

    def shortcut_test(self, args):
        arm = args.get("arm")
        if not isinstance(arm, bool):
            raise ValueError("'arm' deve ser verdadeiro ou falso")
        with self.shortcut_lock:
            self.armed_until = self.clock() + SHORTCUT_TEST_SECONDS if arm else None
        return {"armed": arm}

    def consume_shortcut_test(self):
        """True se o teste de atalho estava armado e válido; desarma em qualquer caso."""
        with self.shortcut_lock:
            until, self.armed_until = self.armed_until, None
        return until is not None and self.clock() < until

    def initial_state(self, subscription):
        """Libera o assinante com o estado atual, obtido pela API pública do serviço."""
        mark = subscription.mark()
        try:
            with self.lock:
                snapshot = self.service.handle("status", {})
        except Exception:
            LOG.exception("Falha ao obter o estado inicial")
            snapshot = None
        subscription.release(snapshot, mark)

    def client(self, conn):
        try:
            while True:
                try:
                    request = conn.receive()
                except (ValueError, UnicodeError):
                    conn.send(dict(ok=False, error="Mensagem JSON inválida", code="bad_request"))
                    break
                if request is None:
                    break
                response = self.dispatch(request, conn)
                conn.send(response)
                if response["ok"] and isinstance(request, dict) and request.get("cmd") == "subscribe":
                    with self.client_lock:
                        subscription = self.clients.get(conn)
                    if subscription:
                        self.initial_state(subscription)
        except OSError:
            pass
        finally:
            with self.client_lock:
                self.clients.pop(conn, None)
            conn.close()

    def run(self):
        with InstanceLock():
            self.serve(Listener())

    def serve(self, listener):
        """Aceita conexões até o listener ser fechado; sempre o fecha ao sair."""
        failures = 0
        try:
            while not listener.closed:
                try:
                    conn = listener.accept()
                except OSError:
                    if listener.closed:
                        break
                    failures += 1
                    if failures >= 5:
                        raise
                    time.sleep(.2)
                    continue
                failures = 0
                threading.Thread(target=self.client, args=(conn,), daemon=True).start()
        finally:
            listener.close()
            if self.unsubscribe:
                self.unsubscribe()
