"""Validated persistent configuration and one-time legacy import."""
import json
import os
from pathlib import Path
import tempfile
from .paths import config_dir, private_dir
from .resources import default_config

DEFAULTS = json.loads(default_config())
RANGES = {"CLAUDE_TIMEOUT": (1, 3600), "MAX_QUESTIONS": (1, 1000), "KEEP_DAYS": (1, 3650),
          "CLICK_SUBMIT": (0, 1), "RETRY_ON_INCORRECT": (0, 1)}


def schema():
    result = []
    for key, default in DEFAULTS.items():
        entry = dict(key=key, type="integer" if type(default) is int else "string", default=default,
                     description=key.lower().replace("_", " "))
        if key in RANGES:
            entry.update(min=RANGES[key][0], max=RANGES[key][1])
        if key == "BROWSER_FALLBACK":
            entry["choices"] = ["", "playwright"]
        result.append(entry)
    return result


def validate(key, value):
    if key not in DEFAULTS or type(value) is not type(DEFAULTS[key]):
        raise ValueError("Chave desconhecida ou tipo de valor inválido")
    if key in RANGES and not RANGES[key][0] <= value <= RANGES[key][1]:
        raise ValueError("Valor fora do intervalo permitido")
    if key == "BROWSER_FALLBACK" and value not in ("", "playwright"):
        raise ValueError("Fallback de navegador não suportado")
    return value


def save(config):
    directory = private_dir(config_dir())
    fd, name = tempfile.mkstemp(dir=directory, prefix=".config-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(config, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, directory / "config.json")
    finally:
        Path(name).unlink(missing_ok=True)


def load():
    path = config_dir() / "config.json"
    values = dict(DEFAULTS)
    if path.exists():
        try:
            stored = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeError) as exc:
            raise ValueError("O arquivo de configuração está corrompido; corrija ou remova config.json") from exc
        if not isinstance(stored, dict):
            raise ValueError("O arquivo de configuração deve conter um objeto JSON")
        for key, value in stored.items():
            values[key] = validate(key, value)
        return values
    # Preserve the old file and import only recognized settings; never execute shell.
    old = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "quiz-helper" / "config"
    if old.is_file():
        for line in old.read_text(encoding="utf-8").splitlines():
            if not line.strip() or line.lstrip().startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key, value = key.strip(), value.strip().strip("\"'")
            if key not in DEFAULTS:
                continue
            if type(DEFAULTS[key]) is int:
                try:
                    value = int(value)
                except ValueError:
                    raise ValueError(f"Valor inválido para {key} na configuração antiga") from None
            values[key] = validate(key, value)
        save(values)
    return values


def set_value(key, value):
    validate(key, value)
    values = load()
    values[key] = value
    save(values)
    return values
