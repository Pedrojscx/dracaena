"""Painel do quiz dentro da área de conteúdo, a partir de âncoras de OCR.

Âncoras: "Question N", "Check Your Understanding", enunciados com "Match" ou
"Choose", o botão Submit e alternativas com rádio/checkbox. O retângulo vai
do título da questão até abaixo do Submit e das alternativas, crescendo por
proximidade a partir das âncoras. A lista de módulos do NetAcad (coluna com
"1/1", "2/2", porcentagens) e a barra Q1..Qn ficam de fora.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..ocr import Box, Line
from ..page import Page
from ..text import contains_phrase, tokens
from .choices import options

_HEADER = re.compile(r"\b(?:Question|Questão|Pergunta)\s+\d+\b", re.IGNORECASE)
_STEM = re.compile(r"\b(?:match|choose)\b", re.IGNORECASE)
_PROGRESS = re.compile(r"^(?:\d+/\d+|\d{1,3}%)$")
_NAV_TOKEN = re.compile(r"^Q\d{1,3}$")

GAP_DOWN = 180      # px lógicos entre elementos para continuar crescendo
GAP_UP = 60
MARGIN = 12
BOTTOM_EXTRA = 60   # folga embaixo para feedback e listas abertas


@dataclass
class PanelResult:
    box: Box | None
    reason: str = ""
    anchors: list[str] = field(default_factory=list)
    module_right: int | None = None


def module_column_right(page: Page) -> int | None:
    """Borda direita da lista de módulos do NetAcad, se houver.

    Linhas de progresso ("1/1", "75%") alinhadas na metade esquerda indicam a
    coluna; tudo à esquerda da maior borda delas + folga fica de fora.
    """
    marks = [ln for ln in page.lines for w in ln.words if _PROGRESS.match(w.text)]
    marks = [ln for ln in marks if ln.box.cx < page.width * 0.5]
    if len(marks) < 2:
        return None
    return max(ln.box.x2 for ln in marks) + round(16 * page.scale)


def is_nav_line(ln: Line) -> bool:
    toks = [w.text for w in ln.words]
    return len(toks) >= 2 and sum(1 for t in toks if _NAV_TOKEN.match(t)) >= len(toks) - 1


def find_panel(page: Page) -> PanelResult:
    """Retângulo do painel em coordenadas de `page` (a área de conteúdo)."""
    s = page.scale
    col = module_column_right(page)
    lines = [ln for ln in page.lines
             if (col is None or ln.box.x >= col) and not is_nav_line(ln)]
    headers = [ln for ln in lines if _HEADER.search(ln.text) and len(tokens(ln.text)) <= 6
               or contains_phrase(ln.text, "check your understanding")]
    stems = [ln for ln in lines if _STEM.search(ln.text)]
    submits = [ln for ln in lines if ln.button and "submit" in tokens(ln.text)]
    sub = Page(page.width, page.height, s, lines,
               [g for g in page.graphics if col is None or g.box.x >= col])
    opts = options(sub)
    option_lines = [o.lines[0] for o in opts]
    seeds = headers + stems + submits + option_lines
    anchors = ([f"cabeçalho: {headers[0].text}"] if headers else []) + \
        ([f"enunciado: {stems[0].text[:40]}"] if stems else []) + \
        (["Submit"] if submits else []) + ([f"{len(opts)} alternativas"] if opts else [])
    if not seeds or (not headers and not stems and not submits and len(opts) < 2):
        return PanelResult(None, "nenhuma âncora de quiz (Question N, Submit, alternativas...)", anchors, col)

    elements: list[Box] = [ln.box for ln in lines] + [g.box for g in sub.graphics] + \
        [o.control.box for o in opts if o.control is not None]
    top_header = min(headers, key=lambda ln: ln.box.y) if headers else None
    next_header_y = None
    if top_header is not None:
        below = [ln.box.y for ln in headers if ln.box.y > top_header.box.y2 + 20 * s]
        next_header_y = min(below) if below else None
    left = min(b.box.x for b in seeds) - round(70 * s)

    def allowed(b: Box) -> bool:
        if b.x < left:
            return False
        if top_header is not None and b.y < top_header.box.y - 4 * s:
            return False
        if next_header_y is not None and b.y2 > next_header_y - 4 * s:
            return False
        return True

    seed_boxes = [b.box for b in seeds if allowed(b.box)]
    if top_header is not None:
        seed_boxes.append(top_header.box)
    if not seed_boxes:
        return PanelResult(None, "âncoras fora da região do painel", anchors, col)
    box = seed_boxes[0]
    for b in seed_boxes[1:]:
        box = box.union(b)
    changed = True
    while changed:
        changed = False
        for b in elements:
            if not allowed(b) or (b.x >= box.x and b.y >= box.y and b.x2 <= box.x2 and b.y2 <= box.y2):
                continue
            up = GAP_UP * s if top_header is None else 0
            if box.y - up <= b.y2 and b.y <= box.y2 + GAP_DOWN * s:
                box = box.union(b)
                changed = True
    m = round(MARGIN * s)
    x0 = max(0, box.x - m)
    y0 = max(0, box.y - m)
    x1 = min(page.width, box.x2 + m + round(4 * s))
    y1 = min(page.height, box.y2 + m + round(BOTTOM_EXTRA * s))
    result = Box(x0, y0, x1 - x0, y1 - y0)
    if result.w < 200 * s or result.h < 80 * s:
        return PanelResult(None, f"painel pequeno demais ({result.w}x{result.h})", anchors, col)
    return PanelResult(result, "", anchors, col)
