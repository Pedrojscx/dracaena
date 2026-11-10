"""Atalho de sessão; nunca tenta capturar teclas globais no Wayland."""
from __future__ import annotations

import os
import select
import sys
import threading
from collections.abc import Callable

WAYLAND_HELP = 'No Wayland, configure o compositor para executar dracaena toggle.'


class GlobalHotkey:
    """Callbacks ocorrem na worker: a UI deve encaminhá-los por sinal/fila."""

    def __init__(self, callback: Callable[[], None], *, key: str = 'P',
                 modifiers: tuple[str, ...] = ('super',),
                 on_status: Callable[[str], None] = lambda message: None):
        if len(key) != 1 or not key.isascii() or not key.isalnum():
            raise ValueError('Use uma letra ou número como tecla do atalho.')
        if not modifiers or set(modifiers) - {'super', 'ctrl', 'alt', 'shift'}:
            raise ValueError('Modificadores do atalho inválidos.')
        self.callback = callback
        self.key = key.upper()
        self.modifiers = modifiers
        self.on_status = on_status
        self._stop = threading.Event()
        self._thread = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        if os.environ.get('XDG_SESSION_TYPE', '').lower() == 'wayland' or os.environ.get('WAYLAND_DISPLAY'):
            self.on_status(WAYLAND_HELP)
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name='dracaena-atalho', daemon=True)
        self._thread.start()

    def close(self) -> None:
        self._stop.set()
        # Sem join na thread da UI; o worker libera o registro em até 100 ms.

    def _run(self) -> None:
        try:
            if sys.platform == 'win32':
                self._windows()
            elif sys.platform.startswith('linux') and os.environ.get('DISPLAY'):
                self._x11()
            else:
                self.on_status('Atalho global indisponível nesta sessão.')
        except Exception:
            self.on_status('Não foi possível registrar o atalho global. Use dracaena toggle.')

    def _windows(self) -> None:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.WinDLL('user32', use_last_error=True)
        user32.RegisterHotKey.argtypes = (wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT)
        user32.RegisterHotKey.restype = wintypes.BOOL
        user32.UnregisterHotKey.argtypes = (wintypes.HWND, ctypes.c_int)
        user32.PeekMessageW.argtypes = (ctypes.POINTER(wintypes.MSG), wintypes.HWND,
                                       wintypes.UINT, wintypes.UINT, wintypes.UINT)
        bits = {'alt': 1, 'ctrl': 2, 'shift': 4, 'super': 8}
        mask = 0x4000  # MOD_NOREPEAT
        for modifier in self.modifiers:
            mask |= bits[modifier]
        if not user32.RegisterHotKey(None, 1, mask, ord(self.key)):
            raise OSError('Atalho já está em uso.')
        try:
            self.on_status('Atalho global registrado.')
            message = wintypes.MSG()
            while not self._stop.wait(0.05):
                while user32.PeekMessageW(ctypes.byref(message), None, 0, 0, 1):
                    if message.message == 0x0312:
                        self.callback()
        finally:
            user32.UnregisterHotKey(None, 1)

    def _x11(self) -> None:
        from Xlib import X, XK, display
        connection = display.Display()
        root = connection.screen().root
        bits = {'alt': X.Mod1Mask, 'ctrl': X.ControlMask, 'shift': X.ShiftMask, 'super': X.Mod4Mask}
        mask = 0
        for modifier in self.modifiers:
            mask |= bits[modifier]
        keycode = connection.keysym_to_keycode(XK.string_to_keysym(self.key.lower()))
        errors = []
        locks = {0, X.LockMask}
        # NumLock pode ocupar qualquer slot do mapa de modificadores.
        numcode = connection.keysym_to_keycode(XK.string_to_keysym('Num_Lock'))
        for index, codes in enumerate(connection.get_modifier_mapping()):
            if numcode in codes:
                locks |= {1 << index, X.LockMask | (1 << index)}
        try:
            for lock in locks:
                root.grab_key(keycode, mask | lock, False, X.GrabModeAsync, X.GrabModeAsync,
                              onerror=lambda error, request: errors.append(error) or True)
            connection.sync()
            if errors:
                raise OSError('Atalho já está em uso.')
            self.on_status('Atalho global registrado.')
            pressed = False
            while not self._stop.is_set():
                if not connection.pending_events():
                    select.select([connection.fileno()], [], [], 0.1)
                while connection.pending_events():
                    event = connection.next_event()
                    if event.type == X.KeyPress and not pressed:
                        pressed = True
                        self.callback()
                    elif event.type == X.KeyRelease:
                        pressed = False
        finally:
            for lock in locks:
                root.ungrab_key(keycode, mask | lock)
            connection.sync()
            connection.close()
