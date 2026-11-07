"""Imagens anotadas: cruz em cada clique, seta em cada arrasto, retângulos."""

from __future__ import annotations

import functools
import math
import subprocess
from pathlib import Path


@functools.lru_cache(maxsize=1)
def _font() -> list[str]:
    """Fonte com acentos para os rótulos (a padrão do magick pode não ter)."""
    for pattern in ("DejaVu Sans", "Liberation Sans", "Noto Sans", "sans-serif"):
        try:
            out = subprocess.run(["fc-match", "-f", "%{file}", pattern], capture_output=True, text=True,
                                 timeout=10, check=True).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return []
        if out and Path(out).exists():
            return ["-font", out]
    return []


def draw_args(marks: list[dict], scale: float = 1.0) -> list[str]:
    """Argumentos do `magick` para desenhar as marcas.

    Marca: {"kind": "click", "x", "y", "label"} | {"kind": "drag", "x", "y",
    "x2", "y2", "label"} | {"kind": "rect", "x", "y", "w", "h", "label"}.
    """
    r = max(8, round(10 * scale))
    sw = max(2, round(2 * scale))
    pt = max(12, round(13 * scale))
    args = _font() + ["-fill", "none", "-strokewidth", str(sw)]
    for i, m in enumerate(marks, 1):
        color = m.get("color", "#e0118a")
        args += ["-stroke", color, "-fill", "none"]
        x, y = round(m["x"]), round(m["y"])
        if m["kind"] == "rect":
            args += ["-draw", f"rectangle {x},{y} {x + round(m['w'])},{y + round(m['h'])}"]
        else:
            args += ["-draw", f"line {x - r},{y} {x + r},{y}", "-draw", f"line {x},{y - r} {x},{y + r}",
                     "-draw", f"circle {x},{y} {x + r // 2},{y}"]
        if m["kind"] == "drag":
            x2, y2 = round(m["x2"]), round(m["y2"])
            ang = math.atan2(y2 - y, x2 - x)
            a1 = (x2 - 3 * r // 2 * math.cos(ang - 0.4), y2 - 3 * r // 2 * math.sin(ang - 0.4))
            a2 = (x2 - 3 * r // 2 * math.cos(ang + 0.4), y2 - 3 * r // 2 * math.sin(ang + 0.4))
            args += ["-draw", f"line {x},{y} {x2},{y2}",
                     "-fill", color, "-draw",
                     f"polygon {x2},{y2} {round(a1[0])},{round(a1[1])} {round(a2[0])},{round(a2[1])}"]
        label = f"{i}. {m.get('label', '')}".strip()
        lx, ly = (x + round(m.get("w", 0)) + 4, y + pt) if m["kind"] == "rect" else (x + r + 3, y - r // 2)
        args += ["-stroke", "white", "-strokewidth", "3", "-fill", color, "-pointsize", str(pt),
                 "-annotate", f"+{lx}+{ly}", label,
                 "-stroke", "none", "-annotate", f"+{lx}+{ly}", label, "-strokewidth", str(sw)]
    return args


def annotate(src: str | Path, out: str | Path, marks: list[dict], scale: float = 1.0) -> None:
    cmd = ["magick", str(src)] + draw_args(marks, scale) + [str(out)]
    subprocess.run(cmd, check=True, capture_output=True, timeout=60)
