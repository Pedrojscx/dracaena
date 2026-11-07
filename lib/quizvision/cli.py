"""Interface de linha de comando usada pelos scripts bash.

Saída sempre em JSON (stdout) ou texto simples quando indicado; erros vão
para stderr com código de saída diferente de zero.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from . import config as configmod
from . import contract, detect, geometry, locate, replay
from .annotate import annotate
from .image import load
from .page import analyze
from .session import Session, load_state, save_state


def _out(obj) -> None:
    json.dump(obj, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")


def _read_json_arg(value: str):
    """Aceita JSON literal ou @arquivo."""
    if value.startswith("@"):
        return json.loads(Path(value[1:]).read_text(encoding="utf-8"))
    return json.loads(value)


def cmd_config(a) -> int:
    _out(configmod.load(a.default, a.user))
    return 0


def cmd_session_new(a) -> int:
    cfg = configmod.load(a.default, a.user)
    if a.override:
        cfg.update(configmod.typed({k: str(v) for k, v in _read_json_arg(a.override).items()}))
    session = Session.new(cfg, a.run_dir, dry_run=a.dry_run, replay=a.replay)
    save_state(session, a.state)
    return 0


def cmd_step(a) -> int:
    session = load_state(a.state)
    event = _read_json_arg(a.event)
    directive = session.step(event)
    save_state(session, a.state)
    _out(directive)
    return 0


def cmd_validate(a) -> int:
    raw = Path(a.file).read_text(encoding="utf-8") if a.file != "-" else sys.stdin.read()
    try:
        answer = contract.parse(raw)
    except contract.ContractError as exc:
        print(f"resposta inválida: {exc}", file=sys.stderr)
        return 2
    if a.readable:
        print(contract.readable(answer))
    else:
        _out(answer)
    return 0


def _window(a) -> geometry.WindowInfo:
    active = _read_json_arg(a.active)
    monitors = _read_json_arg(a.monitors)
    return geometry.window_info(active, monitors)


def cmd_window(a) -> int:
    """Janela ativa: {ok, problems, browser, window{..., geometry, scale}}."""
    try:
        win = _window(a)
    except geometry.GeometryError as exc:
        _out({"ok": False, "browser": False, "problems": [str(exc)]})
        return 0
    try:
        browser = bool(re.search(a.regex, win.cls))
    except re.error:
        browser = False
    problems = geometry.window_problems(win, a.regex)
    _out({"ok": not problems, "browser": browser, "problems": problems, "window": win.to_dict()})
    return 0


def cmd_detect(a) -> int:
    """Detecção sobre uma captura da janela inteira (quiz-ask, quiz-doctor)."""
    cfg = configmod.load(a.default, a.user) if a.default else {}
    det = detect.detect(a.image, a.scale, cfg)
    result = det.to_dict()
    arrow = None
    if a.arrow and det.panel is not None:
        found, why = detect.find_arrow(det)
        result["arrow_reason"] = why
        if found is not None:
            arrow = found
            result["arrow"] = {"method": found.method, "point": [round(found.point[0]), round(found.point[1])],
                               "box": [found.box.x, found.box.y, found.box.w, found.box.h]}
            if a.origin:
                ox, oy = (float(v) for v in a.origin.split(","))
                frame = geometry.Frame(ox, oy, a.scale)
                result["arrow"]["global"] = list(frame.to_global(*found.point))
    if a.annotate:
        marks = [{"kind": "rect", "x": det.content.x, "y": det.content.y, "w": det.content.w,
                  "h": det.content.h, "label": "área de conteúdo", "color": "#888888"}]
        if det.module_right is not None:
            marks.append({"kind": "rect", "x": det.content.x, "y": det.content.y,
                          "w": det.module_right - det.content.x, "h": det.content.h,
                          "label": "lista de módulos (ignorada)", "color": "#c08000"})
        if det.panel is not None:
            marks.append({"kind": "rect", "x": det.panel.x, "y": det.panel.y, "w": det.panel.w,
                          "h": det.panel.h, "label": "painel do quiz", "color": "#0a6ebd"})
        if arrow is not None:
            marks.append({"kind": "click", "x": arrow.point[0], "y": arrow.point[1],
                          "label": f"seta de avançar ({arrow.method})"})
        annotate(a.image, a.annotate, marks, a.scale)
        result["annotated"] = a.annotate
    _out(result)
    return 0


def cmd_analyze(a) -> int:
    page = analyze(a.image, a.scale, use_cache=not a.no_cache)
    img = load(a.image)
    data = {"lines": [ln.to_dict() | {"button": ln.button} for ln in page.lines],
            "graphics": [g.to_dict() for g in page.graphics],
            "signature": locate.question_signature(page, img),
            "options": [{"text": o.text, "checked": o.checked} for o in locate.options(page)]}
    _out(data)
    return 0


def cmd_replay(a) -> int:
    try:
        if a.action == "init":
            replay.init(a.scenario, a.fixtures, a.state)
            return 0
        world = replay.World(a.state)
        if a.action == "capture":
            _out(world.capture(a.out))
        elif a.action == "input":
            _out(world.input(_read_json_arg(a.data)))
        elif a.action == "claude":
            sys.stdout.write(world.claude())
        elif a.action == "point":
            x, y = world.point()
            print(f"{x},{y} 1x1")
        elif a.action == "check":
            problems = replay.check(a.state, _read_json_arg(a.data), a.run_dir)
            for p in problems:
                print(f"FALHA: {p}")
            return 1 if problems else 0
    except replay.ReplayError as exc:
        print(f"replay: {exc}", file=sys.stderr)
        return 3
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="quizvision")
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("config", help="configuração efetiva em JSON")
    c.add_argument("--default", required=True)
    c.add_argument("--user")
    c.set_defaults(func=cmd_config)

    c = sub.add_parser("session-new", help="cria o estado de uma execução do loop")
    c.add_argument("--default", required=True)
    c.add_argument("--user")
    c.add_argument("--override", help="JSON com chaves de configuração a sobrepor")
    c.add_argument("--run-dir", required=True)
    c.add_argument("--state", required=True)
    c.add_argument("--dry-run", action="store_true")
    c.add_argument("--replay", action="store_true")
    c.set_defaults(func=cmd_session_new)

    c = sub.add_parser("step", help="processa um evento e imprime a próxima diretiva")
    c.add_argument("--state", required=True)
    c.add_argument("--event", required=True, help="JSON ou @arquivo")
    c.set_defaults(func=cmd_step)

    c = sub.add_parser("validate", help="valida a resposta do Claude")
    c.add_argument("file", help="arquivo ou - para stdin")
    c.add_argument("--readable", action="store_true", help="imprime o texto legível")
    c.set_defaults(func=cmd_validate)

    c = sub.add_parser("window", help="janela ativa: navegador? monitor ligado? geometria")
    c.add_argument("--active", required=True)
    c.add_argument("--monitors", required=True)
    c.add_argument("--regex", default="^vivaldi")
    c.set_defaults(func=cmd_window)

    c = sub.add_parser("detect", help="detecta área de conteúdo, painel e seta numa captura da janela")
    c.add_argument("--image", required=True)
    c.add_argument("--scale", type=float, default=1.0)
    c.add_argument("--arrow", action="store_true", help="procura também a seta de avançar")
    c.add_argument("--origin", help="X,Y global da janela (para a seta em coordenadas de tela)")
    c.add_argument("--annotate", help="grava imagem anotada com o que foi detectado")
    c.add_argument("--default", help="config padrão (para CHROME_TOP_PX/CHROME_LEFT_PX)")
    c.add_argument("--user")
    c.set_defaults(func=cmd_detect)

    c = sub.add_parser("analyze", help="depuração: OCR, gráficos e alternativas")
    c.add_argument("image")
    c.add_argument("--scale", type=float, default=1.0)
    c.add_argument("--no-cache", action="store_true")
    c.set_defaults(func=cmd_analyze)

    c = sub.add_parser("replay", help="simulador do modo --replay")
    c.add_argument("action", choices=["init", "capture", "input", "claude", "point", "check"])
    c.add_argument("--state", required=True)
    c.add_argument("--scenario")
    c.add_argument("--fixtures")
    c.add_argument("--out")
    c.add_argument("--data")
    c.add_argument("--run-dir")
    c.set_defaults(func=cmd_replay)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (configmod.ConfigError, geometry.GeometryError, ValueError, OSError, RuntimeError) as exc:
        print(f"quizvision: {exc}", file=sys.stderr)
        return 1
