"""Pastas de dados e de execução do app (independentes do módulo de configuração)."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

APP = "dracaena"


def data_dir() -> Path:
    if os.name == "nt":
        return Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / APP
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / APP


def runtime_dir() -> Path:
    """Pasta efêmera e privada (socket, locks, ambiente do Claude)."""
    base = os.environ.get("DRACAENA_RUNTIME_DIR")
    if base:
        return Path(base)
    if os.name == "nt":
        return Path(tempfile.gettempdir()) / f"{APP}-{os.environ.get('USERNAME', 'user')}"
    xdg = os.environ.get("XDG_RUNTIME_DIR")
    return Path(xdg) / APP if xdg else Path(f"/tmp/{APP}-{os.getuid()}")
