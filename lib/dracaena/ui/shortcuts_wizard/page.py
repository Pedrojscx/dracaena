"""Assistente de atalhos (página reutilizável pela primeira execução e pela janela própria)."""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (QApplication, QHBoxLayout, QKeySequenceEdit, QLabel, QLineEdit, QMessageBox,
                               QPlainTextEdit, QPushButton, QVBoxLayout, QWidget)

from dracaena.ui.settings import reply
from . import commands, gnome, hello, instructions
from .env import Environment, detect

TXT_CONFLICT = "Esse atalho já está em uso por outro programa. Escolha outro."
TXT_APP_REGISTER = ("Neste ambiente o DRACAENA registra o atalho sozinho. "
                    "Escolha uma combinação com uma letra ou número e pelo menos um modificador.")
TXT_ARMING = "Preparando o teste…"
TXT_ARM_FAIL = "Não consegui preparar o teste: {erro}"
TXT_WAIT = "Pressione o atalho agora… (o teste não liga o DRACAENA)"
TXT_OK = "Atalho confirmado: o comando chegou ao DRACAENA."
TXT_TIMEOUT = "Não recebi o comando do atalho em {s} s. Confira o atalho e tente de novo."
TXT_OFFLINE = "Sem conexão com o DRACAENA. Não dá para testar o atalho agora."
TXT_PORTAL = ("Este sistema oferece o portal de atalhos globais. O DRACAENA ainda não usa esse recurso; "
              "use o método acima.")
_MODS = {Qt.MetaModifier: "super", Qt.ControlModifier: "ctrl", Qt.AltModifier: "alt", Qt.ShiftModifier: "shift"}


def key_from_sequence(seq: QKeySequence) -> tuple[str, tuple[str, ...]]:
    """(tecla, modificadores) no formato de ``GlobalHotkey``. ValueError com texto para o usuário."""
    if seq.isEmpty() or seq.count() != 1:
        raise ValueError("Pressione uma única combinação de teclas.")
    combo = seq[0]
    mods = tuple(name for flag, name in _MODS.items() if combo.keyboardModifiers() & flag)
    key = QKeySequence(combo.key()).toString()
    if len(key) != 1 or not key.isascii() or not key.isalnum():
        raise ValueError("Use uma letra ou número como tecla do atalho.")
    if not mods:
        raise ValueError("Use pelo menos um modificador (Super, Ctrl, Alt ou Shift).")
    return key.upper(), mods


def detect_portal_global_shortcuts() -> bool | None:
    """True/False se o portal GlobalShortcuts responde; None se não deu para consultar."""
    try:
        from PySide6.QtDBus import QDBusConnection, QDBusInterface, QDBusMessage
        bus = QDBusConnection.sessionBus()
        if not bus.isConnected():
            return None
        iface = QDBusInterface("org.freedesktop.portal.Desktop", "/org/freedesktop/portal/desktop",
                               "org.freedesktop.DBus.Properties", bus)
        if not iface.isValid():
            return None
        iface.setTimeout(1500)
        msg = iface.call("Get", "org.freedesktop.portal.GlobalShortcuts", "version")
        return msg.type() == QDBusMessage.ReplyMessage
    except Exception:
        return None


def _default_confirm(parent: QWidget, text: str) -> bool:
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Question)
    box.setWindowTitle("Confirmar gravação")
    box.setText("O DRACAENA vai gravar isto nas configurações do GNOME (fora da pasta do aplicativo). Continuar?")
    box.setInformativeText(text)
    box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
    box.setDefaultButton(QMessageBox.No)
    return box.exec() == QMessageBox.Yes


class ShortcutWizardPage(QWidget):
    verified = Signal()

    def __init__(self, client, state, *, environ=None, platform: str | None = None,
                 runner: gnome.Runner | None = None, confirm: Callable[[QWidget, str], bool] | None = None,
                 register_hotkey: Callable[[str, tuple[str, ...]], object] | None = None,
                 portal_probe: Callable[[], bool | None] | None = None,
                 command: commands.ToggleCommand | None = None, test_timeout_ms: int = 30000,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._client, self._state = client, state
        self._run = runner or gnome.real_runner
        self._confirm = confirm or _default_confirm
        self._register = register_hotkey
        self._portal = portal_probe or detect_portal_global_shortcuts
        self.env: Environment = detect(environ, platform)
        self._command_fixed = command is not None
        self.command = command or commands.toggle_command()
        self._plan: gnome.Plan | None = None
        self._armed = False
        self._gen = 0
        self.is_verified = False
        self._timeout_ms = test_timeout_ms
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._on_timeout)

        root = QVBoxLayout(self)
        self.env_label = QLabel(self._env_text())
        self.env_label.setObjectName("env_label")
        self.env_label.setWordWrap(True)
        root.addWidget(self.env_label)
        if self.env.app_can_register:
            self._build_app_register(root)
        else:
            self._build_wayland(root)
        self.info = QLabel("")
        self.info.setObjectName("info")
        self.info.setWordWrap(True)
        self.info.setTextInteractionFlags(Qt.TextSelectableByMouse)
        root.addWidget(self.info)
        row = QHBoxLayout()
        self.btn_test = QPushButton("Testar atalho")
        self.btn_test.clicked.connect(self.start_test)
        row.addWidget(self.btn_test)
        self.test_status = QLabel("")
        self.test_status.setObjectName("test_status")
        self.test_status.setWordWrap(True)
        row.addWidget(self.test_status, 1)
        root.addLayout(row)
        root.addStretch(1)
        if hasattr(client, "event_received"):
            client.event_received.connect(self._on_event)
        if not self._command_fixed:
            self._ask_daemon_command()

    # --- comando do atalho ---
    def _text(self) -> str:
        return self.command.text(windows=self.env.session == 'windows')

    def _ask_daemon_command(self) -> None:
        if getattr(self._client, 'is_connected', True) and self._state.run.connected:
            hello.request_toggle_cmd(self._client, self.set_command)
        else:
            self._state.changed.connect(self._retry_hello)

    def _retry_hello(self, run) -> None:
        if run.connected:
            self._state.changed.disconnect(self._retry_hello)
            hello.request_toggle_cmd(self._client, self.set_command)

    def set_command(self, cmd) -> None:
        """Atualiza o comando mostrado (``None``: o hello não trouxe; mantém o fallback)."""
        if cmd is None or self._command_fixed:
            return
        self.command = cmd
        if hasattr(self, 'command_view'):
            self.command_view.setText(self._text())
            self._plan = None
            if hasattr(self, 'plan_view'):
                self.plan_view.clear()
            if hasattr(self, 'snippet_view'):
                self.snippet_view.setPlainText(instructions.build(self.env, cmd).snippet)

    # --- construção ---
    def _env_text(self) -> str:
        sess = {"windows": "Windows", "x11": "X11", "wayland": "Wayland", "unknown": "sessão desconhecida"}[self.env.session]
        comp = {"gnome": "GNOME", "kde": "KDE Plasma", "hyprland": "Hyprland", "sway": "Sway", "i3": "i3",
                "other": ""}[self.env.compositor]
        return "Ambiente detectado: " + sess + (f" ({comp})" if comp else "") + "."

    def _copy_row(self, root: QVBoxLayout, label: str, text: str, name: str, multiline: bool = False) -> QWidget:
        root.addWidget(QLabel(label))
        row = QHBoxLayout()
        view = QPlainTextEdit(text) if multiline else QLineEdit(text)
        view.setReadOnly(True)
        view.setObjectName(name)
        if multiline:
            view.setMaximumHeight(70)
        row.addWidget(view, 1)
        btn = QPushButton("Copiar")
        btn.setObjectName(name + "_copy")
        btn.clicked.connect(lambda: QApplication.clipboard().setText(view.toPlainText() if multiline else view.text()))
        row.addWidget(btn)
        root.addLayout(row)
        return view

    def _build_app_register(self, root: QVBoxLayout) -> None:
        intro = QLabel(TXT_APP_REGISTER)
        intro.setWordWrap(True)
        root.addWidget(intro)
        root.addWidget(QLabel("Clique no campo abaixo e pressione a combinação de teclas:"))
        row = QHBoxLayout()
        self.key_edit = QKeySequenceEdit()
        self.key_edit.setObjectName("key_edit")
        self.key_edit.setMaximumSequenceLength(1)
        row.addWidget(self.key_edit, 1)
        self.btn_register = QPushButton("Registrar atalho")
        self.btn_register.setEnabled(self._register is not None)
        self.btn_register.clicked.connect(self._do_register)
        row.addWidget(self.btn_register)
        root.addLayout(row)

    def _build_wayland(self, root: QVBoxLayout) -> None:
        ins = instructions.build(self.env, self.command)
        intro = QLabel(ins.intro)
        intro.setWordWrap(True)
        intro.setObjectName("intro")
        root.addWidget(intro)
        self.command_view = self._copy_row(root, "Comando:", self._text(), "command_view")
        for s in ins.steps:
            lbl = QLabel("• " + s)
            lbl.setWordWrap(True)
            root.addWidget(lbl)
        if ins.snippet:
            self.snippet_view = self._copy_row(root, ins.snippet_label + ":", ins.snippet, "snippet_view", True)
        if self.env.compositor == "gnome":
            self.plan_view = QPlainTextEdit()
            self.plan_view.setReadOnly(True)
            self.plan_view.setObjectName("plan_view")
            self.plan_view.setMinimumHeight(150)
            self.plan_view.setPlaceholderText("O que será gravado aparece aqui.")
            row = QHBoxLayout()
            self.btn_preview = QPushButton("Mostrar o que será gravado")
            self.btn_preview.clicked.connect(self.gnome_preview)
            self.btn_apply = QPushButton("Aplicar no GNOME…")
            self.btn_apply.clicked.connect(self.gnome_apply)
            row.addWidget(self.btn_preview)
            row.addWidget(self.btn_apply)
            root.addLayout(row)
            root.addWidget(self.plan_view)
            self.btn_plan_copy = QPushButton("Copiar comandos")
            self.btn_plan_copy.clicked.connect(lambda: QApplication.clipboard().setText(self.plan_view.toPlainText()))
            root.addWidget(self.btn_plan_copy)
        self.portal_label = QLabel(TXT_PORTAL)
        self.portal_label.setObjectName("portal_label")
        self.portal_label.setWordWrap(True)
        self.portal_label.setVisible(False)
        root.addWidget(self.portal_label)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if not self.env.app_can_register and self.env.compositor in ("kde", "hyprland") \
                and getattr(self, "_portal_done", False) is False:
            self._portal_done = True
            self.portal_label.setVisible(self._portal() is True)

    # --- Windows e X11 ---
    def _do_register(self) -> None:
        try:
            key, mods = key_from_sequence(self.key_edit.keySequence())
        except ValueError as exc:
            self.info.setText(str(exc))
            return
        try:
            self._register(key, mods)
        except OSError:
            self.info.setText(TXT_CONFLICT)
        except ValueError as exc:
            self.info.setText(str(exc))
        else:
            self.info.setText(f"Atalho {'+'.join(mods).title()}+{key} enviado para registro. Use Testar atalho.")

    # --- GNOME ---
    def gnome_preview(self) -> bool:
        try:
            self._plan = gnome.build_plan(gnome.read_list(self._run), self._text())
        except (OSError, ValueError) as exc:
            self._plan = None
            self.info.setText(f"Não consegui ler os atalhos do GNOME: {exc}")
            return False
        head = "# A lista atual será mantida; o DRACAENA só é acrescentado.\n" if not self._plan.already_listed \
            else "# O DRACAENA já está na lista; o item será apenas atualizado.\n"
        self.plan_view.setPlainText(head + self._plan.text())
        self.info.setText("")
        return True

    def gnome_apply(self) -> bool:
        if not self.gnome_preview():
            return False
        if not self._confirm(self, self.plan_view.toPlainText()):
            self.info.setText("Nada foi gravado.")
            return False
        try:
            gnome.apply_plan(self._plan, self._run)
        except (OSError, RuntimeError, ValueError) as exc:
            self.info.setText(f"Não gravei o atalho: {exc}")
            return False
        self.info.setText("Atalho criado no GNOME (Super+Alt+D). Use Testar atalho para confirmar.")
        return True

    # --- teste ---
    # PROVISÓRIO: aguarda o Backend entregar no simulado (CONTRATO, 2ª rodada): ``shortcut.test {arm:true}``;
    # o próximo toggle do compositor NÃO age e o daemon emite o evento ``shortcut_test {ok:true}``;
    # desarma sozinho em 30 s. A UI só ouve ``event_received``; nunca manda toggle nem stop.
    def start_test(self) -> None:
        if not self._state.run.connected:
            self.test_status.setText(TXT_OFFLINE)
            return
        self._gen += 1
        gen = self._gen
        self._armed = True
        self.test_status.setText(TXT_ARMING)
        self.btn_test.setEnabled(False)
        self._client.request("shortcut.test", {"arm": True}, lambda r: self._on_armed(gen, r))

    def _on_armed(self, gen: int, resp) -> None:
        if gen != self._gen:
            return
        if not reply.is_ok(resp):
            self._armed = False
            self.btn_test.setEnabled(True)
            self.test_status.setText(TXT_ARM_FAIL.format(erro=reply.error_text(resp)))
            return
        self.test_status.setText(TXT_WAIT)
        self._timer.start(self._timeout_ms)

    def _on_event(self, event) -> None:
        name, data = reply.event_parts(event)
        if name != "shortcut_test" or not self._armed or data.get("ok") is not True:
            return
        self._armed = False
        self._timer.stop()
        self.btn_test.setEnabled(True)
        self.is_verified = True
        self.test_status.setText(TXT_OK)
        self.verified.emit()

    def _on_timeout(self) -> None:
        if self._armed:
            self._armed = False
            self.btn_test.setEnabled(True)
            self.test_status.setText(TXT_TIMEOUT.format(s=self._timeout_ms // 1000))
