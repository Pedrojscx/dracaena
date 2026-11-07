"""Área de conteúdo: a parte da janela que é a página, sem a interface do
Vivaldi (abas, barra de endereço, painéis laterais e barra de status).

A interface termina em bordas retas que atravessam a janela inteira: a
última borda horizontal de largura total no topo, a última borda vertical de
altura total à esquerda (faixa e painel lateral do Vivaldi, coluna de
módulos do NetAcad) e as primeiras à direita e embaixo. Margens fixas
(CHROME_TOP_PX, CHROME_LEFT_PX, em pixels lógicos) substituem a detecção.
"""

from __future__ import annotations

from ..image import Image
from ..ocr import Box

EDGE_DIFF = 40          # diferença de cor (soma dos canais) que conta como borda
ROW_FRACTION = 0.8      # fração da largura que a borda horizontal precisa cobrir
COL_FRACTION = 0.9      # fração da altura que a borda vertical precisa cobrir


def _diff(a: tuple[int, int, int], b: tuple[int, int, int]) -> int:
    return abs(a[0] - b[0]) + abs(a[1] - b[1]) + abs(a[2] - b[2])


def _row_edge(img: Image, y: int, x0: int, x1: int, step: int) -> float:
    xs = range(x0, x1, step)
    hits = sum(1 for x in xs if _diff(img.pixel(x, y), img.pixel(x, y - 1)) > EDGE_DIFF)
    return hits / max(1, len(xs))


def _col_edge(img: Image, x: int, y0: int, y1: int, step: int) -> float:
    ys = range(y0, y1, step)
    hits = sum(1 for y in ys if _diff(img.pixel(x, y), img.pixel(x - 1, y)) > EDGE_DIFF)
    return hits / max(1, len(ys))


def side_divider(img: Image, content: Box, scale: float) -> int | None:
    """Borda vertical de altura (quase) total na parte esquerda da área de
    conteúdo: a divisa da lista de módulos do NetAcad. Coordenada da janela."""
    step = max(2, round(3 * scale))
    best = None
    for x in range(content.x + round(80 * scale), content.x + int(content.w * 0.4)):
        # 0.8: o cabeçalho da página e botões laterais costumam interromper a divisa.
        if _col_edge(img, x, content.y + 1, content.y2 - 1, step) >= 0.8:
            best = x
    return best


def detect_content(img: Image, scale: float, top_px: int | None = None, left_px: int | None = None) -> Box:
    s = scale
    w, h = img.width, img.height
    step = max(2, round(3 * s))
    # Topo: última borda de largura total nos primeiros 180 px lógicos.
    if top_px is not None:
        top = round(top_px * s)
    else:
        top = 0
        for y in range(1, min(h - 1, round(180 * s), int(h * 0.3))):
            if _row_edge(img, y, 0, w, step) >= ROW_FRACTION:
                top = y
    # Base: primeira borda de largura total nos últimos 60 px lógicos.
    bottom = h
    for y in range(h - 1, max(top + 1, h - round(60 * s)), -1):
        if _row_edge(img, y, 0, w, step) >= ROW_FRACTION:
            bottom = y
    if left_px is not None:
        left = round(left_px * s)
    else:
        left = 0
        for x in range(1, int(w * 0.25)):
            if _col_edge(img, x, top + 1, bottom - 1, step) >= COL_FRACTION:
                left = x
    right = w
    for x in range(w - 1, int(w * 0.85), -1):
        if _col_edge(img, x, top + 1, bottom - 1, step) >= COL_FRACTION:
            right = x
    if right - left < 100 * s or bottom - top < 100 * s:
        return Box(0, 0, w, h)
    return Box(left, top, right - left, bottom - top)
