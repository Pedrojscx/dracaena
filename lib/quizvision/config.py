"""Leitura da configuração KEY=VALUE (mesmo formato lido pelo bash)."""

from __future__ import annotations

import re
from pathlib import Path

from .text import split_list

_LINE = re.compile(r"^\s*([A-Z][A-Z0-9_]*)\s*=\s*(.*?)\s*$")

INT_KEYS = {
    "CLAUDE_TIMEOUT", "CLICK_OFFSET_X", "OCR_MIN_CONF", "CLICK_SUBMIT", "SUBMIT_DELAY_MS", "DROPDOWN_DELAY_MS",
    "FEEDBACK_DELAY_MS", "NEXT_DELAY_MS", "STABLE_INTERVAL_MS", "STABLE_TOLERANCE_PX", "ADVANCE_TIMEOUT",
    "MAX_QUESTIONS", "MAX_SCROLLS", "SCROLL_STEP", "MOUSE_ABORT_PX", "DRAG_STEPS", "DRAG_STEP_MS",
    "RETRY_ON_INCORRECT", "KEEP_DAYS", "NOTIFY_OVER_DND",
}
FLOAT_KEYS = {"MATCH_THRESHOLD"}
LIST_KEYS = {"SUBMIT_WORDS_BLOCKLIST", "FEEDBACK_CORRECT_WORDS", "FEEDBACK_INCORRECT_WORDS", "END_WORDS",
             "RESET_WORDS"}
CHOICES = {"MATCH_MODE": {"drag", "click"}}


class ConfigError(ValueError):
    pass


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
            elif key in FLOAT_KEYS:
                cfg[key] = float(value)
            elif key in LIST_KEYS:
                cfg[key] = split_list(value)
            else:
                cfg[key] = value
        except ValueError as exc:
            raise ConfigError(f"{key}={value!r}: valor inválido") from exc
        if key in CHOICES and cfg[key] not in CHOICES[key]:
            raise ConfigError(f"{key} precisa ser um de {sorted(CHOICES[key])}")
    if "MATCH_THRESHOLD" in cfg and not 0 < cfg["MATCH_THRESHOLD"] <= 1:
        raise ConfigError("MATCH_THRESHOLD precisa estar entre 0 e 1")
    return cfg


def load(default_path: str | Path, user_path: str | Path | None = None) -> dict:
    """Padrões do repositório sobrepostos pela configuração do usuário."""
    raw = parse_text(Path(default_path).read_text(encoding="utf-8"))
    if user_path and Path(user_path).exists():
        raw.update(parse_text(Path(user_path).read_text(encoding="utf-8")))
    return typed(raw)
