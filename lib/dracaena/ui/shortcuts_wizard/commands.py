"""Comando que o atalho do sistema executa.

O comando vem do daemon (``hello.toggle_cmd``, argv completo; ver ``hello.py``). A UI só exibe e
copia, juntando com aspas seguras para o shell (``shlex.join``); ela não monta o comando.
O fallback ``dracaena toggle`` só vale quando o ``hello`` não trouxer ``toggle_cmd``.
"""
from __future__ import annotations

import shlex
import subprocess
from dataclasses import dataclass

FALLBACK_ARGV = ("dracaena", "toggle")


@dataclass(frozen=True)
class ToggleCommand:
    argv: tuple[str, ...]
    source: str   # "daemon" | "fallback"

    def text(self, windows: bool = False) -> str:
        return subprocess.list2cmdline(list(self.argv)) if windows else shlex.join(self.argv)


def toggle_command() -> ToggleCommand:
    return ToggleCommand(FALLBACK_ARGV, "fallback")
