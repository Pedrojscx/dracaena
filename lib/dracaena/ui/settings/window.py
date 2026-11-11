"""Janela de configuração. Lê ``config.schema`` e ``config.get``; grava com ``config.set`` por chave."""
from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget)

from . import reply
from .form import SettingsForm

TXT_OFFLINE = "Sem conexão com o DRACAENA. Aguardando o programa em segundo plano."
TXT_LOAD_FAIL = "Não consegui carregar as configurações: {erro}"
TXT_SAVED = "Configurações salvas."
TXT_SAVE_FAIL = "Não salvei “{chave}”: {erro}"
TXT_NOTHING = "Nenhuma alteração para salvar."


class SettingsWindow(QWidget):
    """``client``: request(cmd, args, callback). ``state``: AppState (conexão)."""

    def __init__(self, client, state, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Configurações do DRACAENA")
        self.resize(560, 520)
        self._client, self._state = client, state
        self._form: SettingsForm | None = None
        self._loading = False
        self._gen = 0
        root = QVBoxLayout(self)
        self.banner = QLabel(TXT_OFFLINE)
        self.banner.setObjectName("banner")
        self.banner.setWordWrap(True)
        self.banner.setStyleSheet("background:#fff3cd; color:#664d03; padding:6px; border-radius:4px;")
        root.addWidget(self.banner)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.NoFrame)
        root.addWidget(self.scroll, 1)
        self.status = QLabel("")
        self.status.setObjectName("status")
        self.status.setWordWrap(True)
        self.status.setTextInteractionFlags(Qt.TextSelectableByMouse)
        root.addWidget(self.status)
        buttons = QHBoxLayout()
        self.btn_defaults = QPushButton("Restaurar padrões")
        self.btn_reload = QPushButton("Recarregar")
        self.btn_save = QPushButton("Salvar")
        self.btn_save.setDefault(True)
        buttons.addWidget(self.btn_defaults)
        buttons.addWidget(self.btn_reload)
        buttons.addStretch(1)
        buttons.addWidget(self.btn_save)
        root.addLayout(buttons)
        self.btn_defaults.clicked.connect(self._defaults)
        self.btn_reload.clicked.connect(self.load)
        self.btn_save.clicked.connect(self.save)
        state.changed.connect(self._on_state)
        self._refresh_ui()

    # --- conexão ---
    def _on_state(self, _run) -> None:
        was = self._form is not None
        self._refresh_ui()
        if self._state.run.connected and not was and not self._loading:
            self.load()

    def _connected(self) -> bool:
        return bool(self._state.run.connected)

    def _refresh_ui(self) -> None:
        on = self._connected()
        self.banner.setVisible(not on)
        self.btn_reload.setEnabled(on)
        self.btn_save.setEnabled(on and self._form is not None and bool(self._form.changed()))
        self.btn_defaults.setEnabled(self._form is not None)

    # --- carga ---
    def load(self) -> None:
        if self._loading:
            return
        self._loading = True
        self._gen += 1
        gen = self._gen
        self.status.setText("Carregando…")
        self._client.request("config.schema", {}, lambda r: self._on_schema(gen, r))

    def _on_schema(self, gen: int, resp) -> None:
        if gen != self._gen:
            return
        schema = reply.payload(resp)
        if not reply.is_ok(resp) or not isinstance(schema, list):
            return self._load_failed(reply.error_text(resp))
        self._client.request("config.get", {}, lambda r: self._on_values(gen, schema, r))

    def _on_values(self, gen: int, schema: list[dict[str, Any]], resp) -> None:
        if gen != self._gen:
            return
        values = reply.payload(resp)
        if not reply.is_ok(resp) or not isinstance(values, dict):
            return self._load_failed(reply.error_text(resp))
        self._loading = False
        self._form = SettingsForm(schema, values, on_change=self._refresh_ui)
        self.scroll.setWidget(self._form)
        self.status.setText("")
        self._refresh_ui()

    def _load_failed(self, erro: str) -> None:
        self._loading = False
        self.status.setText(TXT_LOAD_FAIL.format(erro=erro))
        self._refresh_ui()

    # --- ações ---
    def _defaults(self) -> None:
        if self._form:
            self._form.reset_to_defaults()
            self.status.setText("Padrões restaurados na tela. Clique em Salvar para gravar.")
            self._refresh_ui()

    def save(self) -> None:
        if not self._form or not self._connected():
            return
        pending = list(self._form.changed().items())
        if not pending:
            self.status.setText(TXT_NOTHING)
            return
        self.btn_save.setEnabled(False)
        self._send_next(pending)

    def _send_next(self, pending: list[tuple[str, Any]]) -> None:
        if not pending:
            self.status.setText(TXT_SAVED)
            self._refresh_ui()
            return
        key, value = pending[0]

        def done(resp, key=key, rest=pending[1:]):
            if reply.is_ok(resp):
                self._form.mark_saved([key])
                self._send_next(rest)
            else:
                self.status.setText(TXT_SAVE_FAIL.format(chave=key, erro=reply.error_text(resp)))
                self._refresh_ui()
        self._client.request("config.set", {"key": key, "value": value}, done)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if self._form is None and not self._loading and self._connected():
            self.load()
