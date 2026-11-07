"""Coordenadas: janela, monitor, escala e conversão imagem -> tela.

Convenções (iguais às do Hyprland):
- coordenadas "globais" são lógicas, no layout de todos os monitores, as
  mesmas de `hyprctl activewindow`, do dispatcher de cursor, do `slurp` e do
  `grim -g`;
- cada ciclo captura a janela inteira com `grim -s <escala do monitor dela>`,
  então um pixel lógico vira `escala` pixels de imagem. Nada é guardado
  entre execuções: toda coordenada é relativa à captura atual.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


class GeometryError(ValueError):
    pass


@dataclass
class WindowInfo:
    cls: str
    title: str
    x: int
    y: int
    w: int
    h: int
    monitor: str
    scale: float
    address: str = ""
    dpms: bool = True   # False = tela do monitor apagada (grim trava esperando quadro)

    def to_dict(self) -> dict:
        return {"class": self.cls, "title": self.title, "at": [self.x, self.y], "size": [self.w, self.h],
                "monitor": self.monitor, "scale": self.scale, "address": self.address, "dpms": self.dpms,
                "geometry": self.geometry}

    @property
    def geometry(self) -> str:
        """Região para `grim -g` (lógica, global)."""
        return f"{self.x},{self.y} {self.w}x{self.h}"


def window_info(window: dict, monitors: list[dict]) -> WindowInfo:
    """Cruza uma janela (`activewindow`/`clients`) com `hyprctl monitors -j`."""
    if not isinstance(window, dict) or "at" not in window or "size" not in window:
        raise GeometryError("nenhuma janela ativa")
    mon_ref = window.get("monitor")
    monitor = None
    for m in monitors:
        if m.get("id") == mon_ref or m.get("name") == mon_ref:
            monitor = m
            break
    if monitor is None:
        raise GeometryError(f"monitor {mon_ref!r} da janela não encontrado")
    return WindowInfo(
        cls=str(window.get("class", "")), title=str(window.get("title", "")),
        x=int(window["at"][0]), y=int(window["at"][1]),
        w=int(window["size"][0]), h=int(window["size"][1]),
        monitor=str(monitor.get("name")), scale=float(monitor.get("scale", 1.0)),
        address=str(window.get("address", "")), dpms=bool(monitor.get("dpmsStatus", True)))


def window_problems(win: WindowInfo, class_regex: str) -> list[str]:
    """Motivos para não capturar/agir nesta janela (vazio = ok)."""
    problems = []
    try:
        if not re.search(class_regex, win.cls):
            problems.append("Deixe o Vivaldi com o quiz em foco")
    except re.error as exc:
        problems.append(f"BROWSER_CLASS_REGEX inválida: {exc}")
    if not win.dpms:
        problems.append(f"a tela do monitor {win.monitor} está apagada (DPMS)")
    if win.w < 200 or win.h < 200:
        problems.append("janela do navegador pequena demais")
    return problems


def parse_point(text: str) -> tuple[int, int]:
    """Formato do `slurp -p` ('X,Y 1x1') ou 'X,Y'."""
    m = re.fullmatch(r"\s*(-?\d+),(-?\d+)(?:\s+\d+x\d+)?\s*", text)
    if not m:
        raise GeometryError(f"ponto inválido: {text!r}")
    return int(m.group(1)), int(m.group(2))


@dataclass
class Frame:
    """Origem global (lógica) e escala de uma imagem capturada ou recortada."""

    ox: float
    oy: float
    scale: float

    def to_global(self, ix: float, iy: float) -> tuple[int, int]:
        return round(self.ox + ix / self.scale), round(self.oy + iy / self.scale)

    def to_image(self, gx: float, gy: float) -> tuple[float, float]:
        return (gx - self.ox) * self.scale, (gy - self.oy) * self.scale

    def px(self, logical: float) -> float:
        """Distância lógica (ex.: CLICK_OFFSET_X) em pixels de imagem."""
        return logical * self.scale

    def sub(self, bx: float, by: float) -> "Frame":
        """Frame de um recorte que começa em (bx, by) pixels desta imagem."""
        return Frame(self.ox + bx / self.scale, self.oy + by / self.scale, self.scale)
