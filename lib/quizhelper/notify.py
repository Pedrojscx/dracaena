"""Notificações do quiz-helper: um único id, substituído (nunca empilha).

O id fica em $XDG_RUNTIME_DIR/quiz-helper/notify.id, o mesmo arquivo usado
por lib/sh/notify.sh: Python e bash substituem a mesma notificação, inclusive
entre invocações diferentes. Com "não perturbe" ativo e NOTIFY_OVER_DND=1, a
urgência sobe para crítica (que os daemons mostram mesmo assim).
"""

from __future__ import annotations

import os
import shutil
import subprocess

from . import config as configmod
from . import private


def _dnd_active() -> bool:
    checks = [(["swaync-client", "--get-dnd"], lambda o: o.strip() == "true"),
              (["makoctl", "mode"], lambda o: "do-not-disturb" in o.split()),
              (["dunstctl", "is-paused"], lambda o: o.strip() == "true")]
    for cmd, ok in checks:
        if shutil.which(cmd[0]):
            try:
                if ok(subprocess.run(cmd, capture_output=True, text=True, timeout=2).stdout):
                    return True
            except (OSError, subprocess.SubprocessError):
                pass
    return False


def notify(body: str, urgency: str = "normal", expire_ms: int = 0, cfg: dict | None = None,
           summary: str = "quiz-helper") -> None:
    if os.environ.get("QH_NOTIFY_ENABLED", "1") != "1" or not shutil.which("notify-send"):
        return
    cfg = cfg or {}
    if urgency != "critical" and int(cfg.get("NOTIFY_OVER_DND", 1)) == 1 and _dnd_active():
        urgency = "critical"
    idfile = configmod.runtime_dir() / "notify.id"
    private.mkdir(idfile.parent)
    old = idfile.read_text().strip() if idfile.exists() else ""
    cmd = ["notify-send", "-a", "quiz-helper", "-u", urgency, "-t", str(expire_ms), "-p"]
    if old.isdigit():
        cmd += ["-r", old]
    try:
        out = subprocess.run(cmd + ["--", summary, body], capture_output=True, text=True, timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return
    if out.isdigit():
        private.write_text(idfile, out + "\n")
