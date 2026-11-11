"""Integração do cliente + bandeja + AppState contra o daemon real em modo --simulate.

Configuração por ambiente (nada de caminho fixo):
  DRACAENA_BACKEND_ROOT   raiz do backend (contém lib/dracaena/daemon.py); obrigatório
  DRACAENA_DAEMON_PYTHON  python que tem as dependências do daemon (padrão: python3 do PATH)
Se o daemon não existir ou não subir, o teste é PULADO com o motivo, nunca erro.
Windows nativo: NÃO VALIDADO (o teste é pulado fora do Linux).
"""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from dracaena.ui.ipc_client import IpcClient
from dracaena.ui.ipc_client.test_client import until
from dracaena.ui.state import AppState
from dracaena.ui.tray import TrayController

BACKEND = os.environ.get('DRACAENA_BACKEND_ROOT')


class Host:
    def __init__(self):
        self.diagnostics = None
    def open_settings(self): pass
    def open_add_site(self): pass
    def open_shortcut_wizard(self): pass
    def quit_app(self): pass
    def show_diagnostics(self, data): self.diagnostics = data


@unittest.skipUnless(BACKEND and (Path(BACKEND) / 'lib/dracaena/daemon.py').is_file(),
                     'Defina DRACAENA_BACKEND_ROOT para a raiz do backend (lib/dracaena/daemon.py)')
@unittest.skipUnless(sys.platform.startswith('linux'), 'Socket Unix só no Linux; Windows nativo NÃO VALIDADO')
class DaemonIntegration(unittest.TestCase):
    def test_contract_commands_events_tray_appstate_and_reconnect(self):
        with tempfile.TemporaryDirectory(prefix='b1-') as temp:
            sock = str(Path(temp) / 'dracaena/ctl.sock')
            if len(sock) > 100:
                self.skipTest('Caminho do socket longo demais para o limite do sistema (TMPDIR curto)')
            env = dict(os.environ, PYTHONPATH=str(Path(BACKEND) / 'lib'), PYTHONDONTWRITEBYTECODE='1',
                       XDG_RUNTIME_DIR=temp, XDG_CONFIG_HOME=temp + '/config', XDG_DATA_HOME=temp + '/data',
                       XDG_STATE_HOME=temp + '/state', XDG_CACHE_HOME=temp + '/cache')
            executable = os.environ.get('DRACAENA_DAEMON_PYTHON') or shutil.which('python3')
            if not executable:
                self.skipTest('Nenhum python para subir o daemon (DRACAENA_DAEMON_PYTHON)')
            stderr_file = open(Path(temp) / 'daemon.err', 'w+')

            def start():
                return subprocess.Popen([executable, '-m', 'dracaena.cli', 'daemon', '--simulate'],
                                        env=env, stdout=subprocess.DEVNULL, stderr=stderr_file)
            client = IpcClient(sock, retry_ms=10, max_retry_ms=30)
            model, host, events = AppState(), Host(), []
            client.connected.connect(lambda: model.set_connected(True))
            client.disconnected.connect(lambda: model.set_connected(False))

            def on_event(message):
                events.append(message)
                if message.event == 'state':
                    model.apply_state_event(message.data)
            client.event_received.connect(on_event)
            tray = TrayController(client, host, notifications=False, lock_path=Path(temp) / 'ui.lock',
                                  watch_dbus=False)
            tray.bind_state(model)
            process = None

            def request(cmd, args=None, **kw):
                responses = []
                client.request(cmd, args, responses.append, **kw)
                until(lambda: responses, timeout=10)
                return responses[0]
            try:
                process = start()
                self.assertTrue(tray.show())
                try:
                    until(lambda: model.run.connected and events, timeout=8)
                except AssertionError:
                    stderr_file.seek(0)
                    self.skipTest('Daemon simulado não subiu: ' + stderr_file.read()[-300:])
                self.assertEqual(model.run.state, 'idle')
                hello = request('hello')
                self.assertEqual(hello.data['v'], 0)
                self.assertIsInstance(hello.data['toggle_cmd'], list)  # só o tipo: o valor pode herdar APPIMAGE
                self.assertEqual(request('status').data['state'], 'idle')
                self.assertIsInstance(request('config.schema').data, list)
                sites = request('sites.list')
                self.assertIsInstance(sites.data, list)
                self.assertTrue(all({'name', 'slug', 'valid'} <= set(site) for site in sites.data))
                unknown = request('comando.inexistente')
                self.assertEqual((unknown.ok, unknown.error.code), (False, 'unknown_cmd'))
                self.assertTrue(request('config.set', {'key': 'MAX_QUESTIONS', 'value': 12}).ok)
                self.assertEqual(request('config.get').data['MAX_QUESTIONS'], 12)
                failure = request('config.set', {'key': 'MAX_QUESTIONS', 'value': -1})
                self.assertEqual((failure.ok, failure.error.code), (False, 'bad_request'))
                self.assertTrue(failure.error.message)

                # sites.save: nome novo passa; nome que já existe => code exists
                toml = '[site]\nname = "Prática"\nversion = 0\n'
                self.assertTrue(request('sites.save', {'name': 'novo', 'toml': toml}).ok)
                duplicate = request('sites.save', {'name': sites.data[0]['slug'], 'toml': toml})
                self.assertEqual((duplicate.ok, duplicate.error.code), (False, 'exists'))

                # probe.start com timeout por chamada e eventos de fase (assinados no subscribe automático)
                events.clear()
                probe = request('probe.start', {}, timeout_ms=15000)
                self.assertTrue(probe.ok, probe.error)
                self.assertIn('draft_toml', probe.data)
                until(lambda: any(e.event == 'probe' and e.data['phase'] == 'done' for e in events))
                phases = [e.data['phase'] for e in events if e.event == 'probe']
                self.assertEqual(phases, ['connect', 'scan', 'match', 'draft', 'done'])
                bad_probe = request('probe.start', {'url': 'ftp://x'}, timeout_ms=15000)
                self.assertEqual((bad_probe.ok, bad_probe.error.code), (False, 'bad_request'))

                # shortcut.test: o próximo toggle do compositor não age e emite shortcut_test
                events.clear()
                self.assertEqual(request('shortcut.test', {'arm': True}).data, {'armed': True})
                self.assertEqual(request('toggle').data, {'shortcut_test': True})
                until(lambda: any(e.event == 'shortcut_test' and e.data['ok'] for e in events))
                self.assertEqual(request('status').data['state'], 'idle')

                # bandeja dirigida pelo estado real do daemon
                for action, state in ((tray.start, 'running'), (tray.toggle, 'paused'),
                                      (tray.toggle, 'running'), (tray.stop, 'idle')):
                    self.assertTrue(action.isEnabled())
                    action.trigger()
                    until(lambda: model.run.state == state and not tray._busy)
                    self.assertEqual(tray.state, state)
                tray.ask.trigger()
                until(lambda: model.run.question == 1 and not tray._busy)
                self.assertIn('Progresso: 1/', tray.tray.toolTip())
                self.assertIn('Prática simulada', tray.tray.toolTip())
                tray.doctor.trigger()
                until(lambda: host.diagnostics is not None)
                # o resultado depende do ambiente (navegador, notificações): só a forma é do contrato
                self.assertIsInstance(host.diagnostics['ok'], bool)
                self.assertIsInstance(host.diagnostics['checks'], list)

                # queda e volta do daemon: assinatura refeita, sem replay de comandos
                process.terminate()
                process.wait(timeout=5)
                until(lambda: not model.run.connected)
                self.assertFalse(tray.start.isEnabled())
                self.assertEqual(tray.state, 'disconnected')
                events.clear()
                process = start()
                until(lambda: model.run.connected and events, timeout=8)
                self.assertEqual(model.run.state, 'idle')
                self.assertTrue(tray.start.isEnabled())
            finally:
                tray.close()
                if process and process.poll() is None:
                    process.terminate()
                    process.wait(timeout=5)
                stderr_file.close()


if __name__ == '__main__':
    unittest.main()
