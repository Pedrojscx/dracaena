#!/usr/bin/env python3
"""Gera fixtures HTML DERIVADAS da estrutura observada na Fase 0.

Não são cópias da página: reproduzem as tags, classes, papéis e atributos que
o quiz-helper lê (mcq-view, matching-view/matching-dropdown-view,
object-matching-view, buttons-view, assessment-toolbar-view, faixa Q1..Qn,
finalscreen-view), com textos de exemplo, em shadow DOM declarativo
(`<template shadowrootmode="open">`). O comportamento (marcar, Submit, avanço,
tela de envio) vem de `html/sim.js`, injetado pelo servidor de teste.

Uso: derived.py <pasta de saída>
"""

from __future__ import annotations

import html
import sys
from pathlib import Path

E = html.escape


def shadow(tag: str, inner: str, attrs: str = "") -> str:
    return f'<{tag}{(" " + attrs) if attrs else ""}><template shadowrootmode="open">{inner}</template></{tag}>'


def header(cid: str, title: str, stem: str, instruction: str = "") -> str:
    instr = (f'<div tabindex="0" class="component__instruction instruction__text"><div class="component__instruction-inner">'
             f'{E(instruction)}</div></div>') if instruction else ""
    inner = (f'<div class="component__header-wrapper"><div class="component__header"><div class="component__header-inner">'
             f'<div class="component__title"><div tabindex="0" role="heading" class="component__title-inner" aria-level="4">'
             f'<span class="accessibility-completion-indicator">Incomplete</span>{E(title)}</div></div>'
             f'<div class="component__content"><div tabindex="0" class="component__body"><div class="component__body-inner">'
             f'<p><span>{E(stem)}</span></p></div></div></div>{instr}</div></div></div>')
    return f'<div class="component__header-container">{shadow("base-view", inner, "type=\"component\"")}</div>'


def buttons_view() -> str:
    inner = ('<div class="btn__container"><div class="btn__response-container">'
             '<div class="btn__marking item-state js-btn-marking" aria-label=""></div>'
             '<div class="js-answer-live-region aria-label" aria-live="assertive" aria-atomic="true"></div>'
             '<button class="btn-text btn__action js-btn-action" aria-label="Submit Your answer will be submitted">Submit</button>'
             '<button class="btn-text btn__action btn__feedback js-btn-feedback" aria-label="Show feedback" aria-disabled="false">'
             'Show feedback</button></div></div>')
    return f'<div class="btn-container">{shadow("buttons-view", inner)}</div>'


def mcq(cid: str, title: str, stem: str, options: list[str], multi: bool, order: list[int] | None = None,
        buttons: bool = False) -> str:
    """`order`: índices internos na ordem exibida (embaralhada, como no NetAcad)."""
    n = len(options)
    order = order or list(range(n))
    role, group = ("checkbox", "group") if multi else ("radio", "radiogroup")
    items = []
    for pos, idx in enumerate(order, 1):
        items.append(
            f'<div class="mcq__item js-mcq-item item-{idx}" tabindex="0" role="{role}" aria-checked="false" '
            f'aria-labelledby="{cid}-{idx}-label" aria-posinset="{pos}" aria-setsize="{n}" data-socialgoodpulse-index="{idx}">'
            f'<input class="mcq__item-input js-item-input" tabindex="-1" aria-hidden="true" id="{cid}-{idx}-input" '
            f'type="{role}" data-socialgoodpulse-index="{idx}">'
            f'<label id="{cid}-{idx}-label" class="mcq__item-label js-item-label" for="{cid}-{idx}-input">'
            f'<div class="mcq__item-state"><div class="mcq__item-icon is-{role}"></div></div>'
            f'<div class="mcq__item-text"><div class="mcq__item-text-inner">{E(options[idx])}'
            f'<span class="screenReader-position-text" role="text" tabindex="-1">{pos} of {n}</span></div></div></label></div>')
    widget = (f'<div class="component__widget mcq__widget" role="{group}"><div class="component__widget-inner mcq__widget-inner">'
              + "".join(items) + '</div></div>')
    inner = (f'<div data-socialgoodpulse-id="{cid}" class="component__inner mcq__inner component is-question mcq {cid}">'
             + header(cid, title, stem) + widget + (buttons_view() if buttons else '<div class="btn-container"></div>') + '</div>')
    return shadow("mcq-view", inner)


def dropdowns(cid: str, stem: str, instruction: str, items: list[str], options: list[str],
              reverse_options: bool = False) -> str:
    dd = []
    for i, text in enumerate(items):
        lis = "".join(
            f'<li role="option" id="dropdown__item-index-{k}" class="dropdown__item js-dropdown-list-item" data-index="{k}" '
            f'aria-selected="false"><div class="dropdown__item-inner js-dropdown-list-item-inner" tabindex="0" '
            f'value="{E(o)}">{E(o)}<span class="sr-only">, {k + 1} of {len(options)}, not selected</span></div></li>'
            for k, o in (reversed(list(enumerate(options))) if reverse_options else enumerate(options)))
        inner = (f'<div class="matching__item-container-options-wrapper {i}"><div class="matching__item-title_inner" '
                 f'data-socialgoodpulse-index="{i}"><div class="matching__item-title" tabindex="0">'
                 f'<div class="matching__item-title_inner">{E(text)}</div></div>'
                 f'<div role="application" tabindex="-1" class="matching__select-container">'
                 f'<button class="dropdown__btn js-dropdown-btn" aria-labelledby="matching__item-title_inner" '
                 f'aria-haspopup="listbox" aria-expanded="false"><div class="dropdown__inner js-dropdown-inner">'
                 f'Please select an option</div></button>'
                 f'<ul role="listbox" tabindex="-1" class="dropdown__list js-dropdown-list hidden">{lis}</ul></div></div></div>')
        dd.append(shadow("matching-dropdown-view", inner, 'class="matching__item_main" placeholder="Please select an option"'))
    inner = (f'<div data-socialgoodpulse-id="{cid}" class="component__inner matching__inner component is-question matching {cid}">'
             + header(cid, "", stem, instruction) + '<div class="component__widget matching__widget">' + "".join(dd) + '</div>'
             + buttons_view() + '</div>')
    return shadow("matching-view", inner)


def object_matching(cid: str, stem: str, left: list[str], right: list[str]) -> str:
    letters = "ABCDEFGH"
    cats = "".join(
        f'<div class="objectMatching-category-item-container item"><button data-id="{i}" class="base objectMatching-category-item" '
        f'data-currentquestionindex="{i + 1}" data-itemindex="{i}"><div class="objectMatching-category-item-inner">'
        f'<div class="category-item-text">{E(t)}</div><div class="category-item-number">{letters[i]}</div>'
        f'<div class="category-line"></div></div></button></div>' for i, t in enumerate(left))
    opts = "".join(
        f'<div class="objectMatching-option-item-container item"><button data-id="{i}" class="base objectMatching-option-item" '
        f'data-currentoptionindex="{i + 1}" data-itemindex="{i}"><div class="objectMatching-option-item-inner">'
        f'<div class="dropdown__icon" aria-hidden="true"><div class="icon matching_item-state"></div></div>'
        f'<div class="category-item-number"></div><div class="category-item-text">{E(t)}</div></div></button></div>'
        for i, t in enumerate(right))
    widget = ('<div class="component__widget objectMatching__widget"><div class="component__widget-inner">'
              '<svg id="lineSVG"></svg>'
              f'<div class="objectMatching-container categories-container">{cats}</div>'
              f'<div class="objectMatching-container options-container">{opts}</div></div></div>')
    inner = (f'<div data-socialgoodpulse-id="{cid}" class="component__inner objectmatching__inner component is-question objectmatching {cid}">'
             + header(cid, "", stem) + widget + buttons_view() + '</div>')
    return shadow("object-matching-view", inner)


def block_heading(title: str) -> str:
    inner = (f'<div class="js-heading is-incomplete"><div id="block-heading" role="heading" aria-level="3">'
             f'<span>Incomplete {E(title)}</span></div></div>')
    return shadow("heading-view", inner)


def page(title: str, body: str) -> str:
    return (f'<!doctype html>\n<html lang="en"><head><meta charset="utf-8"><title>{E(title)}</title></head>'
            f'<body>{body}</body></html>\n')


def section(item: str, components: str, other: str = "") -> str:
    """Seção do curso: o item aberto num bloco, mais um bloco vizinho."""
    blk = shadow("block-view", f'<div class="block"><div class="block__inner">{block_heading(item)}{components}</div></div>')
    return page(f"Module 9: Virtualization and Cloud Computing | {item}", other + blk)


def strip(n: int, active: int = 1) -> str:
    btns = "".join(
        f'<button data-index="{i}" class="block-button{" active-block" if i == active else ""}" '
        f'data-block-id="blk{i:02d}" aria-label="{"selected " if i == active else ""}Question {i}">Q{i}</button>'
        for i in range(1, active + 1))
    inner = ('<div class="review-container"><div class="block-buttons-container">'
             '<button class="btn-icon article__btn-arrow is-left" data-blockstrip-slider="left" '
             'aria-label="Scroll Question strip left">&lsaquo;</button>'
             f'<div class="attempted-blocks-wrapper"><div class="attempted-blocks-inner">{btns}</div></div>'
             '<button class="btn-icon article__btn-arrow is-right" data-blockstrip-slider="right" '
             'aria-label="Scroll Question strip right">&rsaquo;</button></div></div>')
    return shadow("assessment-block-strip-view", inner)


def toolbar(n: int) -> str:
    inner = ('<div class="secure-toolbar-container"><div class="question-label-container">'
             f'<div tabindex="0" class="question-label is-desktop">1 of {n}<span class="secure-question-label">Questions</span>'
             '</div></div><div class="abs__btn-arrow-container">'
             '<div class="abs__skip-all-button abs__skip-button js-abs-toolbar-bottom"><div class="skip-all-inner skip-inner">'
             '<input type="checkbox" id="skip-all-question" tabindex="0" role="button" aria-label="Skip All Question">'
             '<label for="skip-all-question" type="button" aria-hidden="true">Skip All</label></div></div>'
             '<div class="abs__skip-button js-abs-toolbar-bottom"><div class="skip-inner">'
             '<input type="checkbox" id="skip-question" tabindex="0" role="button" aria-label="Skip Question">'
             '<label for="skip-question" type="button" aria-hidden="true">Skip Question</label></div></div>'
             '<button aria-label="submit" tabindex="0" class="btn-icon btn__action abs__btn-arrow submit-button is-disabled" '
             'disabled><div class="submit">Submit</div></button></div></div>')
    return shadow("assessment-toolbar-view", inner)


def finalscreen() -> str:
    inner = ('<div class="finalscreen"><h2>Submit My Assessment</h2>'
             '<div class="unanswered-instruction">You have 0 unanswered questions:</div>'
             '<div>Are you sure you want to submit the quiz?</div>'
             '<input type="checkbox" id="confirm-exam"><label for="confirm-exam" id="confirm-label">'
             'Yes, confirm my submission.</label>'
             '<button class="btn-text btn__action element-color-control adaptive-assessment-submit disabled is-disabled" '
             'aria-label="Submit This button is disabled at the moment">Submit</button></div>')
    return shadow("finalscreen-view", inner, 'style="display:none"')


ASSESSMENT = [
    ("q1", "Question 1", "Synthetic example: select the label Delta.",
     ["Alpha", "Beta", "Gamma", "Delta"], False, [2, 0, 1, 3]),
    ("q2", "Question 2", "Synthetic example: select the two labels beginning with A. (Choose two.)",
     ["Amber", "Azure", "Blue", "Green", "Red"], True, [1, 0, 3, 4, 2]),
    ("q3", "Question 3", "Synthetic example: select the number one.",
     ["One", "Two", "Three", "Four"], False, [0, 1, 2, 3]),
]


def assessment(final_visible: bool = False) -> str:
    blocks = "".join(
        shadow("block-view", f'<div class="blk{i:02d} block"><div class="block__inner"><div class="component__container">'
                             f'{mcq(cid, title, stem, opts, multi, order)}</div></div></div>')
        for i, (cid, title, stem, opts, multi, order) in enumerate(ASSESSMENT, 1))
    carousel = ('<div class="abs__container has-arrows"><div class="abs__slide-container js-abs-slide-container">'
                f'<div class="block__container js-abs-block-container">{blocks}</div></div></div>')
    fs = finalscreen()
    if final_visible:
        fs = fs.replace('style="display:none"', "")
    return page("Practice Final Exam (derivado) | Practice Final Exam (derivado)",
                strip(len(ASSESSMENT)) + carousel + toolbar(len(ASSESSMENT)) + fs)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    out = Path(argv[1])
    out.mkdir(parents=True, exist_ok=True)
    files = {
        "assessment.html": assessment(),
        "assessment_final.html": assessment(final_visible=True),
        "cyu_single.html": section("9.9.1.1 Check Your Understanding - Single", mcq(
            "s1", "Question 1", "Synthetic example: select the label Beta.", ["Alpha", "Beta", "Gamma", "Delta"], False,
            [3, 0, 1, 2], buttons=True), other=shadow("block-view", '<div class="block">' + mcq(
                "other", "Question 1", "Outra atividade da página (não deve ser tocada).", ["A", "B"], False,
                buttons=True) + "</div>")),
        "cyu_dropdown.html": section("9.9.2 Cloud Services", dropdowns(
            "d1", "Synthetic example: there are four colored boxes.", "Select the color named in each invented label.",
            ["Red box.", "Blue box.", "Green box.", "Yellow box."], ["Red", "Blue", "Green", "Yellow"])),
        "cyu_dropdown_reversed.html": section("9.9.2 Cloud Services", dropdowns(
            "d1", "Synthetic example: there are four colored boxes.", "Select the color named in each invented label.",
            ["Red box.", "Blue box.", "Green box.", "Yellow box."], ["Red", "Blue", "Green", "Yellow"],
            reverse_options=True)),
        "cyu_match.html": section("9.9.1.4 Check Your Understanding - Terminology", object_matching(
            "m1", "Synthetic example: match each shape to its label",
            ["Circle", "Square", "Triangle"],
            ["Label for Triangle.", "Label for Circle.", "Label for Square."])),
    }
    for name, text in files.items():
        (out / name).write_text(text, encoding="utf-8")
    print(f"{len(files)} fixtures derivadas em {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
