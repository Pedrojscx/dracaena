"""Linha de comando do Dracaena."""
import argparse
import json
import signal
import sys
from .platform.ipc import request

ALIASES = {"loop": "toggle", "probe": "probe.start"}
__version__ = "0.1.0"  # usado só quando o pacote não está instalado; manter igual ao pyproject.toml


def package_version():
    """Versão do pacote instalado; sem instalação, cai para __version__."""
    from importlib.metadata import PackageNotFoundError, version
    try:
        return version("dracaena")
    except PackageNotFoundError:
        return __version__


def friendly(exc):
    """Mensagem em português para falhas de conexão com o daemon."""
    if isinstance(exc, (FileNotFoundError, ConnectionRefusedError)):
        return "O Dracaena não está em execução. Inicie o aplicativo e tente de novo."
    if isinstance(exc, PermissionError):
        return str(exc) if exc.args and isinstance(exc.args[0], str) else "Sem permissão para acessar o Dracaena."
    if isinstance(exc, TimeoutError):
        return "O Dracaena não respondeu a tempo."
    return f"Falha ao falar com o Dracaena: {exc}"


def install_browser(assume_yes, ask=input, interactive=None):
    """Baixa o Chromium reserva com confirmação explícita; devolve o código de saída."""
    from .platform import browser, config

    def say(ok, message, **extra):
        print(json.dumps({"ok": ok, ("message" if ok else "error"): message, **extra}, ensure_ascii=False))
        return 0 if ok else 1

    try:
        cfg = config.load()
        found = browser.resolve(cfg.get("BROWSER_BIN", ""), "")
        return say(True, f"Já existe um navegador configurado ou detectado ({found}); nada a baixar.")
    except browser.NoBrowser:
        pass
    except (browser.BrowserError, ValueError, OSError) as exc:
        return say(False, str(exc))  # navegador explícito/detectado tem prioridade: não baixa
    if cfg.get("BROWSER_FALLBACK") != "playwright":
        return say(False, "O navegador reserva está desativado nas configurações (BROWSER_FALLBACK).")
    try:
        existing = browser.fallback_executable()
        if existing:
            return say(True, f"O Chromium reserva já está instalado ({existing}).")
        interactive = sys.stdin.isatty() if interactive is None else interactive
        if not assume_yes:
            if not interactive:
                return say(False, "É preciso confirmar o download: rode em um terminal ou use --yes.")
            answer = ask(f"Nenhum navegador foi encontrado. Baixar o Chromium (cerca de {browser.FALLBACK_SIZE} em disco) "
                         f"para {browser.fallback_dir()}? [s/N] ").strip().lower()
            if answer not in ("s", "sim", "y", "yes"):
                return say(False, "Download cancelado.")
        print("Baixando o Chromium; isso pode levar alguns minutos...", file=sys.stderr)
        return say(True, "Chromium reserva instalado.", path=browser.install_fallback())
    except browser.BrowserError as exc:
        return say(False, str(exc))


def main(argv=None):
    parser = argparse.ArgumentParser(prog="dracaena", description="Controle do Dracaena.")
    parser.add_argument("-V", "--version", action="version", version=f"dracaena {package_version()}",
                        help="mostra a versão e sai")
    sub = parser.add_subparsers(dest="command", required=True, metavar="comando")
    daemon = sub.add_parser("daemon", help="inicia o servidor local")
    daemon.add_argument("--simulate", action="store_true", help="usa o simulador no lugar do núcleo")
    for name in ("loop", "ask", "toggle", "stop", "status", "doctor", "probe", "once"):
        sub.add_parser(name)
    install = sub.add_parser("install-browser", help="baixa o Chromium reserva (só se não houver navegador)")
    install.add_argument("--yes", action="store_true", help="confirma o download sem perguntar")
    args = parser.parse_args(argv)
    if args.command == "daemon":
        from .daemon import Daemon, Simulator
        if not args.simulate:
            print("Dracaena: a integração com o núcleo ainda não está disponível; use --simulate", file=sys.stderr)
            return 2
        if hasattr(signal, "SIGTERM"):  # encerra limpo (remove o socket) em vez de morrer abruptamente
            signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
        try:
            Daemon(Simulator(), simulate=True).run()
        except KeyboardInterrupt:
            return 0
        except (OSError, RuntimeError) as exc:
            print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
            return 1
        return 0
    if args.command == "install-browser":
        return install_browser(args.yes)
    if args.command == "doctor":
        from .platform.doctor import run
        result = run()
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result["ok"] else 1
    try:
        result = request(ALIASES.get(args.command, args.command))
    except OSError as exc:
        print(json.dumps({"ok": False, "error": friendly(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result and result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
