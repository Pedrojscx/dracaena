"""Bandeja Qt; estado vem exclusivamente do daemon, sem lógica de navegador."""
from __future__ import annotations

import os
import sys
from pathlib import Path
from PySide6.QtCore import QObject, QPoint, QStandardPaths, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPen, QPixmap, QPolygon
from PySide6.QtWidgets import QApplication, QFrame, QLabel, QMenu, QSystemTrayIcon, QVBoxLayout

try:  # QtDBus só existe/faz sentido nas builds com D-Bus; sem ele o watcher é desligado.
    from PySide6.QtDBus import QDBusConnection, QDBusServiceWatcher
except ImportError:  # pragma: no cover
    QDBusConnection = QDBusServiceWatcher = None

from dracaena.ui.hotkeys import GlobalHotkey
from .lifecycle import SingleInstance, set_autostart

LABELS = {'idle': 'Parado', 'running': 'Rodando',
          'paused': 'Pausado', 'error': 'Erro',
          'disconnected': 'Daemon indisponível'}
COLORS = {'idle': '#64748b', 'running': '#15803d',
          'paused': '#a16207', 'error': '#b91c1c', 
          'disconnected': '#64748b'}


WATCHER_SERVICE = 'org.kde.StatusNotifierWatcher'

# Textos fixos de docs/ui-fluxos.md (avisos de limitação).
NOTICE_NO_TRAY = ('Não encontrei uma bandeja de sistema. O DRACAENA continua funcionando; '
                  'abra as Configurações pelo atalho ou executando `dracaena settings`.')
NOTICE_GNOME = ('O GNOME não mostra ícones de bandeja por padrão. Instale e ative a extensão '
                'AppIndicator (AppIndicator and KStatusNotifierItem Support) ou use o atalho de teclado.')
NOTICE_HYPRLAND = 'No Hyprland o ícone só aparece se a sua barra tiver o módulo de bandeja (tray) ativado.'


def tray_notice(desktop: str | None = None) -> str:
    """Aviso de bandeja ausente; a parte específica depende de XDG_CURRENT_DESKTOP."""
    desktop = (os.environ.get('XDG_CURRENT_DESKTOP', '') if desktop is None else desktop).lower()
    parts = []
    if 'gnome' in desktop:
        parts.append(NOTICE_GNOME)
    elif 'hyprland' in desktop:
        parts.append(NOTICE_HYPRLAND)
    parts.append(NOTICE_NO_TRAY)
    return ' '.join(parts)


def state_icon(state: str) -> QIcon:
    icon = QIcon()
    for size in (16, 24, 32, 48, 64):
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.scale(size / 32, size / 32)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(COLORS.get(state, COLORS['error'])))
        painter.drawEllipse(1, 1, 30, 30)
        painter.setBrush(QColor('white'))
        if state == 'running':
            painter.drawPolygon(QPolygon([QPoint(12, 8), QPoint(25, 16), QPoint(12, 24)]))
        elif state == 'paused':
            painter.drawRect(10, 9, 4, 14)
            painter.drawRect(18, 9, 4, 14)
        elif state == 'error':
            painter.drawRect(14, 7, 4, 12)
            painter.drawEllipse(14, 22, 4, 4)
        elif state == 'disconnected':
            painter.setPen(QPen(QColor('white'), 3))
            painter.drawLine(10, 10, 22, 22)
            painter.drawLine(22, 10, 10, 22)
        else:
            painter.drawRect(10, 10, 12, 12)
        painter.end()
        icon.addPixmap(pixmap)
    return icon


class StateNotification(QFrame):
    """Uma única janela reutilizada: mudanças substituem o aviso, sem pilha."""
    def __init__(self):
        super().__init__(None, Qt.ToolTip | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAccessibleName('Notificação do Dracaena')
        self.setFrameShape(QFrame.StyledPanel)
        layout = QVBoxLayout(self)
        self.title = QLabel('Dracaena')
        self.text = QLabel()
        self.text.setTextFormat(Qt.PlainText)
        self.text.setWordWrap(True)
        self.text.setMaximumWidth(340)
        layout.addWidget(self.title)
        layout.addWidget(self.text)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)

    def replace(self, message: str) -> None:
        self.text.setText(message)
        self.adjustSize()
        screen = QApplication.primaryScreen()
        if screen:
            rect = screen.availableGeometry()
            self.move(rect.right() - self.width() - 16, rect.bottom() - self.height() - 16)
        self.show()
        self._timer.start(4500)

    def mousePressEvent(self, event):
        self.hide()
        super().mousePressEvent(event)


class TrayController(QObject):
    toggle_requested = Signal()
    hotkey_status = Signal(str)
    tray_availability = Signal(bool, str)  # (há bandeja?, aviso quando não há)

    def __init__(self, client, host, parent=None, *, notifications=True, lock_path=None,
                 watch_dbus=True):
        super().__init__(parent)
        self.client = client
        self.host = host
        self._state_model = None
        self._busy = False
        self._closed = False
        self._instance = SingleInstance(Path(lock_path) if lock_path else
            Path(QStandardPaths.writableLocation(QStandardPaths.GenericDataLocation)) / 'dracaena' / 'ui.lock')
        self._notifications = notifications
        self._notification_key = None
        self.notification = StateNotification()
        self.tray = None
        self._tray_available = None
        self._watch_dbus = watch_dbus
        self._watcher = None
        self._shown = False
        self.menu = QMenu()
        self.status = self.menu.addAction('Daemon indisponível')
        self.status.setEnabled(False)
        self.menu.addSeparator()
        self.start = self._action('Iniciar', lambda: self._command('toggle'))
        self.toggle = self._action('Pausar', lambda: self._command('toggle'))
        self.stop = self._action('Parar', lambda: self._command('stop'))
        self.ask = self._action('Responder só esta questão', lambda: self._command('ask'))
        self.menu.addSeparator()
        self.settings = self._action('Abrir configuração', host.open_settings)
        self.add_site = self._action('Adicionar site', host.open_add_site)
        self.shortcut = self._action('Atalho de teclado', host.open_shortcut_wizard)
        self.doctor = self._action('Diagnóstico', lambda: self._command('doctor'))
        self.menu.addSeparator()
        self.exit = self._action('Sair', self._quit)
        self._new_icon()
        self.client.availability_changed.connect(self._availability)
        self.client.protocol_error.connect(self._error)
        self.toggle_requested.connect(lambda: self._command('toggle'))
        self.hotkey_status.connect(self._hotkey_status)
        self.hotkey = None
        self._render()

    def _action(self, label, callback):
        action = QAction(label, self.menu)
        action.triggered.connect(callback)
        self.menu.addAction(action)
        return action

    def _new_icon(self):
        """(Re)cria o QSystemTrayIcon; o menu e o estado pertencem ao controlador."""
        old = self.tray
        if old is not None:
            old.hide()
            old.setContextMenu(None)
            old.deleteLater()
        self.tray = QSystemTrayIcon(self)
        self.tray.setContextMenu(self.menu)
        self.tray.activated.connect(self._activated)
        self._render()

    @property
    def tray_available(self):
        """None até show(); depois True/False conforme o watcher (Linux) ou o Qt."""
        return self._tray_available

    def show(self) -> bool:
        if not self._instance.acquire():
            return False
        self._closed = False
        self._shown = True
        self._start_watcher()
        self._set_tray_available(self._probe_tray())
        self.client.connect_to_daemon()
        return True

    def _probe_tray(self) -> bool:
        if self._watcher is not None:
            return QDBusConnection.sessionBus().interface().isServiceRegistered(WATCHER_SERVICE).value()
        return QSystemTrayIcon.isSystemTrayAvailable()

    def _start_watcher(self):
        """Observa org.kde.StatusNotifierWatcher no barramento de sessão (só Linux).

        HIPÓTESE (não verificada): o host da bandeja pode aparecer depois do app (ex.: autostart
        antes da barra). Por isso o ícone é recriado quando o serviço surge, em vez de depender
        de uma única chamada a show(). Sem D-Bus, o app segue só com isSystemTrayAvailable().
        """
        if (self._watcher is not None or not self._watch_dbus or QDBusServiceWatcher is None
                or not sys.platform.startswith('linux')):
            return
        bus = QDBusConnection.sessionBus()
        if not bus.isConnected():
            return
        self._watcher = QDBusServiceWatcher(WATCHER_SERVICE, bus, QDBusServiceWatcher.WatchForRegistration
                                            | QDBusServiceWatcher.WatchForUnregistration, self)
        self._watcher.serviceRegistered.connect(lambda name: self._watcher_changed(True))
        self._watcher.serviceUnregistered.connect(lambda name: self._watcher_changed(False))

    def _watcher_changed(self, registered: bool):
        if self._closed or not self._shown:
            return
        if registered:
            self._new_icon()  # ícone antigo pode ter sido criado sem host
        self._set_tray_available(registered)

    def _set_tray_available(self, available: bool):
        previous, self._tray_available = self._tray_available, available
        if available:
            self.tray.show()
            if previous is not True:
                self.tray_availability.emit(True, '')
        else:
            self.tray.hide()
            message = tray_notice()
            if previous is not False:
                self.tray_availability.emit(False, message)
                self._notify('no-tray', message)

    def configure_autostart(self, enabled: bool, command: list[str]):
        set_autostart(enabled, command)

    def register_hotkey(self, *, key='P', modifiers=('super',)):
        previous = self.hotkey
        replacement = GlobalHotkey(self.toggle_requested.emit, key=key, modifiers=modifiers,
                                   on_status=self.hotkey_status.emit)
        if previous:
            previous.close()
        self.hotkey = replacement
        def start_after_release():
            if self._closed or self.hotkey is not replacement:
                return
            if previous and previous._thread and previous._thread.is_alive():
                QTimer.singleShot(20, start_after_release)
            else:
                replacement.start()
        start_after_release()

    def _hotkey_status(self, message):
        self.toggle.setStatusTip(message)

    def bind_state(self, state_model):
        """Liga o AppState canônico do A1; não cria nem copia estado do daemon."""
        if self._state_model is not None:
            self._state_model.changed.disconnect(self._state_changed)
        self._state_model = state_model
        state_model.changed.connect(self._state_changed)
        self._render()

    @property
    def state(self):
        run = self._state_model.run if self._state_model is not None else None
        return run.state if run and run.connected else 'disconnected'

    def _state_changed(self, run):
        self._render()
        self._notify(self.state, self.tray.toolTip())

    def _availability(self, available, message):
        if not available:
            self._busy = False
            self._render()
            self._notify('disconnected', message)

    def _notify(self, key, message):
        if self._notifications and key != self._notification_key and not self._closed:
            self._notification_key = key
            self.notification.replace(message)

    def _render(self):
        label = LABELS[self.state]
        self.status.setText(label + (' — aguardando resposta' if self._busy else ''))
        self.tray.setIcon(state_icon(self.state))
        details = ['Dracaena — ' + label]
        run = self._state_model.run if self._state_model is not None else None
        if run and run.connected:
            if run.site:
                details.append('Site: ' + str(run.site)[:160])
            details.append(f'Progresso: {run.question}/{run.max}')
            if run.error:
                details.append('Erro: ' + str(run.error)[:240])
        self.tray.setToolTip('\n'.join(details))
        ready = self.client.is_connected and not self._busy
        self.start.setEnabled(ready and self.state in ('idle', 'error'))
        self.toggle.setText('Retomar' if self.state == 'paused' else 'Pausar')
        self.toggle.setEnabled(ready and self.state in ('running', 'paused'))
        self.stop.setEnabled(ready and self.state in ('running', 'paused', 'error'))
        self.ask.setEnabled(ready and self.state in ('idle', 'paused'))
        self.doctor.setEnabled(ready)

    def _command(self, command):
        if self._busy or not self.client.is_connected:
            return
        self._busy = True
        self._render()
        self.client.request(command, callback=lambda response: self._result(command, response))

    def _result(self, command, response):
        if self._closed:
            return
        self._busy = False
        self._render()
        if not response.ok:
            self._error(response.error.message if response.error else 'O comando falhou.')
        elif command == 'doctor':
            # O host pode exibir o resultado completo; a bandeja não interpreta checks.
            if hasattr(self.host, 'show_diagnostics'):
                self.host.show_diagnostics(response.data)
            else:
                self.notification.replace('Diagnóstico concluído. Consulte os detalhes na configuração.')
        # Confirmações não antecipam estado: somente snapshot/evento altera o ícone.

    def _error(self, message):
        self.notification.replace('Dracaena: ' + message)

    def _activated(self, reason):
        if reason == QSystemTrayIcon.DoubleClick:
            self.host.open_settings()

    def _quit(self):
        self.close()
        self.host.quit_app()

    def close(self):
        self._closed = True
        if self.hotkey:
            self.hotkey.close()
        self.notification.hide()
        self.tray.hide()
        self._shown = False
        self.menu.close()
        self.client.close()
        self._instance.close()
