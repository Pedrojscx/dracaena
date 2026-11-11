"""Integrações opcionais da UI com a sessão do usuário."""
from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess
import sys


class SingleInstance:
    """Lock liberado pelo SO, inclusive quando a UI encerra inesperadamente."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._file = None

    def acquire(self) -> bool:
        if self._file is not None:
            return True
        self.path.parent.mkdir(parents=True, exist_ok=True)
        stream = self.path.open('a+b')
        try:
            if sys.platform == 'win32':
                import msvcrt
                stream.seek(0, 2)
                if stream.tell() == 0:
                    stream.write(b'0')
                    stream.flush()
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            stream.close()
            return False
        self._file = stream
        return True

    def close(self) -> None:
        if self._file is None:
            return
        try:
            if sys.platform == 'win32':
                import msvcrt
                self._file.seek(0)
                msvcrt.locking(self._file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self._file.fileno(), fcntl.LOCK_UN)
        finally:
            self._file.close()
            self._file = None
        # Não excluir: outro processo pode já ter aberto o mesmo inode.


AUTOSTART_FILE = 'dracaena.desktop'
WINDOWS_RUN_KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'
WINDOWS_RUN_VALUE = 'DracaenaUI'
BACKGROUND_FLAG = '--background'


def autostart_command(base: list[str]) -> list[str]:
    """argv base (platform.launch_cmd()) + --background, sem duplicar. Não monta caminho próprio."""
    base = list(base)
    return base if BACKGROUND_FLAG in base else base + [BACKGROUND_FLAG]


def _autostart_path(config_home: Path | None) -> Path:
    root = config_home or Path(os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config')
    return Path(root) / 'autostart' / AUTOSTART_FILE


def _quote_exec(arg: str) -> str:
    """Um argumento do Exec: entre aspas (sem shell), depois o escape de string do arquivo."""
    quoted = '"' + re.sub(r'(["`$\\])', r'\\\1', arg) + '"'
    return quoted.replace('%', '%%').replace('\\', '\\\\')


def _parse_exec(value: str) -> list[str]:
    """Inverso de _quote_exec; aceita também argumentos sem aspas separados por espaço."""
    escapes = {'s': ' ', 'n': '\n', 't': '\t', 'r': '\r', '\\': '\\'}
    value = re.sub(r'\\(.)', lambda m: escapes.get(m.group(1), m.group(0)), value)
    args, current, quoted, started, i = [], [], False, False, 0
    while i < len(value):
        char = value[i]
        if quoted and char == '\\' and i + 1 < len(value) and value[i + 1] in '"`$\\':
            current.append(value[i + 1])
            i += 1
        elif char == '"':
            quoted = not quoted
            started = True
        elif char == ' ' and not quoted:
            if started:
                args.append(''.join(current))
                current, started = [], False
        else:
            current.append(char)
            started = True
        i += 1
    if started:
        args.append(''.join(current))
    return [arg.replace('%%', '%') for arg in args]


def set_autostart(enabled: bool, command: list[str], *, config_home: Path | None = None) -> None:
    """Ativa somente por ação explícita; grava exatamente o argv recebido, sem completar nada.

    Linux: ~/.config/autostart/dracaena.desktop. Windows: chave Run do usuário (NÃO VALIDADO
    em Windows nativo). Não altera o daemon.
    """
    if not command or any('\n' in arg or '\r' in arg or '\0' in arg for arg in command):
        raise ValueError('Comando de início automático inválido.')
    if sys.platform == 'win32':
        import winreg
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, WINDOWS_RUN_KEY) as key:
            if enabled:
                winreg.SetValueEx(key, WINDOWS_RUN_VALUE, 0, winreg.REG_SZ,
                                  subprocess.list2cmdline(command))
            else:
                try:
                    winreg.DeleteValue(key, WINDOWS_RUN_VALUE)
                except FileNotFoundError:
                    pass
        return
    if not sys.platform.startswith('linux'):
        raise RuntimeError('Início automático disponível apenas no Linux e no Windows.')
    path = _autostart_path(config_home)
    if not enabled:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('[Desktop Entry]\nType=Application\nName=Dracaena\n'
                    'Comment=Assistente Dracaena na bandeja\nExec=' +
                    ' '.join(_quote_exec(arg) for arg in command) +
                    '\nTerminal=false\nX-GNOME-Autostart-enabled=true\n', encoding='utf-8')


def autostart_argv(*, config_home: Path | None = None) -> list[str] | None:
    """argv registrado hoje, ou None se o início automático não está ativo."""
    if sys.platform == 'win32':
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, WINDOWS_RUN_KEY) as key:
                value, _ = winreg.QueryValueEx(key, WINDOWS_RUN_VALUE)
        except OSError:
            return None
        return [value] if isinstance(value, str) and value.strip() else None
    if not sys.platform.startswith('linux'):
        return None
    try:
        lines = _autostart_path(config_home).read_text(encoding='utf-8').splitlines()
    except (OSError, UnicodeError):
        return None
    entry = {}
    in_entry = False
    for line in lines:
        line = line.strip()
        if line.startswith('['):
            in_entry = line == '[Desktop Entry]'
        elif in_entry and '=' in line and not line.startswith('#'):
            key, _, value = line.partition('=')
            entry.setdefault(key.strip(), value.strip())
    off = {'true'}  # Hidden=true e X-GNOME-Autostart-enabled=false desligam a entrada
    if entry.get('Hidden', '').lower() in off or entry.get('X-GNOME-Autostart-enabled', '').lower() == 'false':
        return None
    argv = _parse_exec(entry.get('Exec', ''))
    return argv or None


def is_autostart_enabled(*, config_home: Path | None = None) -> bool:
    """Estado real (arquivo/chave) para a caixa em Configurações."""
    return autostart_argv(config_home=config_home) is not None
