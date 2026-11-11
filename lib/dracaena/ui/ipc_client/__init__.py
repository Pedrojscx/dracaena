"""IPC não bloqueante. Nunca reenvia comandos após desconexão."""
from __future__ import annotations

import itertools
import getpass
import os
import sys
import time
from collections.abc import Callable
from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtNetwork import QLocalSocket
from .protocol import EVENT_NAMES, EventMsg, IpcError, LineBuffer, ProtocolError, Response, encode_request, decode_line


def default_socket_name() -> str:
    """Endpoint do contrato; mesma resolução de diretório do daemon."""
    if sys.platform == 'win32':
        return 'dracaena-' + getpass.getuser()
    runtime = os.environ.get('XDG_RUNTIME_DIR')
    if runtime:
        return os.path.join(runtime, 'dracaena', 'ctl.sock')
    from platformdirs import PlatformDirs
    return os.path.join(PlatformDirs('dracaena', appauthor=False, roaming=True).user_runtime_dir, 'ctl.sock')



class IpcClient(QObject):
    connected = Signal()
    disconnected = Signal()
    event_received = Signal(object)
    request_timeout = Signal(int)
    availability_changed = Signal(bool, str)
    protocol_error = Signal(str)

    def __init__(self, socket_name: str | None = None, parent: QObject | None = None,
                 *, timeout_ms: int = 5000, retry_ms: int = 250, max_retry_ms: int = 5000):
        super().__init__(parent)
        self._name = socket_name or default_socket_name()
        self._timeout = max(1, timeout_ms) / 1000
        self._base_retry = max(1, retry_ms)
        self._max_retry = max(self._base_retry, max_retry_ms)
        self._delay = self._base_retry
        self._running = False
        self._available = False
        self._ids = itertools.count(1)
        self._pending = {}
        self._buf = LineBuffer()
        self._sock = QLocalSocket(self)
        self._sock.setReadBufferSize(1_000_001)
        self._sock.connected.connect(self._on_connected)
        self._sock.disconnected.connect(self._lost)
        self._sock.errorOccurred.connect(lambda error: self._lost())
        self._sock.readyRead.connect(self._read)
        self._retry = QTimer(self)
        self._retry.setSingleShot(True)
        self._retry.timeout.connect(self._try_connect)
        self._connecting = QTimer(self)
        self._connecting.setSingleShot(True)
        self._connecting.setInterval(max(1, timeout_ms))
        self._connecting.timeout.connect(self._connect_expired)
        self._deadlines = QTimer(self)
        self._deadlines.setInterval(min(100, max(1, timeout_ms)))
        self._deadlines.timeout.connect(self._expire)

    @property
    def is_connected(self) -> bool:
        return self._available

    def connect_to_daemon(self) -> None:
        if self._running:
            return
        self._running = True
        self._deadlines.start()
        self._try_connect()

    def close(self) -> None:
        self._running = False
        self._retry.stop()
        self._deadlines.stop()
        self._connecting.stop()
        self._sock.abort()
        self._lost()

    def request(self, cmd, args: dict | None = None,
                callback: Callable[[Response], None] | None = None,
                timeout_ms: int | None = None) -> int:
        """Envia um pedido. `timeout_ms` vale só para esta chamada (padrão: o do cliente)."""
        rid = next(self._ids)
        if not self._available:
            if callback:
                QTimer.singleShot(0, lambda: callback(Response(rid, False, error=IpcError(
                    'disconnected', 'Daemon indisponível. Tentando reconectar.'))))
            return rid
        try:
            payload = encode_request(rid, str(getattr(cmd, 'value', cmd)), args)
            if len(payload) > self._buf.limit:
                raise ValueError('Requisição acima do limite.')
        except (TypeError, ValueError):
            if callback:
                QTimer.singleShot(0, lambda: callback(Response(rid, False, error=IpcError(
                    'invalid_request', 'Requisição IPC inválida.'))))
            return rid
        if len(self._pending) >= 128:
            if callback:
                QTimer.singleShot(0, lambda: callback(Response(rid, False, error=IpcError(
                    'busy', 'Aguarde a conclusão dos comandos pendentes.'))))
            return rid
        timeout = self._timeout if timeout_ms is None else max(1, int(timeout_ms)) / 1000
        self._pending[rid] = (time.monotonic() + timeout, callback)
        if self._sock.write(payload) < 0:
            self._sock.abort()
            self._lost()
        return rid

    def _try_connect(self) -> None:
        if self._running and self._sock.state() == QLocalSocket.UnconnectedState:
            self._buf = LineBuffer()
            self._connecting.start()
            self._sock.connectToServer(self._name)

    def _connect_expired(self) -> None:
        self._sock.abort()
        self._lost()

    def _on_connected(self) -> None:
        self._connecting.stop()
        self._available = True
        self._delay = self._base_retry
        self._retry.stop()
        self.availability_changed.emit(True, 'Conectado ao daemon.')
        self.request('subscribe', {'events': list(EVENT_NAMES)},
                     callback=self._subscription_result)
        self.connected.emit()

    def _subscription_result(self, response):
        if not response.ok and self._available:
            self.protocol_error.emit('Não foi possível assinar eventos do daemon: ' +
                                     response.error.message)

    def _lost(self) -> None:
        self._connecting.stop()
        was_available = self._available
        self._available = False
        self._buf = LineBuffer()
        pending, self._pending = self._pending, {}
        for rid, (_, callback) in pending.items():
            if callback:
                callback(Response(rid, False, error=IpcError('disconnected',
                    'Conexão perdida. O comando não será reenviado automaticamente.')))
        if was_available:
            self.disconnected.emit()
        if self._running and not self._retry.isActive():
            self.availability_changed.emit(False, 'Daemon indisponível. Tentando reconectar.')
            self._retry.start(self._delay)
            self._delay = min(self._max_retry, self._delay * 2)

    def _expire(self) -> None:
        now = time.monotonic()
        expired = [rid for rid, (deadline, _) in self._pending.items() if deadline <= now]
        for rid in expired:
            item = self._pending.pop(rid, None)
            if item is None:
                continue
            self.request_timeout.emit(rid)
            if item[1]:
                item[1](Response(rid, False, error=IpcError('timeout',
                    'O daemon não respondeu a tempo. Confira o estado antes de tentar novamente.')))

    def _read(self) -> None:
        try:
            for line in self._buf.feed(bytes(self._sock.readAll())):
                message = decode_line(line)
                if isinstance(message, EventMsg):
                    self.event_received.emit(message)
                else:
                    item = self._pending.pop(message.id, None)
                    if item and item[1]:
                        item[1](message)
        except ProtocolError as exc:
            self.protocol_error.emit(str(exc))
            self._sock.abort()
            self._lost()
