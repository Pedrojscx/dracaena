"""Configuração KEY=VALUE (o mesmo arquivo é lido pelo bash)."""

from __future__ import annotations

import os
import re
from pathlib import Path

_LINE = re.compile(r"^\s*([A-Z][A-Z0-9_]*)\s*=\s*(.*?)\s*$")

INT_KEYS = {"CLAUDE_TIMEOUT", "CDP_PORT", "RETRY_ON_INCORRECT", "MAX_QUESTIONS", "KEEP_DAYS", "NOTIFY_OVER_DND",
            "ACTION_TIMEOUT_MS", "VERIFY_TIMEOUT_MS", "SUBMIT_TIMEOUT_MS", "FEEDBACK_TIMEOUT_MS", "ADVANCE_TIMEOUT_MS", "CLICK_SUBMIT", "CLAUDE_SCHEMA", "RECOVER_TIMEOUT_MS"}
LIST_KEYS = {"SUBMIT_WORDS_BLOCKLIST", "RESET_WORDS", "END_WORDS"}

REPO = Path(__file__).resolve().parents[2]
DEFAULT = REPO / "config" / "quiz-helper.conf"


class ConfigError(ValueError):
    pass


def split_list(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


def parse_text(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = _LINE.match(line)
        if not m:
            raise ConfigError(f"linha {n} inválida: {raw!r}")
        key, value = m.groups()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        out[key] = value
    return out


def typed(raw: dict[str, str]) -> dict:
    cfg: dict = {}
    for key, value in raw.items():
        try:
            if key in INT_KEYS:
                cfg[key] = int(value)
            elif key in LIST_KEYS:
                cfg[key] = split_list(value)
            else:
                cfg[key] = value
        except ValueError as exc:
            raise ConfigError(f"{key}={value!r}: valor inválido") from exc
    return cfg


def config_dir() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "quiz-helper"


def data_dir() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "quiz-helper"


def runtime_dir() -> Path:
    base = os.environ.get("QH_RUNTIME_DIR")
    if base:
        return Path(base)
    xdg = os.environ.get("XDG_RUNTIME_DIR")
    return Path(xdg) / "quiz-helper" if xdg else Path(f"/tmp/quiz-helper-{os.getuid()}")


def load(default_path: str | Path = DEFAULT, user_path: str | Path | None = None) -> dict:
    """Padrões do repositório < caminhos da instalação < config do usuário."""
    raw = parse_text(Path(default_path).read_text(encoding="utf-8"))
    for extra in (config_dir() / "paths", Path(user_path) if user_path else config_dir() / "config"):
        if extra.exists():
            raw.update(parse_text(extra.read_text(encoding="utf-8")))
    return typed(raw)
