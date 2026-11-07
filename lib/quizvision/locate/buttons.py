"""Botões e feedback: Submit isolado, botão que encerra a avaliação (nunca
clicado), botões de reset, frases de feedback e tela final."""

from __future__ import annotations

from ..ocr import Line
from ..page import Page
from ..text import contains_phrase, count_phrase, normalize, similarity, tokens
from .base import Located


def final_buttons(page: Page, blocklist: list[str]) -> list[Line]:
    """Botões que encerram a avaliação inteira (nunca clicar)."""
    verbs = {"submit", "finish", "end"}
    block = {normalize(w) for w in blocklist}
    found = []
    for ln in page.lines:
        words = tokens(ln.text)
        if not words or len(words) > 3:
            continue
        if any(w in block for w in words) and any(w in verbs for w in words):
            found.append(ln)
    return found


def end_screen(page: Page, end_words: list[str]) -> str | None:
    for ln in page.lines:
        if len(tokens(ln.text)) > 7:
            continue
        for phrase in end_words:
            if contains_phrase(ln.text, phrase):
                return phrase
    return None


def locate_submit(page: Page, min_conf: float, blocklist: list[str]) -> Located:
    finals = final_buttons(page, blocklist)
    if finals:
        return Located("final", f"botão final visível: {finals[0].text!r}")
    isolated, mixed = [], []
    for ln in page.lines:
        words = tokens(ln.text)
        if "submit" not in words:
            continue
        if not ln.button and len(words) > 4:
            continue  # frase de instrução ("Click Submit to ..."), não botão
        if len(words) == 1 and len(ln.words) == 1:
            isolated.append(ln)
        else:
            mixed.append(ln)
    if not isolated and not mixed:
        return Located("not_found", "Submit não encontrado")
    if mixed:
        return Located("refused", f"linha com Submit e outras palavras: {mixed[0].text!r}")
    if len(isolated) > 1:
        return Located("refused", f"{len(isolated)} botões Submit na tela")
    ln = isolated[0]
    if ln.conf < min_conf:
        return Located("refused", f"confiança do OCR baixa no Submit ({ln.conf:.0f} < {min_conf})")
    box = ln.button_box or ln.box
    return Located("ok", point=(box.cx, box.cy), box=box, conf=ln.conf)


def locate_button(page: Page, labels: list[str], threshold: float = 0.85) -> Located:
    hits = []
    for ln in page.lines:
        if len(tokens(ln.text)) > 3:
            continue
        for label in labels:
            if similarity(ln.text, label) >= threshold:
                hits.append(ln)
                break
    if not hits:
        return Located("not_found", "botão não encontrado")
    if len(hits) > 1:
        return Located("ambiguous", "mais de um botão compatível")
    box = hits[0].button_box or hits[0].box
    return Located("ok", point=(box.cx, box.cy), text=hits[0].text)


def detect_feedback(before: Page | None, after: Page, correct: list[str], incorrect: list[str]) -> str | None:
    """'incorrect', 'correct' ou None, contando só frases novas após o Submit.

    Frases de erro têm prioridade ("Partly correct" contém "correct").
    """
    before_text = before.text if before else ""
    after_text = after.text

    def new(phrase: str) -> bool:
        return count_phrase(after_text, phrase) > count_phrase(before_text, phrase)

    if any(new(p) for p in incorrect):
        return "incorrect"
    if any(new(p) for p in correct):
        # "Incorrect" não conta como "Correct": count_phrase respeita palavras.
        return "correct"
    return None
