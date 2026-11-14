"""Autoperfil: quando a heurística não basta, pede à Claude CLI um perfil TOML v0.

Somente leitura do início ao fim (usa o adaptador, nunca a guarda):
1. lê a página; se a heurística já tem confiança, não há o que aprender;
1b. pede ao motor o mapa estrutural (`structure`): se ele já traz um perfil
   candidato confiável (verified ou unverified), o rascunho sai dele, sem
   consulta externa; abaixo disso, os candidatos por campo seguem no resultado;
2. recorta a ESTRUTURA da região da atividade (o motor troca o texto pelo
   tamanho e não inclui valores de campos) e passa o recorte por `sanitize`;
3. pede o perfil à Claude CLI e valida com `adapters.profile`; no erro, tenta
   mais uma vez informando o erro e a linha;
4. confere o perfil na própria página (lendo) e devolve o rascunho no formato
   do probe.start: {"matches": {seletor: n}, "questions": n, "draft_toml": str},
   mais status, candidates, fields, fingerprint e notes (só marcação).

O rascunho leva a tabela [meta]: confidence, status, fingerprint, generator, generated.

O rascunho é reescrito daqui (TOML canônico): leva só seletores e metadados
estruturais, nunca texto de questão. Quem salva é `platform.sites.save`.
"""

from __future__ import annotations

import datetime
import json
import re
from collections.abc import Callable
from urllib.parse import urlsplit

from ..core import contract, redact
from . import profile as profiles
from .general import THRESHOLD, GeneralAdapter

PHASES = ("connect", "scan", "match", "draft")
SCHEMA = {"type": "object", "properties": {"toml": {"type": "string"}}, "required": ["toml"],
          "additionalProperties": False}

PROMPT = """Abaixo está o recorte ESTRUTURAL de uma página de atividade de prática: só marcação. Cada texto de
conteúdo aparece como texto(N), em que N é o tamanho; "oculto" marca o que não está visível; os botões trazem
o rótulo. Escreva um perfil declarativo em TOML que permita LER a questão. Use só estas tabelas e campos:

[question]  container, stem, instruction (opcional), figure (opcional)
[options]   item, text (opcional), input (opcional), selected_attr (opcional)
[dropdown]  item, button, option, native (true para <select>)        # só se a resposta for por lista suspensa
[submit]    button                                                   # opcional
[reset]     button                                                   # opcional
[feedback]  correct, incorrect, text (opcional)                      # opcional
[guard]     block_labels = []                                        # opcional

Regras:
- Todo valor é um seletor CSS simples (classes, papéis e atributos estruturais). Nada de código, nada de texto
  da página, nada de identificadores numéricos longos.
- container é o elemento de UMA questão; stem, item, text e input são relativos a ele.
- item é cada alternativa; text é o texto dela dentro do item; input é a entrada (rádio ou checkbox) dentro do item.
- [submit] só existe se houver um botão que confere ESTA questão. Botão de finalizar, encerrar, terminar, enviar
  tudo ou avançar de página NUNCA entra no perfil.
- Não escreva a tabela [site]: ela é preenchida depois.

Responda com um único objeto JSON: {"toml": "<o perfil TOML>"}.
{PREVIOUS}
RECORTE:
{OUTLINE}
"""
RETRY = """
A tentativa anterior foi recusada. Corrija exatamente este erro e devolva o perfil inteiro de novo:
{ERROR}
Perfil anterior:
{TOML}
"""

UNCHECKED = "rascunho só de leitura: não validado com o contrato nem em duas questões"

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_URL = re.compile(r"(?i)\b(?:https?|wss?|ftp)://[^\s\"'<>]+")
_TOKEN = re.compile(r"\b(?=[A-Za-z0-9_-]*\d)(?=[A-Za-z0-9_-]*[A-Za-z])[A-Za-z0-9_-]{16,}\b")
_DIGITS = re.compile(r"\d{5,}")
_PRIVATE = re.compile(r"\d{5,}|[0-9a-f]{12,}|@", re.I)


class AutoprofileError(Exception):
    """Falha do autoperfil; `code` segue o probe do IPC v0."""

    def __init__(self, code: str, msg: str):
        super().__init__(msg)
        self.code, self.msg = code, msg
        self.details: dict = {}


def sanitize(text: str, env: dict | None = None) -> str:
    """Única saída de texto da página para fora da máquina: tira credenciais, endereços e identificadores."""
    text = redact.text(text, env)
    text = _URL.sub("[url]", text)
    text = _EMAIL.sub("[email]", text)
    text = _TOKEN.sub("[token]", text)
    return _DIGITS.sub("[n]", text)


def origin_glob(url: str) -> str:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise AutoprofileError("bad_request", "A página precisa ter um endereço http ou https.")
    return f"{parts.scheme}://{parts.hostname}{':' + str(parts.port) if parts.port else ''}/*"


def _extras(st: dict | None) -> dict:
    """O que o mapa estrutural acrescenta ao resultado: só seletores, números e textos fixos."""
    if not st:
        return {"status": "none", "candidates": {}, "fields": {}, "fingerprint": "", "notes": []}
    return {"status": st["status"], "candidates": st["candidates"], "fields": st["confidence"]["fields"],
            "fingerprint": st["fingerprint"], "notes": [str(n)[:200] for n in st["notes"]]}


def _meta(status: str, confidence: float, fingerprint: str, generator: str) -> dict:
    meta = {"confidence": round(float(confidence), 2), "status": status, "generator": generator,
            "generated": datetime.date.today().isoformat()}
    if fingerprint:
        meta["fingerprint"] = fingerprint
    return meta


def prior_of(saved: profiles.Profile) -> dict | None:
    """A leitura anterior guardada num perfil salvo, no formato que `structure` recebe (None se não há)."""
    if not saved.meta.get("fingerprint"):
        return None
    return {"fingerprint": saved.meta["fingerprint"], "profile": saved.to_engine()}


def status_after(saved: profiles.Profile, fingerprint: str) -> str:
    """Status que um perfil salvo merece diante do fingerprint lido agora: divergente rebaixa verified."""
    status = saved.meta.get("status", "unverified")
    if status == "verified" and saved.meta.get("fingerprint") != fingerprint:
        return "unverified"
    return status


def _draft(parsed: profiles.Profile, url: str, meta: dict | None = None) -> str:
    """TOML canônico: [site] vem da origem da página; o resto, só do que o validador aceitou."""
    tables = {name: body for name, body in parsed.tables.items() if name not in ("site", "meta")}
    if meta:
        tables["meta"] = meta
    host = urlsplit(url).hostname or "site"
    tables["site"] = {"name": host, "version": 0, "match": (origin_glob(url),)}
    for name, body in tables.items():
        for key, value in body.items():
            kind = profiles.SCHEMA[name][key][0]
            if kind == profiles.SELECTOR and (_PRIVATE.search(value) or len(value) > 200):
                raise profiles.ProfileError(f"{name}.{key}: o seletor traz um identificador; use classes ou papéis estruturais")
    return profiles.dump(tables)


def _page_errors(diag: dict, threshold: float) -> str:
    """Motivo pelo qual o perfil não serve nesta página ('' = serve)."""
    bad = [sel for sel, n in diag["matches"].items() if n < 0]
    if bad:
        return f"seletor CSS inválido: {bad[0]}"
    empty = [sel for sel, n in diag["matches"].items() if n == 0]
    if diag["layer"] != "profile":
        return "question.container não achou nenhum elemento visível" + (f" (sem resultado: {empty[0]})" if empty else "")
    for q in diag["questions"]:
        if q["layer"] == "profile" and (q["confidence"] < threshold or not q["actionable"]):
            return "a página lida com o perfil ficou incompleta: " + "; ".join(q["notes"])
    return ""


def learn(frame, url: str, ask: Callable, cfg: dict | None = None, *, threshold: float = THRESHOLD,
          emit: Callable[[dict], None] | None = None, cancelled: Callable[[], bool] | None = None,
          force: bool = False, prior: dict | None = None) -> dict:
    """Lê a página e, se preciso, aprende um perfil. Nunca age na página.

    Devolve {"matches", "questions", "draft_toml", "layer", "confidence", "needed"} mais
    {"status", "candidates", "fields", "fingerprint", "notes"} do mapa estrutural; `draft_toml` vem vazio
    quando a heurística já basta. Levanta `AutoprofileError` (no_site | bad_request | cancelled | internal);
    o erro leva em `details` os candidatos por campo, quando há.

    `prior` = {"fingerprint", "profile"} de uma leitura anterior, em outra execução (ver `prior_of`): sem ela
    o rascunho nunca sai como verified.
    """
    def phase(name: str) -> None:
        if cancelled is not None and cancelled():
            if emit is not None:
                emit({"event": "probe", "phase": "cancelled", "done": PHASES.index(name), "total": len(PHASES)})
            raise AutoprofileError("cancelled", "Sondagem cancelada")
        if emit is not None:
            emit({"event": "probe", "phase": name, "done": PHASES.index(name), "total": len(PHASES)})

    def fail(code: str, msg: str, at: str):
        if emit is not None:
            emit({"event": "probe", "phase": "error", "done": PHASES.index(at), "total": len(PHASES)})
        error = AutoprofileError(code, msg)
        error.details = extras
        return error

    def done(result: dict) -> dict:
        if emit is not None:
            emit({"event": "probe", "phase": "done", "done": len(PHASES), "total": len(PHASES)})
        return {**result, **extras}

    phase("scan")
    origin_glob(url)
    base = GeneralAdapter()
    extras = _extras(None)
    diag = base.diagnose(frame)
    try:
        st = base.structure(frame, prior)
    except Exception:  # noqa: BLE001 - o mapa estrutural é um acréscimo: sem ele, segue o caminho de sempre
        st = None
    extras = _extras(st)
    phase("match")
    if diag["supported"] and diag["confidence"] >= threshold and not force:
        return done({"matches": {}, "questions": len(diag["questions"]), "draft_toml": "", "layer": diag["layer"],
                     "confidence": diag["confidence"], "needed": False})
    if st and st["profile"] and st["status"] in ("verified", "unverified"):
        # Perfil candidato do próprio motor: validado, conferido na página por leitura, sem consulta externa.
        try:
            head = {"site": {"name": "rascunho", "version": 0, "match": ("*",)}, **st["profile"]}
            meta = _meta(st["status"], st["confidence"]["global"], st["fingerprint"], "structure 1")
            draft = _draft(profiles.parse(profiles.dump(head)), url, meta)
            checked = GeneralAdapter(profile=profiles.parse(draft)).diagnose(frame)
            if not _page_errors(checked, threshold):
                phase("draft")
                extras["notes"] = [*extras["notes"], UNCHECKED]
                return done({"matches": checked["matches"], "questions": len(checked["questions"]), "draft_toml": draft,
                             "layer": "profile", "confidence": checked["confidence"], "needed": True})
        except profiles.ProfileError:
            pass
        extras["status"] = "pause"
    if diag["code"] == "typed":
        raise fail("no_site", "Esta atividade pede resposta digitada, que ainda não é suportada.", "match")
    outline = sanitize(base.region(frame)["outline"])
    if not outline.strip():
        raise fail("no_site", "Nenhuma região de atividade foi reconhecida nesta página.", "match")
    phase("draft")
    previous, error = "", "resposta vazia"
    for _attempt in range(2):
        prompt = PROMPT.replace("{PREVIOUS}", previous).replace("{OUTLINE}", outline)
        try:
            raw, _ = ask(cfg or {}, sanitize(prompt), schema=SCHEMA, abort=cancelled)
        except Exception:
            phase("draft")  # cancelamento tem prioridade sobre erro da consulta
            raise
        phase("draft")  # nunca publica rascunho devolvido depois do cancelamento
        found = [c for c in contract.candidates(raw) if isinstance(c.get("toml"), str)]
        toml = found[-1]["toml"] if found else ""
        try:
            if not toml.strip():
                raise profiles.ProfileError("a resposta não trouxe o campo toml")
            head = "" if re.search(r"(?m)^\s*\[site\]", toml) else '[site]\nname = "rascunho"\nversion = 0\nmatch = ["*"]\n\n'
            offset = head.count("\n")
            try:
                parsed = profiles.parse(head + toml)
            except profiles.ProfileError as exc:
                raise profiles.ProfileError(exc.msg, exc.line - offset if exc.line and exc.line > offset else exc.line) from None
            draft = _draft(parsed, url, _meta("unverified", 0.5, extras["fingerprint"], "autoprofile 1"))
            final = profiles.parse(draft)
            checked = GeneralAdapter(profile=final).diagnose(frame)
            error = _page_errors(checked, threshold)
            if not error:
                extras["status"] = "unverified"
                return done({"matches": checked["matches"], "questions": len(checked["questions"]), "draft_toml": draft,
                             "layer": "profile", "confidence": checked["confidence"], "needed": True})
        except profiles.ProfileError as exc:
            error = str(exc)
        previous = RETRY.replace("{ERROR}", error).replace("{TOML}", sanitize(toml)[:4000])
    raise fail("no_site", f"Não foi possível aprender um perfil para esta página ({error}).", "draft")


def probe(frame, url: str, ask: Callable, cfg: dict | None = None, emit: Callable[[dict], None] | None = None,
          cancelled: Callable[[], bool] | None = None) -> dict:
    """Implementação real do probe.start: {"matches", "questions", "draft_toml"} (só leitura)."""
    got = learn(frame, url, ask, cfg, emit=emit, cancelled=cancelled)
    return {key: got[key] for key in ("matches", "questions", "draft_toml", "status", "candidates", "fields",
                                       "fingerprint", "notes")}


def dumps(result: dict) -> str:
    return json.dumps(result, ensure_ascii=False)
