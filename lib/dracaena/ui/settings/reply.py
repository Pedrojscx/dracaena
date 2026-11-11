"""Camada TEMPORÁRIA de normalização de respostas e eventos do daemon.

# PROVISÓRIO: o cliente IPC do B1 ainda não fala o formato real do daemon (resposta
# {id, ok, data | error(str), code}; evento plano). Este é o ÚNICO módulo das telas B2 que
# conhece as duas formas (``data`` ou ``result``; ``error`` como texto ou objeto com
# ``message``; evento plano ou ``EventMsg(event, data)``). Quando o B1 entregar o cliente
# final, reduza este módulo a uma passagem direta e remova-o.
"""
from __future__ import annotations

from typing import Any


def is_ok(response: Any) -> bool:
    return bool(getattr(response, "ok", False))


def payload(response: Any) -> Any:
    data = getattr(response, "data", None)
    return data if data is not None else getattr(response, "result", None)


def error_text(response: Any, default: str = "O daemon recusou o pedido.") -> str:
    err = getattr(response, "error", None)
    if isinstance(err, str) and err:
        return err
    message = getattr(err, "message", None)
    return message if isinstance(message, str) and message else default


def error_code(response: Any) -> str:
    code = getattr(response, "code", None)
    if not isinstance(code, str):
        code = getattr(getattr(response, "error", None), "code", "")
    return code if isinstance(code, str) else ""


def event_parts(event: Any) -> tuple[str, dict[str, Any]]:
    """(nome, dados) de um evento, plano ou no formato EventMsg."""
    if isinstance(event, dict):
        return str(event.get("event", "")), event
    data = getattr(event, "data", None)
    return str(getattr(event, "event", "")), data if isinstance(data, dict) else {}
