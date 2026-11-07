"""Normalização de texto e casamento aproximado com difflib."""

from __future__ import annotations

import difflib
import re
import unicodedata
from dataclasses import dataclass

_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)
_SPACES = re.compile(r"\s+")

# Confusões comuns do OCR em texto de interface.
_OCR_FIXES = str.maketrans({"|": "l", "‘": "'", "’": "'", "“": '"', "”": '"',
                            "—": "-", "–": "-"})


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).translate(_OCR_FIXES).lower()
    text = _PUNCT.sub(" ", text)
    return _SPACES.sub(" ", text).strip()


def tokens(text: str) -> list[str]:
    return normalize(text).split()


def similarity(a: str, b: str) -> float:
    na, nb = normalize(a), normalize(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    return difflib.SequenceMatcher(None, na, nb, autojunk=False).ratio()


@dataclass
class Candidate:
    index: int  # índice do item avaliado (ex.: opção ou linha)
    score: float


@dataclass
class MatchResult:
    status: str  # "ok", "ambiguous", "not_found"
    index: int = -1
    score: float = 0.0
    runner_up: float = 0.0

    @property
    def ok(self) -> bool:
        return self.status == "ok"


def best_match(target: str, candidates: list[str], threshold: float, margin: float = 0.08) -> MatchResult:
    """Escolhe o candidato mais parecido com `target`.

    Ambíguo quando o segundo colocado fica a menos de `margin` do primeiro e
    os dois passam do limiar; nesse caso o chamador não deve clicar.
    """
    scored = sorted((Candidate(i, similarity(target, c)) for i, c in enumerate(candidates)),
                    key=lambda c: c.score, reverse=True)
    if not scored or scored[0].score < threshold:
        return MatchResult("not_found", score=scored[0].score if scored else 0.0)
    top = scored[0]
    second = scored[1].score if len(scored) > 1 else 0.0
    exact = normalize(target) == normalize(candidates[top.index])
    if second >= threshold and top.score - second < margin and not (exact and second < 1.0):
        return MatchResult("ambiguous", top.index, top.score, second)
    return MatchResult("ok", top.index, top.score, second)


def contains_phrase(haystack: str, phrase: str) -> bool:
    """Frase inteira presente respeitando fronteiras de palavra."""
    h = f" {normalize(haystack)} "
    p = normalize(phrase)
    return bool(p) and f" {p} " in h


def count_phrase(haystack: str, phrase: str) -> int:
    p = normalize(phrase)
    if not p:
        return 0
    return len(re.findall(rf"(?<!\S){re.escape(p)}(?!\S)", normalize(haystack)))


def split_list(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]
