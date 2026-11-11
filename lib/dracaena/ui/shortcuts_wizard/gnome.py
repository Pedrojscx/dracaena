"""Atalho personalizado do GNOME via gsettings, feito em Python (sem shell).

Regra de segurança: a lista ``custom-keybindings`` do usuário é LIDA e o caminho do DRACAENA é
ACRESCENTADO; a lista nunca é sobrescrita nem duplicada. Nada roda sem confirmação do chamador.
"""
from __future__ import annotations

import ast
import shlex
import subprocess
from dataclasses import dataclass
from typing import Callable

SCHEMA = "org.gnome.settings-daemon.plugins.media-keys"
LIST_KEY = "custom-keybindings"
ITEM_SCHEMA = SCHEMA + ".custom-keybinding"
ITEM_PATH = "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/dracaena/"
NAME = "DRACAENA"
DEFAULT_BINDING = "<Super><Alt>d"

# Executa argv (sem shell) e devolve (código, saída). Injetável: os testes nunca usam o real.
Runner = Callable[[list[str]], "tuple[int, str]"]


def real_runner(argv: list[str]) -> tuple[int, str]:
    try:
        done = subprocess.run(argv, capture_output=True, text=True, timeout=10, shell=False)
    except FileNotFoundError:
        return 127, "gsettings não encontrado"
    except subprocess.TimeoutExpired:
        return 124, "gsettings não respondeu a tempo"
    return done.returncode, (done.stdout if done.returncode == 0 else (done.stderr or done.stdout)).strip()


def parse_list(text: str) -> list[str]:
    """``@as []`` e ``['/a/', '/b/']`` -> lista. Levanta ValueError se não for lista de textos."""
    text = text.strip()
    if text.startswith("@as"):
        text = text[3:].strip()
    try:
        value = ast.literal_eval(text)
    except (ValueError, SyntaxError) as exc:
        raise ValueError("Lista de atalhos do GNOME em formato inesperado.") from exc
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ValueError("Lista de atalhos do GNOME em formato inesperado.")
    return value


def gvariant_string(value: str) -> str:
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


def display_arg(arg: str) -> str:
    """Argumento legível para o shell: ``"'texto'"`` quando seguro; senão ``shlex.quote``."""
    if arg and not any(c in arg for c in "$`\\\"!"):
        return arg if shlex.quote(arg) == arg else '"' + arg + '"'
    return shlex.quote(arg)


@dataclass(frozen=True)
class Plan:
    current: tuple[str, ...]
    new_list: tuple[str, ...]
    already_listed: bool
    steps: tuple[tuple[str, ...], ...]

    def text(self) -> str:
        """Os comandos exatos, prontos para copiar. ``shlex.split`` de cada linha devolve o argv."""
        return "\n".join(" ".join(display_arg(a) for a in s) for s in self.steps)


def read_list(run: Runner) -> list[str]:
    code, out = run(["gsettings", "get", SCHEMA, LIST_KEY])
    if code != 0:
        raise OSError(out or "Não consegui ler a lista de atalhos do GNOME.")
    return parse_list(out)


def build_plan(current: list[str], command: str, binding: str = DEFAULT_BINDING) -> Plan:
    listed = ITEM_PATH in current
    new = list(current) if listed else [*current, ITEM_PATH]
    item = f"{ITEM_SCHEMA}:{ITEM_PATH}"
    steps = [["gsettings", "set", item, "name", gvariant_string(NAME)],
             ["gsettings", "set", item, "command", gvariant_string(command)],
             ["gsettings", "set", item, "binding", gvariant_string(binding)]]
    if not listed:  # o item só entra na lista depois de completo
        steps.append(["gsettings", "set", SCHEMA, LIST_KEY, "[" + ", ".join(gvariant_string(p) for p in new) + "]"])
    return Plan(tuple(current), tuple(new), listed, tuple(tuple(s) for s in steps))


def apply_plan(plan: Plan, run: Runner) -> None:
    """Executa os passos. Relê a lista antes: se mudou desde o plano, recusa (nunca sobrescreve)."""
    if tuple(read_list(run)) != plan.current:
        raise RuntimeError("A lista de atalhos do GNOME mudou desde a confirmação. Tente de novo.")
    for step in plan.steps:
        code, out = run(list(step))
        if code != 0:
            raise OSError(out or "gsettings falhou.")
