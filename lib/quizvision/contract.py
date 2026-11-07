"""Contrato da resposta do Claude: validação e formatação legível."""

from __future__ import annotations

import json
import re

TYPES = ("SINGLE", "MULTI", "DROPDOWN", "MATCH", "INCOMPLETE")


class ContractError(ValueError):
    pass


_FENCE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)


def _nonempty_str(value, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{where} precisa ser texto não vazio")
    return value.strip()


def parse(raw: str) -> dict:
    """Valida o texto devolvido pelo modelo e devolve o objeto normalizado.

    Aceita apenas um objeto JSON. A única tolerância é remover uma cerca de
    código markdown ao redor do objeto inteiro, porque alguns modelos a
    adicionam mesmo quando instruídos a não fazê-lo.
    """
    text = raw.strip()
    fence = _FENCE.match(text)
    if fence:
        text = fence.group(1).strip()
    try:
        obj = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ContractError(f"não é JSON válido: {exc.msg}") from exc
    return validate(obj)


def validate(obj) -> dict:
    if not isinstance(obj, dict):
        raise ContractError("o JSON precisa ser um objeto")
    kind = obj.get("type")
    if kind not in TYPES:
        raise ContractError(f"type inválido: {kind!r}")
    if kind == "INCOMPLETE":
        return {"type": "INCOMPLETE"}
    if kind in ("SINGLE", "MULTI"):
        answers = obj.get("answers")
        if not isinstance(answers, list) or not answers:
            raise ContractError("answers precisa ser lista não vazia")
        answers = [_nonempty_str(a, "answers[]") for a in answers]
        if len({a.lower() for a in answers}) != len(answers):
            raise ContractError("answers tem itens repetidos")
        if kind == "SINGLE":
            if len(answers) != 1:
                raise ContractError("SINGLE precisa de exatamente uma resposta")
            return {"type": "SINGLE", "answers": answers}
        expected = obj.get("expected")
        if isinstance(expected, bool) or not isinstance(expected, int) or expected < 1:
            raise ContractError("MULTI precisa de expected inteiro positivo")
        if expected != len(answers):
            raise ContractError(f"MULTI: expected={expected} mas {len(answers)} respostas")
        return {"type": "MULTI", "expected": expected, "answers": answers}
    if kind == "DROPDOWN":
        items = obj.get("items")
        if not isinstance(items, list) or not items:
            raise ContractError("items precisa ser lista não vazia")
        out = []
        for i, item in enumerate(items):
            if not isinstance(item, dict):
                raise ContractError(f"items[{i}] precisa ser objeto")
            out.append({"statement": _nonempty_str(item.get("statement"), f"items[{i}].statement"),
                        "answer": _nonempty_str(item.get("answer"), f"items[{i}].answer")})
        return {"type": "DROPDOWN", "items": out}
    pairs = obj.get("pairs")
    if not isinstance(pairs, list) or not pairs:
        raise ContractError("pairs precisa ser lista não vazia")
    out = []
    for i, pair in enumerate(pairs):
        if not isinstance(pair, dict):
            raise ContractError(f"pairs[{i}] precisa ser objeto")
        letter = _nonempty_str(pair.get("letter"), f"pairs[{i}].letter").upper()
        if not re.fullmatch(r"[A-Z]", letter):
            raise ContractError(f"pairs[{i}].letter precisa ser uma letra")
        out.append({"left": _nonempty_str(pair.get("left"), f"pairs[{i}].left"),
                    "letter": letter,
                    "right": _nonempty_str(pair.get("right"), f"pairs[{i}].right")})
    rights = [p["right"].lower() for p in out]
    if len(set(rights)) != len(rights):
        raise ContractError("MATCH: item da direita repetido")
    return {"type": "MATCH", "pairs": out}


def readable(answer: dict, right_order: list[str] | None = None) -> str:
    """Texto curto para notificação e área de transferência.

    Em MATCH, mostra as letras na ordem dos itens da direita na tela; se a
    ordem da tela não for conhecida, usa a ordem dos pares.
    """
    kind = answer["type"]
    if kind == "SINGLE":
        return answer["answers"][0]
    if kind == "MULTI":
        return "\n".join(answer["answers"])
    if kind == "DROPDOWN":
        return "\n".join(f"{i}. {item['answer']}" for i, item in enumerate(answer["items"], 1))
    if kind == "MATCH":
        pairs = answer["pairs"]
        if right_order:
            index = {p["right"]: p for p in pairs}
            ordered = [index[r] for r in right_order if r in index]
            ordered += [p for p in pairs if p not in ordered]
        else:
            ordered = pairs
        return ", ".join(p["letter"] for p in ordered)
    return "Questão incompleta na captura"
