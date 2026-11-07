"""Medidas de pixels sobre regiões pequenas: tinta, cor, anéis e mudanças.

Complementa `page.classify`, que trabalha com os componentes conexos já
extraídos pelo ImageMagick. Aqui ficam as verificações locais (miolo de um
controle, se um círculo-alvo foi preenchido, quanto uma região mudou).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .image import Image
from .ocr import Box

INK_LUMA = 200      # abaixo disso é "tinta" (texto, bordas)
SAT_MIN = 60        # diferença max-min de canais para considerar colorido
COLOR_SAT = 70      # saturação mínima de áreas coloridas


def is_ink(px: tuple[int, int, int]) -> bool:
    r, g, b = px
    luma = (299 * r + 587 * g + 114 * b) // 1000
    return luma < INK_LUMA or (max(px) - min(px)) > SAT_MIN


def is_color(px: tuple[int, int, int]) -> bool:
    r, g, b = px
    luma = (299 * r + 587 * g + 114 * b) // 1000
    return (max(px) - min(px)) > COLOR_SAT and 40 < luma < 235


def ink_ratio(img: Image, box: Box, predicate=is_ink) -> float:
    total = hit = 0
    for y in range(max(0, box.y), min(img.height, box.y2)):
        for x in range(max(0, box.x), min(img.width, box.x2)):
            total += 1
            if predicate(img.pixel(x, y)):
                hit += 1
    return hit / total if total else 0.0


def shrink(box: Box, frac: float) -> Box:
    dx, dy = round(box.w * frac), round(box.h * frac)
    return Box(box.x + dx, box.y + dy, max(1, box.w - 2 * dx), max(1, box.h - 2 * dy))


def corner_ratio(img: Image, box: Box) -> float:
    """Tinta nos quatro cantos da caixa: alta em quadrados, baixa em círculos."""
    cw, ch = max(1, box.w // 6), max(1, box.h // 6)
    corners = [Box(box.x, box.y, cw, ch), Box(box.x2 - cw, box.y, cw, ch),
               Box(box.x, box.y2 - ch, cw, ch), Box(box.x2 - cw, box.y2 - ch, cw, ch)]
    return sum(ink_ratio(img, c) for c in corners) / 4


def cluster_boxes(boxes: list[Box], gap: int) -> list[list[Box]]:
    """Agrupa caixas a até `gap` pixels umas das outras (fecho transitivo)."""
    parent = list(range(len(boxes)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i, a in enumerate(boxes):
        for j in range(i + 1, len(boxes)):
            b = boxes[j]
            if a.x <= b.x2 + gap and a.x2 + gap >= b.x and a.y <= b.y2 + gap and a.y2 + gap >= b.y:
                ri, rj = find(i), find(j)
                if ri != rj:
                    parent[rj] = ri
    groups: dict[int, list[Box]] = {}
    for i, b in enumerate(boxes):
        groups.setdefault(find(i), []).append(b)
    return sorted(groups.values(), key=lambda g: (min(b.y for b in g), min(b.x for b in g)))


@dataclass
class RingState:
    kind: str       # "empty" (contorno/tracejado), "filled", "none"
    ring: float
    inner: float


def _ring_points(cx: float, cy: float, r: float, n: int = 32) -> list[tuple[float, float]]:
    return [(cx + r * math.cos(2 * math.pi * k / n), cy + r * math.sin(2 * math.pi * k / n)) for k in range(n)]


def _ink_at(img: Image, x: float, y: float) -> bool:
    xi, yi = round(x), round(y)
    return img.inside(xi, yi) and is_ink(img.pixel(xi, yi))


def ring_state(img: Image, box: Box) -> RingState:
    """Estado de um círculo conhecido: vazio (tracejado/contorno) ou preenchido."""
    cx, cy = box.cx, box.cy
    r = min(box.w, box.h) / 2 - 1
    best_ring = 0.0
    for rr in (r - 2, r - 1, r, r + 1):
        pts = _ring_points(cx, cy, rr)
        best_ring = max(best_ring, sum(_ink_at(img, x, y) for x, y in pts) / len(pts))
    inner_pts = _ring_points(cx, cy, r * 0.45, 16) + [(cx, cy)]
    inner = sum(_ink_at(img, x, y) for x, y in inner_pts) / len(inner_pts)
    if inner > 0.5:
        kind = "filled"
    elif best_ring > 0.3:
        kind = "empty"
    else:
        kind = "none"
    return RingState(kind, best_ring, inner)


def region_change(a: Image, b: Image, box: Box, tol: int = 40) -> float:
    """Fração de pixels de `box` que mudaram entre duas capturas."""
    if a.width != b.width or a.height != b.height:
        return 1.0
    total = changed = 0
    for y in range(max(0, box.y), min(a.height, box.y2)):
        for x in range(max(0, box.x), min(a.width, box.x2)):
            total += 1
            pa, pb = a.pixel(x, y), b.pixel(x, y)
            if abs(pa[0] - pb[0]) + abs(pa[1] - pb[1]) + abs(pa[2] - pb[2]) > tol:
                changed += 1
    return changed / total if total else 0.0


def image_change(a: Image, b: Image, tol: int = 40, step: int = 3) -> float:
    """Fração (amostrada) de pixels diferentes entre duas imagens inteiras."""
    if a.width != b.width or a.height != b.height:
        return 1.0
    total = changed = 0
    for y in range(0, a.height, step):
        for x in range(0, a.width, step):
            total += 1
            pa, pb = a.pixel(x, y), b.pixel(x, y)
            if abs(pa[0] - pb[0]) + abs(pa[1] - pb[1]) + abs(pa[2] - pb[2]) > tol:
                changed += 1
    return changed / total if total else 0.0


class InkMask:
    """Máscara de tinta pré-calculada para uma região (consultas rápidas)."""

    def __init__(self, img: Image, area: Box):
        self.x0, self.y0 = max(0, area.x), max(0, area.y)
        self.x1, self.y1 = min(img.width, area.x2), min(img.height, area.y2)
        self.w = max(0, self.x1 - self.x0)
        self.mask = bytearray(self.w * max(0, self.y1 - self.y0))
        for y in range(self.y0, self.y1):
            row = (y - self.y0) * self.w
            for x in range(self.x0, self.x1):
                if is_ink(img.pixel(x, y)):
                    self.mask[row + x - self.x0] = 1

    def at(self, x: float, y: float) -> bool:
        xi, yi = round(x), round(y)
        if xi < self.x0 or yi < self.y0 or xi >= self.x1 or yi >= self.y1:
            return False
        return bool(self.mask[(yi - self.y0) * self.w + xi - self.x0])


@dataclass
class RingHit:
    box: Box
    kind: str       # "dashed", "ring" (contorno contínuo) ou "filled"
    score: float


def _ring_frac(mask: InkMask, cx: float, cy: float, r: float, tolerant: bool = True) -> tuple[float, int]:
    hits = []
    for x, y in _ring_points(cx, cy, r):
        if tolerant:
            dx, dy = (x - cx) / r, (y - cy) / r
            hits.append(mask.at(x, y) or mask.at(x - dx, y - dy) or mask.at(x + dx, y + dy))
        else:
            hits.append(mask.at(x, y))
    flips = sum(1 for a, b in zip(hits, hits[1:] + hits[:1]) if a != b)
    return sum(hits) / len(hits), flips


def _ring_candidate(mask: InkMask, cx: float, cy: float, r: float, s: float) -> RingHit | None:
    ring, flips = _ring_frac(mask, cx, cy, r)
    if ring < 0.35:
        return None
    outside, _ = _ring_frac(mask, cx, cy, r + 4 * s, tolerant=False)
    inside, _ = _ring_frac(mask, cx, cy, max(2.0, r - 4 * s), tolerant=False)
    center = mask.at(cx, cy)
    filled = inside > 0.6 and center
    score = ring - outside if filled else ring - max(outside, inside)
    if score < 0.3:
        return None
    if filled:
        kind = "filled"
    elif flips >= 8 and ring < 0.92:
        kind = "dashed"
    else:
        kind = "ring"
    return RingHit(Box(round(cx - r), round(cy - r), round(2 * r), round(2 * r)), kind, score)


def find_ring_near(img: Image, area: Box, scale: float, radius: float | None = None,
                   rmin: float = 9, rmax: float = 22) -> RingHit | None:
    """Melhor círculo dentro de `area` (centro precisa cair na área).

    Pontua a fração de tinta no anel menos a dos anéis vizinhos (fora e
    dentro): bordas retas que atravessam o círculo pesam igual nos três e
    são ignoradas. `radius` (em pixels de imagem), quando conhecido, restringe
    a busca. Varredura grossa seguida de refinamento.
    """
    s = scale
    if radius:
        radii = [radius + d * s for d in (-2, -1, 0, 1, 2)]
    else:
        radii = []
        r = rmin * s
        while r <= rmax * s:
            radii.append(r)
            r += max(1.0, s)
    pad = round(max(radii) + 6 * s)
    mask = InkMask(img, Box(area.x - pad, area.y - pad, area.w + 2 * pad, area.h + 2 * pad))
    coarse = max(2, round(2 * s))
    best: RingHit | None = None
    for cy in range(area.y, area.y2, coarse):
        for cx in range(area.x, area.x2, coarse):
            for r in radii[::2] if len(radii) > 3 else radii:
                cand = _ring_candidate(mask, cx, cy, r, s)
                if cand and (best is None or cand.score > best.score):
                    best = cand
    if best is None:
        return None
    bx, by, br = best.box.cx, best.box.cy, best.box.w / 2
    for cy in range(round(by) - coarse, round(by) + coarse + 1):
        for cx in range(round(bx) - coarse, round(bx) + coarse + 1):
            for r in (br - 1, br, br + 1):
                if r < 4:
                    continue
                cand = _ring_candidate(mask, cx, cy, r, s)
                if cand and cand.score > best.score:
                    best = cand
    return best
