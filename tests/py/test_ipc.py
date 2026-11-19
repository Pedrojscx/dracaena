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

    def test_listener_close_is_idempotent(self):
        import os
        from dracaena.platform import ipc
        listener = ipc.Listener()
        listener.close()
        listener.close()
        self.assertTrue(listener.closed)
        self.assertFalse(os.path.exists(listener.address))

    def test_listener_concurrent_close_does_not_raise(self):
        import os
        from dracaena.platform import ipc
        for _ in range(50):
            listener = ipc.Listener()
            barrier = threading.Barrier(2)
            errors = []

            def closer():
                barrier.wait()
                try:
                    listener.close()
                except BaseException as exc:  # noqa: BLE001 - o teste coleta qualquer falha
                    errors.append(exc)

            threads = [threading.Thread(target=closer) for _ in range(2)]
            for item in threads:
                item.start()
            for item in threads:
                item.join(3)
            self.assertEqual(errors, [])
            self.assertFalse(os.path.exists(listener.address))

    def test_listener_accept_after_close_raises_oserror(self):
        from dracaena.platform import ipc
        listener = ipc.Listener()
        listener.close()
        with self.assertRaisesRegex(OSError, "encerrado"):
            listener.accept()

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


def ask(daemon, cmd, args=None, conn=None):
    return daemon.dispatch({"id": 1, "cmd": cmd, "args": args or {}}, conn)


class CaptureConn(FakeConn):
    pass


def subscribed(daemon, events):
    conn = CaptureConn()
    assert ask(daemon, "subscribe", {"events": events}, conn)["ok"]
    daemon.clients[conn].release(None, 0)
    return conn


class SitesBase(unittest.TestCase):
    TOML = '[site]\nname = "Exemplo"\nversion = 1\n'

    def setUp(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        self.directory = tempfile.TemporaryDirectory()
        self.config = Path(self.directory.name) / "cfg"
        self.patch = patch("dracaena.platform.sites.config_dir", return_value=self.config)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.directory.cleanup()



class SitesSaveTests(SitesBase):
    def test_simulated_returns_path_without_writing(self):
        response = ask(Daemon(Simulator(), simulate=True), "sites.save", {"name": "meu-site_1", "toml": self.TOML})
        self.assertTrue(response["ok"])
        self.assertEqual(set(response["data"]), {"path"})
        self.assertTrue(response["data"]["path"].endswith("meu-site_1.toml"))
        self.assertFalse(self.config.exists())

    def test_name_and_size_validation(self):
        daemon = Daemon(Simulator(), simulate=True)
        for name in ("", "A", "a b", "../x", "a.toml", "x" * 65, None, 3):
            response = ask(daemon, "sites.save", {"name": name, "toml": self.TOML})
            self.assertEqual((response["ok"], response["code"]), (False, "bad_request"), name)
        self.assertTrue(ask(daemon, "sites.save", {"name": "x" * 64, "toml": self.TOML})["ok"])
        edge = "# " + "a" * (64 * 1024 - 3) + "\n"
        self.assertEqual(len(edge.encode()), 64 * 1024)
        self.assertTrue(ask(daemon, "sites.save", {"name": "ok", "toml": edge})["ok"])
        response = ask(daemon, "sites.save", {"name": "ok", "toml": edge + "#"})
        self.assertEqual(response["code"], "bad_request")
        self.assertIn("64 KiB", response["error"])
        for toml in (5, "[quebrado"):
            self.assertEqual(ask(daemon, "sites.save", {"name": "ok", "toml": toml})["code"], "bad_request")
        self.assertEqual(ask(daemon, "sites.save", {"name": "ok", "toml": self.TOML, "overwrite": "sim"})["code"], "bad_request")

    def test_real_write_overwrite_and_permissions(self):
        import os
        daemon = Daemon(Simulator(), simulate=False)
        first = ask(daemon, "sites.save", {"name": "demo", "toml": self.TOML})
        self.assertTrue(first["ok"])
        path = self.config / "sites" / "demo.toml"
        self.assertEqual(first["data"]["path"], str(path))
        self.assertEqual(path.read_text(encoding="utf-8"), self.TOML)
        if os.name != "nt":
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        again = ask(daemon, "sites.save", {"name": "demo", "toml": self.TOML.replace("1", "2")})
        self.assertEqual((again["ok"], again["code"]), (False, "exists"))
        self.assertIn("1", path.read_text())
        replaced = ask(daemon, "sites.save", {"name": "demo", "toml": self.TOML.replace("1", "2"), "overwrite": True})
        self.assertTrue(replaced["ok"])
        self.assertIn("2", path.read_text())
        self.assertEqual([p.name for p in path.parent.iterdir()], ["demo.toml"])
        self.assertEqual(ask(daemon, "sites.list")["data"], [{"name": "Exemplo", "slug": "demo", "valid": True}])


class ProbeTests(unittest.TestCase):
    def test_success_result_and_events_only_for_subscribers(self):
        import tomllib
        daemon = Daemon(Simulator(), simulate=True, probe_step=0)
        watcher, other = subscribed(daemon, ["probe"]), subscribed(daemon, ["state"])
        response = ask(daemon, "probe.start", {"url": "https://exemplo.test/pratica"})
        self.assertTrue(response["ok"])
        data = response["data"]
        self.assertEqual(set(data), {"matches", "questions", "draft_toml"})
        self.assertTrue(all(isinstance(n, int) for n in data["matches"].values()))
        self.assertEqual(data["questions"], 1)
        tomllib.loads(data["draft_toml"])
        self.assertEqual([(e["phase"], e["done"], e["total"]) for e in watcher.sent],
                         [("connect", 0, 4), ("scan", 1, 4), ("match", 2, 4), ("draft", 3, 4), ("done", 4, 4)])
        self.assertTrue(all(e["event"] == "probe" for e in watcher.sent))
        self.assertEqual(other.sent, [])

    def test_simulated_errors_carry_code_and_portuguese_message(self):
        for code in ("no_browser", "no_site", "bad_request", "internal"):
            daemon = Daemon(Simulator(), simulate=True, probe_step=0)
            watcher = subscribed(daemon, ["probe"])
            response = ask(daemon, "probe.start", {"simulate_error": code})
            self.assertEqual((response["ok"], response["code"]), (False, code))
            self.assertRegex(response["error"], "[ãáçéíõ ]")
            self.assertEqual(watcher.sent[-1]["phase"], "error")
            self.assertLess(watcher.sent[-1]["done"], 4)
            self.assertEqual(ask(daemon, "probe.cancel")["data"], {"cancelled": False})

    def test_simulated_cancellation_and_busy_state(self):
        daemon = Daemon(Simulator(), simulate=True, probe_step=0)
        watcher = subscribed(daemon, ["probe"])
        response = ask(daemon, "probe.start", {"simulate_error": "cancelled"})
        self.assertEqual((response["ok"], response["code"]), (False, "cancelled"))
        self.assertEqual(watcher.sent[-1]["phase"], "cancelled")

    def test_real_cancel_stops_a_running_probe(self):
        daemon = Daemon(Simulator(), simulate=True, probe_step=10)
        watcher = subscribed(daemon, ["probe"])
        results = []
        thread = threading.Thread(target=lambda: results.append(ask(daemon, "probe.start")))
        thread.start()
        for _ in range(200):
            if watcher.sent:
                break
            threading.Event().wait(.01)
        busy = ask(daemon, "probe.start")
        self.assertEqual((busy["ok"], busy["code"]), (False, "bad_request"))
        self.assertEqual(ask(daemon, "probe.cancel")["data"], {"cancelled": True})
        thread.join(3)
        self.assertFalse(thread.is_alive())
        self.assertEqual(results[0]["code"], "cancelled")
        self.assertEqual(watcher.sent[-1]["phase"], "cancelled")
        self.assertEqual(ask(daemon, "probe.cancel")["data"], {"cancelled": False})

    def test_invalid_arguments_start_nothing(self):
        daemon = Daemon(Simulator(), simulate=True, probe_step=0)
        watcher = subscribed(daemon, ["probe"])
        for args in ({"url": 5}, {"url": "ftp://x"}, {"url": "https://x/" + "a" * 3000}, {"simulate_error": "xyz"}):
            self.assertEqual(ask(daemon, "probe.start", args)["code"], "bad_request")
        self.assertEqual(watcher.sent, [])

    def test_probe_does_not_block_other_commands(self):
        daemon = Daemon(Simulator(), simulate=True, probe_step=10)
        thread = threading.Thread(target=lambda: ask(daemon, "probe.start"))
        thread.start()
        try:
            self.assertEqual(ask(daemon, "status")["data"]["state"], "idle")
        finally:
            ask(daemon, "probe.cancel")
            thread.join(3)

    def test_probe_is_a_valid_subscription_and_real_mode_is_unavailable(self):
        self.assertTrue(ask(Daemon(Simulator()), "subscribe", {"events": ["probe", "shortcut_test"]}, FakeConn())["ok"])
        response = ask(Daemon(Simulator(), simulate=False), "probe.start")
        self.assertEqual(response["code"], "no_site")


class ConfigSchemaTests(unittest.TestCase):
    def test_schema_covers_every_editable_key_in_portuguese(self):
        from dracaena.platform import config
        schema = ask(Daemon(Simulator(), simulate=True), "config.schema")["data"]
        self.assertEqual([e["key"] for e in schema], list(config.DEFAULTS))
        for entry in schema:
            self.assertIn(entry["type"], ("integer", "string", "boolean"))
            self.assertEqual(entry["default"], config.DEFAULTS[entry["key"]])
            self.assertGreater(len(entry["label"]), 2)
            self.assertGreater(len(entry["description"]), 20)
            self.assertNotEqual(entry["label"], entry["key"])
            self.assertRegex(entry["description"], r"[ãáâçéêíóõú]|(?i:\b(de|do|da|para|em|um|uma|usa|se)\b)")
            if entry["type"] == "integer":
                self.assertLessEqual(entry["min"], entry["default"])
                self.assertGreaterEqual(entry["max"], entry["default"])
        by_key = {e["key"]: e for e in schema}
        self.assertEqual(by_key["BROWSER_FALLBACK"]["choices"], ["", "playwright"])
        self.assertEqual((by_key["MAX_QUESTIONS"]["min"], by_key["MAX_QUESTIONS"]["max"]), (1, 1000))

    def test_schema_limits_are_the_enforced_limits(self):
        from dracaena.platform import config
        for entry in config.schema():
            if "min" in entry:
                config.validate(entry["key"], entry["min"])
                config.validate(entry["key"], entry["max"])
                with self.assertRaises(ValueError):
                    config.validate(entry["key"], entry["min"] - 1)
                with self.assertRaises(ValueError):
                    config.validate(entry["key"], entry["max"] + 1)


class ToggleCommandTests(unittest.TestCase):
    def test_three_modes(self):
        import tempfile
        from pathlib import Path
        from dracaena.platform.launcher import launch_cmd, toggle_command
        with tempfile.TemporaryDirectory() as directory:
            appdir = Path(directory) / "mnt"
            (appdir / "usr/bin").mkdir(parents=True)
            inside = str(appdir / "usr/bin/dracaena")
            env = {"APPIMAGE": "/opt/Dracaena.AppImage", "APPDIR": str(appdir)}
            self.assertEqual(launch_cmd(env, frozen=True, executable=inside), ["/opt/Dracaena.AppImage"])
            self.assertEqual(launch_cmd({}, frozen=True, executable="C:/App/dracaena.exe"), ["C:/App/dracaena.exe"])
            self.assertEqual(launch_cmd({}, frozen=False, executable="/usr/bin/python3"), ["/usr/bin/python3", "-m", "dracaena"])
            self.assertEqual(toggle_command(env, frozen=True, executable=inside), ["/opt/Dracaena.AppImage", "toggle"])

    def test_inherited_appimage_of_another_app_is_ignored(self):
        import tempfile
        from pathlib import Path
        from dracaena.platform.launcher import launch_cmd
        with tempfile.TemporaryDirectory() as directory:
            other = {"APPIMAGE": "/home/u/Applications/Outro.AppImage", "APPDIR": str(Path(directory) / "outro")}
            dev = ["/usr/bin/python3", "-m", "dracaena"]
            self.assertEqual(launch_cmd(other, frozen=False, executable="/usr/bin/python3"), dev)
            self.assertEqual(launch_cmd({"APPIMAGE": other["APPIMAGE"]}, frozen=False, executable="/usr/bin/python3"), dev)
            # congelado, mas fora do $APPDIR (ex.: PyInstaller instalado ao lado de outro AppImage)
            self.assertEqual(launch_cmd(other, frozen=True, executable="/opt/dracaena/dracaena"), ["/opt/dracaena/dracaena"])
            # $APPDIR definido, mas sem build congelado
            inside = str(Path(directory) / "outro/usr/bin/python")
            self.assertEqual(launch_cmd(other, frozen=False, executable=inside), [inside, "-m", "dracaena"])
            # prefixo parecido não conta como "dentro"
            sibling = str(Path(directory) / "outro-x/dracaena")
            self.assertEqual(launch_cmd(other, frozen=True, executable=sibling), [sibling])

    def test_symlink_escape_from_appdir_is_not_inside(self):
        import os
        import tempfile
        from pathlib import Path
        from dracaena.platform.launcher import launch_cmd
        if os.name == "nt":
            self.skipTest("symlinks exigem privilégio no Windows")
        with tempfile.TemporaryDirectory() as directory:
            appdir, outside = Path(directory) / "app", Path(directory) / "fora"
            appdir.mkdir()
            outside.mkdir()
            (outside / "bin").write_text("")
            (appdir / "bin").symlink_to(outside / "bin")
            env = {"APPIMAGE": "/opt/X.AppImage", "APPDIR": str(appdir)}
            self.assertEqual(launch_cmd(env, frozen=True, executable=str(appdir / "bin")), [str(appdir / "bin")])

    def test_toggle_command_is_launch_cmd_plus_toggle(self):
        from dracaena.platform.launcher import launch_cmd, toggle_command
        for frozen in (True, False):
            self.assertEqual(toggle_command({}, frozen, "x"), launch_cmd({}, frozen, "x") + ["toggle"])
        self.assertEqual(toggle_command(), launch_cmd() + ["toggle"])

    def test_dev_command_really_runs(self):
        import json
        import subprocess
        import sys
        from dracaena.platform.launcher import launch_cmd
        command = launch_cmd({}, frozen=False, executable=sys.executable) + ["toggle"]
        self.assertEqual(command[1:], ["-m", "dracaena", "toggle"])
        import os
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            env = {**os.environ, "XDG_RUNTIME_DIR": directory}
            result = subprocess.run(command, capture_output=True, text=True, timeout=30, env=env)
        self.assertEqual(result.returncode, 1)  # sem daemon: erro claro em português, não traceback
        self.assertIn("não está em execução", json.loads(result.stdout)["error"])

    def test_defaults_follow_the_running_interpreter(self):
        import sys
        from dracaena.platform.launcher import toggle_command
        command = toggle_command({})
        self.assertEqual(command[0], sys.executable)
        self.assertEqual(command[-1], "toggle")

    def test_hello_exposes_toggle_cmd(self):
        from unittest.mock import patch
        with patch("dracaena.platform.launcher.sys.frozen", True, create=True):
            data = ask(Daemon(Simulator(), simulate=True), "hello")["data"]
        self.assertEqual(data["toggle_cmd"][-1], "toggle")
        for cmd in ("sites.save", "probe.cancel", "shortcut.test"):
            self.assertIn(cmd, data["caps"])


class ShortcutTestTests(unittest.TestCase):
    def setUp(self):
        self.now = 1000.0
        self.service = Simulator()
        self.daemon = Daemon(self.service, simulate=True, clock=lambda: self.now)
        self.watcher = subscribed(self.daemon, ["shortcut_test", "state"])
        self.calls = []
        original = self.service.handle
        self.service.handle = lambda cmd, args: self.calls.append(cmd) or original(cmd, args)

    def test_armed_toggle_is_consumed_without_touching_the_service(self):
        self.assertEqual(ask(self.daemon, "shortcut.test", {"arm": True})["data"], {"armed": True})
        response = ask(self.daemon, "toggle")
        self.assertTrue(response["ok"])
        self.assertEqual(self.calls, [])
        self.assertEqual(self.service.state, "idle")
        self.assertEqual(self.watcher.sent, [{"event": "shortcut_test", "ok": True}])
        ask(self.daemon, "toggle")  # desarmado: comportamento normal
        self.assertEqual(self.calls, ["toggle"])
        self.assertEqual(self.service.state, "running")
        self.assertEqual(sum(e["event"] == "shortcut_test" for e in self.watcher.sent), 1)

    def test_disarms_itself_after_30_seconds(self):
        ask(self.daemon, "shortcut.test", {"arm": True})
        self.now += 29.9
        # ainda válido ao rearmar: renova o prazo
        ask(self.daemon, "shortcut.test", {"arm": True})
        self.now += 29.9
        self.assertTrue(self.daemon.armed_until is not None)
        self.now += 0.2
        ask(self.daemon, "toggle")
        self.assertEqual(self.calls, ["toggle"])
        self.assertFalse(any(e["event"] == "shortcut_test" for e in self.watcher.sent))
        self.assertIsNone(self.daemon.armed_until)

    def test_disarm_command_and_validation(self):
        ask(self.daemon, "shortcut.test", {"arm": True})
        self.assertEqual(ask(self.daemon, "shortcut.test", {"arm": False})["data"], {"armed": False})
        ask(self.daemon, "toggle")
        self.assertEqual(self.calls, ["toggle"])
        for arm in ("true", 1, None):
            self.assertEqual(ask(self.daemon, "shortcut.test", {"arm": arm})["code"], "bad_request")

    def test_other_commands_do_not_consume_the_test(self):
        ask(self.daemon, "shortcut.test", {"arm": True})
        ask(self.daemon, "status")
        self.assertIsNotNone(self.daemon.armed_until)


class DoctorFormatTests(unittest.TestCase):
    def test_definitive_format_in_portuguese(self):
        from unittest.mock import patch
        from dracaena.platform import browser
        with patch.object(browser, "resolve", side_effect=browser.BrowserError("Nenhum navegador Chromium configurado ou detectado")), \
                patch("shutil.which", return_value=None):
            result = ask(Daemon(Simulator(), simulate=True), "doctor")["data"]
        self.assertEqual(set(result), {"ok", "checks"})
        self.assertFalse(result["ok"])
        for check in result["checks"]:
            self.assertLessEqual(set(check), {"name", "ok", "message", "hint"})
            self.assertIsInstance(check["ok"], bool)
            self.assertTrue(check["message"])
            if not check["ok"]:
                self.assertTrue(check["hint"])
        names = {c["name"]: c for c in result["checks"]}
        self.assertFalse(names["claude"]["ok"])
        self.assertIn("não encontrado", names["claude"]["message"])
        self.assertFalse(names["browser"]["ok"])
        self.assertTrue(names["config"]["ok"])


class UnixPeerOwnerTests(unittest.TestCase):
    def test_client_refuses_foreign_owner_before_sending(self):
        import os
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        from dracaena.platform import ipc
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory) / "r"
            with patch("dracaena.platform.ipc.runtime_dir", return_value=base):
                listener = ipc.Listener()
                received = []
                def serve_once():
                    peer = listener.accept()
                    received.append(peer.receive())
                    peer.close()
                thread = threading.Thread(target=serve_once, daemon=True)
                thread.start()
                try:
                    with patch.object(os, "getuid", return_value=os.getuid() + 1):
                        with self.assertRaisesRegex(PermissionError, "não pertence|outro usuário"):
                            ipc.request("status")
                    self.assertEqual(received, [])
                    conn = ipc.connect(timeout=2)  # dono correto: aceito
                    conn.close()
                finally:
                    listener.close()
                    thread.join(2)

    def test_non_socket_endpoint_is_refused(self):
        import tempfile
        from pathlib import Path
        from dracaena.platform import ipc
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ctl.sock"
            path.write_text("x")
            with self.assertRaises(PermissionError):
                ipc._verify_socket_owner(str(path))
            path.unlink()
            ipc._verify_socket_owner(str(path))  # ausente: deixa o connect() reportar


class SitesExistsAndListTests(SitesBase):
    def test_simulated_exists_without_overwrite(self):
        daemon = Daemon(Simulator(), simulate=True)
        response = ask(daemon, "sites.save", {"name": "existente", "toml": self.TOML})
        self.assertEqual((response["ok"], response["code"]), (False, "exists"))
        self.assertIn("Já existe", response["error"])
        self.assertTrue(ask(daemon, "sites.save", {"name": "existente", "toml": self.TOML, "overwrite": True})["ok"])
        self.assertTrue(ask(daemon, "sites.save", {"name": "novo", "toml": self.TOML})["ok"])

    def test_simulated_list_has_valid_and_invalid_sites(self):
        sites = ask(Daemon(Simulator(), simulate=True), "sites.list")["data"]
        self.assertTrue(any(s["valid"] for s in sites))
        self.assertTrue(any(not s["valid"] for s in sites))
        for site in sites:
            self.assertEqual(set(site), {"name", "slug", "valid"})

    def test_real_list_never_fails_on_bad_files(self):
        directory = self.config / "sites"
        directory.mkdir(parents=True)
        (directory / "bom.toml").write_text('[site]\nname = "Nome Bonito"\n', encoding="utf-8")
        (directory / "sem-nome.toml").write_text("x = 1\n", encoding="utf-8")
        (directory / "quebrado.toml").write_text("[site\n", encoding="utf-8")
        (directory / "binario.toml").write_bytes(b"\xff\xfe\x00")
        (directory / "Slug Ruim.toml").write_text('[site]\nname = "x"\n', encoding="utf-8")
        (directory / "grande.toml").write_text("# " + "a" * 70000 + "\n", encoding="utf-8")
        (directory / "pasta.toml").mkdir()
        (directory / "nome-nao-str.toml").write_text("[site]\nname = 3\n", encoding="utf-8")
        listed = {s["slug"]: s for s in ask(Daemon(Simulator()), "sites.list")["data"]}
        self.assertEqual(listed["bom"], {"name": "Nome Bonito", "slug": "bom", "valid": True})
        self.assertEqual(listed["sem-nome"], {"name": "sem-nome", "slug": "sem-nome", "valid": True})
        self.assertEqual(listed["nome-nao-str"]["name"], "nome-nao-str")
        for slug in ("quebrado", "binario", "Slug Ruim", "grande"):
            self.assertFalse(listed[slug]["valid"], slug)
            self.assertEqual(listed[slug]["name"], slug)
        self.assertNotIn("pasta", listed)

    def test_real_list_without_directory_is_empty(self):
        self.assertEqual(ask(Daemon(Simulator()), "sites.list")["data"], [])

    def test_real_exists_code(self):
        daemon = Daemon(Simulator())
        self.assertTrue(ask(daemon, "sites.save", {"name": "demo", "toml": self.TOML})["ok"])
        self.assertEqual(ask(daemon, "sites.save", {"name": "demo", "toml": self.TOML})["code"], "exists")
