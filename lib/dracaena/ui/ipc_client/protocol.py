"""Codec JSONL do CONTRATO IPC v0 do Dracaena."""
from __future__ import annotations
from dataclasses import dataclass, field
import json
from typing import Any


EVENT_NAMES = ('state', 'log', 'question', 'verdict', 'probe', 'shortcut_test')


class ProtocolError(ValueError):
    pass


@dataclass(frozen=True)
class IpcError:
    code: str
    message: str


@dataclass(frozen=True)
class Response:
    id: int
    ok: bool
    data: Any = field(default_factory=dict)
    error: IpcError | None = None

    @property
    def result(self):
        """Alias local para consumidores anteriores; no wire o campo é data."""
        return self.data


@dataclass(frozen=True)
class EventMsg:
    event: str
    data: dict[str, Any] = field(default_factory=dict)


def encode_request(request_id: int, command: str, args: dict | None = None) -> bytes:
    return (json.dumps({'v': 0, 'id': request_id, 'cmd': command, 'args': args or {}},
                       ensure_ascii=False, allow_nan=False) + '\n').encode('utf-8')


def decode_line(line: bytes) -> Response | EventMsg:
    try:
        raw = json.loads(line)
    except (ValueError, UnicodeError) as exc:
        raise ProtocolError('Mensagem JSON inválida.') from exc
    if not isinstance(raw, dict):
        raise ProtocolError('Mensagem IPC deve ser um objeto.')
    if 'v' in raw and (type(raw['v']) is not int or raw['v'] != 0):
        raise ProtocolError('Versão IPC incompatível.')
    if 'event' in raw:
        if raw['event'] not in EVENT_NAMES:
            raise ProtocolError('Evento IPC desconhecido.')
        if raw['event'] == 'state' and raw.get('state') not in ('idle', 'running', 'paused', 'error'):
            raise ProtocolError('Estado IPC inválido.')
        return EventMsg(raw['event'], {key: value for key, value in raw.items() if key != 'event'})
    if type(raw.get('id')) is not int or type(raw.get('ok')) is not bool:
        raise ProtocolError('Resposta IPC inválida.')
    if raw['ok']:
        if 'data' not in raw:
            raise ProtocolError('Resultado IPC ausente.')
        return Response(raw['id'], True, raw['data'])
    error, code = raw.get('error'), raw.get('code', 'daemon_error')
    if not isinstance(error, str) or not isinstance(code, str):
        raise ProtocolError('Erro IPC inválido.')
    return Response(raw['id'], False, error=IpcError(code, error))



class LineBuffer:
    def __init__(self, limit: int = 1_000_000):
        self.limit = limit
        self.buffer = bytearray()

    def feed(self, data: bytes) -> list[bytes]:
        self.buffer.extend(data)
        lines = []
        while True:
            boundary = self.buffer.find(b'\n')
            if boundary < 0:
                if len(self.buffer) > self.limit:
                    raise ProtocolError('Mensagem IPC acima do limite.')
                return lines
            if boundary > self.limit:
                raise ProtocolError('Mensagem IPC acima do limite.')
            line = bytes(self.buffer[:boundary])
            del self.buffer[:boundary + 1]
            if line.strip():
                lines.append(line)
