import unittest
from types import SimpleNamespace
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication
from dracaena.ui.ipc_client.protocol import EventMsg, Response
from dracaena.ui.tray import TrayController

APP = QApplication.instance() or QApplication([])


class Client(QObject):
    connected = Signal()
    availability_changed = Signal(bool, str)
    event_received = Signal(object)
    protocol_error = Signal(str)
    is_connected = True

    def __init__(self):
        super().__init__()
        self.commands = []

    def request(self, command, args=None, callback=None):
        self.commands.append(command)
        if callback:
            callback(Response(1, True, {}))

    def close(self):
        self.is_connected = False


class Host:
    def open_settings(self): pass
    def open_add_site(self): pass
    def open_shortcut_wizard(self): pass
    def quit_app(self): pass


class StateModel(QObject):
    changed = Signal(object)
    def __init__(self):
        super().__init__()
        self.run = SimpleNamespace(state='idle', connected=True, site='', question=0, max=0, error='')


class TrayTests(unittest.TestCase):
    def setUp(self):
        self.client = Client()
        self.tray = TrayController(self.client, Host(), notifications=False)
        self.model = StateModel()
        self.tray.bind_state(self.model)

    def tearDown(self):
        self.tray.close()

    def state(self, state):
        self.model.run = SimpleNamespace(state=state, connected=True, site='Site de teste',
                                         question=3, max=10, error='')
        self.model.changed.emit(self.model.run)

    def test_state_event_updates_menu_icon_tooltip(self):
        self.state('running')
        self.assertIn('Rodando', self.tray.tray.toolTip())
        self.assertIn('Site de teste', self.tray.tray.toolTip())
        self.assertIn('3/10', self.tray.tray.toolTip())
        self.assertFalse(self.tray.start.isEnabled())
        self.assertTrue(self.tray.toggle.isEnabled())
        self.assertFalse(self.tray.tray.icon().isNull())
        self.state('paused')
        self.assertEqual(self.tray.toggle.text(), 'Retomar')
        self.assertTrue(self.tray.ask.isEnabled())
        self.state('idle')
        self.assertTrue(self.tray.start.isEnabled())
        self.state('error')
        self.assertIn('Erro', self.tray.tray.toolTip())

    def test_command_ack_does_not_predict_daemon_state(self):
        self.state('running')
        self.tray.toggle.trigger()
        self.assertEqual(self.client.commands, ['toggle'])
        self.assertEqual(self.tray.state, 'running')

    def test_disconnect_disables_daemon_actions_but_keeps_configuration(self):
        self.client.is_connected = False
        self.model.run.connected = False
        self.model.changed.emit(self.model.run)
        self.client.availability_changed.emit(False, 'Daemon indisponível.')
        self.assertFalse(self.tray.doctor.isEnabled())
        self.assertFalse(self.tray.start.isEnabled())
        self.assertTrue(self.tray.settings.isEnabled())
        self.assertTrue(self.tray.exit.isEnabled())

    def test_start_and_resume_both_send_toggle(self):
        self.state('idle')
        self.tray.start.trigger()
        self.state('paused')
        self.tray.toggle.trigger()
        self.assertEqual(self.client.commands, ['toggle', 'toggle'])

    def test_notification_reuses_one_window(self):
        notice = self.tray.notification
        notice.replace('Rodando')
        notice.replace('Pausado')
        self.assertIs(self.tray.notification, notice)
        self.assertEqual(notice.text.text(), 'Pausado')
        self.assertTrue(notice._timer.isActive())


if __name__ == '__main__':
    unittest.main()
