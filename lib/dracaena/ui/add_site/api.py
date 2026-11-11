"""Ponto ÚNICO de chamadas do fluxo Adicionar site ao daemon (CONTRATO v0, Decisões do Maestro).

Forma usada (texto do CONTRATO repassado pelo A1, 2026-11-10):
- ``probe.start {url?}`` -> {matches: {seletor: n}, questions: n, draft_toml: str}. Sem ``url``, usa a
  aba atual do navegador dedicado. Evento ``probe {phase, done, total}`` é só progresso.
- ``probe.cancel`` (sem args) -> {cancelled: bool}.
- ``sites.save {name, toml, overwrite?}`` -> {path}. Erro: ``bad_request`` com a mensagem inteira.
Evento ``probe.phase``: connect|scan|match|draft|done|error|cancelled. Códigos de erro do probe:
no_browser|no_site|bad_request|cancelled|internal (a UI mostra a mensagem do daemon inteira).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable

from dracaena.ui.settings import reply

NAME_RE = re.compile(r"^[a-z0-9_-]+$")
MAX_TOML_BYTES = 64 * 1024


@dataclass(frozen=True)
class ProbeResult:
    matches: dict[str, int] = field(default_factory=dict)
    questions: int = 0
    draft_toml: str = ""

    @property
    def recognized(self) -> bool:
        return self.questions > 0


def parse_probe(data: Any) -> ProbeResult | None:
    if not isinstance(data, dict):
        return None
    m, q, t = data.get("matches"), data.get("questions"), data.get("draft_toml", "")
    if not isinstance(m, dict) or not all(isinstance(k, str) and type(v) is int for k, v in m.items()):
        return None
    if type(q) is not int or not isinstance(t, str):
        return None
    return ProbeResult(dict(m), q, t)


PHASE_TEXT = {"connect": "conectando ao navegador", "scan": "lendo a página",
              "match": "procurando os elementos", "draft": "montando o perfil"}


def probe_start(client, url: str, on_done: Callable[[ProbeResult | None, str, str], None]) -> int:
    """``on_done(resultado, erro, codigo)``: ``resultado`` ou ``erro`` (com o código do daemon)."""
    def done(resp) -> None:
        if not reply.is_ok(resp):
            return on_done(None, reply.error_text(resp), reply.error_code(resp))
        result = parse_probe(reply.payload(resp))
        on_done(result, "" if result else "Resposta inesperada do daemon.", "")
    return client.request("probe.start", {"url": url} if url else {}, done)


def probe_cancel(client, on_done: Callable[[bool], None] | None = None) -> None:
    def done(resp) -> None:
        data = reply.payload(resp)
        if on_done:
            on_done(bool(reply.is_ok(resp) and isinstance(data, dict) and data.get("cancelled")))
    client.request("probe.cancel", {}, done)


def probe_progress(event: Any) -> tuple[int, int, str] | None:
    """(feito, total, fase) de um evento ``probe``; ``None`` se não for."""
    name, data = reply.event_parts(event)
    if name != "probe":
        return None
    phase = data.get("phase")
    done, total = data.get("done"), data.get("total")
    if type(done) is int and type(total) is int and total > 0:
        return max(0, min(done, total)), total, str(phase or "")
    return 0, 0, str(phase or "")


def sites_save(client, name: str, toml: str, overwrite: bool,
               on_done: Callable[[str, str, str], None]) -> None:
    """``on_done(caminho, erro, codigo)``."""
    args: dict[str, Any] = {"name": name, "toml": toml}
    if overwrite:
        args["overwrite"] = True

    def done(resp) -> None:
        if not reply.is_ok(resp):
            return on_done("", reply.error_text(resp), reply.error_code(resp))
        data = reply.payload(resp)
        on_done(str(data.get("path", "")) if isinstance(data, dict) else "", "", "")
    client.request("sites.save", args, done)


def sites_list(client, on_done: Callable[[list[dict[str, Any]]], None]) -> None:
    def done(resp) -> None:
        data = reply.payload(resp)
        on_done(data if reply.is_ok(resp) and isinstance(data, list) else [])
    client.request("sites.list", {}, done)
