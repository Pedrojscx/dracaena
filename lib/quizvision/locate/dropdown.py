"""Dropdowns: enunciado, caixa do dropdown, opção na lista aberta e
conferência do valor exibido."""

from __future__ import annotations

from ..ocr import Box, Line
from ..page import Page
from ..text import best_match, normalize, similarity
from .base import Located, blocks, match_block, text_lines


def locate_statement(page: Page, statement: str, threshold: float, below_y: float = -1) -> Located:
    cands = [(t, ls) for t, ls in blocks(text_lines(page)) if ls[0].box.y > below_y]
    res = match_block(statement, cands, threshold)
    if res.status != "ok":
        return Located(res.status, f"enunciado {res.status}: {statement[:40]!r}", score=res.score)
    lines = cands[res.index][1]
    box = lines[0].box
    for ln in lines[1:]:
        box = box.union(ln.box)
    return Located("ok", box=box, lines=lines, score=res.score)


def locate_dropdown(page: Page, stmt_box: Box, statements: list[str], threshold: float) -> Located:
    """Caixa do dropdown do enunciado: na mesma linha à direita ou logo abaixo."""
    s = page.scale
    lines = [ln for ln in text_lines(page) if not stmt_box.contains(ln.box.cx, ln.box.cy)]

    def is_statement(ln: Line) -> bool:
        return any(similarity(ln.text, st) >= max(threshold, 0.8) for st in statements)

    right = [ln for ln in lines if abs(ln.box.cy - stmt_box.cy) < stmt_box.h * 0.6 + 4 * s
             and ln.box.x > stmt_box.x2 + 10 * s and not is_statement(ln)]
    if right:
        ln = min(right, key=lambda l: l.box.x)
        return Located("ok", line=ln, point=(ln.box.cx, ln.box.cy), value=ln.text)
    below = [ln for ln in lines if 0 <= ln.box.y - stmt_box.y2 <= 70 * s
             and abs(ln.box.x - stmt_box.x) <= 60 * s and not is_statement(ln)]
    if not below:
        return Located("not_found", "dropdown não encontrado abaixo do enunciado")
    ln = min(below, key=lambda l: l.box.y)
    return Located("ok", line=ln, point=(ln.box.cx, ln.box.cy), value=ln.text)


def locate_list_option(before: Page, after: Page, answer: str, dd_box: Box, threshold: float) -> Located:
    """Opção `answer` na lista aberta: considera só linhas que surgiram ao abrir."""
    s = after.scale

    def key(ln: Line) -> tuple:
        return normalize(ln.text), round(ln.box.y / (6 * s)), round(ln.box.x / (6 * s))

    old = {key(ln) for ln in text_lines(before)}
    new = [ln for ln in text_lines(after) if key(ln) not in old
           and not (abs(ln.box.cy - dd_box.cy) < dd_box.h and abs(ln.box.x - dd_box.x) < 40 * s)]
    if not new:
        return Located("not_found", "lista do dropdown não apareceu")
    exact = [ln for ln in new if normalize(ln.text) == normalize(answer)]
    if len(exact) == 1:
        ln = exact[0]
        return Located("ok", point=(ln.box.cx, ln.box.cy), line=ln)
    if len(exact) > 1:
        return Located("ambiguous", f"opção {answer!r} aparece {len(exact)} vezes")
    res = best_match(answer, [ln.text for ln in new], max(threshold, 0.8))
    if res.status != "ok":
        return Located(res.status, f"opção {answer!r} {res.status} na lista")
    ln = new[res.index]
    return Located("ok", point=(ln.box.cx, ln.box.cy), line=ln)


def dropdown_shows(page: Page, dd_box: Box, answer: str) -> bool:
    s = page.scale
    for ln in text_lines(page):
        if abs(ln.box.cy - dd_box.cy) <= max(8 * s, dd_box.h * 0.6) and abs(ln.box.x - dd_box.x) <= 30 * s:
            if similarity(ln.text, answer) >= 0.85:
                return True
    return False
