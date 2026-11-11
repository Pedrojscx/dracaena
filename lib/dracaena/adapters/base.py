"""Interface do adaptador (v0) e escolha do adaptador por página.

O adaptador LÊ e PROPÕE alvos; nunca clica, digita nem seleciona: quem age é
`dracaena.guard`. O núcleo não casa texto de erro, só os tipos abaixo.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from ..core.errors import AdapterError, Ambiguous, NotFound, PageGone
from ..core.model import CORRECT, INCORRECT, UNKNOWN, Question, Target, Verdict

__all__ = ["Adapter", "AdapterError", "Ambiguous", "NotFound", "PageGone", "Registry", "Question", "Target",
           "Verdict", "CORRECT", "INCORRECT", "UNKNOWN"]


@runtime_checkable
class Adapter(Protocol):
    name: str
    figure_dir: Any            # pasta (Path) onde extract() grava os PNG das figuras; None = sem figuras
    extra_block: tuple[str, ...]   # termos que o perfil ACRESCENTA à blocklist da guarda

    def matches(self, url: str, title: str) -> int:
        """0..100; o maior vence (o heurístico responde 10)."""

    def locate(self, frame) -> list:
        """Componentes de questão visíveis, em ordem do documento."""

    def extract(self, handle) -> Question:
        """Lê a questão (somente leitura)."""

    def target(self, handle, kind: str, index) -> Target:
        """kind: 'option' (index = int) | 'dropdown' (index = (item, opção))."""

    def submit_target(self, handle) -> Target | None:
        """Só o Submit DA questão (nunca um envio global)."""

    def reset_target(self, handle) -> Target | None:
        """'Tentar de novo' da questão."""

    def verdict(self, handle) -> Verdict:
        """CORRECT | INCORRECT | UNKNOWN, com o feedback da página."""


class Registry:
    """Conjunto de adaptadores; `pick` devolve o de maior `matches`."""

    def __init__(self, adapters=()):
        self.adapters: list = list(adapters)

    def add(self, adapter) -> None:
        self.adapters.append(adapter)

    def pick(self, url: str, title: str = ""):
        best, score = None, -1
        for a in self.adapters:
            s = int(a.matches(url, title))
            if s > score:
                best, score = a, s
        if best is None or score <= 0:
            raise NotFound("nenhum adaptador serve para esta página")
        return best
