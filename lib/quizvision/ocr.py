"""OCR via tesseract (saída TSV) e agrupamento em palavras e linhas.

A execução do tesseract fica isolada em `run_tesseract`; todo o resto opera
sobre o texto TSV e pode ser testado sem binários externos.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path


class OcrError(RuntimeError):
    pass


@dataclass
class Box:
    x: int
    y: int
    w: int
    h: int

    @property
    def x2(self) -> int:
        return self.x + self.w

    @property
    def y2(self) -> int:
        return self.y + self.h

    @property
    def cx(self) -> float:
        return self.x + self.w / 2

    @property
    def cy(self) -> float:
        return self.y + self.h / 2

    def union(self, other: "Box") -> "Box":
        x, y = min(self.x, other.x), min(self.y, other.y)
        return Box(x, y, max(self.x2, other.x2) - x, max(self.y2, other.y2) - y)

    def contains(self, px: float, py: float) -> bool:
        return self.x <= px <= self.x2 and self.y <= py <= self.y2


@dataclass
class Word:
    text: str
    conf: float
    box: Box
    key: tuple[int, int, int]  # (bloco, parágrafo, linha) do tesseract


@dataclass
class Line:
    words: list[Word] = field(default_factory=list)
    button: bool = False            # texto lido de dentro de um botão colorido
    button_box: Box | None = None   # caixa do botão, quando `button`

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words)

    @property
    def box(self) -> Box:
        b = self.words[0].box
        for w in self.words[1:]:
            b = b.union(w.box)
        return b

    @property
    def conf(self) -> float:
        return min(w.conf for w in self.words)

    def to_dict(self) -> dict:
        b = self.box
        return {"text": self.text, "conf": round(self.conf, 1), "box": [b.x, b.y, b.w, b.h]}


def parse_tsv(tsv: str, scale: float = 1.0, min_conf: float = 0.0) -> list[Word]:
    """Converte a saída TSV do tesseract em palavras.

    `scale` é o fator de ampliação aplicado antes do OCR; as caixas são
    devolvidas nas coordenadas da imagem original.
    """
    words: list[Word] = []
    lines = tsv.splitlines()
    if not lines:
        return words
    header = lines[0].split("\t")
    try:
        idx = {name: header.index(name) for name in (
            "level", "block_num", "par_num", "line_num", "left", "top", "width", "height", "conf", "text")}
    except ValueError as exc:
        raise OcrError("TSV do tesseract sem cabeçalho esperado") from exc
    for row in lines[1:]:
        cols = row.split("\t")
        if len(cols) < len(header):
            cols += [""] * (len(header) - len(cols))
        if cols[idx["level"]] != "5":
            continue
        text = cols[idx["text"]].strip()
        if not text:
            continue
        try:
            conf = float(cols[idx["conf"]])
        except ValueError:
            continue
        if conf < min_conf:
            continue
        box = Box(
            round(int(cols[idx["left"]]) / scale),
            round(int(cols[idx["top"]]) / scale),
            max(1, round(int(cols[idx["width"]]) / scale)),
            max(1, round(int(cols[idx["height"]]) / scale)),
        )
        key = (int(cols[idx["block_num"]]), int(cols[idx["par_num"]]), int(cols[idx["line_num"]]))
        words.append(Word(text, conf, box, key))
    return words


def group_lines(words: list[Word], gap_factor: float = 2.5) -> list[Line]:
    """Agrupa palavras por linha do tesseract e separa trechos distantes.

    Duas colunas na mesma altura às vezes caem na mesma linha do tesseract;
    um espaço horizontal maior que `gap_factor` vezes a altura da linha
    indica colunas diferentes.
    """
    by_key: dict[tuple[int, int, int], list[Word]] = {}
    for w in words:
        by_key.setdefault(w.key, []).append(w)
    result: list[Line] = []
    for group in by_key.values():
        group.sort(key=lambda w: w.box.x)
        current = Line([group[0]])
        for w in group[1:]:
            prev = current.words[-1]
            height = max(prev.box.h, w.box.h)
            if w.box.x - prev.box.x2 > gap_factor * height:
                result.append(current)
                current = Line([w])
            else:
                current.words.append(w)
        result.append(current)
    result.sort(key=lambda ln: (ln.box.y, ln.box.x))
    return result


def _cache_path(image_path: Path) -> Path:
    return image_path.with_name(image_path.name + ".ocr.json")


def run_tesseract(image_path: str | Path, upscale: float = 2.0, psm: int = 3,
                  lang: str = "eng", extra: list[str] | None = None) -> str:
    """Roda o tesseract e devolve o TSV. Amplia antes com o ImageMagick."""
    tess = shutil.which("tesseract")
    if not tess:
        raise OcrError("tesseract não encontrado no PATH")
    src = Path(image_path)
    with tempfile.TemporaryDirectory(prefix="qv-ocr-") as tmp:
        target = src
        if upscale and upscale != 1.0:
            magick = shutil.which("magick")
            if not magick:
                raise OcrError("magick não encontrado no PATH")
            target = Path(tmp) / "ocr.png"
            pct = f"{upscale * 100:.0f}%"
            subprocess.run(
                [magick, str(src), "-alpha", "off", "-colorspace", "Gray", "-filter", "Triangle",
                 "-resize", pct, str(target)],
                check=True, capture_output=True, timeout=30)
        cmd = [tess, str(target), "stdout", "-l", lang, "--psm", str(psm), "-c", "preserve_interword_spaces=0"]
        cmd += extra or []
        cmd.append("tsv")
        env = dict(os.environ, OMP_THREAD_LIMIT="1")
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60, env=env)
        if proc.returncode != 0:
            raise OcrError(f"tesseract falhou: {proc.stderr.strip()[:300]}")
        return proc.stdout


def ocr_words(image_path: str | Path, upscale: float = 2.0, psm: int = 3, use_cache: bool = True) -> list[Word]:
    p = Path(image_path)
    digest = hashlib.sha1(p.read_bytes()).hexdigest()
    cache = _cache_path(p)
    if use_cache and cache.exists():
        try:
            data = json.loads(cache.read_text(encoding="utf-8"))
            if data.get("sha1") == digest and data.get("upscale") == upscale and data.get("psm") == psm:
                return [Word(w["text"], w["conf"], Box(*w["box"]), tuple(w["key"])) for w in data["words"]]
        except (ValueError, KeyError, TypeError):
            pass
    tsv = run_tesseract(p, upscale=upscale, psm=psm)
    words = parse_tsv(tsv, scale=upscale)
    if use_cache:
        payload = {
            "sha1": digest, "upscale": upscale, "psm": psm,
            "words": [{"text": w.text, "conf": w.conf, "box": [w.box.x, w.box.y, w.box.w, w.box.h],
                       "key": list(w.key)} for w in words],
        }
        try:
            cache.write_text(json.dumps(payload), encoding="utf-8")
        except OSError:
            pass
    return words


def ocr_lines(image_path: str | Path, upscale: float = 2.0, psm: int = 3, use_cache: bool = True) -> list[Line]:
    return group_lines(ocr_words(image_path, upscale=upscale, psm=psm, use_cache=use_cache))


def ocr_char(image_path: str | Path, box: Box, upscale: float = 4.0) -> tuple[str, float]:
    """Lê uma única letra maiúscula dentro de um círculo (`box`).

    Corta 20% de cada lado (sobra o disco e a letra), binariza e, se o disco
    escuro dominar, inverte para deixar a letra escura sobre fundo branco.
    """
    tess = shutil.which("tesseract")
    magick = shutil.which("magick")
    if not tess or not magick:
        raise OcrError("tesseract ou magick ausente")
    shave_x, shave_y = max(1, round(box.w * 0.2)), max(1, round(box.h * 0.2))
    with tempfile.TemporaryDirectory(prefix="qv-char-") as tmp:
        out = Path(tmp) / "char.png"
        geom = f"{box.w}x{box.h}+{box.x}+{box.y}"
        subprocess.run(
            [magick, str(image_path), "-crop", geom, "+repage", "-shave", f"{shave_x}x{shave_y}",
             "-colorspace", "Gray", "-auto-level", "-threshold", "60%", str(out)],
            check=True, capture_output=True, timeout=20)
        mean = subprocess.run([magick, str(out), "-format", "%[fx:mean]", "info:"],
                              capture_output=True, text=True, timeout=20)
        try:
            dark_disc = float(mean.stdout.strip() or 1) < 0.5
        except ValueError:
            dark_disc = True
        cmd = [magick, str(out)] + (["-negate"] if dark_disc else []) + [
            "-resize", f"{upscale * 100:.0f}%", "-bordercolor", "white", "-border", "15", str(out)]
        subprocess.run(cmd, check=True, capture_output=True, timeout=20)
        proc = subprocess.run(
            [tess, str(out), "stdout", "--psm", "10", "-c",
             "tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ", "tsv"],
            capture_output=True, text=True, timeout=30, env=dict(os.environ, OMP_THREAD_LIMIT="1"))
        words = parse_tsv(proc.stdout)
        if not words:
            return "", 0.0
        best = max(words, key=lambda w: w.conf)
        return best.text.strip()[:1].upper(), best.conf


def lines_to_json(lines: list[Line]) -> list[dict]:
    return [ln.to_dict() for ln in lines]


__all__ = ["Box", "Word", "Line", "OcrError", "parse_tsv", "group_lines", "ocr_words",
           "ocr_lines", "ocr_char", "run_tesseract", "lines_to_json"]
