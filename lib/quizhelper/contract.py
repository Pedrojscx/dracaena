"""Contrato com o Claude: resposta por ÍNDICE (sem casamento aproximado de texto).

    SINGLE   {"type":"SINGLE","answers":[2]}
    MULTI    {"type":"MULTI","answers":[0,3]}
    DROPDOWN {"type":"DROPDOWN","items":[{"item":0,"option":1}, ...]}
    MATCH    {"type":"MATCH","pairs":[{"right":0,"left":"C"}, ...]}

Validação contra a questão lida do DOM: tipo igual, índices dentro do
intervalo, quantidade igual à pedida, sem repetição, todos os itens cobertos.
"""

from __future__ import annotations

import json
import re


class ContractError(ValueError):
    pass


_FENCE = re.compile(r"```(?:json)?[ \t]*\n?(.*?)```", re.S | re.I)


def candidates(raw: str) -> list[dict]:
    """Objetos JSON balanceados da saída do modelo, na ordem em que aparecem.

    Cercas de código são removidas antes (o conteúdo é mantido). Cada `{` é tentado com
    json.raw_decode (ciente de strings e aninhamento); um `{` solto na prosa é só pulado.
    """
    text = _FENCE.sub(lambda m: "\n" + m.group(1) + "\n", raw.strip())
    dec = json.JSONDecoder()
    out: list[dict] = []
    i = text.find("{")
    while i != -1:
        try:
            data, end = dec.raw_decode(text, i)
        except ValueError:
            i = text.find("{", i + 1)
            continue
        if isinstance(data, dict):
            out.append(data)
        i = text.find("{", end)
    return out


def parse(raw: str) -> dict:
    """O ÚLTIMO objeto JSON da saída (sem validar contra a questão)."""
    found = candidates(raw)
    if not found:
        raise ContractError("não há nenhum objeto JSON na resposta")
    return found[-1]


def parse_validated(raw: str, q: dict) -> dict:
    """O último objeto JSON que passa na validação; se nenhum passar, levanta o motivo do último."""
    found = candidates(raw)
    if not found:
        raise ContractError("não há nenhum objeto JSON na resposta")
    first_err: ContractError | None = None
    for data in reversed(found):
        try:
            return validate(data, q)
        except ContractError as exc:
            first_err = first_err or exc
    raise first_err  # type: ignore[misc]


def _int(v, what: str) -> int:
    if isinstance(v, bool) or not isinstance(v, int):
        raise ContractError(f"{what} precisa ser um inteiro: {v!r}")
    return v


def validate(ans: dict, q: dict) -> dict:
    kind = q["kind"]
    if ans.get("type") != kind:
        raise ContractError(f"tipo {ans.get('type')!r}, esperado {kind!r}")
    if kind in ("SINGLE", "MULTI"):
        n = len(q["options"])
        idx = ans.get("answers")
        if not isinstance(idx, list) or not idx:
            raise ContractError("answers precisa ser uma lista de índices")
        idx = [_int(i, "índice") for i in idx]
        if any(not 0 <= i < n for i in idx):
            raise ContractError(f"índice fora de 0..{n - 1}: {idx}")
        if len(set(idx)) != len(idx):
            raise ContractError(f"índice repetido: {idx}")
        want = 1 if kind == "SINGLE" else q.get("expected")
        if want and len(idx) != want:
            raise ContractError(f"{len(idx)} alternativa(s), pedidas {want}")
        if kind == "MULTI" and not want and len(idx) < 2:
            raise ContractError("múltipla seleção com uma alternativa só")
        return {"type": kind, "answers": idx}
    if kind == "DROPDOWN":
        items = ans.get("items")
        if not isinstance(items, list):
            raise ContractError("items precisa ser uma lista")
        out: dict[int, int] = {}
        for it in items:
            if not isinstance(it, dict):
                raise ContractError(f"item inválido: {it!r}")
            i, o = _int(it.get("item"), "item"), _int(it.get("option"), "option")
            if not 0 <= i < len(q["items"]):
                raise ContractError(f"item fora do intervalo: {i}")
            if i in out:
                raise ContractError(f"item repetido: {i}")
            nopt = len(q["items"][i]["options"])
            if not 0 <= o < nopt:
                raise ContractError(f"opção {o} fora de 0..{nopt - 1} no item {i}")
            out[i] = o
        if len(out) != len(q["items"]):
            raise ContractError(f"{len(out)} de {len(q['items'])} itens respondidos")
        return {"type": kind, "items": [{"item": i, "option": out[i]} for i in sorted(out)]}
    if kind == "MATCH":
        pairs = ans.get("pairs")
        if not isinstance(pairs, list):
            raise ContractError("pairs precisa ser uma lista")
        letters = {c["letter"] for c in q["left"]}
        out2: dict[int, str] = {}
        for p in pairs:
            if not isinstance(p, dict):
                raise ContractError(f"par inválido: {p!r}")
            r = _int(p.get("right"), "right")
            left = str(p.get("left", "")).strip().upper()
            if not 0 <= r < len(q["right"]):
                raise ContractError(f"right fora do intervalo: {r}")
            if r in out2:
                raise ContractError(f"right repetido: {r}")
            if left not in letters:
                raise ContractError(f"letra {left!r} não existe (há {sorted(letters)})")
            out2[r] = left
        if len(out2) != len(q["right"]):
            raise ContractError(f"{len(out2)} de {len(q['right'])} itens da direita ligados")
        return {"type": kind, "pairs": [{"right": r, "left": out2[r]} for r in sorted(out2)]}
    raise ContractError(f"tipo de questão não suportado: {kind}")


def schema_for(q: dict) -> dict:
    """JSON Schema do contrato para a questão (usado com `claude --json-schema`)."""
    kind = q["kind"]
    ints = {"type": "integer", "minimum": 0}
    if kind in ("SINGLE", "MULTI"):
        n = 1 if kind == "SINGLE" else (q.get("expected") or 2)
        arr = {"type": "array", "items": {**ints, "maximum": len(q["options"]) - 1}, "minItems": n,
               "uniqueItems": True}
        if kind == "SINGLE" or q.get("expected"):
            arr["maxItems"] = n
        props, req = {"type": {"const": kind}, "answers": arr}, ["type", "answers"]
    elif kind == "DROPDOWN":
        item = {"type": "object", "properties": {"item": ints, "option": ints}, "required": ["item", "option"],
                "additionalProperties": False}
        props = {"type": {"const": kind}, "items": {"type": "array", "items": item, "minItems": len(q["items"]),
                                                    "maxItems": len(q["items"])}}
        req = ["type", "items"]
    elif kind == "MATCH":
        pair = {"type": "object", "properties": {"right": ints, "left": {"enum": [c["letter"] for c in q["left"]]}},
                "required": ["right", "left"], "additionalProperties": False}
        props = {"type": {"const": kind}, "pairs": {"type": "array", "items": pair, "minItems": len(q["right"]),
                                                    "maxItems": len(q["right"])}}
        req = ["type", "pairs"]
    else:
        raise ContractError(f"tipo de questão não suportado: {kind}")
    return {"type": "object", "properties": props, "required": req, "additionalProperties": False}


def readable(ans: dict, q: dict) -> str:
    """Texto curto para notificação e área de transferência."""
    kind = ans["type"]
    if kind in ("SINGLE", "MULTI"):
        return "\n".join(f"• {q['options'][i]['text']}" for i in ans["answers"])
    if kind == "DROPDOWN":
        return "\n".join(f"• {q['items'][it['item']]['text'][:60]} → {q['items'][it['item']]['options'][it['option']]['text']}"
                         for it in ans["items"])
    if kind == "MATCH":
        left = {c["letter"]: c["text"] for c in q["left"]}
        return "\n".join(f"• {p['left']} ({left[p['left']][:30]}) → {q['right'][p['right']]['text'][:60]}"
                         for p in ans["pairs"])
    return json.dumps(ans, ensure_ascii=False)


def question_text(q: dict) -> str:
    """A questão como texto estruturado para o prompt (índices explícitos)."""
    lines = [f"Tipo: {q['kind']}"]
    if q.get("title"):
        lines.append(f"Título: {q['title']}")
    lines.append(f"Enunciado: {q['stem']}")
    if q.get("instruction"):
        lines.append(f"Instrução: {q['instruction']}")
    if q["kind"] in ("SINGLE", "MULTI"):
        if q["kind"] == "MULTI":
            lines.append(f"Quantidade pedida: {q.get('expected') or 'não informada'}")
        lines.append("Alternativas:")
        lines += [f"[{o['index']}] {o['text']}" for o in q["options"]]
    elif q["kind"] == "DROPDOWN":
        for it in q["items"]:
            lines.append(f"Item [{it['index']}]: {it['text']}")
            lines += [f"    opção [{o['index']}] {o['text']}" for o in it["options"]]
    elif q["kind"] == "MATCH":
        lines.append("Coluna da esquerda (letras):")
        lines += [f"{c['letter']}) {c['text']}" for c in q["left"]]
        lines.append("Coluna da direita (índices):")
        lines += [f"[{r['index']}] {r['text']}" for r in q["right"]]
    return "\n".join(lines)
