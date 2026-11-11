"""Ponto único: comando do atalho vindo do daemon (``hello``).

# PROVISÓRIO: aguarda CONTRATO (decisão do Maestro repassada pelo A1, 2026-11-10): o ``hello``
# devolve ``toggle_cmd`` (argv, lista de textos; AppImage usa $APPIMAGE, nunca o mount
# temporário). Caminho exato assumido: ``data.toggle_cmd``. Se o ``hello`` não trouxer, vale o
# fallback de ``commands.toggle_command``.
"""
from __future__ import annotations

from typing import Callable

from dracaena.ui.settings import reply
from .commands import ToggleCommand


def request_toggle_cmd(client, callback: Callable[[ToggleCommand | None], None]) -> None:
    def done(resp) -> None:
        data = reply.payload(resp) if reply.is_ok(resp) else None
        argv = data.get("toggle_cmd") if isinstance(data, dict) else None
        if isinstance(argv, list) and argv and all(isinstance(a, str) and a for a in argv):
            callback(ToggleCommand(tuple(argv), "daemon"))
        else:
            callback(None)
    client.request("hello", {}, done)
