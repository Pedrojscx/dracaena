"""Linha de comando do Dracaena."""
import argparse
import json
import signal
from .platform.ipc import request

ALIASES = {"loop": "toggle", "probe": "probe.start"}


def friendly(exc):
    """Mensagem em português para falhas de conexão com o daemon."""
    if isinstance(exc, (FileNotFoundError, ConnectionRefusedError)):
        return "O Dracaena não está em execução. Inicie o aplicativo e tente de novo."
    if isinstance(exc, PermissionError):
        return str(exc) if exc.args and isinstance(exc.args[0], str) else "Sem permissão para acessar o Dracaena."
    if isinstance(exc, TimeoutError):
        return "O Dracaena não respondeu a tempo."
    return f"Falha ao falar com o Dracaena: {exc}"


def main(argv=None):
    parser = argparse.ArgumentParser(prog="dracaena", description="Controle do Dracaena.")
    sub = parser.add_subparsers(dest="command", required=True, metavar="comando")
    daemon = sub.add_parser("daemon", help="inicia o servidor local")
    daemon.add_argument("--simulate", action="store_true", help="usa o simulador no lugar do núcleo")
    for name in ("loop", "ask", "toggle", "stop", "status", "doctor", "probe", "once"):
        sub.add_parser(name)
    args = parser.parse_args(argv)
    if args.command == "daemon":
        from .daemon import Daemon, Simulator
        if not args.simulate:
            parser.error("a integração com o núcleo ainda não está disponível; use --simulate")
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
