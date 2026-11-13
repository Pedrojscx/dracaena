"""Validated persistent configuration and one-time legacy import."""
import json
import os
from pathlib import Path
import tempfile
from .paths import config_dir, private_dir
from .resources import default_config

DEFAULTS = json.loads(default_config())
# Tabela única das chaves editáveis: validação (min/max/choices) e schema saem dela.
FIELDS = {
    "MODEL": dict(label="Modelo", description="Modelo do Claude usado para responder às questões (por exemplo, haiku, sonnet ou opus)."),
    "RETRY_MODEL": dict(label="Modelo da nova tentativa", description="Modelo usado ao tentar de novo depois de uma resposta incorreta. Vazio usa o mesmo modelo."),
    "CLAUDE_TIMEOUT": dict(label="Tempo limite do Claude (s)", description="Segundos de espera pela resposta do Claude antes de desistir da questão.", min=1, max=3600),
    "CLAUDE_BIN": dict(label="Executável do Claude", description="Caminho do Claude Code. Vazio procura o comando 'claude' no PATH."),
    "BROWSER_BIN": dict(label="Navegador", description="Caminho de um navegador baseado em Chromium. Vazio usa o navegador padrão detectado."),
    "BROWSER_FALLBACK": dict(label="Navegador reserva", description="Usado só quando nenhum navegador estiver configurado ou detectado. 'playwright' usa o Chromium do Playwright; vazio desativa.", choices=["", "playwright"]),
    "MAX_QUESTIONS": dict(label="Máximo de questões", description="Quantidade máxima de questões respondidas por sessão.", min=1, max=1000),
    "KEEP_DAYS": dict(label="Dias de retenção", description="Dias em que registros e respostas locais são mantidos antes da limpeza.", min=1, max=3650),
    "CLICK_SUBMIT": dict(label="Enviar a prática automaticamente", description="1 clica no botão de envio da prática depois de marcar a resposta; 0 apenas marca.", min=0, max=1),
    "RETRY_ON_INCORRECT": dict(label="Tentar de novo se incorreta", description="1 tenta outra vez quando a prática indicar resposta incorreta; 0 segue adiante.", min=0, max=1),
    "DRY_RUN": dict(label="Modo simulação", description="Modo simulação: valida e registra sem clicar na página."),
}
assert set(FIELDS) == set(DEFAULTS), "FIELDS e default.json devem ter as mesmas chaves"
RANGES = {key: (field["min"], field["max"]) for key, field in FIELDS.items() if "min" in field}


def schema():
    result = []
    for key, default in DEFAULTS.items():
        field = FIELDS[key]
        kind = "boolean" if type(default) is bool else "integer" if type(default) is int else "string"
        entry = dict(key=key, type=kind, default=default,
                     label=field["label"], description=field["description"])
        for extra in ("min", "max", "choices"):
            if extra in field:
                entry[extra] = field[extra]
        result.append(entry)
    return result


def validate(key, value):
    if key not in DEFAULTS or type(value) is not type(DEFAULTS[key]):
        raise ValueError("Chave desconhecida ou tipo de valor inválido")
    if key in RANGES and not RANGES[key][0] <= value <= RANGES[key][1]:
        raise ValueError("Valor fora do intervalo permitido")
    if "choices" in FIELDS[key] and value not in FIELDS[key]["choices"]:
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
            if type(DEFAULTS[key]) is bool:
                flags = {"1": True, "true": True, "sim": True, "0": False, "false": False, "nao": False, "não": False}
                if value.lower() not in flags:
                    raise ValueError(f"Valor inválido para {key} na configuração antiga") from None
                value = flags[value.lower()]
            elif type(DEFAULTS[key]) is int:
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
