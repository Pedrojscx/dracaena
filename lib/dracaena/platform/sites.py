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
    code = "bad_state"


def save(name, toml, overwrite=False, write=True):
    """Grava sites/<name>.toml e devolve {"path"}; com write=False só valida (simulado)."""
    validate(name, toml, overwrite)
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


def list_sites():
    sites = []
    for path in sorted(sites_dir().glob("*.toml")):
        try:
            with path.open("rb") as stream:
                site = tomllib.load(stream).get("site", {})
        except (OSError, tomllib.TOMLDecodeError):
            continue
        sites.append({"name": site.get("name", path.stem), "version": site.get("version", 0)})
    return sites
