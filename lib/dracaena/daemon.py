"""Servidor IPC v0 local e simulador determinístico do núcleo."""
import logging
import threading
import time
from .platform.ipc import Listener
from .platform.instance import InstanceLock

COMMANDS = ("hello", "subscribe", "status", "toggle", "stop", "ask", "once", "config.get",
            "config.set", "config.schema", "sites.list", "probe.start", "doctor")


class ServiceUnavailable(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


class Simulator:
    def __init__(self):
        self.callbacks = []
        self.state = "idle"
        self.question = 0
        self.maximum = 80

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
                    max=self.maximum, error="")

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


EVENTS = ("state", "log", "question", "verdict")
LOG = logging.getLogger("dracaena")


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
    def __init__(self, service, simulate=False):
        self.simulate = simulate
        self.service = service
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
            return config.set_value(args.get("key"), args.get("value"))
        if cmd == "doctor":
            from .platform.doctor import run
            return run()
        if cmd == "sites.list":
            if self.simulate:
                return [{"name": "Prática simulada", "version": 0, "simulated": True}]
            import tomllib
            from .platform.paths import config_dir
            sites = []
            for path in sorted((config_dir() / "sites").glob("*.toml")):
                with path.open("rb") as stream:
                    site = tomllib.load(stream).get("site", {})
                sites.append({"name": site.get("name", path.stem), "version": site.get("version", 0)})
            return sites
        if cmd == "probe.start":
            if self.simulate:
                return {"simulated": True, "matches": 1, "questions": 1}
            raise ServiceUnavailable("no_site", "O probe aguarda a integração com o adaptador")
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
                data = {"v": 0, "app_version": "0.1.0", "caps": list(COMMANDS)}
            elif cmd == "subscribe":
                events = args.get("events", ["state"])
                if not isinstance(events, list) or any(e not in EVENTS for e in events):
                    raise ValueError("Assinatura de eventos inválida")
                with self.client_lock:
                    self.clients[conn] = Subscription(conn, events)
                data = {"events": events}
            else:
                with self.lock:
                    if cmd in ("status", "toggle", "stop", "ask", "once"):
                        data = self.service.handle(cmd, args)
                    else:
                        data = self.platform_command(cmd, args)
            return dict(id=ident, ok=True, data=data)
        except ValueError as exc:
            return dict(id=ident, ok=False, error=str(exc), code="bad_request")
        except Exception as exc:
            code = getattr(exc, "code", "internal")
            allowed = ("bad_request", "unknown_cmd", "bad_state", "no_browser", "no_site", "refused")
            if code not in allowed:
                LOG.exception("Falha interna ao executar %s", cmd)
            return dict(id=ident, ok=False, error=str(exc) if code in allowed else "Falha ao executar comando",
                        code=code if code in allowed else "internal")

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
