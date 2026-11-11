"""Stub Qt: Unix socket no Linux e named pipe no Windows."""
import json
import os
import time
import unittest
import uuid
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from PySide6.QtNetwork import QLocalServer
from dracaena.ui.ipc_client import IpcClient
from dracaena.ui.ipc_client.protocol import LineBuffer, ProtocolError, decode_line

APP = QApplication.instance() or QApplication([])


def until(predicate, timeout=1.5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        APP.processEvents()
        if predicate():
            return
        time.sleep(0.001)
    raise AssertionError('Condição não foi alcançada dentro do prazo.')


class Stub:
    def __init__(self, name):
        self.server = QLocalServer()
        self.sockets = []
        self.requests = []
        self.reply = True
        self.server.newConnection.connect(self.accept)
        if not self.server.listen(name):
            raise RuntimeError(self.server.errorString())

    def accept(self):
        socket = self.server.nextPendingConnection()
        self.sockets.append(socket)
        socket.readyRead.connect(lambda: self.read(socket))

    def read(self, socket):
        while socket.canReadLine():
            request = json.loads(bytes(socket.readLine()))
            self.requests.append(request)
            if self.reply:
                socket.write(json.dumps({'id': request['id'], 'ok': True,
                                         'data': {'state': 'idle'}}).encode() + b'\n')

    def send(self, data):
        self.sockets[-1].write(data)

    def close(self):
        for socket in self.sockets:
            socket.abort()
        self.server.close()


class ClientTests(unittest.TestCase):
    def setUp(self):
        self.name = 'dracaena-test-' + uuid.uuid4().hex
        self.client = IpcClient(self.name, timeout_ms=60, retry_ms=10, max_retry_ms=20)
        self.stub = None

    def tearDown(self):
        self.client.close()
        if self.stub:
            self.stub.close()
        APP.processEvents()

    def connect(self):
        self.stub = Stub(self.name)
        self.client.connect_to_daemon()
        until(lambda: self.client.is_connected and self.stub.sockets)

    def test_response_and_fragmented_event(self):
        self.connect()
        responses, events = [], []
        self.client.event_received.connect(events.append)
        rid = self.client.request('status', callback=responses.append)
        until(lambda: responses)
        self.assertEqual(responses[0].id, rid)
        self.assertTrue(responses[0].ok)
        self.stub.send(b'{"event":"state",')
        APP.processEvents()
        self.assertFalse(events)
        self.stub.send(b'"state":"running","question":1,"max":5}\n')
        until(lambda: events)
        self.assertEqual(events[0].data['state'], 'running')

    def test_missing_daemon_recovers_without_replaying_command(self):
        responses, availability = [], []
        self.client.availability_changed.connect(lambda ok, text: availability.append(ok))
        self.client.connect_to_daemon()
        self.client.request('toggle', callback=responses.append)
        until(lambda: responses and availability)
        self.assertFalse(responses[0].ok)
        self.stub = Stub(self.name)
        until(lambda: self.client.is_connected)
        self.assertTrue(all(req['cmd'] == 'subscribe' for req in self.stub.requests))

    def test_timeout_keeps_ui_event_loop_running(self):
        self.connect()
        self.stub.reply = False
        responses, ticks = [], []
        timer = QTimer()
        timer.setInterval(2)
        timer.timeout.connect(lambda: ticks.append(True))
        timer.start()
        self.client.request('doctor', callback=responses.append)
        until(lambda: responses)
        timer.stop()
        self.assertEqual(responses[0].error.code, 'timeout')
        self.assertGreater(len(ticks), 5)
        self.assertFalse(self.client._pending)

    def test_disconnect_fails_pending_and_reconnects(self):
        self.connect()
        self.stub.reply = False
        responses = []
        rid = self.client.request('ask', callback=responses.append)
        until(lambda: any(req['cmd'] == 'ask' for req in self.stub.requests))
        self.stub.close()
        until(lambda: responses)
        self.assertEqual(responses[0].id, rid)
        self.assertEqual(responses[0].error.code, 'disconnected')
        self.stub = Stub(self.name)
        until(lambda: self.client.is_connected)
        self.assertTrue(all(req['cmd'] == 'subscribe' for req in self.stub.requests))

    def test_subscribe_asks_every_contract_event_on_each_connection(self):
        self.connect()
        wanted = ['state', 'log', 'question', 'verdict', 'probe', 'shortcut_test']
        until(lambda: self.stub.requests)
        first = self.stub.requests[0]
        self.assertEqual((first['v'], first['cmd']), (0, 'subscribe'))
        self.assertEqual(first['args'], {'events': wanted})
        self.stub.close()
        until(lambda: not self.client.is_connected)
        self.stub = Stub(self.name)
        until(lambda: self.client.is_connected and self.stub.requests)
        self.assertEqual(self.stub.requests[0]['args'], {'events': wanted})

    def test_per_call_timeout_overrides_default(self):
        self.client = IpcClient(self.name, timeout_ms=60, retry_ms=10, max_retry_ms=20)
        self.connect()
        until(lambda: self.stub.requests)
        self.stub.reply = False
        responses = []
        started = time.monotonic()
        self.client.request('probe.start', {}, responses.append, timeout_ms=400)
        self.client.request('doctor', None, responses.append)  # padrão: 60 ms
        until(lambda: responses)
        self.assertEqual(responses[0].error.code, 'timeout')
        self.assertLess(time.monotonic() - started, 0.3)  # a chamada curta expirou primeiro
        until(lambda: len(responses) == 2, timeout=2)
        self.assertGreaterEqual(time.monotonic() - started, 0.38)

    def test_wrong_version_disconnects_and_notifies(self):
        self.connect()
        errors = []
        self.client.protocol_error.connect(errors.append)
        self.stub.send(b'{"v":9,"event":"state","state":"idle"}\n')
        until(lambda: errors)
        self.assertIn('incompatível', errors[0])

    def test_close_stops_retry(self):
        self.client.connect_to_daemon()
        self.client.close()
        self.assertFalse(self.client._retry.isActive())
        self.assertFalse(self.client._deadlines.isActive())


class ProtocolTests(unittest.TestCase):
    def test_limit_applies_to_complete_lines_and_trailing_partial(self):
        for data in (b'123456\n', b'1\n123456'):
            with self.assertRaises(ProtocolError):
                LineBuffer(5).feed(data)

    def test_contract_arrays_errors_and_extra_events(self):
        schema = decode_line(b'{"id":1,"ok":true,"data":[{"key":"MAX_QUESTIONS"}]}')
        self.assertEqual(schema.data[0]['key'], 'MAX_QUESTIONS')
        self.assertIs(schema.result, schema.data)
        error = decode_line(b'{"id":2,"ok":false,"error":"Pedido recusado"}')
        self.assertEqual(error.error.message, 'Pedido recusado')
        self.assertEqual(error.error.code, 'daemon_error')
        coded = decode_line('{"id":3,"ok":false,"error":"Já existe","code":"exists"}'.encode())
        self.assertEqual((coded.error.code, coded.error.message), ('exists', 'Já existe'))
        self.assertFalse(coded.ok)
        flat = decode_line(b'{"event":"state","state":"running","site":"S","question":2,"max":9,"error":""}')
        self.assertEqual((flat.event, flat.data['state'], flat.data['max']), ('state', 'running', 9))
        probe = decode_line(b'{"event":"probe","phase":"scan","done":1,"total":4}')
        self.assertEqual(probe.data, {'phase': 'scan', 'done': 1, 'total': 4})
        test = decode_line(b'{"event":"shortcut_test","ok":true}')
        self.assertEqual((test.event, test.data['ok']), ('shortcut_test', True))
        for name in ('log', 'question', 'verdict'):
            event = decode_line(json.dumps({'event': name, 'text': 'Teste'}).encode())
            self.assertEqual(event.event, name)
            self.assertEqual(event.data['text'], 'Teste')

    def test_invalid_messages(self):
        for line in (b'[]', b'{', b'{"id":true,"ok":true,"data":{}}',
                     b'{"v":0,"id":1,"ok":"false"}', b'{"v":0,"id":1,"ok":false}'):
            with self.assertRaises(ProtocolError):
                decode_line(line)


if __name__ == '__main__':
    unittest.main()
