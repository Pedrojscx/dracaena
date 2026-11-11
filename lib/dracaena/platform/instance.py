"""Lifetime lock and cooperative loop controls, without POSIX signals."""
import os
import threading
from .paths import private_dir, runtime_dir


class LoopControl:
    def __init__(self):
        self.stop = threading.Event()
        self.paused = threading.Event()

    def toggle(self):
        if self.paused.is_set():
            self.paused.clear()
        else:
            self.paused.set()
        return self.paused.is_set()


class InstanceLock:
    def __init__(self, name="daemon"):
        self.path = private_dir(runtime_dir()) / (name + ".lock")
        self.file = None

    def __enter__(self):
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(self.path, flags, 0o600)
        self.file = os.fdopen(fd, "r+b", buffering=0)
        try:
            if os.name == "nt":
                import msvcrt
                if not self.file.read(1):
                    self.file.write(b"0")
                self.file.seek(0)
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.file.close()
            self.file = None
            raise RuntimeError("O Dracaena já está em execução") from None
        return self

    def __exit__(self, *exc):
        if self.file:
            if os.name == "nt":
                import msvcrt
                self.file.seek(0)
                msvcrt.locking(self.file.fileno(), msvcrt.LK_UNLCK, 1)
            self.file.close()
            self.file = None
