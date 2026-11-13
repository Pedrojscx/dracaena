"""Diagnóstico somente leitura, utilizável mesmo sem o daemon em execução.

Formato: {ok, checks: [{name, ok, message?, hint?}]}, com textos em português.
"""
import importlib.util
import os
import shutil
from . import browser, config
from .paths import config_dir, data_dir, runtime_dir

PROMPTS = ("system.txt", "answer.txt", "invalid.txt", "retry.txt")


def _prompts_check():
    """Os prompts pertencem ao núcleo; a checagem só existe quando o pacote está presente."""
    try:
        present = importlib.util.find_spec("dracaena.core.prompts") is not None
    except (ImportError, ValueError):
        present = False
    if not present:
        return None
    from importlib.resources import files
    missing = [name for name in PROMPTS if not files("dracaena.core.prompts").joinpath(name).is_file()]
    if missing:
        return False, "Prompts ausentes: " + ", ".join(missing), "Reinstale o Dracaena."
    return True, "Prompts do núcleo legíveis.", None


def run():
    checks = []

    def add(name, ok, message, hint=None):
        check = dict(name=name, ok=ok, message=message)
        if hint and not ok:
            check["hint"] = hint
        checks.append(check)

    try:
        cfg = config.load()
        add("config", True, "Configuração legível.")
    except (OSError, ValueError) as exc:
        cfg = {}
        add("config", False, str(exc), "Corrija ou remova o arquivo config.json da pasta de configuração.")
    prompts = _prompts_check()
    if prompts:
        add("prompts", *prompts)
    claude = cfg.get("CLAUDE_BIN") or "claude"
    found = shutil.which(claude)
    add("claude", bool(found), found or f"Claude Code não encontrado ({claude}).",
        "Instale o Claude Code e confirme que o comando 'claude' está no PATH, ou informe o caminho nas configurações.")
    try:
        add("browser", True, browser.resolve(cfg.get("BROWSER_BIN", ""), cfg.get("BROWSER_FALLBACK", "")))
    except browser.FallbackMissing as exc:
        add("browser", False, str(exc),
            f"Rode 'dracaena install-browser' para baixar o Chromium reserva (cerca de {browser.FALLBACK_SIZE} em disco, com confirmação) "
            "ou informe um navegador Chromium nas configurações.")
    except browser.BrowserError as exc:
        add("browser", False, str(exc),
            "Informe um navegador Chromium nas configurações ou rode 'dracaena install-browser' para o navegador reserva.")
    except Exception:
        add("browser", False, "Não foi possível verificar o navegador.",
            "Informe um navegador Chromium nas configurações.")
    if os.name != "nt":
        add("notifications", bool(shutil.which("notify-send")), "notify-send disponível." if shutil.which("notify-send")
            else "notify-send não encontrado.", "Instale o libnotify (notify-send) para receber avisos.")
        has_clip = bool(shutil.which("wl-copy") or shutil.which("xclip"))
        add("clipboard", has_clip, "Área de transferência disponível." if has_clip else "wl-copy/xclip não encontrados.",
            "Instale wl-clipboard (Wayland) ou xclip (X11).")
    add("paths", True, f"Configuração: {config_dir()} · Dados: {data_dir()} · Execução: {runtime_dir()}")
    return dict(ok=all(c["ok"] for c in checks), checks=checks)
