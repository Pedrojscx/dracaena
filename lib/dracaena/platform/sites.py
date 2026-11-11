"""Definições de site (TOML) do usuário: validação, listagem e gravação atômica."""
import os
from pathlib import Path
import re
import tempfile
import tomllib
from .paths import config_dir, private_dir

MAX_TOML_BYTES = 64 * 1024
NAME = re.compile(r"[a-z0-9_-]{1,64}")


def sites_dir():
    return config_dir() / "sites"


def validate(name, toml, overwrite=False):
    """Valida os argumentos de sites.save; levanta ValueError em português."""
    if not isinstance(name, str) or not NAME.fullmatch(name):
        raise ValueError("Nome inválido: use de 1 a 64 caracteres entre a-z, 0-9, '_' e '-'")
    if not isinstance(toml, str):
        raise ValueError("O conteúdo TOML deve ser um texto")
    if len(toml.encode("utf-8", "surrogatepass")) > MAX_TOML_BYTES:
        raise ValueError("O TOML excede o limite de 64 KiB")
    if not isinstance(overwrite, bool):
        raise ValueError("'overwrite' deve ser verdadeiro ou falso")
    try:
        tomllib.loads(toml)
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"TOML inválido: {exc}") from None
    return name, toml, overwrite


class SiteExists(Exception):
    code = "exists"


def save(name, toml, overwrite=False, write=True, existing=()):
    """Grava sites/<name>.toml e devolve {"path"}; com write=False só valida (simulado).

    `existing` (só no simulado) lista nomes que contam como já existentes.
    """
    validate(name, toml, overwrite)
    if not write and not overwrite and name in existing:
        raise SiteExists("Já existe um site com esse nome; confirme a substituição (overwrite)")
    target = sites_dir() / (name + ".toml")
    if not write:
        return {"path": str(target)}
    directory = private_dir(sites_dir())
    fd, temporary = tempfile.mkstemp(dir=directory, prefix=".site-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(toml)
            stream.flush()
            os.fsync(stream.fileno())
        if overwrite:
            os.replace(temporary, target)
        else:
            try:
                os.link(temporary, target)  # atômico: falha se já existir
            except FileExistsError:
                raise SiteExists("Já existe um site com esse nome; confirme a substituição (overwrite)") from None
    finally:
        Path(temporary).unlink(missing_ok=True)
    return {"path": str(target)}


def _describe(path):
    """{name, slug, valid} de um arquivo; nunca levanta: ilegível/inválido => valid=False."""
    slug = path.stem
    info = dict(name=slug, slug=slug, valid=False)
    if not NAME.fullmatch(slug):
        return info
    try:
        with path.open("rb") as stream:
            raw = stream.read(MAX_TOML_BYTES + 1)
        if len(raw) > MAX_TOML_BYTES:
            return info
        data = tomllib.loads(raw.decode("utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError):
        return info
    display = data.get("site", {}).get("name") if isinstance(data.get("site"), dict) else None
    if isinstance(display, str) and display.strip():
        info["name"] = display
    info["valid"] = True  # TODO: trocar pelo validador de perfil do B1 (adapters/profile.py)
    return info


def list_sites():
    try:
        paths = sorted(p for p in sites_dir().glob("*.toml") if p.is_file())
    except OSError:
        return []
    return [_describe(path) for path in paths]
