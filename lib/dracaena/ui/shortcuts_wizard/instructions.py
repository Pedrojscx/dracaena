"""Instruções por compositor no Wayland. Ponto de extensão: ``register(compositor, provider)``.

Só entra aqui o que a pesquisa confirmou (nota pesquisa-frontend-dracaena, via A1). O que não foi
confirmado fica de fora (ex.: KDE por ``.desktop``/``kglobalshortcutsrc``).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from .commands import ToggleCommand
from .env import Environment

WAYLAND_INTRO = ("No Wayland o aplicativo não pode registrar um atalho global sozinho. "
                 "Crie um atalho no seu sistema que execute este comando:")


@dataclass(frozen=True)
class Instruction:
    intro: str
    steps: tuple[str, ...] = ()
    snippet: str = ""           # texto copiável (linha de configuração); nunca executado
    snippet_label: str = ""
    notes: tuple[str, ...] = field(default=())


Provider = Callable[[Environment, ToggleCommand], Instruction]
_providers: dict[str, Provider] = {}


def register(compositor: str, provider: Provider) -> None:
    _providers[compositor] = provider


def _gnome(env, cmd):
    return Instruction(WAYLAND_INTRO, ("Configurações → Teclado → Atalhos personalizados.",
                                       "Ou use o botão abaixo para criar o atalho com o gsettings (pede confirmação)."))


def _kde(env, cmd):
    return Instruction(WAYLAND_INTRO, ("Configurações do sistema → Atalhos → Adicionar comando.",
                                       "Cole o comando acima e escolha a combinação de teclas."))


def _hyprland(env, cmd):
    return Instruction(WAYLAND_INTRO, ("Acrescente esta linha ao seu hyprland.conf e recarregue a configuração.",),
                       f"bind = SUPER_ALT, D, exec, {cmd.text()}", "Linha para o hyprland.conf")


def _sway(env, cmd):
    return Instruction(WAYLAND_INTRO, ("Acrescente esta linha ao seu arquivo de configuração do Sway e recarregue.",),
                       f"bindsym Mod4+Mod1+d exec {cmd.text()}", "Linha para o arquivo de configuração do Sway")


def _other(env, cmd):
    return Instruction(WAYLAND_INTRO, ("Use a ferramenta de atalhos do seu ambiente e associe uma combinação de teclas "
                                       "a esse comando.",))


for _name, _fn in (("gnome", _gnome), ("kde", _kde), ("hyprland", _hyprland), ("sway", _sway), ("other", _other)):
    register(_name, _fn)


def build(env: Environment, cmd: ToggleCommand) -> Instruction:
    return _providers.get(env.compositor, _providers["other"])(env, cmd)
