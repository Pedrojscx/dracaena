"""Seta de avançar para a próxima questão.

Ordem de busca (só aceita quando há exatamente um candidato):
  (a) o chevron ">" logo à direita da barra de questões Q1 Q2 ... Qn
      (fileira de bolhas iguais confirmada pelo OCR + pixels do chevron);
  (b) o botão de borda verde com chevron ">" na lateral direita do painel
      (pixels: componente verde vazado com um chevron apontando para a
      direita dentro).
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from ..image import Image
from ..ocr import Box
from ..page import Page
from ..widgets import is_ink, shrink

@dataclass
class Arrow:
    point: tuple[float, float]
    box: Box
    method: str          # "nav" ou "green"


def chevron_direction(img: Image, box: Box) -> str | None:
    """'right' (">"), 'left' ("<") ou None pela distribuição da tinta:
    no ">" o miolo vertical fica à direita das pontas de cima e de baixo."""
    pts = [(x, y) for y in range(max(0, box.y), min(img.height, box.y2))
           for x in range(max(0, box.x), min(img.width, box.x2)) if is_ink(img.pixel(x, y))]
    if len(pts) < 6:
        return None
    ys = [y for _, y in pts]
    xs = [x for x, _ in pts]
    y0, y1 = min(ys), max(ys)
    h = y1 - y0 + 1
    w = max(xs) - min(xs) + 1
    if h < 6 or w < 3:
        return None
    third = h / 3
    top = [x for x, y in pts if y < y0 + third]
    mid = [x for x, y in pts if y0 + third <= y < y0 + 2 * third]
    bot = [x for x, y in pts if y >= y0 + 2 * third]
    if not top or not mid or not bot:
        return None
    d = sum(mid) / len(mid) - (sum(top) / len(top) + sum(bot) / len(bot)) / 2
    if d > 0.2 * w:
        return "right"
    if d < -0.2 * w:
        return "left"
    return None


def _ink_clusters(img: Image, band: Box, max_gap: int) -> list[Box]:
    """Grupos de colunas com tinta dentro de `band` (da esquerda p/ direita)."""
    cols = []
    for x in range(max(0, band.x), min(img.width, band.x2)):
        ys = [y for y in range(max(0, band.y), min(img.height, band.y2)) if is_ink(img.pixel(x, y))]
        cols.append((x, min(ys), max(ys)) if ys else None)
    clusters: list[Box] = []
    cur = None
    gap = 0
    for c in cols:
        if c is None:
            gap += 1
            if cur is not None and gap > max_gap:
                clusters.append(cur)
                cur = None
            continue
        gap = 0
        x, ya, yb = c
        b = Box(x, ya, 1, yb - ya + 1)
        cur = b if cur is None else cur.union(b)
    if cur is not None:
        clusters.append(cur)
    return clusters


def nav_rows(page: Page) -> list[list[Box]]:
    """Fileiras da barra de questões: 3+ caixas do mesmo tamanho (molduras
    ou a bolha ativa preenchida) na mesma altura, com espaçamento regular,
    confirmadas pelo OCR (algum rótulo começando com "Q" na fileira) ou por
    cinco ou mais bolhas (os rótulos pequenos dentro de caixas nem sempre
    são lidos)."""
    s = page.scale
    boxes = [g.box for g in page.graphics if g.kind in ("frame", "filled", "button", "control")
             and 14 * s <= g.box.h <= 48 * s and g.box.w <= 90 * s]
    rows: list[list[Box]] = []
    for b in sorted(boxes, key=lambda b: (b.cy, b.x)):
        for row in rows:
            r0 = row[0]
            if abs(r0.cy - b.cy) <= 4 * s and abs(r0.h - b.h) <= 0.2 * r0.h and abs(r0.w - b.w) <= 0.35 * r0.w:
                row.append(b)
                break
        else:
            rows.append([b])
    good = []
    for row in rows:
        if len(row) < 3:
            continue
        row.sort(key=lambda b: b.x)
        # Centros em múltiplos inteiros do passo (tolera bolhas que o
        # detector perdeu), sem buracos maiores que 3 passos.
        diffs = [b.cx - a.cx for a, b in zip(row, row[1:])]
        pitch = min(diffs)
        if pitch < row[0].w * 0.8:
            continue
        if any(abs(d / pitch - round(d / pitch)) > 0.15 or round(d / pitch) > 3 for d in diffs):
            continue
        band = Box(row[0].x, row[0].y, row[-1].x2 - row[0].x, row[0].h)
        words = [w for ln in page.lines for w in ln.words if band.contains(w.box.cx, w.box.cy)]
        # Confirmação: OCR com rótulo "Q..." ou geometria forte (5+ bolhas).
        if any(w.text[:1] in ("Q", "q") for w in words) or len(row) >= 5:
            good.append(row)
    return good


def nav_candidates(img: Image, page: Page, origin: tuple[int, int] = (0, 0)) -> list[Arrow]:
    """(a) chevron ">" à direita da barra Q1..Qn. `page` é a análise da área
    de conteúdo; `origin` é o canto dela dentro de `img`."""
    s = page.scale
    ox, oy = origin
    rows = nav_rows(page)
    if len(rows) != 1:
        return []
    row = rows[0]
    last = row[-1]
    pitch = min(b.cx - a.cx for a, b in zip(row, row[1:]))
    cy = last.cy + oy
    # Até 3 passos além da última bolha detectada (a ativa, preenchida, ou
    # uma que o detector perdeu podem estar no caminho; grupos largos como
    # uma bolha são ignorados abaixo).
    band = Box(round(last.x2 + ox + 2 * s), round(cy - 16 * s), round(3 * pitch + 60 * s), round(32 * s))
    found = []
    for cl in _ink_clusters(img, band, max_gap=max(2, round(3 * s))):
        # Chevron tem largura de pelo menos ~1/3 da altura; a borda direita
        # arredondada de uma bolha (que parece um ")") é fina demais.
        if not (8 * s <= cl.h <= 40 * s and 0.35 * cl.h <= cl.w <= 30 * s):
            continue
        pad = max(1, round(2 * s))
        if chevron_direction(img, Box(cl.x - pad, cl.y - pad, cl.w + 2 * pad, cl.h + 2 * pad)) == "right":
            found.append(Arrow((cl.cx, cl.cy), cl, "nav"))
            break
    return found


def _is_green(px: tuple[int, int, int]) -> bool:
    r, g, b = px
    return g > 100 and g - r > 40 and g - b > 25


def green_candidates(img: Image, area: Box, panel: Box | None, scale: float) -> list[Arrow]:
    """(b) botões de borda verde com ">" na lateral direita do painel."""
    s = scale
    step = 2 if s < 1.5 else 3
    x0, y0 = max(0, area.x), max(0, area.y)
    x1, y1 = min(img.width, area.x2), min(img.height, area.y2)
    cols = (x1 - x0 + step - 1) // step
    rows = (y1 - y0 + step - 1) // step
    if cols <= 0 or rows <= 0:
        return []
    mask = bytearray(cols * rows)
    for r in range(rows):
        y = y0 + r * step
        for c in range(cols):
            if _is_green(img.pixel(x0 + c * step, y)):
                mask[r * cols + c] = 1
    seen = bytearray(cols * rows)
    found = []
    ref = panel or area
    for start in range(cols * rows):
        if not mask[start] or seen[start]:
            continue
        seen[start] = 1
        q = deque([start])
        minc = maxc = start % cols
        minr = maxr = start // cols
        count = 0
        while q:
            i = q.popleft()
            count += 1
            r, c = divmod(i, cols)
            minc, maxc, minr, maxr = min(minc, c), max(maxc, c), min(minr, r), max(maxr, r)
            for nr in (r - 1, r, r + 1):
                if 0 <= nr < rows:
                    for nc in (c - 1, c, c + 1):
                        if 0 <= nc < cols:
                            n = nr * cols + nc
                            if mask[n] and not seen[n]:
                                seen[n] = 1
                                q.append(n)
        box = Box(x0 + minc * step, y0 + minr * step, (maxc - minc + 1) * step, (maxr - minr + 1) * step)
        if not (24 * s <= box.w <= 90 * s and 24 * s <= box.h <= 90 * s and 0.6 <= box.w / box.h <= 1.6):
            continue
        if count * step * step / (box.w * box.h) > 0.6:
            continue  # botão cheio sem contorno: não é o padrão procurado
        if not (box.cx > ref.cx and box.cx <= ref.x2 + 160 * s and ref.y - 40 * s <= box.cy <= ref.y2 + 40 * s):
            continue
        if chevron_direction(img, shrink(box, 0.22)) != "right":
            continue
        found.append(Arrow((box.cx, box.cy), box, "green"))
    return found


def find_next(img: Image, content_page: Page | None, content: Box, panel: Box | None,
              scale: float) -> tuple[Arrow | None, str]:
    """Seta escolhida (coordenadas de `img`) e um resumo da busca."""
    nav = nav_candidates(img, content_page, (content.x, content.y)) if content_page else []
    if len(nav) == 1:
        return nav[0], "barra de questões"
    green = green_candidates(img, content, panel, scale)
    if len(green) == 1:
        return green[0], "botão verde"
    return None, f"barra de questões: {len(nav)} candidato(s); botão verde: {len(green)} candidato(s)"
