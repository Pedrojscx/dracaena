"""Apoio aos testes das telas B2: QApplication offscreen, cliente falso e daemon simulado real.

``DaemonTransport`` é um DUBLÊ DE TESTE que fala o formato real do daemon (ctl.sock, resposta
{id, ok, data|error, code}, evento plano). Não é cliente de produção: o de produção é o do B1.
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, QTimer, Signal  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

BACKEND = Path(os.environ.get("DRACAENA_BACKEND_WORKTREE", str(Path.home() / "wt" / "b2-backend")))


def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def pump(ms: int = 50) -> None:
    """Processa eventos Qt por ``ms`` milissegundos."""
    end = time.monotonic() + ms / 1000
    while time.monotonic() < end:
        app().processEvents()
        time.sleep(0.005)


def wait_for(cond: Callable[[], bool], timeout: float = 3.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        app().processEvents()
        if cond():
            return True
        time.sleep(0.005)
    return cond()


@dataclass
class Resp:
    id: int
    ok: bool
    data: Any = None
    error: str | None = None
    code: str | None = None


class FakeClient(QObject):
    """Cliente falso: ``answers[cmd]`` é um valor (resposta ok) ou ``Resp``/callable(args)."""
    connected = Signal()
    disconnected = Signal()
    event_received = Signal(object)

    def __init__(self, answers: dict[str, Any] | None = None) -> None:
        super().__init__()
        self.answers = answers or {}
        self.calls: list[tuple[str, dict]] = []
        self.is_connected = True

    def request(self, cmd, args=None, callback=None) -> int:
        args = args or {}
        self.calls.append((cmd, args))
        rid = len(self.calls)
        ans = self.answers.get(cmd, {})
        if callable(ans):
            ans = ans(args)
        resp = ans if isinstance(ans, Resp) else Resp(rid, True, ans)
        if callback:
            QTimer.singleShot(0, lambda: callback(resp))
        return rid


class DaemonTransport(QObject):
    """Fala com o daemon simulado real por socket Unix (síncrono; só para testes)."""
    connected = Signal()
    disconnected = Signal()
    event_received = Signal(object)

    def __init__(self, path: str) -> None:
        super().__init__()
        self._rid = 0
        self.is_connected = True
        self._req = self._open(path)
        self._ev = self._open(path)
        self._send(self._ev, "subscribe", {"events": ["state"]})
        self._ev_buf = b""
        self._ev.setblocking(False)
        self._timer = QTimer(self)
        self._timer.setInterval(10)
        self._timer.timeout.connect(self._poll)
        self._timer.start()

    @staticmethod
    def _open(path: str) -> socket.socket:
        s = socket.socket(socket.AF_UNIX)
        s.settimeout(3)
        s.connect(path)
        return s

    def _send(self, sock, cmd, args) -> int:
        self._rid += 1
        sock.sendall((json.dumps({"v": 0, "id": self._rid, "cmd": cmd, "args": args}) + "\n").encode())
        return self._rid

    @staticmethod
    def _line(sock, buf=b"") -> tuple[dict, bytes]:
        while b"\n" not in buf:
            chunk = sock.recv(65536)
            if not chunk:
                raise ConnectionError("daemon fechou a conexão")
            buf += chunk
        line, rest = buf.split(b"\n", 1)
        return json.loads(line), rest

    def request(self, cmd, args=None, callback=None) -> int:
        rid = self._send(self._req, cmd, args or {})
        raw, _ = self._line(self._req)
        resp = Resp(raw.get("id", rid), raw["ok"], raw.get("data"), raw.get("error"), raw.get("code"))
        if callback:
            QTimer.singleShot(0, lambda: callback(resp))
        return rid

    def _poll(self) -> None:
        try:
            chunk = self._ev.recv(65536)
        except BlockingIOError:
            return
        except OSError:
            return
        self._ev_buf += chunk
        while b"\n" in self._ev_buf:
            line, self._ev_buf = self._ev_buf.split(b"\n", 1)
            msg = json.loads(line)
            if "event" in msg:
                self.event_received.emit(msg)

    def close(self) -> None:
        self._timer.stop()
        for s in (self._req, self._ev):
            s.close()


def _imports_platformdirs(python: str) -> bool:
    try:
        return subprocess.run([python, "-I", "-c", "from platformdirs import PlatformDirs"], capture_output=True,
                              timeout=15).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def daemon_python(candidates: list[str] | None = None, probe=_imports_platformdirs) -> str | None:
    """Primeiro interpretador que importa ``platformdirs``: o atual, depois o python3 do sistema."""
    for c in candidates if candidates is not None else [sys.executable, shutil.which("python3") or "",
                                                         "/usr/bin/python3"]:
        if c and probe(c):
            return c
    return None


def daemon_unavailable_reason() -> str | None:
    """Motivo para PULAR (skip) os testes com o daemon real; ``None`` se dá para tentar subir."""
    if not backend_available():
        return f"worktree do Backend ausente ({BACKEND}); defina DRACAENA_BACKEND_WORKTREE"
    if daemon_python() is None:
        return "nenhum python3 com platformdirs disponível para subir o daemon simulado"
    return None


class SimulatedDaemon:
    """Sobe ``python -m dracaena.cli daemon --simulate`` do worktree do Backend, isolado em tmp.

    Levanta ``unittest.SkipTest`` (nunca erro) se o daemon não puder subir.
    """

    def __init__(self) -> None:
        import unittest
        reason = daemon_unavailable_reason()
        if reason:
            raise unittest.SkipTest(reason)
        try:
            self._start()
        except RuntimeError as exc:
            raise unittest.SkipTest(f"daemon simulado não subiu: {exc}") from exc

    def _start(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="dxr"))  # curto: limite do caminho do socket Unix
        self.sock = self.tmp / "run" / "dracaena" / "ctl.sock"
        env = dict(os.environ, XDG_RUNTIME_DIR=str(self.tmp / "run"), XDG_CONFIG_HOME=str(self.tmp / "cfg"),
                   XDG_DATA_HOME=str(self.tmp / "data"), PYTHONPATH=str(BACKEND / "lib"))
        (self.tmp / "run").mkdir(mode=0o700)
        self.proc = subprocess.Popen([daemon_python(), "-m", "dracaena.cli", "daemon", "--simulate"], env=env,
                                     cwd=str(BACKEND), stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        end = time.monotonic() + 8
        while time.monotonic() < end and not self.sock.exists():
            if self.proc.poll() is not None:
                raise RuntimeError("daemon simulado saiu: " + (self.proc.stderr.read() or b"").decode()[-400:])
            time.sleep(0.05)
        if not self.sock.exists():
            self.stop()
            raise RuntimeError("daemon simulado não criou o socket")

    def transport(self) -> DaemonTransport:
        return DaemonTransport(str(self.sock))

    def stop(self) -> None:
        self.proc.terminate()
        try:
            self.proc.wait(3)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        shutil.rmtree(self.tmp, ignore_errors=True)


def backend_available() -> bool:
    return (BACKEND / "lib" / "dracaena" / "cli.py").is_file()


def screenshot_dir() -> Path:
    d = Path(os.environ.get("DRACAENA_SHOT_DIR", tempfile.gettempdir())) / "dracaena-capturas"
    d.mkdir(parents=True, exist_ok=True)
    return d


class ContractFake(FakeClient):
    """Servidor falso que segue o CONTRATO (Decisões do Maestro): hello.toggle_cmd, probe.start com
    draft_toml, probe.cancel, sites.save com overwrite, doctor. Único módulo de teste para isso."""
    DRAFT = '[site]\nname = "exemplo"\n'

    def __init__(self, *, toggle_cmd=None, probe=None, saved=None, defer_probe=False) -> None:
        super().__init__()
        self.toggle_cmd = toggle_cmd
        self.probe = probe if probe is not None else {"matches": {"questao": 1, "alternativa": 4, "enviar": 1},
                                                      "questions": 1, "draft_toml": self.DRAFT}
        self.saved: dict[str, str] = dict(saved or {})
        self.defer_probe = defer_probe
        self.pending_probe = None
        self.armed = False
        self.shortcut_test_error = ""
        self.doctor = {"ok": True, "checks": [{"name": "navegador", "ok": True},
                                              {"name": "Claude Code", "ok": True, "message": "autenticado"}]}
        self.is_connected = True
        self.sites = [{"name": n, "version": 0} for n in self.saved]

    def request(self, cmd, args=None, callback=None) -> int:
        args = args or {}
        self.calls.append((cmd, args))
        rid = len(self.calls)
        if cmd == "probe.start" and self.defer_probe:
            self.pending_probe = lambda: callback(Resp(rid, True, self.probe)) if callback else None
            return rid
        resp = self._answer(rid, cmd, args)
        if callback:
            QTimer.singleShot(0, lambda: callback(resp))
        return rid

    def fire_shortcut_test(self, ok: bool = True) -> None:
        """O compositor disparou o atalho: o daemon emite shortcut_test (e NÃO age)."""
        self.event_received.emit({"event": "shortcut_test", "ok": ok})
        self.armed = False

    def finish_probe(self) -> None:
        if self.pending_probe:
            self.pending_probe()
            self.pending_probe = None

    def _answer(self, rid, cmd, args) -> Resp:
        if cmd == "hello":
            data = {"v": 0, "app_version": "0.1.0", "caps": []}
            if self.toggle_cmd is not None:
                data["toggle_cmd"] = self.toggle_cmd
            return Resp(rid, True, data)
        if cmd == "probe.start":
            if isinstance(self.probe, Resp):
                return self.probe
            return Resp(rid, True, self.probe)
        if cmd == "probe.cancel":
            return Resp(rid, True, {"cancelled": True})
        if cmd == "shortcut.test":
            if self.shortcut_test_error:
                return Resp(rid, False, error=self.shortcut_test_error, code="bad_request")
            self.armed = bool(args.get("arm"))
            return Resp(rid, True, {"armed": self.armed})
        if cmd == "sites.save":
            import re
            name, toml = args.get("name", ""), args.get("toml", "")
            if not re.fullmatch(r"[a-z0-9_-]+", name):
                return Resp(rid, False, error="nome inválido", code="bad_request")
            if len(toml.encode()) > 64 * 1024:
                return Resp(rid, False, error="toml acima de 64 KiB", code="bad_request")
            if "desconhecido" in toml:
                return Resp(rid, False, error="linha 2: campo desconhecido “desconhecido”", code="bad_request")
            if name in self.saved and not args.get("overwrite"):
                return Resp(rid, False, error="o site já existe", code="bad_request")
            self.saved[name] = toml
            if not any(s["name"] == name for s in self.sites):
                self.sites.append({"name": name, "version": 0})
            return Resp(rid, True, {"path": f"/dados/sites/{name}.toml"})
        if cmd == "sites.list":
            return Resp(rid, True, list(self.sites))
        if cmd == "doctor":
            return Resp(rid, True, self.doctor)
        return Resp(rid, True, {})
