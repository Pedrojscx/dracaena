"""Validador do PERFIL TOML v0 (arquivo PROVISÓRIO: o dono definitivo aguarda decisão).

Um perfil é só dado: seletores CSS e rótulos. Não há código executável nele, e
os seletores nunca são avaliados como código (o motor só os entrega a `matches`).
Campo ou tabela desconhecida é erro, com a linha.

    [site]      name, version = 0, match = ["glob de URL"], title (regex, opcional), frame (opcional)
    [question]  container, stem, instruction (opcional), figure (opcional)
    [options]   item, text (opcional), input (opcional), selected_attr (opcional)
    [dropdown]  item, button, option, native (bool)                     # opcional
    [submit]    button                                                   # opcional
    [reset]     button                                                   # opcional
    [feedback]  correct, incorrect, text (opcional)                      # opcional
    [guard]     block_labels = []                                        # só acrescenta
    [meta]      confidence (0 a 1), status, fingerprint, generator, generated   # opcional; o motor ignora
"""

from __future__ import annotations

import re
import tomllib
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

MAX_BYTES = 64 * 1024
SELECTOR, TEXT, BOOL, INT, ATTR, GLOBS, LABELS, REGEX = "selector", "text", "bool", "int", "attr", "globs", "labels", "regex"
UNIT, STATUS, WORD, DATE = "unit", "status", "word", "date"
STATUSES = ("verified", "unverified", "experimental")

# tabela -> campo -> (tipo, obrigatório)
SCHEMA: dict[str, dict[str, tuple[str, bool]]] = {
    "site": {"name": (TEXT, True), "version": (INT, True), "match": (GLOBS, True), "title": (REGEX, False),
             "frame": (TEXT, False)},
    "question": {"container": (SELECTOR, True), "stem": (SELECTOR, True), "instruction": (SELECTOR, False),
                 "figure": (SELECTOR, False)},
    "options": {"item": (SELECTOR, True), "text": (SELECTOR, False), "input": (SELECTOR, False),
                "selected_attr": (ATTR, False)},
    "dropdown": {"item": (SELECTOR, True), "button": (SELECTOR, False), "option": (SELECTOR, False),
                 "native": (BOOL, False)},
    "submit": {"button": (SELECTOR, True)},
    "reset": {"button": (SELECTOR, True)},
    "feedback": {"correct": (SELECTOR, False), "incorrect": (SELECTOR, False), "text": (SELECTOR, False)},
    "guard": {"block_labels": (LABELS, False)},
    "meta": {"confidence": (UNIT, False), "status": (STATUS, False), "fingerprint": (WORD, False),
             "generator": (WORD, False), "generated": (DATE, False)},
}
REQUIRED_TABLES = ("site", "question")
ENGINE_TABLES = ("question", "options", "dropdown", "submit", "reset", "feedback")
_FORBIDDEN = ("<", ">>", "{", "}", ";", "`", "\\", "\n", "\r", "javascript:", "expression(", "url(", "@import")
_ATTR = re.compile(r"[A-Za-z_][\w:.-]{0,63}")
_TABLE = re.compile(r"^\s*\[\s*([\w.-]+)\s*\]")
_KEY = re.compile(r"^\s*([\w-]+)\s*=")
_WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9 ._-]{0,39}")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}(:\d{2})?Z?)?")


class ProfileError(ValueError):
    """Perfil inválido; `line` é a linha do TOML (1 = primeira) ou None."""

    def __init__(self, msg: str, line: int | None = None):
        super().__init__(f"linha {line}: {msg}" if line else msg)
        self.msg, self.line = msg, line


@dataclass(frozen=True)
class Profile:
    name: str
    match: tuple[str, ...]
    title: str = ""
    frame: str = ""
    block_labels: tuple[str, ...] = ()
    meta: dict = field(default_factory=dict, compare=False)
    tables: dict = field(default_factory=dict, compare=False)
    slug: str = ""

    def to_engine(self) -> dict:
        """O perfil como dados para o motor (só as tabelas de leitura)."""
        return {name: dict(self.tables[name]) for name in ENGINE_TABLES if name in self.tables}


def _lines(text: str) -> dict:
    """(tabela, campo) -> linha e (tabela, None) -> linha do cabeçalho."""
    where: dict = {}
    table = ""
    for number, raw in enumerate(text.splitlines(), 1):
        head = _TABLE.match(raw)
        if head:
            table = head.group(1)
            where.setdefault((table, None), number)
            continue
        key = _KEY.match(raw)
        if key:
            where.setdefault((table, key.group(1)), number)
    return where


def _selector(value, what: str, line) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProfileError(f"{what} precisa ser um seletor CSS em texto", line)
    if len(value) > 300:
        raise ProfileError(f"{what}: seletor com mais de 300 caracteres", line)
    low = value.lower()
    for bad in _FORBIDDEN:
        if bad in low:
            raise ProfileError(f"{what}: o seletor não pode conter {bad!r} (perfil não leva código)", line)
    return value.strip()


def _value(kind: str, value, what: str, line):
    if kind == SELECTOR:
        return _selector(value, what, line)
    if kind == BOOL:
        if not isinstance(value, bool):
            raise ProfileError(f"{what} precisa ser true ou false", line)
        return value
    if kind == INT:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ProfileError(f"{what} precisa ser um inteiro", line)
        return value
    if kind == UNIT:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 1:
            raise ProfileError(f"{what} precisa ser um número de 0 a 1", line)
        return round(float(value), 2)
    if kind == STATUS:
        if value not in STATUSES:
            raise ProfileError(f"{what} precisa ser um de: {', '.join(STATUSES)}", line)
        return value
    if kind in (WORD, DATE):
        if not isinstance(value, str) or not (_WORD if kind == WORD else _DATE).fullmatch(value):
            raise ProfileError(f"{what} precisa ser " + ("um nome curto (letras, dígitos, espaço, ponto, hífen)"
                                                         if kind == WORD else "uma data AAAA-MM-DD"), line)
        return value
    if kind == ATTR:
        if not isinstance(value, str) or not _ATTR.fullmatch(value):
            raise ProfileError(f"{what} precisa ser um nome de atributo", line)
        return value
    if kind in (GLOBS, LABELS):
        limit = 300 if kind == GLOBS else 60
        if not isinstance(value, list) or len(value) > 40 or any(
                not isinstance(v, str) or not v.strip() or len(v) > limit or "\n" in v for v in value):
            raise ProfileError(f"{what} precisa ser uma lista de textos curtos", line)
        if kind == GLOBS:
            if not value:
                raise ProfileError(f"{what} precisa de ao menos um padrão de URL", line)
            for glob in value:
                if not re.match(r"(https?://|\*)", glob):
                    raise ProfileError(f"{what}: o padrão precisa começar com http://, https:// ou *", line)
        return tuple(v.strip() for v in value)
    if not isinstance(value, str) or not value.strip() or len(value) > 200 or "\n" in value:
        raise ProfileError(f"{what} precisa ser um texto curto", line)
    if kind == REGEX:
        try:
            re.compile(value)
        except re.error as exc:
            raise ProfileError(f"{what}: expressão regular inválida ({exc})", line) from None
    return value.strip()


def parse(text: str, slug: str = "") -> Profile:
    """Valida o TOML v0 e devolve o perfil; levanta `ProfileError` com a linha."""
    if not isinstance(text, str):
        raise ProfileError("o perfil precisa ser um texto TOML")
    if len(text.encode("utf-8", "surrogatepass")) > MAX_BYTES:
        raise ProfileError("o perfil excede o limite de 64 KiB")
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        found = re.search(r"line (\d+)", str(exc))
        raise ProfileError(f"TOML inválido ({exc})", int(found.group(1)) if found else None) from None
    where = _lines(text)
    tables: dict = {}
    for name, body in data.items():
        line = where.get((name, None)) or where.get(("", name))
        if name not in SCHEMA:
            raise ProfileError(f"tabela ou campo desconhecido: {name}", line)
        if not isinstance(body, dict):
            raise ProfileError(f"{name} precisa ser uma tabela", line)
        out = {}
        for key, value in body.items():
            at = where.get((name, key)) or line
            if key not in SCHEMA[name]:
                raise ProfileError(f"campo desconhecido: {name}.{key}", at)
            out[key] = _value(SCHEMA[name][key][0], value, f"{name}.{key}", at)
        for key, (_, required) in SCHEMA[name].items():
            if required and key not in out:
                raise ProfileError(f"falta o campo {name}.{key}", line)
        tables[name] = out
    for name in REQUIRED_TABLES:
        if name not in tables:
            raise ProfileError(f"falta a tabela [{name}]")
    if "options" not in tables and "dropdown" not in tables:
        raise ProfileError("falta a tabela [options] ou [dropdown]")
    site = tables["site"]
    if site["version"] != 0:
        raise ProfileError("site.version precisa ser 0", where.get(("site", "version")))
    drop = tables.get("dropdown")
    if drop is not None and drop.get("native") is False and not (drop.get("button") and drop.get("option")):
        raise ProfileError("dropdown com native = false precisa de button e option", where.get(("dropdown", None)))
    return Profile(name=site["name"], match=site["match"], title=site.get("title", ""), frame=site.get("frame", ""),
                   block_labels=tuple(tables.get("guard", {}).get("block_labels", ())), tables=tables, slug=slug,
                   meta=dict(tables.get("meta", {})))


def load_all(directory, warn: Callable[[str], None] | None = None) -> list[Profile]:
    """Perfis válidos de `directory/*.toml`, em ordem de nome. Arquivo inválido é ignorado com aviso."""
    out = []
    try:
        paths = sorted(p for p in Path(directory).glob("*.toml") if p.is_file())
    except OSError:
        return out
    for path in paths:
        try:
            with path.open("rb") as stream:
                raw = stream.read(MAX_BYTES + 1)
            out.append(parse(raw.decode("utf-8"), slug=path.stem))
        except (OSError, UnicodeError, ProfileError) as exc:
            if warn is not None:
                warn(f"perfil ignorado ({path.name}): {exc}")
    return out


def _quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def dump(tables: dict) -> str:
    """TOML canônico das tabelas já validadas (ordem do contrato; só os campos do esquema)."""
    lines: list[str] = []
    for name, fields in SCHEMA.items():
        body = tables.get(name)
        if not body:
            continue
        lines.append(f"[{name}]")
        for key in fields:
            if key not in body:
                continue
            value = body[key]
            if isinstance(value, bool):
                text = "true" if value else "false"
            elif isinstance(value, (int, float)):
                text = str(value)
            elif isinstance(value, (list, tuple)):
                text = "[" + ", ".join(_quote(v) for v in value) + "]"
            else:
                text = _quote(value)
            lines.append(f"{key} = {text}")
        lines.append("")
    return "\n".join(lines)
