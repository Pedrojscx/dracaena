"""Detecção automática da página a cada captura da janela inteira.

1. área de conteúdo (sem a interface do Vivaldi) por bordas de pixels;
2. um único OCR da área de conteúdo;
3. painel do quiz por âncoras; o recorte do painel recebe a análise já
   feita (sub-página), sem OCR de novo;
4. seta de avançar sob demanda (`find_arrow`).

Com `reuse`, um painel já detectado na mesma questão é recortado direto da
captura nova (sem OCR da área de conteúdo); é o caso das capturas de
conferência logo após um clique, que precisam do mesmo enquadramento.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from .image import Image, load
from .locate.content import detect_content, side_divider
from .locate.nextarrow import Arrow, find_next
from .locate.panel import find_panel
from .ocr import Box
from .page import Page, analyze, save_cache


@dataclass
class Detection:
    window: str
    scale: float
    content: Box
    panel: Box | None
    reason: str = ""
    anchors: list[str] | None = None
    module_right: int | None = None     # coordenadas da janela
    content_path: str = ""
    panel_path: str = ""

    def to_dict(self) -> dict:
        def b(x):
            return [x.x, x.y, x.w, x.h] if x else None
        return {"window": self.window, "scale": self.scale, "content": b(self.content), "panel": b(self.panel),
                "reason": self.reason, "anchors": self.anchors or [], "module_right": self.module_right,
                "content_path": self.content_path, "panel_path": self.panel_path}

    @classmethod
    def from_dict(cls, d: dict) -> "Detection":
        def b(x):
            return Box(*x) if x else None
        return cls(d["window"], d["scale"], b(d["content"]), b(d["panel"]), d.get("reason", ""),
                   d.get("anchors"), d.get("module_right"), d.get("content_path", ""), d.get("panel_path", ""))


def _crop(src: str, box: Box, out: str) -> None:
    subprocess.run(["magick", src, "-crop", f"{box.w}x{box.h}+{box.x}+{box.y}", "+repage",
                    "-define", "png:color-type=2", out], check=True, capture_output=True, timeout=30)


def _logical(value, scale: float) -> int | None:
    if value in (None, "", "auto"):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def detect(window_path: str, scale: float, cfg: dict | None = None, reuse: Box | None = None) -> Detection:
    cfg = cfg or {}
    img = load(window_path)
    stem = str(Path(window_path).with_suffix(""))
    content = detect_content(img, scale, _logical(cfg.get("CHROME_TOP_PX"), scale),
                             _logical(cfg.get("CHROME_LEFT_PX"), scale))
    det = Detection(window_path, scale, content, None)
    if reuse is not None and reuse.x2 <= img.width and reuse.y2 <= img.height:
        det.panel = reuse
        det.panel_path = f"{stem}.panel.png"
        _crop(window_path, reuse, det.panel_path)
        det.reason = "enquadramento reaproveitado"
        return det
    det.content_path = f"{stem}.content.png"
    _crop(window_path, content, det.content_path)
    cpage = analyze(det.content_path, scale)
    res = find_panel(cpage)
    det.anchors = res.anchors
    # Lista de módulos: pelos marcadores de progresso no OCR ou, se eles não
    # foram lidos, pela borda vertical que a separa do conteúdo.
    det.module_right = content.x + res.module_right if res.module_right is not None else None
    if det.module_right is None:
        divider = side_divider(img, content, scale)
        if divider is not None and (res.box is None or divider <= content.x + res.box.x):
            det.module_right = divider
    if res.box is None:
        det.reason = res.reason
        return det
    det.panel = Box(res.box.x + content.x, res.box.y + content.y, res.box.w, res.box.h)
    det.panel_path = f"{stem}.panel.png"
    _crop(window_path, det.panel, det.panel_path)
    save_cache(det.panel_path, cpage.subpage(res.box))
    return det


def content_page(det: Detection) -> Page | None:
    """Análise da área de conteúdo (do cache), se esta captura a teve."""
    if not det.content_path or not Path(det.content_path).exists():
        return None
    return analyze(det.content_path, det.scale)


def content_lines_outside_modules(det: Detection):
    """Linhas da área de conteúdo, sem a lista de módulos (para fim/botão final)."""
    page = content_page(det)
    if page is None:
        return []
    col = det.module_right - det.content.x if det.module_right is not None else None
    return [ln for ln in page.lines if col is None or ln.box.x >= col]


def find_arrow(det: Detection, img: Image | None = None) -> tuple[Arrow | None, str]:
    img = img or load(det.window)
    return find_next(img, content_page(det), det.content, det.panel, det.scale)
