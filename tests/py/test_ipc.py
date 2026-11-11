"""IPC contract tests against sockets and the Service callback boundary."""
import socket
from unittest.mock import MagicMock
import threading
import unittest
from dracaena.daemon import Daemon, Simulator
from dracaena.platform.ipc import Connection


class MinimalService:
    def __init__(self):
        self.callback = None
    def subscribe(self, callback):
        self.callback = callback
        return lambda: None
    def handle(self, cmd, args):
        if cmd == "status":
            return {"state": "idle", "site": "", "question": 0, "max": 80, "error": ""}
        raise AssertionError("platform command leaked into core")


class IPCTests(unittest.TestCase):
    def test_service_without_snapshot_and_callback_events(self):
        service = MinimalService()
        daemon = Daemon(service)
        left, right = socket.socketpair()
        left.settimeout(2)
        conn = Connection(left)
        worker = threading.Thread(target=daemon.client, args=(Connection(right),))
        worker.start()
        try:
            conn.send({"id": 12, "cmd": "subscribe", "args": {"events": ["state"]}})
            self.assertEqual(conn.receive()["id"], 12)
            self.assertEqual(conn.receive()["state"], "idle")
            thread = threading.Thread(target=service.callback, args=({"event": "state", "state": "running"},))
            thread.start()
            self.assertEqual(conn.receive()["state"], "running")
            thread.join(2)
            conn.send({"id": 13, "cmd": "config.schema"})
            self.assertTrue(conn.receive()["ok"])
        finally:
            conn.close()
            worker.join(2)
        self.assertFalse(worker.is_alive())

    def test_simulator_emits_and_unsubscribes(self):
        simulator = Simulator()
        events = []
        unsubscribe = simulator.subscribe(events.append)
        simulator.handle("toggle", {})
        simulator.handle("toggle", {})
        self.assertEqual([e["state"] for e in events], ["running", "paused"])
        unsubscribe()
        simulator.handle("stop", {})
        self.assertEqual(len(events), 2)

    def test_service_error_code_preserved(self):
        class ServiceError(Exception):
            code = "refused"
        class Service(MinimalService):
            def handle(self, cmd, args):
                raise ServiceError("ação recusada")
        response = Daemon(Service()).dispatch({"id": 2, "cmd": "once"}, None)
        self.assertEqual(response, {"id": 2, "ok": False, "error": "ação recusada", "code": "refused"})


class FakeConn:
    def __init__(self):
        self.sent = []
    def send(self, value):
        self.sent.append(value)


class SubscriptionOrderTests(unittest.TestCase):
    def test_snapshot_precedes_newer_events_and_drops_older_states(self):
        from dracaena.daemon import Subscription
        conn = FakeConn()
        sub = Subscription(conn, ["state", "verdict"])
        sub.deliver({"event": "state", "state": "antigo"})
        sub.deliver({"event": "verdict", "ok": True})
        mark = sub.mark()
        sub.deliver({"event": "state", "state": "novo"})
        sub.deliver({"event": "log", "text": "não assinado"})
        sub.release({"state": "atual"}, mark)
        sub.deliver({"event": "state", "state": "depois"})
        self.assertEqual([(e["event"], e.get("state")) for e in conn.sent],
                         [("state", "atual"), ("verdict", None), ("state", "novo"), ("state", "depois")])

    def test_failed_status_does_not_block_events(self):
        class Broken(MinimalService):
            def handle(self, cmd, args):
                raise RuntimeError("falha interna")
        daemon = Daemon(Broken())
        conn = FakeConn()
        daemon.clients[conn] = sub = __import__("dracaena.daemon", fromlist=["Subscription"]).Subscription(conn, ["state"])
        with self.assertLogs("dracaena", "ERROR"):
            daemon.initial_state(sub)
        daemon.emit({"event": "state", "state": "running"})
        self.assertEqual(conn.sent, [{"event": "state", "state": "running"}])

    def test_subscribe_validation_in_portuguese(self):
        response = Daemon(MinimalService()).dispatch({"id": 1, "cmd": "subscribe", "args": {"events": ["x"]}}, None)
        self.assertEqual((response["ok"], response["code"]), (False, "bad_request"))
        self.assertIn("inválida", response["error"])


class RealSocketTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        self.directory = tempfile.TemporaryDirectory()
        base = Path(self.directory.name) / "r"
        self.patches = [patch("dracaena.platform.ipc.runtime_dir", return_value=base),
                        patch("dracaena.platform.instance.runtime_dir", return_value=base)]
        for item in self.patches:
            item.start()
        self.base = base

    def tearDown(self):
        for item in self.patches:
            item.stop()
        self.directory.cleanup()

    def test_permissions_flow_and_clean_shutdown(self):
        import os
        from dracaena.platform import ipc
        listener = ipc.Listener()
        daemon = Daemon(Simulator(), simulate=True)
        thread = threading.Thread(target=daemon.serve, args=(listener,))
        thread.start()
        try:
            self.assertEqual(self.base.stat().st_mode & 0o777, 0o700)
            self.assertEqual(os.stat(listener.address).st_mode & 0o777, 0o600)
            conn = ipc.connect(timeout=2)
            conn.send({"v": 0, "id": 1, "cmd": "subscribe", "args": {"events": ["state"]}})
            self.assertEqual(conn.receive()["id"], 1)
            self.assertEqual(conn.receive()["state"], "idle")
            self.assertEqual(ipc.request("toggle")["data"]["state"], "running")
            self.assertEqual(conn.receive()["state"], "running")
            conn.close()
        finally:
            listener.close()
            thread.join(3)
        self.assertFalse(thread.is_alive())
        self.assertFalse(os.path.exists(listener.address))

    def test_request_without_reply_is_an_error(self):
        from dracaena.platform import ipc
        listener = ipc.Listener()
        thread = threading.Thread(target=lambda: listener.accept().close())
        thread.start()
        try:
            with self.assertRaisesRegex(ConnectionError, "encerrou"):
                ipc.request("status")
        finally:
            thread.join(3)
            listener.close()

    def test_long_socket_path_message(self):
        from pathlib import Path
        from unittest.mock import patch
        from dracaena.platform import ipc
        with patch("dracaena.platform.ipc.runtime_dir", return_value=Path(self.directory.name) / ("x" * 120)):
            with self.assertRaisesRegex(OSError, "excede"):
                ipc.Listener()

    def test_symlink_endpoint_is_refused(self):
        import os
        from dracaena.platform import ipc
        self.base.mkdir(mode=0o700)
        os.symlink("/nonexistent", self.base / "ctl.sock")
        with self.assertRaisesRegex(OSError, "link simbólico"):
            ipc.Listener()

    def test_cli_reports_missing_daemon_in_portuguese(self):
        import contextlib
        import io
        import json
        from unittest.mock import patch
        from dracaena import cli
        out = io.StringIO()
        with patch.object(cli, "request", side_effect=FileNotFoundError(2, "No such file")), contextlib.redirect_stdout(out):
            self.assertEqual(cli.main(["status"]), 1)
        self.assertIn("não está em execução", json.loads(out.getvalue())["error"])


class WindowsPipeTests(unittest.TestCase):
    """Exercita a lógica do pipe com módulos pywin32 simulados (roda em qualquer SO)."""

    def setUp(self):
        import sys
        import types
        from unittest.mock import MagicMock, patch

        class WinError(Exception):
            def __init__(self, winerror, funcname, strerror):
                super().__init__(winerror, funcname, strerror)
                self.winerror, self.funcname, self.strerror = winerror, funcname, strerror

        self.WinError = WinError
        self.pipe_calls = []
        self.server_sid = "eu"
        outer = self

        class Token:
            def __init__(self, sid):
                self.sid = sid
            def Close(self):
                pass

        class Process:
            def Close(self):
                pass

        pywintypes = types.SimpleNamespace(error=WinError, SECURITY_ATTRIBUTES=lambda: types.SimpleNamespace())
        win32api = types.SimpleNamespace(GetCurrentProcess=lambda: "atual", OpenProcess=lambda *a: Process())
        win32con = types.SimpleNamespace(TOKEN_QUERY=8, GENERIC_READ=1, GENERIC_WRITE=2)
        win32security = types.SimpleNamespace(
            TokenUser=1, ACL_REVISION=2, ACL=lambda: MagicMock(), SECURITY_DESCRIPTOR=lambda: MagicMock(),
            OpenProcessToken=lambda process, flags: Token("eu" if process == "atual" else outer.server_sid),
            GetTokenInformation=lambda token, kind: (token.sid,))
        self.win32pipe = types.SimpleNamespace(
            PIPE_ACCESS_DUPLEX=3, PIPE_TYPE_BYTE=0, PIPE_READMODE_BYTE=0, PIPE_WAIT=0,
            CreateNamedPipe=lambda *args: self.pipe_calls.append(args) or MagicMock(name="pipe"),
            ConnectNamedPipe=MagicMock(), DisconnectNamedPipe=MagicMock())
        self.win32file = types.SimpleNamespace(ReadFile=MagicMock(), WriteFile=MagicMock())
        modules = dict(pywintypes=pywintypes, win32api=win32api, win32con=win32con,
                       win32security=win32security, win32pipe=self.win32pipe, win32file=self.win32file)
        self.patch = patch.dict(sys.modules, modules)
        self.patch.start()

        import ctypes

        class Kernel:
            class Function:
                argtypes = restype = None
                def __call__(self, handle, reference):
                    reference._obj.value = 1234
                    return 1
            GetNamedPipeServerProcessId = Function()

        self.ctypes_patch = patch.object(ctypes, "WinDLL", create=True, return_value=Kernel())
        self.ctypes_patch.start()

    def tearDown(self):
        self.ctypes_patch.stop()
        self.patch.stop()

    def listener(self):
        from dracaena.platform import ipc
        listener = ipc.Listener.__new__(ipc.Listener)
        listener.address, listener.socket, listener.pipe, listener.closed = "\\\\.\\pipe\\dracaena-teste", None, None, False
        return listener

    def test_first_instance_flag_only_on_first_pipe(self):
        listener = self.listener()
        listener._create_pipe(first=True)
        listener._create_pipe()
        first, second = (call[1] for call in self.pipe_calls)
        self.assertTrue(first & 0x00080000)
        self.assertFalse(second & 0x00080000)
        self.assertTrue(self.pipe_calls[0][2] & 0x8)  # rejeita clientes remotos

    def test_first_instance_conflict_is_reported_in_portuguese(self):
        listener = self.listener()
        self.win32pipe.CreateNamedPipe = lambda *args: (_ for _ in ()).throw(self.WinError(5, "CreateNamedPipe", "Acesso negado"))
        with self.assertRaisesRegex(OSError, "Já existe um servidor IPC"):
            listener._create_pipe(first=True)

    def test_client_accepts_server_of_same_user_only(self):
        from dracaena.platform import ipc
        ipc._verify_server(5)
        self.server_sid = "outro"
        with self.assertRaisesRegex(PermissionError, "outro usuário"):
            ipc._verify_server(5)

    def test_accept_tolerates_already_connected_and_keeps_listening(self):
        listener = self.listener()
        listener.pipe = first = object.__new__(type("H", (), {"Close": lambda self: None}))
        self.win32pipe.ConnectNamedPipe = MagicMock(side_effect=self.WinError(535, "ConnectNamedPipe", "conectado"))
        conn = listener.accept()
        self.assertIs(conn.handle, first)
        self.assertTrue(conn.windows and conn.server)
        self.assertIsNot(listener.pipe, first)

    def test_accept_failure_becomes_oserror_and_recovers(self):
        listener = self.listener()
        closed = []
        listener.pipe = type("H", (), {"Close": lambda self: closed.append(1)})()
        self.win32pipe.ConnectNamedPipe = MagicMock(side_effect=self.WinError(109, "ConnectNamedPipe", "pipe quebrado"))
        with self.assertRaises(OSError):
            listener.accept()
        self.assertEqual(closed, [1])
        self.assertIsNotNone(listener.pipe)

    def test_read_and_write_errors_become_oserror(self):
        from dracaena.platform.ipc import Connection
        conn = Connection(object(), True)
        self.win32file.ReadFile = MagicMock(side_effect=self.WinError(109, "ReadFile", "quebrado"))
        self.assertIsNone(conn.receive())
        self.win32file.WriteFile = MagicMock(side_effect=self.WinError(232, "WriteFile", "fechando"))
        with self.assertRaises(OSError):
            conn.send({"ok": True})
