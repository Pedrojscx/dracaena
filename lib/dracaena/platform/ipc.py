"""Transporte JSONL. No Windows usa named pipe em modo byte com ACL restrita ao usuário."""
import getpass
import json
import os
from pathlib import Path
import socket
import stat
import threading
from .paths import private_dir, runtime_dir

MAX_FRAME = 1024 * 1024
UNIX_PATH_LIMIT = 107  # sun_path tem 108 bytes, incluindo o terminador

FILE_FLAG_FIRST_PIPE_INSTANCE = 0x00080000
PIPE_REJECT_REMOTE_CLIENTS = 0x00000008
SECURITY_SQOS_PRESENT = 0x00100000
SECURITY_IDENTIFICATION = 0x00010000
ERROR_PIPE_CONNECTED = 535
ERROR_ACCESS_DENIED = 5
ERROR_PIPE_BUSY = 231


class PipeError(OSError):
    """pywintypes.error convertido para OSError, preservando o código do Windows."""

    def __init__(self, code, message):
        super().__init__(code, message)
        self.code = code


def _win_call(function, *args):
    import pywintypes
    try:
        return function(*args)
    except pywintypes.error as exc:
        raise PipeError(exc.winerror, exc.strerror or "Falha no named pipe") from exc


def _current_sid():
    import win32api
    import win32con
    import win32security
    token = _win_call(win32security.OpenProcessToken, win32api.GetCurrentProcess(), win32con.TOKEN_QUERY)
    try:
        return win32security.GetTokenInformation(token, win32security.TokenUser)[0]
    finally:
        token.Close()


def _verify_server(handle):
    """Confere que o processo servidor do pipe roda com o SID do usuário atual."""
    import ctypes
    from ctypes import wintypes
    import win32api
    import win32con
    import win32security
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    function = kernel.GetNamedPipeServerProcessId
    function.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.ULONG)]
    function.restype = wintypes.BOOL
    pid = wintypes.ULONG()
    if not function(int(handle), ctypes.byref(pid)):
        raise OSError(ctypes.get_last_error(), "Não foi possível identificar o servidor IPC")
    process = _win_call(win32api.OpenProcess, 0x1000, False, pid.value)  # QUERY_LIMITED_INFORMATION
    try:
        token = _win_call(win32security.OpenProcessToken, process, win32con.TOKEN_QUERY)
        try:
            sid = win32security.GetTokenInformation(token, win32security.TokenUser)[0]
            if sid != _current_sid():
                raise PermissionError("O servidor IPC pertence a outro usuário; conexão recusada")
        finally:
            token.Close()
    finally:
        process.Close()


def endpoint():
    if os.name == "nt":
        return "\\\\.\\pipe\\dracaena-" + getpass.getuser()
    return str(runtime_dir() / "ctl.sock")


class Connection:
    def __init__(self, handle, windows=False, server=False):
        self.handle, self.windows, self.server = handle, windows, server
        self.buffer = b""
        self.lock = threading.Lock()

    def receive(self):
        while b"\n" not in self.buffer:
            if self.windows:
                import win32file
                try:
                    _, chunk = _win_call(win32file.ReadFile, self.handle, 4096)
                except OSError:
                    return None  # pipe quebrado/encerrado pelo par
            else:
                chunk = self.handle.recv(4096)
            if not chunk:
                return None
            self.buffer += chunk
            if len(self.buffer) > MAX_FRAME:
                raise ValueError("Mensagem IPC grande demais")
        line, self.buffer = self.buffer.split(b"\n", 1)
        return json.loads(line)

    def send(self, value):
        raw = (json.dumps(value, ensure_ascii=False) + "\n").encode("utf-8")
        with self.lock:
            if self.windows:
                import win32file
                _win_call(win32file.WriteFile, self.handle, raw)
            else:
                self.handle.sendall(raw)

    def close(self):
        if self.windows:
            if self.server:
                import win32pipe
                try:
                    _win_call(win32pipe.DisconnectNamedPipe, self.handle)
                except OSError:
                    pass
            self.handle.Close()
        else:
            self.handle.close()


class Listener:
    def __init__(self):
        self.address = endpoint()
        self.socket = None
        self.pipe = None
        self.closed = False
        if os.name == "nt":
            self.pipe = self._create_pipe(first=True)
            return
        if len(os.fsencode(self.address)) > UNIX_PATH_LIMIT:
            raise OSError(f"Caminho do socket IPC excede {UNIX_PATH_LIMIT} bytes; defina um XDG_RUNTIME_DIR mais curto")
        private_dir(runtime_dir())
        path = Path(self.address)
        # O chamador já detém o InstanceLock, então um socket antigo é seguro de remover.
        if path.is_symlink():
            raise OSError("Recusado: o endpoint IPC é um link simbólico")
        if path.exists() and not stat.S_ISSOCK(path.stat().st_mode):
            raise OSError("O endpoint IPC existente não é um socket")
        path.unlink(missing_ok=True)
        self.socket = socket.socket(socket.AF_UNIX)
        try:
            self.socket.bind(self.address)
            os.chmod(self.address, 0o600)
            self.socket.listen(16)
        except BaseException:
            self.socket.close()
            raise

    def accept(self):
        if self.socket:
            conn, _ = self.socket.accept()
            return Connection(conn)
        import win32pipe
        handle = self.pipe
        if handle is None:
            raise OSError("Servidor IPC encerrado")
        try:
            _win_call(win32pipe.ConnectNamedPipe, handle, None)
        except PipeError as exc:
            if exc.code != ERROR_PIPE_CONNECTED:  # cliente já conectado antes da chamada
                self.pipe = None
                handle.Close()
                self.pipe = self._create_pipe()
                raise
        # Mantém uma instância à escuta antes de entregar esta ao cliente.
        try:
            self.pipe = self._create_pipe()
        except OSError:
            self.pipe = None
            Connection(handle, True, server=True).close()
            raise
        return Connection(handle, True, server=True)

    def _create_pipe(self, first=False):
        import pywintypes
        import win32con
        import win32pipe
        import win32security
        acl = win32security.ACL()
        acl.AddAccessAllowedAce(win32security.ACL_REVISION, win32con.GENERIC_READ | win32con.GENERIC_WRITE, _current_sid())
        descriptor = win32security.SECURITY_DESCRIPTOR()
        descriptor.SetSecurityDescriptorDacl(1, acl, 0)
        attributes = pywintypes.SECURITY_ATTRIBUTES()
        attributes.SECURITY_DESCRIPTOR = descriptor
        try:
            return _win_call(win32pipe.CreateNamedPipe,
                self.address, win32pipe.PIPE_ACCESS_DUPLEX | (FILE_FLAG_FIRST_PIPE_INSTANCE if first else 0),
                win32pipe.PIPE_TYPE_BYTE | win32pipe.PIPE_READMODE_BYTE | win32pipe.PIPE_WAIT | PIPE_REJECT_REMOTE_CLIENTS,
                32, MAX_FRAME, MAX_FRAME, 5000, attributes)
        except PipeError as exc:
            if first and exc.code in (ERROR_ACCESS_DENIED, ERROR_PIPE_BUSY):
                raise OSError("Já existe um servidor IPC neste endpoint (talvez de outro usuário); "
                              "não será reutilizado") from exc
            raise

    def close(self):
        self.closed = True
        if self.pipe:
            self.pipe.Close()
            self.pipe = None
        if self.socket:
            try:
                self.socket.shutdown(socket.SHUT_RDWR)  # acorda um accept() bloqueado em outra thread
            except OSError:
                pass
            self.socket.close()
            self.socket = None
            Path(self.address).unlink(missing_ok=True)


def connect(timeout=5):
    """Conecta ao daemon. `timeout=None` mantém a conexão bloqueante (assinantes)."""
    if os.name == "nt":
        import win32file
        import win32pipe
        _win_call(win32pipe.WaitNamedPipe, endpoint(), 5000)
        # SQOS/IDENTIFICATION impede que um servidor falso personifique o cliente.
        handle = _win_call(win32file.CreateFile, endpoint(), win32file.GENERIC_READ | win32file.GENERIC_WRITE,
                           0, None, win32file.OPEN_EXISTING, SECURITY_SQOS_PRESENT | SECURITY_IDENTIFICATION, None)
        try:
            _verify_server(handle)
        except BaseException:
            handle.Close()
            raise
        return Connection(handle, True)
    sock = socket.socket(socket.AF_UNIX)
    sock.settimeout(timeout)
    try:
        sock.connect(endpoint())
    except BaseException:
        sock.close()
        raise
    return Connection(sock)


def request(cmd, args=None):
    conn = connect()
    try:
        try:
            conn.send({"v": 0, "id": 1, "cmd": cmd, "args": args or {}})
            response = conn.receive()
        except (BrokenPipeError, ConnectionResetError):
            response = None
        if response is None:
            raise ConnectionError("O Dracaena encerrou a conexão sem responder")
        return response
    finally:
        conn.close()
