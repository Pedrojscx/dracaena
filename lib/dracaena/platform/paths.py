"""Writable per-user locations; never write beside the executable."""
from pathlib import Path
import os
from platformdirs import PlatformDirs


def directories():
    return PlatformDirs("dracaena", appauthor=False, roaming=True)


def config_dir():
    return Path(directories().user_config_dir)


def data_dir():
    return Path(directories().user_data_dir)


def runtime_dir():
    if os.name != "nt" and os.environ.get("XDG_RUNTIME_DIR"):
        return Path(os.environ["XDG_RUNTIME_DIR"]) / "dracaena"
    return Path(directories().user_runtime_dir)


def private_dir(path):
    path = Path(path)
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.is_symlink() or not path.is_dir():
        raise OSError(f"Esperava-se um diretório privado em {path}")
    if os.name != "nt":
        if path.stat().st_uid != os.getuid():
            raise PermissionError(f"O diretório {path} pertence a outro usuário")
        path.chmod(0o700)
    return path
