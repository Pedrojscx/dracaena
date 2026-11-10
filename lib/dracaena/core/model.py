"""Modelo neutro da questão, do alvo de ação e do veredito da página.

Tudo aqui é independente de site: o adaptador preenche `Question`, o Claude
responde por ÍNDICE, e a guarda executa apenas `Target`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

SINGLE, MULTI, DROPDOWN, MATCH = "SINGLE", "MULTI", "DROPDOWN", "MATCH"
KINDS = (SINGLE, MULTI, DROPDOWN, MATCH)

CORRECT, INCORRECT, UNKNOWN = "CORRECT", "INCORRECT", "UNKNOWN"


@dataclass(frozen=True)
class Option:
    index: int
    text: str
    checked: bool = False


@dataclass(frozen=True)
class Choice:
    index: int
    text: str
    selected: bool = False


@dataclass(frozen=True)
class Item:
    label: str
    options: tuple[Choice, ...] = ()


@dataclass(frozen=True)
class Side:
    """Lado de uma associação (MATCH, opcional): letra à esquerda, índice à direita."""
    index: int
    text: str
    letter: str = ""
    linked: str | None = None


@dataclass(frozen=True)
class Question:
    id: str
    kind: str
    stem: str
    instruction: str = ""
    options: tuple[Option, ...] = ()
    expected: int | None = None
    items: tuple[Item, ...] = ()
    figures: tuple[str, ...] = ()
    feedback: str | None = None
    left: tuple[Side, ...] = ()
    right: tuple[Side, ...] = ()

    def to_dict(self) -> dict:
        from dataclasses import asdict
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Question":
        """Aceita o formato de dicionário (testes, diagnósticos e o IPC)."""
        def opts(rows):
            return tuple(Option(int(o["index"]), str(o.get("text", "")), bool(o.get("checked", False))) for o in rows)

        def items(rows):
            return tuple(Item(str(it.get("label", it.get("text", ""))),
                              tuple(Choice(int(o["index"]), str(o.get("text", "")), bool(o.get("selected", False)))
                                    for o in it.get("options", ()))) for it in rows)

        def sides(rows):
            return tuple(Side(int(s.get("index", i)), str(s.get("text", "")), str(s.get("letter", "")),
                              s.get("linked")) for i, s in enumerate(rows))

        return cls(id=str(d.get("id", "")), kind=d["kind"], stem=str(d.get("stem", "")),
                   instruction=str(d.get("instruction", "")), options=opts(d.get("options", ())),
                   expected=d.get("expected"), items=items(d.get("items", ())),
                   figures=tuple(d.get("figures", ())), feedback=d.get("feedback"),
                   left=sides(d.get("left", ())), right=sides(d.get("right", ())))


@dataclass(frozen=True)
class Verdict:
    result: str = UNKNOWN
    feedback: str | None = None


@dataclass(frozen=True)
class Target:
    """O que a guarda pode executar.

    role:   option | submit | reset
    action: click | select (select = escolher a opção `value` de um <select> nativo)
    element: handle do elemento; label: rótulo legível; qid: id da questão dona.
    opener: Target opcional a executar antes (abrir um dropdown personalizado).
    """
    role: str
    action: str
    element: Any
    label: str
    qid: str
    value: Any = None
    opener: "Target | None" = None
