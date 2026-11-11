"""Read-only diagnostics, usable even when no daemon is running."""
import os
import shutil
from . import browser, config
from .paths import config_dir, data_dir, runtime_dir
from .resources import default_config


def run():
    checks = []
    def add(name, ok, detail):
        checks.append(dict(name=name, ok=ok, detail=detail))
    try:
        cfg = config.load()
        add("resources", bool(default_config()), "Configuração padrão embutida legível")
    except (OSError, ValueError) as exc:
        cfg = {}
        add("resources", False, str(exc))
    add("claude", bool(cfg.get("CLAUDE_BIN") or shutil.which("claude")), "Claude Code é uma dependência externa")
    try:
        executable = browser.resolve(cfg.get("BROWSER_BIN", ""), cfg.get("BROWSER_FALLBACK", ""))
        add("browser", True, executable)
    except browser.BrowserError as exc:
        add("browser", False, str(exc))
    if os.name != "nt":
        add("notifications", bool(shutil.which("notify-send")), "notify-send (freedesktop)")
        add("clipboard", bool(shutil.which("wl-copy") or shutil.which("xclip")), "wl-copy (Wayland) ou xclip (X11)")
    return dict(ok=all(c["ok"] for c in checks), checks=checks,
                paths=dict(config=str(config_dir()), data=str(data_dir()), runtime=str(runtime_dir())))
