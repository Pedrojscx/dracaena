"""Diagnósticos exibem presença de credenciais, nunca seu conteúdo."""
from __future__ import annotations

import os
import re

SECRET_NAME = re.compile(r"secret|token|passw(?:or)?d|password|passwd|cookie|credential|api.?key|authorization|auth|passphrase|private.?key|(?:^|_)key(?:$|_)", re.I)
ASSIGNMENT = re.compile(
    r"(?i)(\b[\w.-]*(?:secret|token|password|passwd|cookie|credential|api[_-]?key|authorization)[\w.-]*[\"']?\s*[=:]\s*)(?:\"[^\"]*\"|'[^']*'|[^\s,;]+)")


def sensitive(name: str) -> bool:
    return bool(SECRET_NAME.search(name))


def environment(keys, env=None) -> dict:
    env = os.environ if env is None else env
    names = set(keys) | {k for k in env if sensitive(k)}
    return {k: ("definida" if env.get(k) else "ausente") if sensitive(k) else env.get(k)
            for k in sorted(names)}


def text(value: str, env=None) -> str:
    env = os.environ if env is None else env
    secrets = sorted({v for k, v in env.items() if sensitive(k) and v}, key=len, reverse=True)
    for secret in secrets:
        value = value.replace(secret, "[credencial omitida]")
    value = re.sub(r"(?im)^((?:set-)?cookie|authorization)\s*:\s*.*$", r"\1: [credencial omitida]", value)
    value = ASSIGNMENT.sub(r"\1[credencial omitida]", value)
    value = re.sub(r"(?i)\bBearer\s+[^\s,;]+", "Bearer [credencial omitida]", value)
    value = re.sub(r"(https?://)[^/\s:@]+:[^/\s@]+@", r"\1[credencial omitida]@", value)
    return value


def data(value):
    if isinstance(value, dict):
        return {k: (v if isinstance(v, str) and v in ("definida", "ausente") else ("definida" if v else "ausente")) if sensitive(k) else data(v) for k, v in value.items()}
    if isinstance(value, list):
        return [data(v) for v in value]
    return text(value) if isinstance(value, str) else value
