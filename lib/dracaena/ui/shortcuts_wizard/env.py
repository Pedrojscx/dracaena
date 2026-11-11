"""Detecção do ambiente gráfico para escolher o caminho do assistente de atalhos."""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class Environment:
    session: str        # "windows" | "x11" | "wayland" | "unknown"
    compositor: str     # "gnome" | "kde" | "hyprland" | "sway" | "i3" | "other"
    desktops: tuple[str, ...] = ()

    @property
    def app_can_register(self) -> bool:
        """Windows e X11: o próprio app registra o atalho (B1/hotkeys)."""
        return self.session in ("windows", "x11")


def detect(environ: Mapping[str, str] | None = None, platform: str | None = None) -> Environment:
    env = os.environ if environ is None else environ
    plat = sys.platform if platform is None else platform
    desktops = tuple(p.strip().lower() for p in env.get("XDG_CURRENT_DESKTOP", "").split(":") if p.strip())
    if plat == "win32":
        return Environment("windows", "other", desktops)
    stype = env.get("XDG_SESSION_TYPE", "").strip().lower()
    if stype not in ("x11", "wayland"):
        stype = "wayland" if env.get("WAYLAND_DISPLAY") else ("x11" if env.get("DISPLAY") else "unknown")
    names = set(desktops)
    if "hyprland" in names or env.get("HYPRLAND_INSTANCE_SIGNATURE"):
        comp = "hyprland"
    elif "sway" in names or env.get("SWAYSOCK"):
        comp = "sway"
    elif "i3" in names or env.get("I3SOCK"):
        comp = "i3"
    elif "gnome" in names:
        comp = "gnome"
    elif "kde" in names:
        comp = "kde"
    else:
        comp = "other"
    return Environment(stype, comp, desktops)
