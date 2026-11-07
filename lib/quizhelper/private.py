"""Criação privada de registros novos; não altera permissões preexistentes."""
from __future__ import annotations

import os
from pathlib import Path


def mkdir(path: Path) -> None:
    path = Path(path)
    if path.is_dir():
        return
    mkdir(path.parent)
    try:
        path.mkdir(mode=0o700)
    except FileExistsError:
        if not path.is_dir():
            raise


def open_file(path: Path, mode: str = "w"):
    """Abre texto/binário para escrita ou append; arquivos novos nascem 600."""
    if mode not in ("w", "a", "wb"):
        raise ValueError("modo de escrita não suportado")
    path = Path(path)
    mkdir(path.parent)
    flags = os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW
    flags |= os.O_APPEND if mode == "a" else os.O_TRUNC
    fd = os.open(path, flags, 0o600)
    return os.fdopen(fd, mode, **({} if "b" in mode else {"encoding": "utf-8"}))


def write_text(path: Path, text: str) -> None:
    with open_file(path) as fh:
        fh.write(text)


def write_bytes(path: Path, data: bytes) -> None:
    with open_file(path, "wb") as fh:
        fh.write(data)
