"""Primeira execução: boas-vindas + verificação, Adicionar site, atalho e fim.

As páginas de Adicionar site e de atalho são injetadas (``add_site_page`` e ``shortcut_page``):
a tela não importa as outras telas; ``default_pages`` faz a ligação padrão.
"""
from __future__ import annotations

from typing import Any, Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QHBoxLayout, QLabel, QPushButton, QStackedWidget, QVBoxLayout, QWidget)

from dracaena.ui.settings import reply

TXT_WELCOME = "Bem-vindo ao DRACAENA. Ele ajuda em atividades de prática. Vamos configurar em dois passos."
TXT_DONE = "Pronto. O DRACAENA fica na bandeja. Use o atalho ou o menu para ligar e desligar."
TXT_DOCTOR_OK = "Verificação do ambiente: tudo certo."
TXT_DOCTOR_FAIL = "Verificação do ambiente: há itens para resolver."
TXT_DOCTOR_ERR = "Não consegui verificar o ambiente: {erro}"


def default_pages(client, state) -> tuple[QWidget, QWidget]:
    from dracaena.ui.add_site import AddSitePage
    from dracaena.ui.shortcuts_wizard import ShortcutWizardPage
    return AddSitePage(client, state), ShortcutWizardPage(client, state)


def format_checks(data: Any) -> tuple[bool, list[str]]:
    """CONTRATO (definitivo): ``doctor`` -> {ok, checks:[{name, ok, message?, hint?}]}."""
    if not isinstance(data, dict):
        return False, []
    lines = []
    for c in data.get("checks") or []:
        if isinstance(c, dict):
            mark = "✔" if c.get("ok") else "✘"
            msg = f" — {c['message']}" if c.get("message") else ""
            lines.append(f"{mark} {c.get('name', '?')}{msg}")
            if c.get("hint") and not c.get("ok"):
                lines.append(f"    Dica: {c['hint']}")
    return bool(data.get("ok")), lines


class FirstRunWindow(QWidget):
    finished = Signal(object)        # {"site_saved": bool, "shortcut_verified": bool, "autostart": bool}
    dismissed = Signal()             # janela fechada sem concluir (o app.py decide se reabre depois)
    autostart_requested = Signal(bool)

    def __init__(self, client, state, *, pages: tuple[QWidget, QWidget] | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Primeira execução do DRACAENA")
        self.resize(660, 640)
        self._client, self._state = client, state
        self.add_page, self.shortcut_page = pages or default_pages(client, state)
        self._site_saved = False
        self._shortcut_ok = False
        self._concluded = False
        root = QVBoxLayout(self)
        self.steps = QLabel("")
        self.steps.setObjectName("steps")
        root.addWidget(self.steps)
        self.stack = QStackedWidget()
        root.addWidget(self.stack, 1)

        welcome = QWidget()
        wl = QVBoxLayout(welcome)
        title = QLabel(TXT_WELCOME)
        title.setWordWrap(True)
        title.setObjectName("welcome")
        wl.addWidget(title)
        self.doctor_label = QLabel("")
        self.doctor_label.setObjectName("doctor")
        self.doctor_label.setWordWrap(True)
        self.doctor_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        wl.addWidget(self.doctor_label)
        wl.addStretch(1)
        finish = QWidget()
        fl = QVBoxLayout(finish)
        self.done_label = QLabel(TXT_DONE)
        self.done_label.setWordWrap(True)
        self.done_label.setObjectName("done")
        fl.addWidget(self.done_label)
        self.summary = QLabel("")
        self.summary.setObjectName("summary")
        self.summary.setWordWrap(True)
        fl.addWidget(self.summary)
        self.autostart = QCheckBox("Iniciar com o sistema")
        self.autostart.setChecked(False)
        fl.addWidget(self.autostart)
        fl.addStretch(1)
        for w in (welcome, self.add_page, self.shortcut_page, finish):
            self.stack.addWidget(w)

        nav = QHBoxLayout()
        self.btn_back = QPushButton("Voltar")
        self.btn_skip = QPushButton("Pular este passo")
        self.btn_next = QPushButton("Avançar")
        nav.addWidget(self.btn_back)
        nav.addStretch(1)
        nav.addWidget(self.btn_skip)
        nav.addWidget(self.btn_next)
        root.addLayout(nav)
        self.btn_back.clicked.connect(lambda: self._go(self.stack.currentIndex() - 1))
        self.btn_skip.clicked.connect(lambda: self._go(self.stack.currentIndex() + 1))
        self.btn_next.clicked.connect(self._next)
        if hasattr(self.add_page, "saved"):
            self.add_page.saved.connect(self._on_site_saved)
        if hasattr(self.shortcut_page, "verified"):
            self.shortcut_page.verified.connect(self._on_shortcut)
        state.changed.connect(lambda _r: self._maybe_doctor())
        self._doctor_done = False
        self._go(0)
        self._maybe_doctor()

    def _maybe_doctor(self) -> None:
        if self._doctor_done or not self._state.run.connected:
            return
        self._doctor_done = True
        self._client.request("doctor", {}, self._on_doctor)

    def _on_doctor(self, resp) -> None:
        if not reply.is_ok(resp):
            self._doctor_done = False
            self.doctor_label.setText(TXT_DOCTOR_ERR.format(erro=reply.error_text(resp)))
            return
        ok, lines = format_checks(reply.payload(resp))
        self.doctor_label.setText("\n".join([TXT_DOCTOR_OK if ok else TXT_DOCTOR_FAIL, *lines]))

    def _on_site_saved(self, _name: str) -> None:
        self._site_saved = True
        self._update_nav()

    def _on_shortcut(self) -> None:
        self._shortcut_ok = True
        self._update_nav()

    def _go(self, i: int) -> None:
        self.stack.setCurrentIndex(max(0, min(i, self.stack.count() - 1)))
        self._update_nav()

    def _update_nav(self) -> None:
        i, last = self.stack.currentIndex(), self.stack.count() - 1
        self.steps.setText(["Início", "Passo 1 de 2 — Adicionar site", "Passo 2 de 2 — Atalho", "Fim"][i])
        self.btn_back.setVisible(0 < i < last)
        self.btn_next.setText("Concluir" if i == last else "Avançar")
        done = {1: self._site_saved, 2: self._shortcut_ok}.get(i, True)
        self.btn_skip.setVisible(i in (1, 2) and not done)
        if i == last:
            self.summary.setText("\n".join([
                ("✔ Site salvo." if self._site_saved else "• Nenhum site salvo ainda: use “Adicionar site” no menu."),
                ("✔ Atalho confirmado." if self._shortcut_ok
                 else "• Atalho não confirmado: reabra o assistente de atalhos no menu quando quiser.")]))

    def _next(self) -> None:
        if self.stack.currentIndex() < self.stack.count() - 1:
            return self._go(self.stack.currentIndex() + 1)
        want = self.autostart.isChecked()
        self._concluded = True
        self.autostart_requested.emit(want)
        self.finished.emit({"site_saved": self._site_saved, "shortcut_verified": self._shortcut_ok,
                            "autostart": want})
        self.close()

    def closeEvent(self, event) -> None:  # noqa: N802
        if not self._concluded:
            self._concluded = True
            self.dismissed.emit()
        super().closeEvent(event)
