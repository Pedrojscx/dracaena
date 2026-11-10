"""AppState: único lugar onde telas e bandeja leem o estado do daemon.

Alimentado pelo cliente IPC (ui/ipc_client, B1) e pelo CONTRATO v0:
evento {"event":"state","state":"idle|running|paused|error","site","question","max","error"}.
Nenhum widget fala com o socket; todos assinam os sinais daqui.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import QObject, Signal

STATES = ("idle", "running", "paused", "error")


@dataclass(frozen=True)
class RunState:
    state: str = "idle"        # idle | running | paused | error
    site: str = ""
    question: int = 0
    max: int = 0
    error: str = ""
    connected: bool = False    # só da UI


class AppState(QObject):
    changed = Signal(object)         # RunState
    sites_changed = Signal(object)   # list[dict] de sites.list
    schema_ready = Signal(object)    # list[dict] de config.schema
    config_ready = Signal(object)    # dict de config.get

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.run = RunState()
        self.sites: list[dict[str, Any]] = []
        self.schema: list[dict[str, Any]] = []

    def set_connected(self, ok: bool) -> None:
        self.run = RunState(**{**self.run.__dict__, "connected": ok})
        self.changed.emit(self.run)

    def apply_state_event(self, data: dict[str, Any]) -> None:
        st = data.get("state", "idle")
        if st not in STATES:
            return
        self.run = RunState(state=st, site=str(data.get("site", "")), question=int(data.get("question", 0)),
                            max=int(data.get("max", 0)), error=str(data.get("error", "")),
                            connected=self.run.connected)
        self.changed.emit(self.run)

    def set_sites(self, sites: list[dict[str, Any]]) -> None:
        self.sites = sites
        self.sites_changed.emit(sites)

    def set_schema(self, schema: list[dict[str, Any]]) -> None:
        self.schema = schema
        self.schema_ready.emit(schema)
