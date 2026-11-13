"""Chromium discovery and dedicated-profile CDP launch."""
import configparser
import contextlib
import ipaddress
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import time
from urllib.request import urlopen
from .paths import data_dir, private_dir


class BrowserError(RuntimeError):
    pass


class BrowserUnsupported(BrowserError):
    pass


class NoBrowser(BrowserError):
    """Nenhum navegador configurado nem detectado (único caso em que o fallback é permitido)."""


class FallbackMissing(BrowserError):
    """O Chromium reserva ainda não foi baixado; precisa de confirmação explícita do usuário."""


BROWSERS_KEY = "PLAYWRIGHT_BROWSERS_PATH"
FALLBACK_SIZE = "400 MB"  # espaço em disco do Chromium (sem o headless shell)


def is_chromium(executable):
    if os.name == "nt":
        import win32api
        try:
            translations = win32api.GetFileVersionInfo(executable, r"\VarFileInfo\Translation")
            names = [win32api.GetFileVersionInfo(executable, f"\\StringFileInfo\\{language:04x}{codepage:04x}\\ProductName")
                     for language, codepage in translations]
        except Exception:
            return False
        return any(brand in name.lower() for name in names for brand in ("chromium", "google chrome", "microsoft edge", "vivaldi", "brave"))
    try:
        result = subprocess.run([executable, "--version"], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return False
    text = (result.stdout + result.stderr).lower()
    return result.returncode == 0 and any(name in text for name in ("chromium", "google chrome", "microsoft edge", "vivaldi", "brave"))


def default_browser():
    if os.name == "nt":
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\Shell\Associations\UrlAssociations\https\UserChoice") as key:
            prog = winreg.QueryValueEx(key, "ProgId")[0]
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, prog + r"\shell\open\command") as key:
            command = winreg.QueryValueEx(key, None)[0]
        # Registry commands normally quote the executable; preserve spaces.
        command = os.path.expandvars(command).strip()
        return command.split('"', 2)[1] if command.startswith('"') else command.split()[0]
    result = subprocess.run(["xdg-settings", "get", "default-web-browser"], capture_output=True, text=True, timeout=5, check=True)
    desktop = result.stdout.strip()
    if not desktop or Path(desktop).name != desktop:
        raise BrowserError("Identificador de aplicativo do navegador padrão inválido")
    bases = [Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))]
    bases += [Path(p) for p in os.environ.get("XDG_DATA_DIRS", "/usr/local/share:/usr/share").split(":")]
    for base in bases:
        file = base / "applications" / desktop
        if file.is_file():
            config = configparser.ConfigParser(interpolation=None)
            config.read(file, encoding="utf-8")
            args = shlex.split(config["Desktop Entry"]["Exec"])
            if args and Path(args[0]).name not in ("env", "flatpak", "snap"):
                return shutil.which(args[0]) or args[0]
            raise BrowserUnsupported("Navegador Flatpak/Snap ou wrapper detectado: configure o executável; suporte depende do sandbox")
    raise BrowserError("Entrada .desktop do navegador padrão não encontrada")


def resolve(executable="", fallback="playwright"):
    if executable:
        if is_chromium(executable):
            return executable
        raise BrowserError("Navegador configurado não é Chromium válido; configuração explícita tem prioridade")
    try:
        candidate = default_browser()
    except BrowserUnsupported:
        raise
    except (OSError, KeyError, subprocess.SubprocessError, BrowserError):
        candidate = ""
    if candidate:
        if is_chromium(candidate):
            return candidate
        raise BrowserError("Navegador padrão detectado não é Chromium; configure um navegador compatível")
    if fallback == "playwright":
        path = fallback_executable()
        if path:
            return path
        raise FallbackMissing(f"O Chromium reserva ainda não foi baixado (ocupa cerca de {FALLBACK_SIZE} em disco)")
    raise NoBrowser("Nenhum navegador Chromium configurado ou detectado")


def fallback_dir():
    """Pasta própria (por usuário) do Chromium reserva; nunca a do instalador do sistema."""
    return data_dir() / "browsers"


@contextlib.contextmanager
def _browsers_env():
    old = os.environ.get(BROWSERS_KEY)
    os.environ[BROWSERS_KEY] = str(fallback_dir())
    try:
        yield
    finally:
        if old is None:
            os.environ.pop(BROWSERS_KEY, None)
        else:
            os.environ[BROWSERS_KEY] = old


def fallback_executable():
    """Caminho do Chromium reserva já baixado, ou None."""
    from playwright.sync_api import sync_playwright
    with _browsers_env(), sync_playwright() as pw:
        candidate = pw.chromium.executable_path
    return candidate if Path(candidate).is_file() else None


def _explain(output, target):
    text = output.lower()
    if any(mark in text for mark in ("enotfound", "eai_again", "econnrefused", "econnreset", "etimedout",
                                     "getaddrinfo", "socket hang up", "download failed", "network")):
        return "Sem conexão com a internet para baixar o Chromium. Conecte-se e tente de novo."
    if any(mark in text for mark in ("eacces", "eperm", "permission denied")):
        return f"Sem permissão para gravar em {target}. Ajuste as permissões da pasta e tente de novo."
    if "enospc" in text or "no space" in text:
        return f"Sem espaço em disco em {target} (são necessários cerca de {FALLBACK_SIZE})."
    return "Falha ao baixar o Chromium. Tente de novo ou informe um navegador nas configurações."


def install_fallback(timeout=900):
    """Baixa o Chromium com o driver embutido do Playwright para fallback_dir().

    Só deve ser chamado após confirmação explícita do usuário (a CLI pergunta).
    """
    from playwright._impl._driver import compute_driver_executable, get_driver_env
    target = fallback_dir()
    try:
        private_dir(target)
    except OSError:
        raise BrowserError(f"Sem permissão para gravar em {target}. Ajuste as permissões da pasta e tente de novo.") from None
    node, cli = compute_driver_executable()
    env = get_driver_env()
    env[BROWSERS_KEY] = str(target)
    try:
        result = subprocess.run([node, cli, "install", "chromium", "--no-shell", "--no-progress"], env=env, capture_output=True, text=True,
                                timeout=timeout, stdin=subprocess.DEVNULL)
    except FileNotFoundError:
        raise BrowserError("O instalador do Playwright não foi encontrado nesta instalação") from None
    except subprocess.TimeoutExpired:
        raise BrowserError("Tempo esgotado ao baixar o Chromium. Verifique a conexão e tente de novo.") from None
    if result.returncode != 0:
        raise BrowserError(_explain(result.stdout + result.stderr, target))
    path = fallback_executable()
    if not path:
        raise BrowserError("O download terminou, mas o Chromium não foi encontrado")
    return path


def read_port(profile):
    lines = (Path(profile) / "DevToolsActivePort").read_text(encoding="utf-8").splitlines()
    if len(lines) < 2 or not lines[0].isdigit() or not 1 <= int(lines[0]) <= 65535 or not lines[1].startswith("/devtools/browser/"):
        raise BrowserError("DevToolsActivePort inválido")
    return int(lines[0])


def launch(executable="", fallback="", url="about:blank", timeout=15):
    import psutil
    binary = resolve(executable, fallback)
    profile = private_dir(data_dir() / "browser-profile")
    active = profile / "DevToolsActivePort"
    # A live owner keeps its endpoint; never delete its DevToolsActivePort.
    for running in psutil.process_iter(["cmdline"]):
        arguments = running.info.get("cmdline") or []
        if "--user-data-dir=" + str(profile) in arguments or any(
                argument == "--user-data-dir" and i + 1 < len(arguments) and arguments[i + 1] == str(profile)
                for i, argument in enumerate(arguments)):
            raise BrowserError("O perfil dedicado já está aberto; encerre-o antes de reiniciar")
    active.unlink(missing_ok=True)
    proc = subprocess.Popen([binary, "--user-data-dir=" + str(profile), "--remote-debugging-port=0",
                             "--remote-debugging-address=127.0.0.1", "--no-first-run", "--no-default-browser-check", url],
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.monotonic() + timeout
    try:
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                raise BrowserError("O navegador encerrou antes de o CDP ficar pronto (o perfil pode já estar aberto)")
            try:
                port = read_port(profile)
                process = psutil.Process(proc.pid)
                connections = []
                for child in [process] + process.children(recursive=True):
                    connections.extend(child.net_connections(kind="tcp"))
                listeners = [c for c in connections if c.status == psutil.CONN_LISTEN and c.laddr.port == port]
                if not listeners:
                    time.sleep(.1)
                    continue
                if any(not ipaddress.ip_address(c.laddr.ip).is_loopback for c in listeners):
                    raise BrowserError("O CDP não está restrito ao loopback; conexão recusada")
                with urlopen(f"http://127.0.0.1:{port}/json/version", timeout=1) as response:
                    info = json.load(response)
                if not str(info.get("webSocketDebuggerUrl", "")).startswith(f"ws://127.0.0.1:{port}/devtools/browser/"):
                    raise BrowserError("Endpoint CDP inválido")
                return {"port": port, "profile": str(profile), "pid": proc.pid}
            except (FileNotFoundError, ConnectionError, TimeoutError):
                time.sleep(.1)
        raise BrowserError("Tempo esgotado aguardando o DevToolsActivePort")
    except BaseException:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        raise
