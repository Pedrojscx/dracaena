"""Base da localização: resultado `Located`, linhas e blocos de texto e
identificação da questão (número, título, trecho inicial e hash)."""

from __future__ import annotations

import re

from ..image import Image
from ..ocr import Line
from ..page import Page
from ..text import best_match, normalize, similarity


class Located:
    """Resultado de uma localização: ok, ambiguous ou not_found + motivo."""

    def __init__(self, status: str, reason: str = "", **data):
        self.status = status
        self.reason = reason
        self.data = data

    @property
    def ok(self) -> bool:
        return self.status == "ok"

    def __getattr__(self, name):
        try:
            return self.__dict__["data"][name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def __repr__(self) -> str:
        return f"Located({self.status!r}, {self.reason!r}, {self.data!r})"


def text_lines(page: Page) -> list[Line]:
    return [ln for ln in page.lines if not ln.button]


def blocks(lines: list[Line], max_join: int = 3) -> list[tuple[str, list[Line]]]:
    """Linhas isoladas e emendas de até `max_join` linhas consecutivas
    alinhadas à esquerda (texto que quebrou em várias linhas)."""
    out = []
    ordered = sorted(lines, key=lambda ln: (ln.box.y, ln.box.x))
    for i, ln in enumerate(ordered):
        out.append((ln.text, [ln]))
        group = [ln]
        for nxt in ordered[i + 1:]:
            if len(group) >= max_join:
                break
            last = group[-1]
            if abs(nxt.box.x - ln.box.x) > max(6, ln.box.h) or nxt.box.y - last.box.y2 > 1.4 * last.box.h:
                continue
            if nxt.box.y <= last.box.y:
                continue
            group = group + [nxt]
            out.append((" ".join(g.text for g in group), list(group)))
    return out


def match_block(target: str, cands: list[tuple[str, list[Line]]], threshold: float):
    """best_match sobre blocos, contando cada linha inicial uma só vez.

    Um bloco e sua extensão (mesma primeira linha) não competem entre si
    para efeito de ambiguidade; fica o de maior similaridade.
    """
    best_by_first: dict[int, tuple[float, int]] = {}
    for i, (text, ls) in enumerate(cands):
        sc = similarity(target, text)
        key = id(ls[0])
        if key not in best_by_first or sc > best_by_first[key][0]:
            best_by_first[key] = (sc, i)
    order = [i for _, i in best_by_first.values()]
    res = best_match(target, [cands[i][0] for i in order], threshold)
    if res.index >= 0:
        res.index = order[res.index]
    return res


def question_signature(page: Page, img: Image) -> dict:
    lines = text_lines(page)
    number = None
    for ln in lines[:6]:
        m = re.search(r"\b(?:Question|Questão|Pergunta)\s+(\d+)", ln.text, re.IGNORECASE)
        if m:
            number = int(m.group(1))
            break
    stem = " ".join(ln.text for ln in lines[:5])
    return {"number": number, "title": lines[0].text if lines else "", "stem": normalize(stem)[:400],
            "hash": img.dhash()}


def same_question(a: dict | None, b: dict | None) -> bool:
    if not a or not b:
        return False
    if a.get("number") is not None and b.get("number") is not None:
        if a["number"] != b["number"]:
            return False
        return similarity(a.get("title", ""), b.get("title", "")) > 0.6 or \
            similarity(a.get("stem", ""), b.get("stem", "")) > 0.6
    return similarity(a.get("stem", ""), b.get("stem", "")) >= 0.9
