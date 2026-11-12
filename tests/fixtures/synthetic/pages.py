#!/usr/bin/env python3
"""Gera as páginas HTML sintéticas dos testes (nada vem de site real).

Cobre radio, checkbox, <select>, ARIA em shadow DOM, feedback, reset, tela de
resultado e casos de erro (sem Submit, só envio global, alternativa com rótulo
sobreposto). O comportamento (Submit, feedback, Reset) vem de `sim.js`.

Uso: pages.py <pasta de saída>
"""

from __future__ import annotations

import html
import sys
from pathlib import Path

E = html.escape
CSS = """<style>
[hidden]{display:none!important}
body{font:16px sans-serif;margin:24px} .q{border:1px solid #888;margin:0 0 24px;padding:12px}
label,button,[role=radio],[role=checkbox],[role=option],[role=button]{display:block;margin:6px 0;padding:6px;cursor:pointer}
[role=radio],[role=checkbox],[role=option]{border:1px solid #aaa} [aria-checked=true],[aria-selected=true]{background:#cfc}
.fb{min-height:1.2em} .hiddeninput{position:absolute;opacity:0;width:1px;height:1px}
.fake{display:block;border:1px solid #aaa;padding:8px;margin:6px 0}
</style>"""
GLOBALS = ('<div id="globals"><button type="button" data-sim="global">Finish quiz</button>'
           '<button type="button" data-sim="global">Submit all answers</button></div>')
CONTROLS = ('<button type="button" data-sim="submit">Submit</button>'
            '<button type="button" data-sim="reset" hidden>Try again</button>'
            '<div class="fb" role="status"></div>')


def page(title: str, body: str) -> str:
    return (f'<!doctype html>\n<html lang="en"><head><meta charset="utf-8"><title>{E(title)}</title>{CSS}</head>'
            f'<body><h1>{E(title)}</h1>{body}</body></html>\n')


def radio(qid: str, legend: str, options: list[str], correct: int, name: str | None = None) -> str:
    name = name or qid
    items = "".join(f'<label><input type="radio" name="{name}" value="{i}"> {E(o)}</label>' for i, o in enumerate(options))
    return (f'<section class="q" id="{qid}" data-correct="{correct}"><fieldset><legend>{E(legend)}</legend>{items}'
            f'</fieldset>{CONTROLS}</section>')


def checkbox(qid: str, legend: str, options: list[str], correct: list[int]) -> str:
    items = "".join(f'<label><input type="checkbox" name="{qid}" value="{i}"> {E(o)}</label>' for i, o in enumerate(options))
    return (f'<section class="q" id="{qid}" data-correct="{",".join(map(str, correct))}"><fieldset><legend>{E(legend)}'
            f'</legend>{items}</fieldset>{CONTROLS}</section>')


def selects(qid: str, legend: str, rows: list[tuple[str, list[str]]], correct: list[int]) -> str:
    # `correct` = índice DOM da opção certa em cada select (0 é o espaço reservado).
    parts = []
    for n, (label, opts) in enumerate(rows):
        lis = '<option value="" disabled selected>Choose…</option>' + "".join(
            f'<option value="{i}">{E(o)}</option>' for i, o in enumerate(opts))
        parts.append(f'<label for="{qid}-s{n}">{E(label)}</label><select id="{qid}-s{n}">{lis}</select>')
    return (f'<section class="q" id="{qid}" data-correct="{",".join(map(str, correct))}"><fieldset><legend>{E(legend)}'
            f'</legend>{"".join(parts)}</fieldset>{CONTROLS}</section>')


def shadow(tag: str, inner: str, attrs: str = "") -> str:
    return f'<{tag}{(" " + attrs) if attrs else ""}><template shadowrootmode="open">{inner}</template></{tag}>'


def aria_radio(qid: str, label: str, options: list[str], correct: int) -> str:
    items = "".join(f'<div role="radio" aria-checked="false" tabindex="0">{E(o)}</div>' for o in options)
    inner = (f'<section class="q" id="{qid}" data-correct="{correct}"><div id="{qid}-t">{E(label)}</div>'
             f'<div role="radiogroup" aria-labelledby="{qid}-t">{items}</div>'
             '<div role="button" tabindex="0" data-sim="submit">Check answer</div>'
             '<div role="button" tabindex="0" data-sim="reset" hidden>Try again</div><div class="fb" role="status"></div></section>')
    return shadow("quiz-item", inner)


def aria_checkbox(qid: str, label: str, options: list[str], correct: list[int]) -> str:
    items = "".join(f'<div role="checkbox" aria-checked="false" tabindex="0">{E(o)}</div>' for o in options)
    inner = (f'<section class="q" id="{qid}" data-correct="{",".join(map(str, correct))}"><div aria-hidden="false">{E(label)}</div>'
             f'<div role="group" aria-label="{E(label)}">{items}</div>'
             '<div role="button" tabindex="0" data-sim="submit">Check answer</div>'
             '<div role="button" tabindex="0" data-sim="reset" hidden>Try again</div><div class="fb" role="status"></div></section>')
    return shadow("quiz-item", inner)


def aria_listbox(qid: str, label: str, options: list[str], correct: int) -> str:
    items = "".join(f'<div role="option" aria-selected="false" tabindex="0">{E(o)}</div>' for o in options)
    inner = (f'<section class="q" id="{qid}" data-correct="{correct}"><p>{E(label)}</p>'
             f'<div role="listbox" aria-label="{E(label)}">{items}</div>'
             '<div role="button" tabindex="0" data-sim="submit">Check answer</div>'
             '<div role="button" tabindex="0" data-sim="reset" hidden>Try again</div><div class="fb" role="status"></div></section>')
    return shadow("quiz-item", inner)


def styled_radio() -> str:
    """Input escondido por baixo de um rótulo estilizado: o alvo correto é o rótulo."""
    items = "".join(
        f'<label class="fake"><input class="hiddeninput" type="radio" name="st" value="{i}"><span>{E(o)}</span></label>'
        for i, o in enumerate(["Red", "Green", "Blue"]))
    return (f'<section class="q" id="st" data-correct="2"><fieldset><legend>What color is a clear daytime sky?</legend>{items}</fieldset>{CONTROLS}</section>')


def build() -> dict[str, str]:
    q = {}
    q["radio.html"] = page("Practice A", radio("r1", "Which animal barks?", ["Cat", "Dog", "Cow", "Bird"], 1)
                           + radio("r2", "Pick the largest number.", ["3", "17", "9"], 1) + GLOBALS)
    q["checkbox.html"] = page("Practice B", checkbox(
        "c1", "Select the two even numbers. (Choose two.)", ["1", "2", "3", "4", "5"], [1, 3]) + GLOBALS)
    q["select.html"] = page("Practice C", selects(
        "d1", "Match each shape with its number of sides.",
        [("Triangle", ["2", "3", "4"]), ("Square", ["3", "4", "5"]), ("Pentagon", ["4", "5", "6"])], [2, 2, 2]) + GLOBALS)
    q["aria.html"] = page("Practice D", aria_radio("a1", "Which planet is known as the red planet?",
                                                  ["Venus", "Mars", "Jupiter"], 1)
                          + aria_checkbox("a2", "Select the primary colors. (Choose two.)",
                                          ["Red", "Green", "Blue", "Black"], [0, 2])
                          + aria_listbox("a3", "Pick the smallest number.", ["8", "2", "5"], 1) + GLOBALS)
    q["styled.html"] = page("Practice E", styled_radio() + GLOBALS)
    q["result.html"] = page("Practice F", '<h2>Quiz complete</h2><p>Thanks for practicing.</p>')
    q["nosubmit.html"] = page("Practice G", (
        '<section class="q" id="n1" data-correct="0"><fieldset><legend>Pick the first.</legend>'
        '<label><input type="radio" name="n1" value="0"> First</label><label><input type="radio" name="n1" value="1"> Second</label>'
        '</fieldset><div class="fb" role="status"></div></section>') + GLOBALS)
    # Duas questões num único formulário com um só envio: não há Submit por questão.
    q["oneform.html"] = page("Practice H", (
        '<form id="f" onsubmit="return false">' + radio("f1", "First question?", ["Yes", "No"], 0).replace(CONTROLS, '')
        + radio("f2", "Second question?", ["Yes", "No"], 1).replace(CONTROLS, '')
        + '<button type="submit">Submit</button></form>'))
    return q


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    out = Path(argv[1])
    out.mkdir(parents=True, exist_ok=True)
    files = build()
    for name, text in files.items():
        (out / name).write_text(text, encoding="utf-8")
    print(f"{len(files)} páginas sintéticas em {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
