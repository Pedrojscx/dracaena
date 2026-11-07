"""Chamada ao Claude Code (`claude -p`) só com TEXTO (sem ferramentas).

Para responder rápido e sem herdar nada do projeto, o claude roda:
- numa pasta vazia ($XDG_RUNTIME_DIR/quiz-helper/claude-cwd), nunca no
  repositório: não carrega CLAUDE.md, settings nem MCPs do projeto;
- com `--safe-mode` (sem CLAUDE.md, skills, plugins, hooks, MCPs, comandos),
  `--strict-mcp-config`, `--no-chrome`, `--disable-slash-commands`,
  `--no-session-persistence` e `--tools ""` (nenhuma ferramenta);
- com um prompt de sistema curto (prompts/system.txt) no lugar do padrão.
`--bare` não é usado: nele a autenticação exige ANTHROPIC_API_KEY (o login
OAuth do Claude Code deixaria de valer). Medido na 2.1.319: média de 4,5 s
para 3,3 s por consulta, mesma resposta.

Nos atalhos do Hyprland não há o ambiente do shell interativo:
CLAUDE_CODE_TMPDIR aponta para um diretório próprio quando não vier definido
(o claude recusa um /tmp/claude-<uid> que não seja do usuário).
"""

from __future__ import annotations

import base64
import json
import os
import re
import shutil
import subprocess
import threading
import time
from collections.abc import Callable
from pathlib import Path

from . import config as configmod
from .config import REPO
from . import private, redact

PROMPTS = REPO / "prompts"


class ClaudeError(RuntimeError):
    pass


class Aborted(RuntimeError):
    """Consulta interrompida (pausa ou parada)."""


def claude_bin(cfg: dict) -> str:
    for c in (cfg.get("CLAUDE_BIN"), shutil.which("claude"), str(Path.home() / ".local/bin/claude"),
              str(Path.home() / ".claude/local/claude"), "/usr/bin/claude"):
        if c and os.access(c, os.X_OK):
            return c
    raise ClaudeError("claude não encontrado (CLAUDE_BIN na configuração ou no PATH)")


def prompt(kind: str, question: str, previous: str = "", feedback: str = "") -> str:
    text = (PROMPTS / f"{kind}.txt").read_text(encoding="utf-8")
    return text.replace("{QUESTION}", question).replace("{PREVIOUS}", previous).replace("{FEEDBACK}", feedback)


def system_prompt() -> str:
    return (PROMPTS / "system.txt").read_text(encoding="utf-8").strip()


def claude_env(cfg: dict) -> tuple[dict, Path, Path]:
    """(ambiente, cwd, tmp) da consulta: independe do shell que a chamou (terminal ou atalho)."""
    env = dict(os.environ)
    tmp = Path(env.get("CLAUDE_CODE_TMPDIR") or str(configmod.runtime_dir() / "claude-tmp"))
    cwd = configmod.runtime_dir() / "claude-cwd"
    for d in (tmp, cwd):
        private.mkdir(d)
    env["CLAUDE_CODE_TMPDIR"] = str(tmp)
    return env, cwd, tmp


def model_for(cfg: dict, retry: bool = False) -> str:
    """Modelo da consulta: MODEL; na segunda tentativa, RETRY_MODEL se estiver preenchido."""
    if retry and cfg.get("RETRY_MODEL", "").strip():
        return cfg["RETRY_MODEL"].strip()
    return cfg.get("MODEL", "haiku").strip() or "haiku"


def build_cmd(cfg: dict, text: str, model: str | None = None, schema: dict | None = None,
              images: bool = False) -> list[str]:
    """Linha de comando. Com `images`, o texto e as figuras vão por stdin (stream-json), sem ferramentas."""
    fmt = ["--input-format", "stream-json", "--output-format", "stream-json", "--verbose"] if images else \
        ["--output-format", "json" if schema else "text"]
    cmd = [claude_bin(cfg), "-p", "--model", model or model_for(cfg), "--tools", "", "--safe-mode",
           "--strict-mcp-config", "--no-chrome", "--disable-slash-commands", "--no-session-persistence",
           *fmt, "--system-prompt", system_prompt()]
    if schema:
        cmd += ["--json-schema", json.dumps(schema, ensure_ascii=False)]
    cmd += cfg.get("CLAUDE_EXTRA_ARGS", "").split()
    if not images:
        cmd.append(text)
    return cmd


def stream_message(text: str, images: list[bytes]) -> str:
    """Mensagem de usuário (uma linha JSON) com o texto e as figuras em base64."""
    content: list[dict] = [{"type": "text", "text": text}]
    content += [{"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                             "data": base64.b64encode(b).decode()}} for b in images]
    return json.dumps({"type": "user", "message": {"role": "user", "content": content}}) + "\n"


def _stream_result(out: str) -> str:
    for line in reversed(out.strip().splitlines()):
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if d.get("type") == "result":
            if d.get("is_error"):
                raise ClaudeError(error_message(0, str(d.get("result", "")), ""))
            return str(d.get("result", ""))
    raise ClaudeError("saída stream-json sem resultado")


def _feed(proc, payload: str) -> None:
    try:
        proc.stdin.write(payload)
        proc.stdin.close()
    except (BrokenPipeError, OSError, ValueError):
        pass


def error_message(code: int, out: str, err: str) -> str:
    """Resume os dois canais e prioriza causas acionáveis sobre avisos."""
    lines = [redact.text(line.strip()) for line in (err + "\n" + out).splitlines() if line.strip()]
    if not lines:
        return f"código {code}: sem saída em stdout ou stderr"
    counts = {}
    for line in lines:
        counts[line] = counts.get(line, 0) + 1
    unique = list(counts)
    cause = re.compile(r"expired|expirad|not logged|not authenticated|log.?in|sign.?in|authenticate|authentication|"
                       r"unauthorized|invalid.*(?:token|key)|rate.?limit|limit.*(?:reached|exceeded)|quota|"
                       r"network|connection|econn|enotfound|timed? ?out|fetch failed|rede", re.I)
    error = re.compile(r"error|erro|fail|fatal|denied|refused", re.I)
    warnings = re.compile(r"warn|aviso|deprecated", re.I)
    priority = [line for line in unique if cause.search(line) and not warnings.search(line)]
    errors = [line for line in unique if error.search(line) and line not in priority and not warnings.search(line)]
    selected = priority[-2:] + errors[-1:] if priority else errors[-3:] or unique[-2:]
    def short(line):
        if len(line) > 240:
            return line[:100] + " … " + line[-130:]
        return line
    body = " | ".join(short(line) + (f" (repetida {counts[line]} vezes)" if counts[line] > 1 else "")
                      for line in selected)
    omitted = sum(counts[line] for line in unique if line not in selected)
    if omitted:
        body += f" | {omitted} linhas de contexto/avisos resumidas"
    return f"código {code}: {body}"


def ask(cfg: dict, text: str, abort: Callable[[], bool] | None = None,
        model: str | None = None, schema: dict | None = None,
        images: list[bytes] | None = None) -> tuple[str, float]:
    """Roda o claude e devolve (saída bruta, segundos). `abort()` é checado a cada 100 ms.

    Com `schema`, usa --json-schema e devolve o objeto estruturado já como texto JSON.
    """
    env, cwd, _ = claude_env(cfg)
    cmd = build_cmd(cfg, text, model, schema, images=bool(images))
    t0 = time.monotonic()
    proc = subprocess.Popen(cmd, cwd=cwd, env=env, stdin=subprocess.PIPE if images else subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
    if images:
        threading.Thread(target=_feed, args=(proc, stream_message(text, images)), daemon=True).start()
    limit = float(cfg.get("CLAUDE_TIMEOUT", 45))
    while proc.poll() is None:
        if abort and abort():
            proc.kill()
            proc.wait()
            raise Aborted("consulta interrompida")
        if time.monotonic() - t0 > limit:
            proc.kill()
            proc.wait()
            raise ClaudeError(f"tempo esgotado ({limit:.0f}s)")
        time.sleep(0.1)
    out, err = proc.communicate()
    elapsed = time.monotonic() - t0
    if proc.returncode != 0 or not out.strip():
        raise ClaudeError(error_message(proc.returncode, out, err))
    if images:
        out = _stream_result(out)
    elif schema:
        try:
            env_json = json.loads(out)
            payload = env_json.get("structured_output")
            out = json.dumps(payload, ensure_ascii=False) if payload is not None else str(env_json.get("result", ""))
        except ValueError:
            pass
    return out, elapsed
