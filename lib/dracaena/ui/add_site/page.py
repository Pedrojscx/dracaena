"""Fluxo Adicionar site: verificar (probe), revisar o rascunho do perfil e salvar (sites.save).

A UI nunca toca a página nem escreve em disco: tudo passa pelo daemon (ver ``api.py``).
"""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QRegularExpressionValidator
from PySide6.QtCore import QRegularExpression
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QProgressBar,
                               QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget, QHeaderView)

from . import api

TXT_VERIFYING = "Verificando…"
TXT_OK = "Página reconhecida."
TXT_FAIL = ("Não consegui reconhecer as questões nessa página. Abra a atividade de prática no navegador "
            "e tente de novo.")
TXT_BAD_URL = "Digite um endereço que comece com http:// ou https://, ou deixe em branco para usar a aba atual."
TXT_OFFLINE = "Sem conexão com o DRACAENA."
TXT_CANCELLED = "Verificação cancelada."
TXT_SAVED = "Site salvo."


def _default_confirm(parent: QWidget, text: str) -> bool:
    return QMessageBox.question(parent, "Sobrescrever site", text, QMessageBox.Yes | QMessageBox.No,
                                QMessageBox.No) == QMessageBox.Yes


class AddSitePage(QWidget):
    saved = Signal(str)   # nome do site salvo

    def __init__(self, client, state, *, confirm: Callable[[QWidget, str], bool] | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._client, self._state = client, state
        self._confirm = confirm or _default_confirm
        self._gen = 0
        self._probing = False
        self.result: api.ProbeResult | None = None
        self.is_saved = False
        root = QVBoxLayout(self)
        root.addWidget(QLabel("Endereço da página de prática"))
        row = QHBoxLayout()
        self.url = QLineEdit()
        self.url.setObjectName("url")
        self.url.setPlaceholderText("https://… (em branco: aba atual do navegador do DRACAENA)")
        self.url.returnPressed.connect(self.verify)
        self.btn_verify = QPushButton("Verificar")
        self.btn_verify.clicked.connect(self.verify)
        self.btn_cancel = QPushButton("Cancelar")
        self.btn_cancel.clicked.connect(self.cancel)
        self.btn_cancel.setVisible(False)
        row.addWidget(self.url, 1)
        row.addWidget(self.btn_verify)
        row.addWidget(self.btn_cancel)
        root.addLayout(row)
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        root.addWidget(self.progress)
        self.status = QLabel("")
        self.status.setObjectName("status")
        self.status.setWordWrap(True)
        self.status.setTextInteractionFlags(Qt.TextSelectableByMouse)
        root.addWidget(self.status)
        self.table = QTableWidget(0, 2)
        self.table.setObjectName("matches")
        self.table.setHorizontalHeaderLabels(["Seletor", "Elementos achados"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setMaximumHeight(130)
        self.table.setVisible(False)
        root.addWidget(self.table)
        self.review = QWidget()
        rv = QVBoxLayout(self.review)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.addWidget(QLabel("Revise o perfil do site (você pode editar o texto):"))
        self.draft = QPlainTextEdit()
        self.draft.setObjectName("draft")
        rv.addWidget(self.draft, 1)
        nrow = QHBoxLayout()
        nrow.addWidget(QLabel("Nome do site:"))
        self.name = QLineEdit()
        self.name.setObjectName("name")
        self.name.setPlaceholderText("letras minúsculas, números, - e _")
        self.name.setValidator(QRegularExpressionValidator(QRegularExpression(r"[a-z0-9_-]*")))
        self.name.textChanged.connect(self._refresh)
        self.draft.textChanged.connect(self._refresh)
        self.btn_save = QPushButton("Salvar site")
        self.btn_save.clicked.connect(self.save)
        nrow.addWidget(self.name, 1)
        nrow.addWidget(self.btn_save)
        rv.addLayout(nrow)
        self.review.setVisible(False)
        root.addWidget(self.review, 1)
        self.save_status = QLabel("")
        self.save_status.setObjectName("save_status")
        self.save_status.setWordWrap(True)
        self.save_status.setTextInteractionFlags(Qt.TextSelectableByMouse)
        root.addWidget(self.save_status)
        if hasattr(client, "event_received"):
            client.event_received.connect(self._on_event)
        state.changed.connect(lambda _r: self._refresh())
        self._refresh()

    # --- verificação ---
    def verify(self) -> None:
        if self._probing:
            return
        url = self.url.text().strip()
        if url and not url.lower().startswith(("http://", "https://")):
            self.status.setText(TXT_BAD_URL)
            return
        if not self._state.run.connected:
            self.status.setText(TXT_OFFLINE)
            return
        self._gen += 1
        gen = self._gen
        self._probing = True
        self.result = None
        self.is_saved = False
        self.table.setVisible(False)
        self.review.setVisible(False)
        self.save_status.setText("")
        self.status.setText(TXT_VERIFYING)
        self.progress.setRange(0, 0)   # indeterminado até chegar progresso
        self.progress.setVisible(True)
        self.btn_cancel.setVisible(True)
        self._refresh()
        api.probe_start(self._client, url, lambda res, err, code: self._on_probe(gen, res, err, code))

    def _on_event(self, event) -> None:
        if not self._probing:
            return
        prog = api.probe_progress(event)
        if not prog:
            return
        if prog[1] > 0:
            self.progress.setRange(0, prog[1])
            self.progress.setValue(prog[0])
        what = api.PHASE_TEXT.get(prog[2])
        self.status.setText(f"{TXT_VERIFYING} ({what})" if what else TXT_VERIFYING)

    def _on_probe(self, gen: int, result: api.ProbeResult | None, error: str, code: str = "") -> None:
        if gen != self._gen:   # cancelado ou substituído
            return
        self._probing = False
        self.progress.setVisible(False)
        self.btn_cancel.setVisible(False)
        if result is None and code == "cancelled":
            self.status.setText(TXT_CANCELLED)
            return self._refresh()
        if result is None:
            self.status.setText(f"Não consegui verificar a página: {error}")
            return self._refresh()
        self.result = result
        self.table.setRowCount(0)
        for sel, n in result.matches.items():
            r = self.table.rowCount()
            self.table.insertRow(r)
            self.table.setItem(r, 0, QTableWidgetItem(sel))
            self.table.setItem(r, 1, QTableWidgetItem(str(n)))
        self.table.setVisible(True)
        if result.recognized:
            self.status.setText(f"{TXT_OK} Questões encontradas: {result.questions}.")
            self.draft.setPlainText(result.draft_toml)
            self.review.setVisible(True)
        else:
            self.status.setText(TXT_FAIL)
        self._refresh()

    def cancel(self) -> None:
        if not self._probing:
            return
        self._gen += 1   # descarta o resultado que ainda chegar
        self._probing = False
        self.progress.setVisible(False)
        self.btn_cancel.setVisible(False)
        self.status.setText(TXT_CANCELLED)
        api.probe_cancel(self._client)
        self._refresh()

    # --- salvar ---
    def _refresh(self) -> None:
        on = bool(self._state.run.connected)
        self.btn_verify.setEnabled(on and not self._probing)
        name, toml = self.name.text(), self.draft.toPlainText()
        ok = (on and self.result is not None and self.result.recognized and bool(api.NAME_RE.match(name))
              and bool(toml.strip()) and len(toml.encode()) <= api.MAX_TOML_BYTES)
        self.btn_save.setEnabled(ok)

    def save(self) -> None:
        name, toml = self.name.text(), self.draft.toPlainText()
        if not self.btn_save.isEnabled():
            return
        existing = {str(s.get("name")) for s in self._state.sites if isinstance(s, dict)}
        overwrite = False
        if name in existing:
            if not self._confirm(self, f"Já existe um site chamado “{name}”. Sobrescrever?"):
                self.save_status.setText("Nada foi salvo.")
                return
            overwrite = True
        self.btn_save.setEnabled(False)
        api.sites_save(self._client, name, toml, overwrite, lambda path, err: self._on_saved(name, path, err))

    def _on_saved(self, name: str, path: str, error: str) -> None:
        if error:
            self.save_status.setText(f"Não salvei o site: {error}")
            return self._refresh()
        self.is_saved = True
        self.save_status.setText(TXT_SAVED + (f" ({path})" if path else ""))
        api.sites_list(self._client, self._state.set_sites)
        self.saved.emit(name)
        self._refresh()
