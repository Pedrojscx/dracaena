"""Service do núcleo: a API que o daemon consome (status, toggle, stop, ask, once).

O Service NÃO navega: marca só a questão atual, espera o humano avançar e para
em tela de resumo/revisão/resultado, como o runner. Toda ação passa por
``Guard.perform``; dry-run é o padrão.

O laço roda numa thread própria (o Playwright
síncrono fica preso à thread que o criou, então toda chamada ao navegador
acontece lá). A descoberta CDP também roda nessa thread; falhas de descoberta
são comunicadas pelo evento state com estado error.
``handle`` pode esperar uma ação em curso sob o lock; veja seu contrato abaixo.

Os eventos saem numa fila única, entregue por uma thread própria: a ordem é a
das mudanças de estado e um callback lento ou que levanta não trava o laço.
"""

from __future__ import annotations

import json
import logging
import queue
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.request import urlopen

from ..adapters.base import Registry
from ..guard import Guard, Refused, ResultScreen
from ..platform.browser import BrowserError, BrowserSandboxUnavailable
from ..platform.paths import data_dir
from . import claude, contract
from .errors import AdapterError, NotFound, ServiceError
from .model import UNKNOWN, Question
from .runner import _answers, default_record_path, record_review

__all__ = ["Service", "ServiceError", "COMMANDS", "SUPPORTED_KINDS"]

LOG = logging.getLogger("dracaena")
COMMANDS = ("status", "toggle", "stop", "ask", "once")
SUPPORTED_KINDS = ("SINGLE", "MULTI", "DROPDOWN")
ONCE_WAIT_SECONDS = 180.0   # igual ao --espera padrão do runner
POLL_SECONDS = 0.2
_END_EVENTS = object()


@dataclass(frozen=True)
class Step:
    """Resultado de uma questão.

    status: answered | skipped (tipo não suportado, nada feito) | end | unsupported (sem questão)
            | stalled | interrupted | invalid | refused | failed
    """
    status: str
    question: Question | None = None
    reason: str = ""


BROWSER_HINT = ("Se o navegador padrão não for Chromium, rode 'dracaena install-browser' para baixar o Chromium "
                "reserva ou informe o caminho de um Chromium em BROWSER_BIN.")


def default_endpoint() -> int:
    """Porta CDP do perfil dedicado; sem ele aberto, ``no_browser``."""
    from ..platform.browser import read_port
    try:
        return read_port(data_dir() / "browser-profile")
    except (OSError, BrowserError) as exc:
        raise ServiceError("no_browser", f"Nenhum navegador dedicado aberto; abra o navegador do Dracaena. {BROWSER_HINT}") from exc


def default_tabs(port: int) -> list[dict]:
    """Abas do navegador pelo endpoint HTTP local do CDP (somente leitura)."""
    try:
        with urlopen(f"http://127.0.0.1:{port}/json/list", timeout=1.0) as response:
            rows = json.load(response)
    except (OSError, ValueError) as exc:
        raise ServiceError("no_browser", "O navegador dedicado não respondeu.") from exc
    return [row for row in rows if isinstance(row, dict) and row.get("type") == "page"]


def default_playwright():
    from playwright.sync_api import sync_playwright
    return sync_playwright()


def _default_config() -> dict:
    from ..platform import config
    return config.load()


def _web(url: str) -> bool:
    return str(url).startswith(("http://", "https://"))


class Service:
    """Estados: idle | running | paused | error. Ver o módulo para a semântica."""

    def __init__(self, *, dry_run: bool = True, registry: Registry | None = None,
                 config: Callable[[], dict] = _default_config, max_questions: int | None = None,
                 endpoint: Callable[[], int] = default_endpoint, tabs: Callable[[int], list] = default_tabs,
                 playwright_factory: Callable = default_playwright, ask: Callable = claude.ask,
                 record_path: Path | None = None, sleep: Callable[[float], None] = time.sleep,
                 monotonic: Callable[[], float] = time.monotonic, once_wait: float = ONCE_WAIT_SECONDS):
        if registry is None:
            from ..adapters.heuristic import HeuristicAdapter
            registry = Registry([HeuristicAdapter()])
        self.dry_run = bool(dry_run)
        self.registry = registry
        self._config, self._max_arg = config, max_questions
        self._endpoint, self._tabs, self._pw = endpoint, tabs, playwright_factory
        self._ask, self._record = ask, record_path
        self._sleep, self._mono, self._once_wait = sleep, monotonic, once_wait
        self._lock = threading.RLock()
        self._cond = threading.Condition(self._lock)
        self.state, self.site, self.error, self.condition = "idle", "", "", ""
        self.count, self.maximum = 0, int(max_questions or 0)
        self._closed = False
        self._gen = 0              # geração do laço atual; laço de geração antiga não muda nada
        self._oneshot = None       # "ask" | "once" pedido com o laço pausado
        self._thread: threading.Thread | None = None
        self._subs: list[Callable[[dict], None]] = []
        self._events: queue.Queue = queue.Queue()
        self._dispatcher: threading.Thread | None = None

    def close(self, timeout: float = 5.0) -> None:
        """Para o trabalho e drena eventos; joins compartilham o prazo informado.

        O prazo começa na entrada, mas só limita os joins: adquirir o lock
        não tem timeout. Se Guard.perform estiver em curso sob esse lock,
        close espera seu término antes de marcar o serviço fechado. A guarda
        usa frame.evaluate na checagem e element.evaluate na ação, sem timeout
        próprio ou cancelamento em guard.py. Uma página travada pode portanto
        bloquear close por tempo indeterminado, inclusive além de timeout.
        A ação já iniciada não é interrompida; após marcar o fechamento,
        nenhuma nova ação começa. Os joins usam apenas o prazo restante.
        Outra dependência bloqueada pode sobreviver ao prazo de join; uma
        nova chamada pode esperar seu encerramento.
        Em callback, a entrega termina depois que o próprio callback retorna.
        """
        deadline = time.monotonic() + max(0.0, timeout)
        with self._lock:
            if not self._closed:
                self._gen += 1
                self._oneshot = None
                self._set(state="idle", error="", condition="")
                self._closed = True
                self._events.put(_END_EVENTS)
            worker, dispatcher = self._thread, self._dispatcher
        current = threading.current_thread()
        for thread in (worker, dispatcher):
            if thread is not None and thread is not current:
                thread.join(max(0.0, deadline - time.monotonic()))

    # ---- eventos
    def subscribe(self, cb: Callable[[dict], None]) -> Callable[[], None]:
        with self._lock:
            if self._closed:
                raise ServiceError("bad_state", "O serviço já foi fechado.")
            self._subs.append(cb)

        def unsubscribe():
            with self._lock:
                if cb in self._subs:
                    self._subs.remove(cb)
        return unsubscribe

    def _emit(self, event: dict) -> None:
        with self._lock:
            if self._closed:
                return
            self._events.put(event)
            if self._dispatcher is None:
                self._dispatcher = threading.Thread(target=self._deliver, name="dracaena-events", daemon=True)
                self._dispatcher.start()

    def _deliver(self) -> None:
        while True:
            event = self._events.get()
            if event is _END_EVENTS:
                with self._lock:
                    self._subs.clear()
                return
            if isinstance(event, threading.Event):
                event.set()
                continue
            with self._lock:
                subs = list(self._subs)
            for cb in subs:
                try:
                    cb(dict(event))
                except Exception:  # noqa: BLE001 - assinante com defeito não derruba o laço
                    LOG.exception("Falha num assinante de eventos")

    def flush(self, timeout: float = 5.0) -> bool:
        """Espera a entrega dos eventos já emitidos (útil em testes)."""
        done = threading.Event()
        with self._lock:
            if threading.current_thread() is self._dispatcher:
                return False
            closed, dispatcher = self._closed, self._dispatcher
            if not closed:
                self._emit(done)
        if closed:
            if dispatcher is not None:
                dispatcher.join(timeout)
            return dispatcher is None or not dispatcher.is_alive()
        return done.wait(timeout)

    def _log(self, msg: str, level: str = "info") -> None:
        LOG.log(logging.WARNING if level == "warning" else logging.ERROR if level == "error" else logging.INFO, msg)
        self._emit({"event": "log", "level": level, "msg": msg})

    # ---- estado
    def snapshot(self) -> dict:
        with self._lock:
            result = {"state": self.state, "site": self.site, "question": self.count, "max": self.maximum,
                      "error": self.error, "dry_run": self.dry_run}
            if self.condition:
                result["condition"] = self.condition
            return result

    def _set(self, gen: int | None = None, **changes) -> bool:
        """Muda o estado e emite ``state``; com ``gen``, só se o laço ainda for o atual."""
        with self._lock:
            if self._closed or (gen is not None and gen != self._gen):
                return False
            for key, val in changes.items():
                setattr(self, key, val)
            self._emit({"event": "state", **self.snapshot()})
            self._cond.notify_all()
            return True

    # ---- comandos
    def handle(self, cmd: str, args: dict | None = None) -> dict:
        """Despacha comandos; descoberta e laço executam em thread própria.

        Não há limite de latência ao adquirir o lock: status e stop também
        esperam Guard.perform em curso. Sua checagem e ação usam evaluate,
        sem timeout próprio ou cancelamento em guard.py. Uma página travada
        pode bloquear estes comandos por tempo indeterminado. stop só muda
        a geração após obter o lock; não cancela a ação já iniciada.
        """
        if cmd not in COMMANDS:
            raise ServiceError("unknown_cmd", f"Comando desconhecido: {cmd}")
        args = {} if args is None else args
        if not isinstance(args, dict):
            raise ServiceError("bad_request", "args deve ser um objeto")
        contains = args.get("url_contains", "")
        if not isinstance(contains, str):
            raise ServiceError("bad_request", "url_contains deve ser texto")
        with self._lock:
            state = self.state
            if cmd == "status":
                return self.snapshot()
            if self._closed:
                raise ServiceError("bad_state", "O serviço já foi fechado.")
            if cmd == "stop":
                if state == "idle":
                    raise ServiceError("bad_state", "Nada em execução para parar")
                self._gen += 1        # o laço antigo encerra sem agir mais
                self._oneshot = None
                self._set(state="idle", error="", condition="")
                self._log("parada: pedida pelo usuário")
                return self.snapshot()
            if cmd == "toggle" and state == "running":
                self._set(state="paused")
                self._log("pausa: depois da questão atual")
                return self.snapshot()
            if cmd == "toggle" and state == "paused":
                self._set(state="running")
                return self.snapshot()
            if cmd in ("ask", "once") and state == "running":
                raise ServiceError("bad_state", "Já em execução; pause ou pare antes")
            if cmd in ("ask", "once") and state == "paused":
                self._oneshot = cmd
                self._set(state="running")
                return self.snapshot()
            # idle ou error: começa um laço novo
            self._gen += 1
            gen, previous = self._gen, self._thread
            self._oneshot = None
            maximum = 1 if cmd in ("ask", "once") else int(self._max_arg or 80)
            mode = "loop" if cmd == "toggle" else cmd
            self._thread = threading.Thread(target=self._work, args=(gen, mode, contains, previous),
                                            name="dracaena-loop", daemon=True)
            self._set(state="running", error="", condition="", count=0, maximum=maximum, site="")
            self._thread.start()
            return self.snapshot()

    def _load_config(self) -> dict:
        try:
            cfg = self._config()
        except (OSError, ValueError) as exc:
            raise ServiceError("bad_request", f"Configuração inválida: {exc}") from exc
        return dict(cfg or {})

    def _preflight(self, port: int, contains: str) -> str:
        pages = [tab for tab in self._tabs(port) if _web(tab.get("url", "")) and contains in tab.get("url", "")]
        if not pages:
            raise ServiceError("no_site", "Nenhuma aba com uma página compatível foi encontrada.")
        names = []
        for tab in pages:
            try:
                names.append(self.registry.pick(tab.get("url", ""), tab.get("title", "")).name)
            except NotFound:
                continue
        if not names:
            raise ServiceError("no_site", "Nenhum adaptador serve para as abas abertas.")
        return names[0] if len(set(names)) == 1 else ""

    # ---- laço (thread própria)
    def _alive(self, gen: int) -> bool:
        with self._lock:
            return not self._closed and gen == self._gen

    def _pausing(self, gen: int, shot: str | None) -> bool:
        """Interromper a espera: laço parado, pausa pedida ou um ask/once novo com o laço pausado."""
        with self._lock:
            return gen != self._gen or self._oneshot != shot or (self.state == "paused" and shot is None)

    def _fail(self, gen: int, msg: str, condition: str = "") -> None:
        self._log(f"erro: {msg}", "error")
        self._set(gen, state="error", error=msg, condition=condition)

    def _work(self, gen, mode, contains, previous) -> None:
        if previous is not None:
            previous.join()   # um laço por vez no navegador
        try:
            if not self._alive(gen):
                return
            cfg = self._load_config()
            port = self._endpoint()
            self._preflight(port, contains)
            if not self._alive(gen):
                return
            if mode == "loop":
                with self._lock:
                    if gen != self._gen:
                        return
                    self.maximum = int(self._max_arg or cfg.get("MAX_QUESTIONS", 80))
            with self._pw() as pw:
                browser = pw.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
                try:
                    page, adapter = self._choose(browser, contains)
                    self._set(gen, site=adapter.name)
                    self._loop(gen, mode, page, adapter, cfg)
                finally:
                    browser.close()
        except BrowserSandboxUnavailable as exc:
            self._fail(gen, str(exc), exc.condition)
        except BrowserError as exc:
            self._fail(gen, f"{exc} {BROWSER_HINT}")
        except ServiceError as exc:
            self._fail(gen, exc.msg)
        except AdapterError as exc:
            self._fail(gen, f"página indisponível ({exc})")
        except Exception as exc:  # noqa: BLE001 - qualquer falha vira estado error, nunca thread morta calada
            LOG.exception("Falha interna no laço")
            self._fail(gen, f"falha interna ({type(exc).__name__})")

    def _choose(self, browser, contains: str):
        found, ended = [], []
        for page in (p for ctx in browser.contexts for p in ctx.pages):
            if not _web(page.url) or contains not in page.url:
                continue
            try:
                adapter = self.registry.pick(page.url, page.title())
            except NotFound:
                continue
            if adapter.locate(page.main_frame):
                found.append((page, adapter))
            elif Guard(self._log, dry_run=True).result_visible(page.main_frame):
                ended.append((page, adapter))   # o passo relata o fim sem agir
        if not found and len(ended) == 1:
            found = ended
        if len(found) > 1:
            visible = [pair for pair in found if pair[0].evaluate("document.visibilityState") == "visible"]
            found = visible if len(visible) == 1 else found
        if not found:
            raise ServiceError("no_site", "Nenhuma questão visível nas abas abertas.")
        if len(found) > 1:
            raise ServiceError("no_site", "Mais de uma aba com questão; deixe só uma à vista.")
        self._log(f"aba escolhida ({found[0][1].name})")
        return found[0]

    def _loop(self, gen, mode, page, adapter, cfg) -> None:
        previous_id = None
        while True:
            with self._cond:
                while gen == self._gen and self.state == "paused" and self._oneshot is None:
                    self._cond.wait()
                if gen != self._gen:
                    return
                shot = self._oneshot
            kind = shot or mode
            wait = 0.0 if kind == "ask" else self._once_wait if kind == "once" else None
            step = self._step(gen, page, adapter, cfg, None if kind == "ask" else previous_id, wait, shot)
            if step.question is not None and step.status in ("answered", "skipped"):
                previous_id = step.question.id
            if step.status == "answered":
                with self._lock:
                    count = self.count + 1
                self._set(gen, count=count)
            if step.status == "interrupted":
                continue
            if step.status in ("invalid", "refused", "failed"):
                self._fail(gen, step.reason)
                return
            if step.status in ("end", "unsupported", "stalled"):
                self._set(gen, state="idle")
                return
            if mode in ("ask", "once"):
                self._set(gen, state="idle")
                return
            if shot is not None:
                with self._lock:
                    if gen != self._gen:
                        return
                    self._oneshot = None
                self._set(gen, state="paused")
                continue
            with self._lock:
                limit = self.count >= self.maximum > 0
            if limit:
                self._log("parada: limite de questões")
                self._set(gen, state="idle")
                return

    def _step(self, gen, page, adapter, cfg, previous_id, wait, shot=None) -> Step:
        """Uma questão, com a mesma semântica do laço do runner (sem navegar)."""
        log = self._log
        extra = tuple(getattr(adapter, "extra_block", ()) or ())
        frame = page.main_frame

        def ended() -> bool:
            return Guard(log, dry_run=self.dry_run, extra_block=extra).result_visible(frame)

        if ended():
            log("parada: fim da atividade")
            return Step("end")
        hosts = adapter.locate(frame)
        if not hosts:
            log("parada: não suportado")
            return Step("unsupported")
        host = hosts[0]
        question = adapter.extract(host)
        deadline = None if wait is None else self._mono() + wait
        while previous_id is not None and question.id == previous_id:
            if self._pausing(gen, shot):
                return Step("interrupted")
            if ended():
                log("parada: fim da atividade")
                return Step("end")
            if deadline is not None and self._mono() >= deadline:
                log("parada: sem avanço (a navegação entre questões é do humano)")
                return Step("stalled")
            self._sleep(POLL_SECONDS if deadline is None else min(POLL_SECONDS, max(0, deadline - self._mono())))
            hosts = adapter.locate(frame)
            if not hosts:
                if ended():
                    log("parada: fim da atividade")
                    return Step("end")
                log("parada: não suportado")
                return Step("unsupported")
            host = hosts[0]
            question = adapter.extract(host)
        if not self._alive(gen):
            return Step("interrupted")
        self._emit({"event": "question", "id": question.id, "kind": question.kind, "stem": question.stem})
        log(f"tipo da questão: {question.kind}")
        if question.kind not in SUPPORTED_KINDS:
            log(f"não suportado: tipo {question.kind}; nenhuma ação", "warning")
            self._emit({"event": "verdict", "id": question.id, "result": UNKNOWN, "feedback": "não suportado"})
            return Step("skipped", question)
        try:
            text = claude.prompt("answer", contract.question_text(question))
            raw, _ = self._ask(cfg, text, abort=lambda: not self._alive(gen), schema=contract.schema_for(question))
            answer = contract.parse_validated(raw, question)
        except contract.ContractError as exc:
            log(f"parada: resposta inválida ({exc})", "error")
            return Step("invalid", question, f"resposta inválida ({exc})")
        except claude.Aborted:
            return Step("interrupted", question)
        except claude.ClaudeError as exc:
            log(f"parada: falha do Claude ({exc})", "error")
            return Step("failed", question, f"falha do Claude ({exc})")
        log("resposta validada")
        guard = Guard(log, dry_run=self.dry_run, extra_block=extra)
        guard.bind(frame, host, question.id)
        try:
            for target in _answers(adapter, host, answer):
                # Serializa o início da ação com close: não há intervalo entre
                # conferir a geração e entregar o alvo à única porta de ação.
                with self._lock:
                    if not self._alive(gen):
                        log("parada: interrompido antes de agir")
                        return Step("interrupted", question)
                    guard.perform(target, target.label)
        except ResultScreen:
            log("parada: fim da atividade")
            return Step("end", question)
        except Refused as exc:
            log(f"parada: guarda recusou ({exc.reason})", "warning")
            return Step("refused", question, f"guarda recusou ({exc.reason})")
        if self.dry_run:
            path = self._record or default_record_path()
            if record_review(question, answer, path):
                log(f"revisão local: {path}")
        verdict = adapter.verdict(host)
        self._emit({"event": "verdict", "id": question.id, "result": verdict.result, "feedback": verdict.feedback})
        return Step("answered", question)
