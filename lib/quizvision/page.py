"""Análise de uma captura: elementos gráficos + OCR limpo + texto de botões.

Pipeline:
1. `magick -connected-components` sobre a máscara de "tinta" lista cada
   componente conexo (rápido, em C).
2. Python classifica os componentes: controles (rádio/checkbox), círculos
   preenchidos (letras da associação), círculos tracejados (destinos da
   associação, formados por vários traços pequenos) e botões (retângulos
   preenchidos largos).
3. Esses gráficos são apagados (pintados de branco) antes do OCR da página,
   para o tesseract não ler círculos como "O" e emendá-los ao texto.
4. Cada botão é recortado, invertido e lido isoladamente (texto claro sobre
   fundo colorido não sobrevive à binarização da página inteira).

O resultado é serializável e fica em cache ao lado da imagem.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from . import ocr as ocrmod
from .image import Image, load
from .ocr import Box, Line, Word
from .widgets import cluster_boxes, corner_ratio, ink_ratio, is_color, shrink

CACHE_VERSION = 7
INK_THRESHOLD = "78%"  # luminância abaixo de ~199 vira tinta

_CC_LINE = re.compile(r"^\s*\d+:\s+(\d+)x(\d+)\+(-?\d+)\+(-?\d+)\s+\S+\s+(\d+)\s+(\S+)")


class PageError(RuntimeError):
    pass


@dataclass
class Graphic:
    kind: str           # control, filled, dashed, button, frame
    box: Box
    fill: float = 0.0   # área do componente / área da caixa
    shape: str = ""     # circle ou square (controles e preenchidos)
    checked: bool = False
    colored: bool = False

    def to_dict(self) -> dict:
        b = self.box
        return {"kind": self.kind, "box": [b.x, b.y, b.w, b.h], "fill": round(self.fill, 3),
                "shape": self.shape, "checked": self.checked, "colored": self.colored}

    @classmethod
    def from_dict(cls, d: dict) -> "Graphic":
        return cls(d["kind"], Box(*d["box"]), d.get("fill", 0.0), d.get("shape", ""),
                   d.get("checked", False), d.get("colored", False))


@dataclass
class Page:
    width: int
    height: int
    scale: float
    lines: list[Line] = field(default_factory=list)
    graphics: list[Graphic] = field(default_factory=list)

    def of_kind(self, *kinds: str) -> list[Graphic]:
        return [g for g in self.graphics if g.kind in kinds]

    @property
    def text(self) -> str:
        return "\n".join(ln.text for ln in self.lines)

    def subpage(self, box: Box) -> "Page":
        """Recorte da análise: só o que está inteiro dentro de `box`, com
        coordenadas relativas ao canto do recorte."""
        def inside(b: Box) -> bool:
            return b.x >= box.x and b.y >= box.y and b.x2 <= box.x2 and b.y2 <= box.y2

        def shift(b: Box) -> Box:
            return Box(b.x - box.x, b.y - box.y, b.w, b.h)

        lines = []
        for ln in self.lines:
            if not inside(ln.box):
                continue
            words = [Word(w.text, w.conf, shift(w.box), w.key) for w in ln.words]
            lines.append(Line(words, ln.button, shift(ln.button_box) if ln.button_box else None))
        graphics = [Graphic(g.kind, shift(g.box), g.fill, g.shape, g.checked, g.colored)
                    for g in self.graphics if inside(g.box)]
        return Page(box.w, box.h, self.scale, lines, graphics)

    def to_dict(self) -> dict:
        return {
            "width": self.width, "height": self.height, "scale": self.scale,
            "lines": [{"button": ln.button,
                       "button_box": [ln.button_box.x, ln.button_box.y, ln.button_box.w, ln.button_box.h]
                       if ln.button_box else None,
                       "words": [{"text": w.text, "conf": w.conf, "box": [w.box.x, w.box.y, w.box.w, w.box.h],
                                  "key": list(w.key)} for w in ln.words]} for ln in self.lines],
            "graphics": [g.to_dict() for g in self.graphics],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Page":
        lines = []
        for ld in d["lines"]:
            bb = ld.get("button_box")
            lines.append(Line([Word(w["text"], w["conf"], Box(*w["box"]), tuple(w["key"])) for w in ld["words"]],
                              ld.get("button", False), Box(*bb) if bb else None))
        return cls(d["width"], d["height"], d["scale"], lines, [Graphic.from_dict(g) for g in d["graphics"]])


@dataclass
class Component:
    box: Box
    area: int


def parse_components(text: str) -> list[Component]:
    """Lê a saída verbose de `-connected-components` (só objetos de frente)."""
    out = []
    for raw in text.splitlines():
        m = _CC_LINE.match(raw)
        if not m:
            continue
        w, h, x, y, area = (int(v) for v in m.groups()[:5])
        color = m.group(6)
        if "255" not in color and "white" not in color and "100%" not in color:
            continue  # fundo/buracos (preto após a negação)
        out.append(Component(Box(x, y, w, h), area))
    return out


def _overlaps(a: Box, b: Box, frac: float = 0.5) -> bool:
    ix = max(0, min(a.x2, b.x2) - max(a.x, b.x))
    iy = max(0, min(a.y2, b.y2) - max(a.y, b.y))
    inter = ix * iy
    return inter >= frac * min(a.w * a.h, b.w * b.h)


def _looks_like_letter(comp: Component, components: list[Component]) -> bool:
    """Letra grande (título, fonte ampliada) e não controle: tem um vizinho
    de altura parecida colado na mesma linha, como as letras de uma palavra.
    Rádios e checkboxes ficam afastados do rótulo e são bem mais altos que
    as letras dele."""
    b = comp.box
    reach = 0.5 * b.h
    for other in components:
        o = other.box
        if o is b or not 0.7 * b.h <= o.h <= 1.4 * b.h:
            continue
        overlap = min(b.y2, o.y2) - max(b.y, o.y)
        if overlap < 0.6 * min(b.h, o.h):
            continue
        gap = max(o.x - b.x2, b.x - o.x2)
        if -1 <= gap <= reach:
            return True
    return False


def _contains_text(comp: Component, components: list[Component]) -> bool:
    """Contorno com duas ou mais letras dentro (ex.: bolha "Q10" da barra de
    questões): é um rótulo, não um rádio/checkbox. Rádio marcado tem só um
    ponto dentro; checkbox marcado tem a marca como "buraco" branco."""
    b = comp.box
    inner = 0
    for other in components:
        o = other.box
        if o is b:
            continue
        if o.x > b.x and o.y > b.y and o.x2 < b.x2 and o.y2 < b.y2 and o.h >= 0.25 * b.h:
            inner += 1
            if inner >= 2:
                return True
    return False


def classify(components: list[Component], img: Image, scale: float,
             color_components: list[Component] | None = None) -> list[Graphic]:
    """Separa controles, círculos, tracejados e botões dos componentes.

    `color_components` vem de uma máscara só de pixels coloridos; recupera
    círculos coloridos que tocam bordas cinzentas (e por isso se fundem a
    elas na máscara de tinta).
    """
    s = scale
    graphics: list[Graphic] = []
    small: list[Box] = []
    for comp in components:
        b = comp.box
        fill = comp.area / max(1, b.w * b.h)
        aspect = b.w / max(1, b.h)
        # Moldura: contorno que envolve texto (bolhas Q1..Qn, caixas de itens).
        # Só a borda é apagada antes do OCR, para o texto de dentro ser lido.
        if fill < 0.35 and 14 * s <= b.h <= 140 * s and b.w >= 0.9 * b.h and _contains_text(comp, components):
            graphics.append(Graphic("frame", b, fill, "rect"))
            continue
        if 16 * s <= b.w <= 64 * s and 16 * s <= b.h <= 64 * s and 0.75 <= aspect <= 1.33:
            if _looks_like_letter(comp, components) or _contains_text(comp, components):
                continue
            corner = corner_ratio(img, b)
            shape = "square" if corner > 0.45 else "circle"
            colored = ink_ratio(img, shrink(b, 0.15), is_color) > 0.3
            if fill > 0.6:
                graphics.append(Graphic("filled", b, fill, shape, True, colored))
            elif fill < 0.5:
                inner = ink_ratio(img, shrink(b, 0.3))
                graphics.append(Graphic("control", b, fill, shape, inner > 0.3, colored))
            continue
        if 18 * s <= b.h <= 80 * s and 40 * s <= b.w <= 700 * s and aspect >= 1.6 and fill > 0.6:
            colored = ink_ratio(img, shrink(b, 0.2), is_color) > 0.3
            graphics.append(Graphic("button", b, fill, "rect", False, colored))
            continue
        if comp.area <= 24 * s * s and b.w <= 8 * s and b.h <= 8 * s:
            small.append(b)
    for group in cluster_boxes(small, gap=round(5 * s)):
        if len(group) < 5:
            continue
        box = group[0]
        for g in group[1:]:
            box = box.union(g)
        if not (18 * s <= box.w <= 64 * s and 18 * s <= box.h <= 64 * s and 0.75 <= box.w / box.h <= 1.33):
            continue
        if ink_ratio(img, shrink(box, 0.3)) > 0.15:
            continue
        graphics.append(Graphic("dashed", box, 0.0, "circle"))
    for comp in color_components or []:
        b = comp.box
        fill = comp.area / max(1, b.w * b.h)
        if not (16 * s <= b.w <= 64 * s and 16 * s <= b.h <= 64 * s and 0.75 <= b.w / b.h <= 1.33):
            continue
        if fill < 0.55 or any(_overlaps(b, g.box) for g in graphics):
            continue
        shape = "square" if corner_ratio(img, b) > 0.45 else "circle"
        graphics.append(Graphic("filled", b, fill, shape, True, True))
    graphics.sort(key=lambda g: (g.box.y, g.box.x))
    return graphics


def _run(cmd: list[str], timeout: int = 60) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError as exc:
        raise PageError(f"programa ausente: {cmd[0]}") from exc
    except subprocess.CalledProcessError as exc:
        raise PageError(f"{cmd[0]} falhou: {exc.stderr.strip()[:300]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise PageError(f"{cmd[0]} excedeu o tempo") from exc


def find_components(image_path: Path) -> list[Component]:
    proc = _run(["magick", str(image_path), "-alpha", "off", "-colorspace", "Gray", "-threshold", INK_THRESHOLD,
                 "-negate", "-define", "connected-components:verbose=true",
                 "-define", "connected-components:area-threshold=2",
                 "-connected-components", "8", "null:"])
    return parse_components(proc.stdout)


def find_color_components(image_path: Path) -> list[Component]:
    """Componentes da máscara de croma (max-min dos canais) acima de ~27%."""
    proc = _run(["magick", str(image_path), "-alpha", "off", "-colorspace", "HCL", "-channel", "G", "-separate",
                 "+channel", "-threshold", "27%", "-define", "connected-components:verbose=true",
                 "-define", "connected-components:area-threshold=20",
                 "-connected-components", "8", "null:"])
    return parse_components(proc.stdout)


def _masked_copy(image_path: Path, graphics: list[Graphic], out: Path, scale: float) -> None:
    cmd = ["magick", str(image_path), "-alpha", "off", "-fill", "white", "-stroke", "none"]
    pad = max(1, round(2 * scale))
    for g in graphics:
        b = g.box
        if g.kind == "frame":
            continue
        cmd += ["-draw", f"rectangle {b.x - pad},{b.y - pad} {b.x2 + pad},{b.y2 + pad}"]
    sw = max(3, round(3 * scale))
    cmd += ["-fill", "none", "-stroke", "white", "-strokewidth", str(sw)]
    for g in graphics:
        if g.kind == "frame":
            b = g.box
            cmd += ["-draw", f"rectangle {b.x},{b.y} {b.x2 - 1},{b.y2 - 1}"]
    cmd.append(str(out))
    _run(cmd)


def _button_line(image_path: Path, g: Graphic, tmp: Path, idx: int) -> Line | None:
    b = g.box
    shave = max(2, b.h // 10)
    up = 3
    border = 20
    crop = tmp / f"btn{idx}.png"
    _run(["magick", str(image_path), "-crop", f"{b.w}x{b.h}+{b.x}+{b.y}", "+repage", "-shave", f"{shave}x{shave}",
          "-colorspace", "Gray", "-negate", "-auto-level", "-threshold", "50%", "-resize", f"{up * 100}%",
          "-bordercolor", "white", "-border", str(border), str(crop)])
    tsv = ocrmod.run_tesseract(crop, upscale=1.0, psm=7)
    words = []
    for w in ocrmod.parse_tsv(tsv):
        if not re.search(r"[A-Za-z0-9]", w.text):
            continue
        bx = b.x + shave + (w.box.x - border) / up
        by = b.y + shave + (w.box.y - border) / up
        words.append(Word(w.text, w.conf, Box(round(bx), round(by), max(1, round(w.box.w / up)),
                                              max(1, round(w.box.h / up))), (9000 + idx, 0, 0)))
    if not words:
        return None
    return Line(words, True, b)


_GLYPH_JUNK = re.compile(r"^[\W_]+$")


def is_junk(text: str, conf: float, min_conf: float = 35.0) -> bool:
    """Palavra-lixo: pontuação solta, confiança muito baixa ou fragmento
    curto misturando letras e símbolos (restos de círculos e bordas)."""
    if conf < min_conf or _GLYPH_JUNK.match(text):
        return True
    alnum = sum(ch.isalnum() for ch in text)
    if alnum <= 2 and len(text) > alnum and not re.fullmatch(r"\(?\w{1,2}[.,:;)?!]?|\w+'\w+", text):
        return True
    if len(text) == 1 and conf < 70:
        return True
    return False


def clean_lines(lines: list[Line], min_conf: float = 35.0) -> list[Line]:
    """Remove palavras-lixo (ver `is_junk`)."""
    out = []
    for ln in lines:
        words = [w for w in ln.words if not is_junk(w.text, w.conf, min_conf)]
        if words:
            out.append(Line(words, ln.button, ln.button_box))
    return out


def _cache_paths(path: Path, digest: str, scale: float) -> list[Path]:
    # Cache ao lado da imagem e, se QV_CACHE_DIR estiver definido, também
    # por conteúdo (útil nos testes, que reutilizam as mesmas telas).
    caches = [path.with_name(path.name + ".page.json")]
    shared = os.environ.get("QV_CACHE_DIR")
    if shared:
        caches.append(Path(shared) / f"{digest}-{scale:g}.page.json")
    return caches


def save_cache(image_path: str | Path, page: Page) -> None:
    """Grava `page` como análise de `image_path` (ex.: recorte de outra página)."""
    path = Path(image_path)
    digest = hashlib.sha1(path.read_bytes()).hexdigest()
    payload = json.dumps({"sha1": digest, "version": CACHE_VERSION, "scale": page.scale, "page": page.to_dict()})
    for cache in _cache_paths(path, digest, page.scale):
        try:
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(payload, encoding="utf-8")
        except OSError:
            pass


def analyze(image_path: str | Path, scale: float = 1.0, use_cache: bool = True,
            upscale: float | None = None) -> Page:
    path = Path(image_path)
    if not shutil.which("magick") or not shutil.which("tesseract"):
        raise PageError("magick e tesseract são necessários")
    digest = hashlib.sha1(path.read_bytes()).hexdigest()
    if use_cache:
        for cache in _cache_paths(path, digest, scale):
            if not cache.exists():
                continue
            try:
                data = json.loads(cache.read_text(encoding="utf-8"))
                if data.get("sha1") == digest and data.get("version") == CACHE_VERSION and data.get("scale") == scale:
                    return Page.from_dict(data["page"])
            except (ValueError, KeyError, TypeError):
                pass
    img = load(path)
    graphics = classify(find_components(path), img, scale, find_color_components(path))
    if upscale is None:
        upscale = min(2.0, max(1.0, 2.0 / scale))
    with tempfile.TemporaryDirectory(prefix="qv-page-") as tmpdir:
        tmp = Path(tmpdir)
        masked = tmp / "masked.png"
        _masked_copy(path, graphics, masked, scale)
        lines = ocrmod.group_lines(ocrmod.parse_tsv(ocrmod.run_tesseract(masked, upscale=upscale), scale=upscale))
        lines = clean_lines(lines)
        for i, g in enumerate(graphics):
            if g.kind == "button":
                bl = _button_line(path, g, tmp, i)
                if bl:
                    lines.append(bl)
    lines.sort(key=lambda ln: (ln.box.y, ln.box.x))
    page = Page(img.width, img.height, scale, lines, graphics)
    if use_cache:
        save_cache(path, page)
    return page
