"""Chromium discovery and dedicated-profile CDP launch."""
import configparser
import contextlib
import importlib
import ipaddress
import json
import logging
import os
from pathlib import Path
import shlex
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from urllib.request import ProxyHandler, build_opener, urlopen
from .paths import data_dir, private_dir

LOG = logging.getLogger("dracaena")


class BrowserError(RuntimeError):
    pass


class BrowserUnsupported(BrowserError):
    pass


class NoBrowser(BrowserError):
    """Nenhum navegador configurado nem detectado (único caso em que o fallback é permitido)."""


class FallbackMissing(BrowserError):
    """O Chromium reserva ainda não foi baixado; precisa de confirmação explícita do usuário."""


class FallbackUnavailable(BrowserError):
    """Esta instalação não traz o módulo do Chromium reserva; não há o que baixar."""


class BrowserSandboxUnavailable(BrowserError):
    """O Chromium reserva não conseguiu criar o sandbox do processo."""

    condition = "sandbox_unavailable"


BROWSERS_KEY = "PLAYWRIGHT_BROWSERS_PATH"
NO_SANDBOX_ENV = "DRACAENA_CHROMIUM_NO_SANDBOX"
FALLBACK_SIZE = "400 MB"  # espaço em disco do Chromium (sem o headless shell)
SANDBOX_ERROR = (
    "O Chromium reserva não iniciou porque o sandbox do sistema está indisponível. "
    "Crie um perfil AppArmor que permita userns para o executável ou ajuste o sysctl "
    "kernel.apparmor_restrict_unprivileged_userns. Como último recurso, aceite o risco "
    f"explicitamente com {NO_SANDBOX_ENV}=1."
)
_SANDBOX_MARKERS = (
    "no usable sandbox",
    "suid sandbox helper binary was found, but is not configured correctly",
    "running as root without --no-sandbox is not supported",
)


CHROMIUM_NAMES = ("chromium", "google chrome", "microsoft edge", "vivaldi", "brave", "opera")
# Navegadores sabidamente sem CDP: nunca são sondados (poderiam ignorar --user-data-dir).
NOT_CHROMIUM = ("firefox", "mozilla", "librewolf", "waterfox", "floorp", "safari", "epiphany", "gnome web",
                "webkit", "konqueror", "falkon", "qutebrowser", "midori")
PROBE_TIMEOUT = 10
PROBE_CACHE_LIMIT = 32


class ProbeTimeout(BrowserError):
    """A sonda não viu o CDP no tempo limite (não vai para o cache: pode ser lentidão passageira)."""


def _product_text(executable):
    """Identificação em minúsculas (ProductName no Windows, --version nos demais).

    None quando o executável não pode ser executado; "" quando não se identifica.
    """
    if os.name == "nt":
        import win32api
        try:
            translations = win32api.GetFileVersionInfo(executable, r"\VarFileInfo\Translation")
            names = [win32api.GetFileVersionInfo(executable, f"\\StringFileInfo\\{language:04x}{codepage:04x}\\ProductName")
                     for language, codepage in translations]
        except Exception:
            return ""
        return " ".join(str(name) for name in names).lower()
    try:
        result = subprocess.run([executable, "--version"], capture_output=True, text=True, timeout=5,
                                stdin=subprocess.DEVNULL)
    except OSError:
        return None
    except subprocess.TimeoutExpired:
        return ""
    return (result.stdout + result.stderr).lower() if result.returncode == 0 else ""


def is_chromium(executable):
    """Chromium pelo nome; nome desconhecido só é aceito se a sonda confirmar o CDP."""
    text = _product_text(executable)
    if text is None:
        return False
    if any(name in text for name in CHROMIUM_NAMES):
        return True
    if any(name in text for name in NOT_CHROMIUM):
        return False
    return supports_cdp(executable)


def _probe_cache_file():
    return data_dir() / "browser-probe.json"


def _load_probe_cache():
    try:
        data = json.loads(_probe_cache_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_probe_cache(cache):
    try:
        private_dir(data_dir())
        target = _probe_cache_file()
        temporary = target.with_name(target.name + ".tmp")
        entries = dict(list(cache.items())[-PROBE_CACHE_LIMIT:])
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as file:
            json.dump(entries, file, ensure_ascii=False)
        os.replace(temporary, target)
    except OSError:
        pass  # cache é só otimização


def supports_cdp(executable, timeout=PROBE_TIMEOUT):
    """True se o executável abre o CDP; resultado guardado por (caminho real, mtime, tamanho)."""
    located = shutil.which(executable) or executable
    real = os.path.realpath(located)
    try:
        stat = os.stat(real)
    except OSError:
        return False
    if not Path(real).is_file():
        return False
    stamp = {"mtime_ns": stat.st_mtime_ns, "size": stat.st_size}
    cache = _load_probe_cache()
    entry = cache.get(real)
    if isinstance(entry, dict) and all(entry.get(k) == v for k, v in stamp.items()) and "ok" in entry:
        return bool(entry["ok"])
    try:
        probe_cdp(located, timeout)
        ok = True
    except ProbeTimeout:
        return False
    except BrowserError:
        ok = False
    cache.pop(real, None)
    cache[real] = {**stamp, "ok": ok}
    _save_probe_cache(cache)
    return ok


def _isolated_env(base):
    """Ambiente da sonda: HOME e pastas de perfil dentro do diretório temporário."""
    env = dict(os.environ)
    home = Path(base) / "home"
    home.mkdir(mode=0o700)
    if os.name == "nt":
        for key in ("APPDATA", "LOCALAPPDATA"):
            env[key] = str(home / key.lower())
    else:
        env["HOME"] = str(home)
        for key, sub in (("XDG_CONFIG_HOME", ".config"), ("XDG_CACHE_HOME", ".cache"), ("XDG_DATA_HOME", ".local/share")):
            env[key] = str(home / sub)
    env["MOZ_NO_REMOTE"] = "1"
    return env


def _exited(proc):
    """Sem colher o processo: o pid (e o grupo) seguem reservados até o kill final."""
    if os.name == "nt":
        return proc.poll() is not None
    try:
        return os.waitid(os.P_PID, proc.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT) is not None
    except ChildProcessError:
        return True


def _stop_group(proc, grace=3):
    """Encerra o processo da sonda e todos os filhos: terminate e, se preciso, kill."""
    import psutil
    try:
        children = psutil.Process(proc.pid).children(recursive=True)
    except psutil.Error:
        children = []
    if os.name == "nt":
        for item in children:
            with contextlib.suppress(psutil.Error):
                item.terminate()
        with contextlib.suppress(OSError):
            proc.terminate()
    else:
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(proc.pid, signal.SIGTERM)
    deadline = time.monotonic() + grace
    while time.monotonic() < deadline and not _exited(proc):
        time.sleep(.05)
    if os.name == "nt":
        with contextlib.suppress(OSError):
            proc.kill()
    else:
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(proc.pid, signal.SIGKILL)  # o líder ainda não foi colhido: o grupo é o nosso
    proc.wait()
    _, alive = psutil.wait_procs(children, timeout=grace)
    for item in alive:
        with contextlib.suppress(psutil.Error):
            item.kill()
    psutil.wait_procs(alive, timeout=grace)


def _remove_tree(path):
    for _ in range(10):
        shutil.rmtree(path, ignore_errors=True)
        if not os.path.exists(path):
            return
        time.sleep(.1)


def probe_cdp(executable, timeout=PROBE_TIMEOUT):
    """Sobe o executável headless num perfil temporário novo e confirma /json/version.

    Nunca usa o perfil do usuário; o processo e o diretório são removidos em qualquer caminho.
    """
    base = tempfile.mkdtemp(prefix="dracaena-probe-")
    proc = None
    try:
        profile = Path(base) / "profile"
        profile.mkdir(mode=0o700)
        options = dict(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=_isolated_env(base))
        if os.name == "nt":
            options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            options["start_new_session"] = True
        try:
            proc = subprocess.Popen([executable, "--headless=new", "--remote-debugging-port=0", "--remote-debugging-address=127.0.0.1",
                                     "--user-data-dir=" + str(profile), "--no-first-run", "--no-default-browser-check",
                                     "about:blank"], **options)
        except OSError:
            raise BrowserError("Não foi possível executar o navegador para verificar o CDP") from None
        opener = build_opener(ProxyHandler({}))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if _exited(proc):
                raise BrowserError("O navegador encerrou sem abrir o CDP")
            try:
                port = read_port(profile)
            except (OSError, BrowserError):
                time.sleep(.1)
                continue
            try:
                with opener.open(f"http://127.0.0.1:{port}/json/version", timeout=1) as response:
                    info = json.load(response)
            except (OSError, ValueError):
                time.sleep(.1)
                continue
            if isinstance(info, dict) and info.get("Browser") and info.get("webSocketDebuggerUrl"):
                return info
            raise BrowserError("O endpoint /json/version não parece de um navegador com CDP")
        raise ProbeTimeout(f"O navegador não abriu o CDP em {timeout} s")
    finally:
        if proc is not None:
            _stop_group(proc)
        _remove_tree(base)


def sandboxed(executable):
    text = str(executable).replace("\\", "/")
    return "/snap/bin/" in text or "/flatpak/exports/bin/" in text


def _unwrap_exec(args):
    """Executável real de um Exec= com env/flatpak/snap (melhor esforço)."""
    while args and Path(args[0]).name == "env":
        args = args[1:]
        while args and ("=" in args[0] or args[0].startswith("-")):
            args = args[1:]
    if not args:
        raise BrowserUnsupported("Entrada .desktop do navegador padrão sem executável: informe o executável nas configurações")
    name = Path(args[0]).name
    if name not in ("flatpak", "snap"):
        return shutil.which(args[0]) or args[0]
    rest = args[1:]
    if not rest or rest[0] != "run":
        raise BrowserUnsupported("Navegador Flatpak/Snap não reconhecido: informe o executável nas configurações")
    names = [item for item in rest[1:] if not item.startswith(("-", "%", "@@"))]
    if names:
        app = names[0]
        if name == "flatpak":
            places = [Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "flatpak/exports/bin" / app,
                      Path("/var/lib/flatpak/exports/bin") / app]
        else:
            places = [Path("/snap/bin") / app]
        for place in places:
            if place.is_file():
                return str(place)
    raise BrowserUnsupported("Navegador Flatpak/Snap sem executável exportado: informe o executável nas configurações")


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
            return _unwrap_exec(shlex.split(config["Desktop Entry"]["Exec"]))
    raise BrowserError("Entrada .desktop do navegador padrão não encontrada")


def resolve(executable="", fallback="playwright"):
    if executable:
        if is_chromium(executable):
            return executable
        raise BrowserError("Navegador configurado não é Chromium válido nem respondeu ao CDP; configuração explícita tem prioridade")
    try:
        candidate = default_browser()
    except BrowserUnsupported as exc:
        return _reserve(fallback, exc)
    except (OSError, KeyError, subprocess.SubprocessError, BrowserError):
        candidate = ""
    if candidate:
        if sandboxed(candidate):  # Flatpak/Snap: nome não basta, só a sonda decide
            if supports_cdp(candidate):
                return candidate
            return _reserve(fallback, BrowserUnsupported("Navegador padrão em Flatpak/Snap não respondeu ao CDP"))
        if is_chromium(candidate):
            return candidate
        return _reserve(fallback, BrowserError("Navegador padrão detectado não é Chromium nem respondeu ao CDP; configure um navegador compatível"))
    return _reserve(fallback, NoBrowser("Nenhum navegador Chromium configurado ou detectado"))


def _reserve(fallback, error):
    """Sem navegador utilizável (ausente ou incompatível): Chromium reserva, se ativado; senão, o erro."""
    if fallback != "playwright":
        raise error
    path = fallback_executable()
    if path:
        return path
    raise FallbackMissing(f"O Chromium reserva ainda não foi baixado (ocupa cerca de {FALLBACK_SIZE} em disco)")


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


def _fallback_module(name):
    """Importa um módulo do Playwright; a ausência dele vira erro legível, sem traceback."""
    try:
        return importlib.import_module(name)
    except ImportError:
        raise FallbackUnavailable("O Chromium reserva não está disponível neste executável. "
                                  "Informe um navegador Chromium nas configurações (BROWSER_BIN).") from None


def fallback_executable():
    """Caminho do Chromium reserva já baixado, ou None."""
    sync_playwright = _fallback_module("playwright.sync_api").sync_playwright
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
    driver = _fallback_module("playwright._impl._driver")
    compute_driver_executable, get_driver_env = driver.compute_driver_executable, driver.get_driver_env
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


def sandbox_failure(output):
    """Reconhece diagnósticos do Chromium quando userns/SUID não podem criar o sandbox."""
    text = str(output or "").lower()
    if any(marker in text for marker in _SANDBOX_MARKERS):
        return True
    return "operation not permitted" in text and any(word in text for word in ("namespace", "sandbox", "userns"))


def _resolve_launch(executable, fallback):
    """Resolve o binário e informa se veio do fallback, sem confundir navegador do sistema."""
    if executable or not fallback:
        return resolve(executable, fallback), False
    try:
        return resolve("", ""), False
    except NoBrowser:
        return resolve("", fallback), True


class _StderrTail:
    """Drena stderr sem bloquear o Chromium e conserva só os últimos bytes."""

    def __init__(self, stream, limit=16 * 1024):
        self.stream, self.limit = stream, limit
        self.data = bytearray()
        self.lock = threading.Lock()
        self.thread = threading.Thread(target=self._drain, name="dracaena-browser-stderr", daemon=True)
        self.thread.start()

    def _drain(self):
        while True:
            chunk = self.stream.read(4096)
            if not chunk:
                return
            with self.lock:
                self.data.extend(chunk)
                del self.data[:-self.limit]

    def text(self):
        self.thread.join(.2)
        with self.lock:
            return bytes(self.data).decode("utf-8", "replace")


def _launch_args(binary, profile, url, fallback_used):
    args = [binary, "--user-data-dir=" + str(profile), "--remote-debugging-port=0",
            "--remote-debugging-address=127.0.0.1", "--no-first-run", "--no-default-browser-check"]
    if fallback_used and os.environ.get(NO_SANDBOX_ENV) == "1":
        args.append("--no-sandbox")
        LOG.warning("Chromium reserva iniciado SEM SANDBOX por opt-in explícito (%s=1)", NO_SANDBOX_ENV)
    args.append(url)
    return args


def launch(executable="", fallback="", url="about:blank", timeout=15):
    import psutil
    binary, fallback_used = _resolve_launch(executable, fallback)
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
    proc = subprocess.Popen(_launch_args(binary, profile, url, fallback_used), stdin=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    errors = _StderrTail(proc.stderr)
    deadline = time.monotonic() + timeout
    try:
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                if fallback_used and sandbox_failure(errors.text()):
                    raise BrowserSandboxUnavailable(SANDBOX_ERROR)
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
        if fallback_used and sandbox_failure(errors.text()):
            raise BrowserSandboxUnavailable(SANDBOX_ERROR)
        raise BrowserError("Tempo esgotado aguardando o DevToolsActivePort")
    except BaseException:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        raise
