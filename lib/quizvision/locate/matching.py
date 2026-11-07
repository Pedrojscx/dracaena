"""Associação de colunas: círculos coloridos com letra (origem), círculos
tracejados à esquerda dos itens da direita (alvo) e verificação da ligação."""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import median

from ..image import Image
from ..ocr import Box, Line
from ..page import Graphic, Page
from ..text import best_match, normalize
from ..widgets import find_ring_near, region_change, ring_state
from .base import Located, blocks, match_block, text_lines


@dataclass
class MatchLayout:
    sources: list[dict] = field(default_factory=list)   # {letter, box, left_text}
    radius: float = 0.0
    header_lines: list[Line] = field(default_factory=list)


def _letter_circles(page: Page) -> list[Graphic]:
    s = page.scale
    return [g for g in page.graphics if g.kind == "filled" and g.shape == "circle" and g.colored
            and 18 * s <= g.box.w <= 64 * s]


def _text_starts_right_of(page: Page, box: Box, max_gap: float) -> Line | None:
    for ln in text_lines(page):
        if 0 <= ln.box.x - box.x2 <= max_gap and abs(ln.box.cy - box.cy) < box.h * 0.8:
            return ln
    return None


def match_sources(page: Page, img_path: str, read_letter) -> MatchLayout:
    """Círculos de letra (origem) com sua letra e o texto do item à esquerda.

    `read_letter(path, box)` faz o OCR de um caractere (injeção facilita
    testes). Círculos com texto começando logo à direita são alvos já
    ligados, não origens.
    """
    s = page.scale
    layout = MatchLayout()
    circles = _letter_circles(page)
    if circles:
        layout.radius = median(c.box.w for c in circles) / 2
    for c in circles:
        if _text_starts_right_of(page, c.box, 45 * s):
            continue
        left = [ln for ln in text_lines(page) if ln.box.x2 <= c.box.x and abs(ln.box.cy - c.box.cy) < c.box.h]
        left_text = max(left, key=lambda l: l.box.x2).text if left else ""
        letter, conf = read_letter(img_path, c.box)
        layout.sources.append({"letter": letter if conf >= 40 else "", "box": c.box, "left_text": left_text,
                               "conf": conf})
    for ln in text_lines(page):
        if normalize(ln.text) in ("categories", "options", "category", "option"):
            layout.header_lines.append(ln)
    return layout


def locate_source(layout: MatchLayout, letter: str, left_text: str, threshold: float) -> Located:
    by_letter = [src for src in layout.sources if src["letter"] == letter]
    by_text = []
    if left_text:
        texts = [src["left_text"] for src in layout.sources]
        res = best_match(left_text, texts, threshold)
        if res.ok:
            by_text = [layout.sources[res.index]]
    if len(by_letter) > 1:
        return Located("ambiguous", f"letra {letter} lida em {len(by_letter)} círculos")
    if by_letter and by_text and by_letter[0] is not by_text[0]:
        return Located("ambiguous", f"letra {letter} e texto {left_text[:30]!r} apontam círculos diferentes")
    src = (by_letter or by_text or [None])[0]
    if src is None:
        return Located("not_found", f"círculo da letra {letter} não encontrado")
    b = src["box"]
    return Located("ok", point=(b.cx, b.cy), box=b)


def locate_target(page: Page, img: Image, right_text: str, threshold: float, radius: float,
                  exclude: list[Box] | None = None) -> Located:
    """Círculo-alvo à esquerda do texto do item da direita (mesma faixa)."""
    s = page.scale
    exclude = exclude or []
    cands = []
    for text, ls in blocks(text_lines(page), max_join=2):
        if any(ex.contains(ls[0].box.cx, ls[0].box.cy) for ex in exclude):
            continue
        cands.append((text, ls))
    res = match_block(right_text, cands, threshold)
    if res.status != "ok":
        return Located(res.status, f"item {right_text[:40]!r} {res.status}")
    first = cands[res.index][1][0]
    r = radius or 15 * s
    area = Box(round(first.box.x - 3 * r - 20 * s), round(first.box.cy - r), round(3 * r + 18 * s), round(2 * r))
    hit = find_ring_near(img, area, s, radius=radius or None)
    if hit is None:
        return Located("not_found", f"círculo-alvo de {right_text[:30]!r} não encontrado")
    return Located("ok", point=(hit.box.cx, hit.box.cy), box=hit.box, kind=hit.kind, line=first)


def target_linked(before: Image | None, after: Image, box: Box) -> bool:
    """Ligação visível: círculo preenchido ou mudança forte na região."""
    if ring_state(after, box).kind == "filled":
        return True
    if before is not None:
        pad = max(2, box.w // 6)
        grown = Box(box.x - pad, box.y - pad, box.w + 2 * pad, box.h + 2 * pad)
        return region_change(before, after, grown) > 0.25
    return False
