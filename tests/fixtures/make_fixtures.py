#!/usr/bin/env python3
"""Gera telas sintéticas no estilo do NetAcad com o ImageMagick.

Uso: make_fixtures.py <pasta de saída>

Para cada tela grava <nome>.png e <nome>.truth.json com as posições
desenhadas (pontos de clique esperados, caixas de controles etc.), usadas
pelos testes para conferir as funções de localização. A renderização é toda
feita pelo `magick`; este script só descreve as cenas.

Há dois níveis: painéis do quiz (<nome>.png) e janelas inteiras do Vivaldi
com o NetAcad (win_<nome>[__variante].png), que colam um painel dentro da
interface do navegador (abas, endereço, faixa/painel lateral), do cabeçalho
e da lista de módulos do NetAcad, com a barra Q1..Q10 e os botões verdes.
O gabarito da janela traz os itens do painel já deslocados, mais "panel",
"content" e "next" (a seta esperada, se houver).
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

BLUE = "#0a6ebd"
GRAY = "#8c8c8c"
TEXT = "#1f2933"
LETTER_COLORS = ["#1f78b4", "#e07b00", "#2e9e44", "#9b3fb5", "#c0392b", "#16808c"]


def font(bold: bool = False) -> str:
    pattern = "Liberation Sans:bold" if bold else "Liberation Sans"
    try:
        out = subprocess.run(["fc-match", "-f", "%{file}", pattern], capture_output=True, text=True, check=True)
        if out.stdout.strip():
            return out.stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        pass
    return "DejaVu-Sans-Bold" if bold else "DejaVu-Sans"


class Scene:
    def __init__(self, name: str, w: int = 900, h: int = 720, s: float = 1.0):
        self.name, self.s = name, s
        self.w, self.h = round(w * s), round(h * s)
        self.args: list[str] = []
        self.composites: list[tuple[str, int, int]] = []
        self.truth: dict = {"name": name, "scale": s, "size": [self.w, self.h], "items": {}}
        self.regular, self.bold = font(False), font(True)

    def v(self, n: float) -> int:
        return round(n * self.s)

    def text(self, x, y, text, size=16, bold=False, color=TEXT):
        """`y` é a linha de base, em unidades lógicas."""
        self.args += ["-font", self.bold if bold else self.regular, "-pointsize", str(self.v(size)),
                      "-fill", color, "-stroke", "none", "-annotate", f"+{self.v(x)}+{self.v(y)}", text]

    def rect(self, x, y, w, h, fill="none", stroke=GRAY, sw=1.5, radius=0):
        if radius:
            draw = (f"roundrectangle {self.v(x)},{self.v(y)} {self.v(x + w)},{self.v(y + h)} "
                    f"{self.v(radius)},{self.v(radius)}")
        else:
            draw = f"rectangle {self.v(x)},{self.v(y)} {self.v(x + w)},{self.v(y + h)}"
        self.args += ["-fill", fill, "-stroke", stroke, "-strokewidth", str(sw * self.s), "-draw", draw]

    def circle(self, cx, cy, r, fill="none", stroke=GRAY, sw=2, dashed=False):
        dash = f"stroke-dasharray {self.v(4)} {self.v(4)} " if dashed else ""
        self.args += ["-fill", fill, "-stroke", stroke, "-strokewidth", str(sw * self.s),
                      "-draw", f"{dash}circle {self.v(cx)},{self.v(cy)} {self.v(cx + r)},{self.v(cy)}"]

    def poly(self, points, fill):
        pts = " ".join(f"{self.v(x)},{self.v(y)}" for x, y in points)
        self.args += ["-fill", fill, "-stroke", "none", "-draw", f"polygon {pts}"]

    def line(self, x1, y1, x2, y2, color, sw=2):
        self.args += ["-stroke", color, "-strokewidth", str(sw * self.s), "-fill", "none",
                      "-draw", f"line {self.v(x1)},{self.v(y1)} {self.v(x2)},{self.v(y2)}"]

    def item(self, key, **data):
        self.truth["items"][key] = data

    def render(self, out: Path):
        png = out / f"{self.name}.png"
        cmd = ["magick", "-size", f"{self.w}x{self.h}", "xc:white"] + self.args
        for path, x, y in self.composites:
            cmd += [path, "-geometry", f"+{x}+{y}", "-composite"]
        cmd += ["-strip", "-depth", "8", "-define", "png:color-type=2", str(png)]
        subprocess.run(cmd, check=True)
        (out / f"{self.name}.truth.json").write_text(json.dumps(self.truth, indent=1), encoding="utf-8")


# ---------------------------------------------------------------- componentes

def header(sc: Scene, title: str):
    sc.rect(0, 0, 900, 56, fill="#f2f5f8", stroke="#f2f5f8")
    sc.text(32, 37, title, size=20, bold=True)
    sc.item("title", text=title)


def stem(sc: Scene, lines: list[str], y: int = 100) -> int:
    for i, ln in enumerate(lines):
        sc.text(32, y + i * 26, ln, size=17)
    return y + len(lines) * 26


def option(sc: Scene, key: str, text: str, y: int, kind: str, checked: bool = False, x: int = 96):
    """Alternativa com rádio ou checkbox; controle centrado 32 px à esquerda do texto."""
    cx, cy = x - 32, y - 6
    if kind == "radio":
        sc.circle(cx, cy, 10, stroke=BLUE if checked else GRAY)
        if checked:
            sc.circle(cx, cy, 5, fill=BLUE, stroke=BLUE, sw=1)
    else:
        if checked:
            sc.rect(cx - 10, cy - 10, 20, 20, fill=BLUE, stroke=BLUE, radius=2)
            sc.line(cx - 5, cy, cx - 1, cy + 5, "white", sw=2.5)
            sc.line(cx - 1, cy + 5, cx + 6, cy - 5, "white", sw=2.5)
        else:
            sc.rect(cx - 10, cy - 10, 20, 20, stroke=GRAY, sw=1.5, radius=2)
    sc.text(x, y, text, size=16)
    sc.item(key, text=text, control=[sc.v(cx - 11), sc.v(cy - 11), sc.v(22), sc.v(22)],
            click=[sc.v(cx), sc.v(cy)], text_x=sc.v(x), text_cy=sc.v(y - 6), checked=checked, kind=kind)


def button(sc: Scene, key: str, label: str, x: int, y: int, w: int = 110, h: int = 40, color=BLUE):
    sc.rect(x, y, w, h, fill=color, stroke=color, radius=4)
    sc.text(x + 18, y + 26, label, size=16, bold=True, color="white")
    sc.item(key, text=label, box=[sc.v(x), sc.v(y), sc.v(w), sc.v(h)], click=[sc.v(x + w / 2), sc.v(y + h / 2)])


def dropdown(sc: Scene, key: str, x: int, y: int, value: str, w: int = 300):
    sc.rect(x, y, w, 36, fill="white", stroke=GRAY, radius=3)
    sc.text(x + 12, y + 24, value, size=15, color=TEXT if value != "Please select an option" else "#55606b")
    sc.poly([(x + w - 26, y + 15), (x + w - 14, y + 15), (x + w - 20, y + 22)], fill="#55606b")
    sc.item(key, value=value, box=[sc.v(x), sc.v(y), sc.v(w), sc.v(36)], click=[sc.v(x + w / 2), sc.v(y + 18)])


def dropdown_list(sc: Scene, key: str, x: int, y: int, options: list[str], w: int = 300):
    sc.rect(x, y, w, 8 + 32 * len(options), fill="white", stroke="#6b7785", sw=1)
    for i, opt in enumerate(options):
        oy = y + 4 + 32 * i
        sc.text(x + 12, oy + 22, opt, size=15)
        sc.item(f"{key}_{i}", text=opt, click=[sc.v(x + w / 2), sc.v(oy + 16)],
                box=[sc.v(x), sc.v(oy), sc.v(w), sc.v(32)])


def letter_circle(sc: Scene, key: str, cx: int, cy: int, letter: str, color: str):
    sc.circle(cx, cy, 15, fill=color, stroke=color, sw=1)
    sc.text(cx - 6, cy + 6, letter, size=17, bold=True, color="white")
    sc.item(key, letter=letter, center=[sc.v(cx), sc.v(cy)], box=[sc.v(cx - 15), sc.v(cy - 15), sc.v(30), sc.v(30)])


def target_circle(sc: Scene, key: str, cx: int, cy: int, linked: str | None = None, color: str = BLUE):
    if linked:
        sc.circle(cx, cy, 15, fill=color, stroke=color, sw=1)
        sc.text(cx - 6, cy + 6, linked, size=17, bold=True, color="white")
    else:
        sc.circle(cx, cy, 15, stroke="#7a8794", sw=2, dashed=True)
    sc.item(key, center=[sc.v(cx), sc.v(cy)], box=[sc.v(cx - 15), sc.v(cy - 15), sc.v(30), sc.v(30)],
            linked=linked)


# ---------------------------------------------------------------- cenas

SINGLE_OPTS = ["RAM", "Hard disk drive", "Power supply unit", "Network interface card"]


def scene_single(name, checked=None, s=1.0, number=1, feedback=None, extra_button=None, submit=True):
    sc = Scene(name, s=s)
    header(sc, f"Question {number}")
    y = stem(sc, ["Which component converts AC power into DC power for the",
                  "internal components of a computer?"])
    for i, text in enumerate(SINGLE_OPTS):
        option(sc, f"opt{i}", text, y + 40 + i * 44, "radio", checked=(checked == i))
    if submit:
        button(sc, "submit", "Submit", 32, 460)
    if extra_button:
        button(sc, "extra", extra_button, 170, 460, w=150)
    if feedback == "correct":
        sc.rect(32, 530, 836, 70, fill="#e6f4ea", stroke="#2e9e44")
        sc.text(52, 560, "Correct", size=18, bold=True, color="#1e7b34")
        sc.text(52, 586, "You answered correctly.", size=15)
    elif feedback == "incorrect":
        sc.rect(32, 530, 836, 70, fill="#fdecea", stroke="#c0392b")
        sc.text(52, 560, "Incorrect", size=18, bold=True, color="#a93226")
        sc.text(52, 586, "That is not right. Review the material and try again.", size=15)
    sc.item("question", number=number)
    return sc


MULTI_OPTS = ["Motherboard", "Optical drive", "CPU", "Monitor", "Keyboard"]


def scene_multi(name, checked=(), number=2):
    sc = Scene(name)
    header(sc, f"Question {number}")
    y = stem(sc, ["Which two components are located inside the computer case?",
                  "(Choose two.)"])
    for i, text in enumerate(MULTI_OPTS):
        option(sc, f"opt{i}", text, y + 40 + i * 44, "checkbox", checked=(i in checked))
    button(sc, "submit", "Submit", 32, 500)
    sc.item("question", number=number)
    return sc


DD_ITEMS = [
    "A UPS protects a computer against power outages.",
    "Thermal paste is applied between the CPU and the RAM.",
    "An ESD strap should be connected to the computer chassis.",
]


def scene_dropdown(name, values=("", "", ""), open_index=None, number=3):
    sc = Scene(name)
    header(sc, f"Question {number}")
    stem(sc, ["Indicate whether each statement is true or false."])
    y = 160
    for i, text in enumerate(DD_ITEMS):
        sc.text(32, y, text, size=16)
        sc.item(f"stmt{i}", text=text, y=sc.v(y))
        dropdown(sc, f"dd{i}", 32, y + 14, values[i] or "Please select an option")
        y += 100
    button(sc, "submit", "Submit", 32, 470)
    if open_index is not None:
        ly = 160 + open_index * 100 + 14 + 38
        dropdown_list(sc, "list", 32, ly, ["Please select an option", "True", "False"])
    sc.item("question", number=number)
    return sc


MATCH_LEFT = [("A", "Motherboard"), ("B", "Power supply"), ("C", "Heat sink")]
MATCH_RIGHT = [
    "Dissipates heat away from the processor",
    "Main printed circuit board of the computer",
    "Converts AC power into lower voltage DC power",
]


def scene_match_letters(name, links=(None, None, None), number=4):
    """Variante 1: termos com letra à esquerda, descrições com círculo à direita."""
    sc = Scene(name)
    header(sc, f"Question {number}")
    stem(sc, ["Match the component to its description."])
    for i, (letter, text) in enumerate(MATCH_LEFT):
        y = 170 + i * 80
        sc.rect(32, y - 26, 260, 52, fill="#f7f9fb", stroke="#c9d1d9", radius=4)
        sc.text(48, y + 6, text, size=16)
        letter_circle(sc, f"L{letter}", 292, y, letter, LETTER_COLORS[i])
        sc.item(f"left{i}", text=text, letter=letter)
    for i, text in enumerate(MATCH_RIGHT):
        y = 170 + i * 80
        sc.rect(420, y - 26, 448, 52, fill="#f7f9fb", stroke="#c9d1d9", radius=4)
        link = links[i]
        color = LETTER_COLORS["ABC".index(link)] if link else BLUE
        target_circle(sc, f"T{i}", 420, y, linked=link, color=color)
        sc.text(450, y + 6, text, size=15)
        sc.item(f"right{i}", text=text)
    button(sc, "submit", "Submit", 32, 430)
    sc.item("question", number=number)
    return sc


CAT_LEFT = [("A", "Input device"), ("B", "Output device")]
CAT_RIGHT = ["Scanner", "Printer", "Microphone", "Projector"]


def scene_match_categories(name, links=(None, None, None, None), number=5):
    """Variante 2: 'Categories' com letras e 'Options' com círculos tracejados."""
    sc = Scene(name)
    header(sc, f"Question {number}")
    stem(sc, ["Match the device to the correct category."])
    sc.text(32, 160, "Categories", size=17, bold=True)
    sc.text(420, 160, "Options", size=17, bold=True)
    for i, (letter, text) in enumerate(CAT_LEFT):
        y = 210 + i * 80
        sc.rect(32, y - 26, 260, 52, fill="#f7f9fb", stroke="#c9d1d9", radius=4)
        sc.text(48, y + 6, text, size=16)
        letter_circle(sc, f"L{letter}", 292, y, letter, LETTER_COLORS[i])
        sc.item(f"left{i}", text=text, letter=letter)
    for i, text in enumerate(CAT_RIGHT):
        y = 210 + i * 70
        sc.rect(420, y - 24, 300, 48, fill="#f7f9fb", stroke="#9aa5b1", radius=4)
        link = links[i]
        color = LETTER_COLORS["AB".index(link)] if link else BLUE
        target_circle(sc, f"T{i}", 420, y, linked=link, color=color)
        sc.text(450, y + 6, text, size=15)
        sc.item(f"right{i}", text=text)
    button(sc, "submit", "Submit", 32, 520)
    sc.item("question", number=number)
    return sc


AMBIG_OPTS = ["Ethernet cable", "Ethernet cables", "Wireless adapter", "Bluetooth dongle"]


def scene_ambiguous(name, number=11):
    """Duas alternativas quase iguais: uma resposta com erro de digitação
    casa com as duas e precisa ser recusada como ambígua."""
    sc = Scene(name)
    header(sc, f"Question {number}")
    y = stem(sc, ["Which item connects a desktop to a wired network?"])
    for i, text in enumerate(AMBIG_OPTS):
        option(sc, f"opt{i}", text, y + 40 + i * 44, "radio")
    button(sc, "submit", "Submit", 32, 400)
    sc.item("question", number=number)
    return sc


def scene_two_submits(name):
    sc = scene_single(name, checked=0, submit=True)
    button(sc, "submit2", "Submit", 300, 460)
    return sc


def scene_submit_all(name, checked=1):
    sc = scene_single(name, checked=checked, number=10, submit=False)
    button(sc, "final", "Submit All", 32, 460, w=140)
    return sc


def scene_final(name):
    sc = Scene(name)
    header(sc, "Module 1 Quiz")
    sc.text(32, 140, "Assessment Complete", size=26, bold=True)
    sc.text(32, 190, "Your score: 9 of 10 (90%)", size=18)
    sc.text(32, 230, "Results are saved to your gradebook.", size=16)
    sc.item("question", number=None)
    return sc


LONG_OPTS = ["To store the BIOS settings when the computer is powered off",
             "To provide a backup power source for the RAM modules",
             "To keep the system clock running while the computer is off",
             "To supply power to the CPU fan during startup"]


def scene_long(name, part: str, checked=None):
    """Questão mais alta que a área visível: 'top' corta as alternativas."""
    sc = Scene(name, h=520)
    if part == "top":
        header(sc, "Question 6")
        stem(sc, ["A technician replaces the CMOS battery on a motherboard.",
                  "After the replacement, the computer keeps the correct date",
                  "and time even after being unplugged for several days.",
                  "Considering how the motherboard firmware stores its",
                  "configuration, what is the main purpose of this battery?"])
        option(sc, "opt0", LONG_OPTS[0], 300 + 140, "radio", checked=(checked == 0))
        sc.item("question", number=6)
    else:
        sc.text(32, 40, "configuration, what is the main purpose of this battery?", size=17)
        for i, text in enumerate(LONG_OPTS):
            option(sc, f"opt{i}", text, 100 + i * 44, "radio", checked=(checked == i))
        button(sc, "submit", "Submit", 32, 300)
        sc.item("question", number=None)
    return sc


# ---------------------------------------------------------------- janela do Vivaldi

GREEN = "#2f9e4f"
CHROME = "#26262b"


def chevron(sc: Scene, cx, cy, size, color, direction="right", sw=2.5):
    h = size / 2
    if direction == "right":
        pts = [(cx - h / 2, cy - h), (cx + h / 2, cy), (cx - h / 2, cy + h)]
    else:
        pts = [(cx + h / 2, cy - h), (cx - h / 2, cy), (cx + h / 2, cy + h)]
    sc.line(*pts[0], *pts[1], color, sw=sw)
    sc.line(*pts[1], *pts[2], color, sw=sw)


MODULES = [("1.0 Introduction", "1/1"), ("1.1 PC Components", "2/2"), ("1.2 Power Supplies", "3/4"),
           ("1.3 Storage", "0/3"), ("1.4 Module Quiz", "75%")]


def scene_window(panel: str, arrow: str = "both", sidebar: bool = False, s: float = 1.0,
                 name: str | None = None, out: Path | None = None) -> Scene:
    """Janela inteira do Vivaldi com o NetAcad e o painel `panel` colado.

    arrow: both (chevron da barra Q1..Qn e botões verdes), nav, green ou none.
    """
    ptruth = json.loads((out / f"{panel}.truth.json").read_text(encoding="utf-8"))
    pw, ph = ptruth["size"]
    W, H = 1720, 1000
    sc = Scene(name or f"win_{panel}", w=W, h=H, s=s)
    x0 = 320 if sidebar else 40
    # Interface do Vivaldi: abas, barra de endereço, faixa lateral, status.
    sc.rect(0, 0, W, 34, fill="#1b1b1f", stroke="#1b1b1f")
    sc.rect(50, 4, 250, 30, fill="#34343a", stroke="#34343a", radius=5)
    sc.text(64, 24, "Module 1 Quiz - NetAcad", size=13, color="#e8e8ea")
    sc.rect(305, 4, 210, 30, fill="#26262b", stroke="#26262b", radius=5)
    sc.text(318, 24, "Caixa de entrada", size=13, color="#a8a8ad")
    sc.rect(0, 34, W, 44, fill="#34343a", stroke="#34343a")
    sc.rect(120, 41, 1180, 30, fill="#26262b", stroke="#26262b", radius=6)
    sc.text(136, 61, "netacad.com/launch?id=it-essentials-8", size=14, color="#d0d0d4")
    sc.rect(0, 78, 40, H - 78, fill=CHROME, stroke=CHROME)
    for i in range(5):
        sc.rect(11, 96 + i * 40, 18, 18, fill="#55555c", stroke="#55555c", radius=3)
    if sidebar:
        sc.rect(40, 78, 280, H - 78, fill="#2e2e33", stroke="#2e2e33")
        sc.line(320, 78, 320, H, "#4a4a50", sw=1)
        for i, t in enumerate(["Favoritos", "Netacad", "Documentos", "Notas"]):
            sc.text(60, 112 + i * 30, t, size=14, color="#d8d8dc")
    sc.rect(0, H - 22, W, 22, fill=CHROME, stroke=CHROME)
    # Página do NetAcad: cabeçalho e lista de módulos à esquerda.
    sc.rect(x0, 78, W - x0, 50, fill="#0b3c5d", stroke="#0b3c5d")
    sc.text(x0 + 20, 110, "Cisco Networking Academy", size=17, bold=True, color="white")
    sc.rect(x0, 128, 260, H - 22 - 128, fill="#f4f6f8", stroke="#f4f6f8")
    sc.line(x0 + 260, 128, x0 + 260, H - 22, "#c3ccd5", sw=1)
    for i, (title, prog) in enumerate(MODULES):
        y = 168 + i * 46
        sc.text(x0 + 14, y, title, size=14)
        sc.text(x0 + 222, y, prog, size=13, color="#4a5560")
    # Barra de questões Q1..Q10.
    px, py = x0 + 300, 210
    current = ptruth["items"].get("question", {}).get("number")
    quiz = panel != "final"          # tela de resultado não tem barra nem botões
    nav_y = 150
    if quiz:
        chevron(sc, x0 + 290, nav_y + 14, 18, "#55606b", "left")
        for i in range(10):
            bx = x0 + 310 + i * 48
            active = (i + 1) == current
            sc.rect(bx, nav_y, 40, 28, fill=BLUE if active else "white", stroke=BLUE if active else "#9aa5b1",
                    radius=4)
            sc.text(bx + (9 if i < 9 else 5), nav_y + 20, f"Q{i + 1}", size=13, bold=active,
                    color="white" if active else TEXT)
        last_x2 = x0 + 310 + 9 * 48 + 40
        if arrow in ("both", "nav"):
            cx = last_x2 + 22
            chevron(sc, cx, nav_y + 14, 18, "#55606b", "right")
            sc.item("next", kind="nav", box=[sc.v(cx - 10), sc.v(nav_y + 2), sc.v(20), sc.v(24)],
                    click=[sc.v(cx), sc.v(nav_y + 14)])
    # Painel do quiz colado.
    sc.composites.append((str(out / f"{panel}.png"), sc.v(px), sc.v(py)))
    pw_l, ph_l = pw / s, ph / s
    if arrow in ("both", "green") and quiz:
        gy = py + 260
        rx = px + pw_l + 18
        sc.rect(rx, gy, 46, 46, fill="white", stroke=GREEN, sw=2.5, radius=8)
        chevron(sc, rx + 23, gy + 23, 20, GREEN, "right")
        lx = px - 64
        sc.rect(lx, gy, 46, 46, fill="white", stroke=GREEN, sw=2.5, radius=8)
        chevron(sc, lx + 23, gy + 23, 20, GREEN, "left")
        if arrow == "green":
            sc.item("next", kind="green", box=[sc.v(rx), sc.v(gy), sc.v(46), sc.v(46)],
                    click=[sc.v(rx + 23), sc.v(gy + 23)])
        sc.item("prev_green", box=[sc.v(lx), sc.v(gy), sc.v(46), sc.v(46)])
    # Gabarito: itens do painel deslocados para a janela.
    ox, oy = sc.v(px), sc.v(py)
    for key, item in ptruth["items"].items():
        moved = dict(item)
        for k in ("box", "control"):
            if k in moved:
                b = moved[k]
                moved[k] = [b[0] + ox, b[1] + oy, b[2], b[3]]
        for k in ("click", "center"):
            if k in moved:
                moved[k] = [moved[k][0] + ox, moved[k][1] + oy]
        for k, d in (("text_x", ox), ("text_cy", oy), ("y", oy)):
            if k in moved:
                moved[k] = moved[k] + d
        sc.item(key, **moved)
    sc.item("panel", box=[ox, oy, pw, ph])
    sc.item("content", box=[sc.v(x0), sc.v(78), sc.v(W - x0), sc.v(H - 22 - 78)], module_right=sc.v(x0 + 260))
    sc.truth["arrow"] = arrow
    sc.truth["sidebar"] = sidebar
    return sc


WINDOW_VARIANTS = [
    ("single", "nav", False, "win_single__nav"),
    ("single", "green", False, "win_single__green"),
    ("single", "none", False, "win_single__none"),
    ("single", "both", True, "win_single__sidebar"),
    ("single_selected", "none", False, "win_single_selected__none"),
    ("single_correct", "none", False, "win_single_correct__none"),
    ("dropdown", "green", True, "win_dropdown__green_sidebar"),
    ("match_categories", "both", True, "win_match_categories__sidebar"),
]


def window_scenes(out: Path, panels: list[Scene]) -> list[Scene]:
    wins = []
    for sc in panels:
        wins.append(scene_window(sc.name, "both", False, s=sc.s, out=out))
    for panel, arrow, sidebar, name in WINDOW_VARIANTS:
        wins.append(scene_window(panel, arrow, sidebar, name=name, out=out))
    return wins


def scenes() -> list[Scene]:
    out = [
        scene_single("single"),
        scene_single("single_selected", checked=2),
        scene_single("single_hidpi", s=2.0),
        scene_single("single_correct", checked=2, feedback="correct"),
        scene_single("single_incorrect", checked=1, feedback="incorrect", extra_button="Reset"),
        scene_single("single_retry_selected", checked=2, feedback="incorrect", extra_button="Reset"),
        scene_single("single_sel1", checked=1),
        scene_single("single_q7", number=7),
        scene_single("single_q7_selected", number=7, checked=2),
        scene_multi("multi"),
        scene_multi("multi_partial", checked=(0,)),
        scene_multi("multi_wrong", checked=(1,)),
        scene_multi("multi_done", checked=(0, 2)),
        scene_multi("multi8", number=8),
        scene_multi("multi8_0", checked=(0,), number=8),
        scene_multi("multi8_done", checked=(0, 2), number=8),
        scene_multi("multi9_wrong", checked=(1,), number=9),
        scene_multi("multi9_wrong_0", checked=(0, 1), number=9),
        scene_multi("multi9_0", checked=(0,), number=9),
        scene_multi("multi9_done", checked=(0, 2), number=9),
        scene_ambiguous("ambiguous"),
        scene_dropdown("dropdown"),
        scene_dropdown("dropdown_open0", open_index=0),
        scene_dropdown("dropdown_v1", values=("True", "", "")),
        scene_dropdown("dropdown_v1_open1", values=("True", "", ""), open_index=1),
        scene_dropdown("dropdown_v2", values=("True", "False", "")),
        scene_dropdown("dropdown_v2_open2", values=("True", "False", ""), open_index=2),
        scene_dropdown("dropdown_done", values=("True", "False", "True")),
        scene_match_letters("match_letters"),
        scene_match_letters("match_letters_1", links=("C", None, None)),
        scene_match_letters("match_letters_2", links=("C", "A", None)),
        scene_match_letters("match_letters_done", links=("C", "A", "B")),
        scene_match_categories("match_categories"),
        scene_match_categories("match_categories_1", links=("A", None, None, None)),
        scene_match_categories("match_categories_2", links=("A", "B", None, None)),
        scene_match_categories("match_categories_3", links=("A", "B", "A", None)),
        scene_match_categories("match_categories_done", links=("A", "B", "A", "B")),
        scene_two_submits("two_submits"),
        scene_submit_all("submit_all"),
        scene_submit_all("submit_all_sel2", checked=2),
        scene_final("final"),
        scene_long("long_top", "top"),
        scene_long("long_bottom", "bottom"),
        scene_long("long_bottom_selected", "bottom", checked=2),
    ]
    return out


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    if not shutil.which("magick"):
        print("magick (ImageMagick 7) não encontrado", file=sys.stderr)
        return 1
    out = Path(argv[1])
    out.mkdir(parents=True, exist_ok=True)
    panels = scenes()
    for sc in panels:
        sc.render(out)
    wins = window_scenes(out, panels)
    for sc in wins:
        sc.render(out)
    print(f"{len(panels)} painéis e {len(wins)} janelas em {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
