"""Alternativas (SINGLE/MULTI): linhas com rádio ou checkbox à esquerda,
estado marcado/desmarcado, ponto de clique e associação resposta -> linha."""

from __future__ import annotations

from dataclasses import dataclass

from ..ocr import Box, Line
from ..page import Graphic, Page
from ..text import best_match
from .base import text_lines


@dataclass
class Option:
    text: str
    lines: list[Line]
    control: Graphic | None

    @property
    def box(self) -> Box:
        b = self.lines[0].box
        for ln in self.lines[1:]:
            b = b.union(ln.box)
        return b

    @property
    def checked(self) -> bool | None:
        return None if self.control is None else self.control.checked


def _controls(page: Page) -> list[Graphic]:
    s = page.scale
    return [g for g in page.graphics
            if g.kind in ("control", "filled") and g.box.w <= 34 * s and g.box.h <= 34 * s]


def options(page: Page) -> list[Option]:
    """Alternativas = linhas de texto com um controle logo à esquerda."""
    s = page.scale
    lines = text_lines(page)
    opts: list[Option] = []
    used: set[int] = set()
    for ctrl in _controls(page):
        best = None
        for i, ln in enumerate(lines):
            if i in used:
                continue
            gap = ln.box.x - ctrl.box.x2
            if not (-2 * s <= gap <= 45 * s):
                continue
            if abs(ln.box.cy - ctrl.box.cy) > max(ln.box.h, ctrl.box.h) * 0.75:
                continue
            if best is None or gap < best[1]:
                best = (i, gap)
        if best is None:
            continue
        i = best[0]
        used.add(i)
        opts.append(Option(lines[i].text, [lines[i]], ctrl))
    # Continuações: linhas logo abaixo, mesmo recuo, sem controle próprio.
    controlled_y = sorted(o.lines[0].box.y for o in opts)
    for opt in sorted(opts, key=lambda o: o.lines[0].box.y):
        first = opt.lines[0]
        next_ctrl = min((y for y in controlled_y if y > first.box.y), default=10 ** 9)
        for i, ln in enumerate(lines):
            if i in used or ln.box.y >= next_ctrl:
                continue
            last = opt.lines[-1]
            if abs(ln.box.x - first.box.x) <= 6 * s and 0 < ln.box.y - last.box.y2 <= 1.2 * last.box.h:
                opt.lines.append(ln)
                used.add(i)
        opt.text = " ".join(ln.text for ln in opt.lines)
    opts.sort(key=lambda o: o.lines[0].box.y)
    return opts


def text_options(page: Page) -> list[Option]:
    """Plano B sem controles detectados: cada linha de texto vira candidata
    (estado desconhecido). Só serve para alternativa única."""
    return [Option(ln.text, [ln], None) for ln in text_lines(page)[1:]]


def click_point_for(opt: Option, offset_px: float) -> tuple[float, float]:
    first = opt.lines[0]
    return first.box.x - offset_px, first.box.cy


def map_answers(answers: list[str], opts: list[Option], threshold: float) -> dict:
    """Associa cada resposta a uma alternativa visível.

    Devolve {"found": {resposta: índice}, "missing": [...], "ambiguous": [...]}.
    """
    texts = [o.text for o in opts]
    found: dict[str, int] = {}
    missing, ambiguous = [], []
    for ans in answers:
        res = best_match(ans, texts, threshold)
        if res.status == "ok":
            if res.index in found.values():
                ambiguous.append(ans)
            else:
                found[ans] = res.index
        elif res.status == "ambiguous":
            ambiguous.append(ans)
        else:
            missing.append(ans)
    return {"found": found, "missing": missing, "ambiguous": ambiguous}
