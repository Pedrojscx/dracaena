"""Máquina de estados do quiz-loop.

O bash chama `quizvision step` a cada evento (captura feita, resposta do
Claude, ações executadas...). Esta classe lê o estado salvo, decide o
próximo passo e devolve uma *diretiva* JSON para o bash executar:

    capture     capturar o painel (estabilizado) em `out`, após `delay_ms`
    input       executar `actions` (click, drag, scroll, click_next)
    ask_claude  consultar o Claude com `images` e o prompt `prompt`
    end         encerrar o loop com `reason` e `summary`

Toda diretiva traz `status` (texto da notificação persistente). O estado é
um dicionário JSON (persistido entre chamadas e entre pausas/retomadas).
"""

from __future__ import annotations

import json
import os
import time
import traceback
from datetime import datetime
from pathlib import Path

from . import annotate as annotmod
from . import contract, detect, locate
from .geometry import Frame
from .image import Image, hamming_hex, load
from .ocr import Box, ocr_char
from .page import Page, analyze
from .text import best_match
from .widgets import image_change

STATE_VERSION = 2

# Capturas de conferência logo após um clique: mesmo enquadramento do painel
# (as comparações antes/depois precisam do mesmo recorte e não há rolagem).
REUSE_EXPECTS = {"choice_verify", "dd_opened", "dd_picked", "match_verify"}
# Capturas em que a tela final / botão final é verificado na área de conteúdo.
FINAL_EXPECTS = {"identify", "manual", "next", "submit", "feedback"}


def _box(b: Box) -> list[int]:
    return [b.x, b.y, b.w, b.h]


def _unbox(v: list[int]) -> Box:
    return Box(*v)


class Pause(Exception):
    """Pausa em modo manual: o loop espera a questão mudar sozinho."""


class Session:
    def __init__(self, state: dict):
        self.st = state
        self._pages: dict[str, Page] = {}
        self._images: dict[str, Image] = {}

    # ------------------------------------------------------------ criação

    @classmethod
    def new(cls, cfg: dict, run_dir: str, dry_run: bool = False, replay: bool = False) -> "Session":
        st = {
            "version": STATE_VERSION, "cfg": cfg, "run_dir": run_dir, "dry_run": dry_run, "replay": replay,
            "t0": time.time(), "clock": 0, "seq": 0, "n": 0, "q": None, "prev_sig": None, "wait_since": None,
            "expect": "start", "status": "iniciando", "frames": {}, "last_cap": None, "resume": False,
            "dets": {}, "crops": {}, "panel_misses": 0, "manual_next": None, "cap_expect": None,
            "last_win": None,
            "stats": {"auto": 0, "retry": 0, "manual": 0, "refused": 0, "failed": 0, "questions": 0},
            "ended": None,
        }
        Path(run_dir).mkdir(parents=True, exist_ok=True)
        return cls(st)

    @property
    def cfg(self) -> dict:
        return self.st["cfg"]

    @property
    def q(self) -> dict:
        return self.st["q"]

    # ------------------------------------------------------------ utilidades

    def now_ms(self) -> float:
        return self.st["clock"] if self.st["replay"] else time.time() * 1000

    def _advance_clock(self, ms: float) -> None:
        self.st["clock"] += ms

    def log(self, msg: str) -> None:
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"{stamp} {msg}\n"
        target = Path(self.q["dir"]) / "log.txt" if self.q else Path(self.st["run_dir"]) / "run.log"
        with open(target, "a", encoding="utf-8") as fh:
            fh.write(line)
        if self.q:
            with open(Path(self.st["run_dir"]) / "run.log", "a", encoding="utf-8") as fh:
                fh.write(f"{stamp} [Q{self.q['n']}] {msg}\n")

    def page(self, path: str) -> Page:
        if path not in self._pages:
            scale = self.st["frames"].get(path, [0, 0, 1.0])[2]
            self._pages[path] = analyze(path, scale)
        return self._pages[path]

    def image(self, path: str) -> Image:
        if path not in self._images:
            self._images[path] = load(path)
        return self._images[path]

    def frame(self, path: str) -> Frame:
        ox, oy, s = self.st["frames"][path]
        return Frame(ox, oy, s)

    def _cap_path(self, upcoming: bool = False) -> str:
        """Capturas de identificação vão para a pasta da próxima questão
        (é para ela que servem); as demais, para a da questão atual."""
        self.st["seq"] += 1
        n = self.st["n"] + (1 if upcoming or not self.q else 0)
        base = Path(self.st["run_dir"]) / f"q{n:03d}"
        base.mkdir(parents=True, exist_ok=True)
        return str(base / f"cap-{self.st['seq']:04d}.png")

    def status(self, text: str) -> None:
        self.st["status"] = text

    def qlabel(self) -> str:
        return f"Questão {self.q['n']}" if self.q else "quiz-loop"

    # ------------------------------------------------------------ diretivas

    def _directive(self, d: dict) -> dict:
        d["status"] = self.st["status"]
        if self.q and self.q.get("answer_text"):
            d["answer"] = self.q["answer_text"]
        return d

    def capture(self, expect: str, delay_ms: int = 0, stable: bool = True, manual: bool = False) -> dict:
        self.st["expect"] = expect
        self._advance_clock(delay_ms)
        return self._directive({"do": "capture", "out": self._cap_path(expect in ("identify", "manual")),
                                "delay_ms": delay_ms,
                                "stable": stable, "manual": manual})

    def act(self, actions: list[dict], expect: str, cap: str | None = None) -> dict:
        self.st["expect"] = expect
        for a in actions:
            desc = {k: v for k, v in a.items() if k not in ("ix", "iy", "ix2", "iy2")}
            self.log(f"ação {'(dry-run) ' if self.st['dry_run'] else ''}{json.dumps(desc, ensure_ascii=False)}")
            if cap and self.st["dry_run"] and a["type"] in ("click", "drag"):
                self._mark(cap, a)
        d = {"do": "input", "actions": actions, "dry_run": self.st["dry_run"]}
        win = self.st.get("last_win")
        if win and win in self.st["frames"]:
            # Janela no momento da captura: o bash não clica se ela mudou.
            ox, oy, sc = self.st["frames"][win]
            img = self.image(win)
            d["window"] = {"at": [round(ox), round(oy)], "size": [round(img.width / sc), round(img.height / sc)]}
        return self._directive(d)

    def click(self, cap: str, point: tuple[float, float], label: str) -> dict:
        gx, gy = self.frame(cap).to_global(*point)
        return {"type": "click", "x": gx, "y": gy, "ix": round(point[0]), "iy": round(point[1]), "label": label}

    def drag(self, cap: str, a: tuple[float, float], b: tuple[float, float], label: str) -> dict:
        f = self.frame(cap)
        x, y = f.to_global(*a)
        x2, y2 = f.to_global(*b)
        return {"type": "drag", "x": x, "y": y, "x2": x2, "y2": y2, "ix": round(a[0]), "iy": round(a[1]),
                "ix2": round(b[0]), "iy2": round(b[1]), "label": label,
                "steps": self.cfg.get("DRAG_STEPS", 12), "step_ms": self.cfg.get("DRAG_STEP_MS", 15)}

    def _mark(self, cap: str, a: dict) -> None:
        """Marca de dry-run em coordenadas da captura da janela inteira."""
        crop = self.st["crops"].get(cap)
        win, dx, dy = (crop["win"], crop["box"][0], crop["box"][1]) if crop else (cap, 0, 0)
        marks = self.q.setdefault("marks", {}).setdefault(win, [])
        kind = "click" if a["type"] == "click_next" else a["type"]
        m = {"kind": kind, "x": a["ix"] + dx, "y": a["iy"] + dy, "label": a.get("label", "")}
        if kind == "rect":
            m.update(w=a["w"], h=a["h"], color=a.get("color", "#0a8a3a"))
        if a["type"] == "drag":
            m.update(x2=a["ix2"] + dx, y2=a["iy2"] + dy)
        marks.append(m)

    def ask(self, retry: bool = False) -> dict:
        q = self.q
        q["claude_round"] = 0 if q.get("claude_round") is None else q["claude_round"]
        self.st["expect"] = "claude"
        self.status(f"{self.qlabel()}: {'retry' if retry else 'consultando'}")
        d = {"do": "ask_claude", "images": list(q["claude_images"]), "prompt": "retry" if retry else "answer",
             "stitched": str(Path(q["dir"]) / f"claude-{len(q['claude_images'])}.png")}
        if retry:
            d["previous"] = json.dumps(q["answer"], ensure_ascii=False)
        q["asking_retry"] = retry
        return self._directive(d)

    def end(self, reason: str, message: str) -> dict:
        self._finish_marks()
        st = self.st
        stats = st["stats"]
        elapsed = time.time() - st["t0"]
        summary = dict(stats, elapsed_s=round(elapsed, 1))
        st["ended"] = reason
        st["expect"] = "ended"
        self.status(f"fim: {message}")
        text = (f"{message}\nAutomáticas: {stats['auto']} | com retry: {stats['retry']} | "
                f"esperaram por você: {stats['manual']} | recusas: {stats['refused']} | "
                f"erradas após retry: {stats['failed']} | tempo: {elapsed / 60:.1f} min")
        self.log(f"fim ({reason}): {text}")
        return self._directive({"do": "end", "reason": reason, "summary": summary, "message": text})

    # ------------------------------------------------------------ entrada

    def step(self, event: dict) -> dict:
        etype = event.get("type")
        if etype == "captured":
            self.st["frames"][event["image"]] = [event["origin"][0], event["origin"][1], float(event["scale"])]
            for key in ("frames", "dets", "crops"):
                if len(self.st[key]) > 400:
                    for k in list(self.st[key])[:200]:
                        del self.st[key][k]
        try:
            return self._dispatch(event)
        except Pause as p:
            return self._pause(str(p))
        except Exception as exc:  # noqa: BLE001 - qualquer erro vira pausa explicada
            self.log("erro interno:\n" + traceback.format_exc())
            if self.q is None:
                return self.end("error", f"erro interno: {exc}")
            return self._pause(f"erro interno: {exc}")

    def _dispatch(self, event: dict) -> dict:
        etype = event.get("type")
        expect = self.st["expect"]
        if etype == "start":
            return self.capture("identify")
        if etype == "resume":
            self.st["resume"] = True
            self.status(f"{self.qlabel()}: retomando")
            return self.capture("identify")
        if etype == "capture_skipped":
            # Janela não ativa durante espera manual: só tenta de novo.
            return self.capture(expect, delay_ms=1500, manual=True)
        if etype == "captured":
            handler = getattr(self, f"on_{expect}", None)
            if handler is None:
                raise RuntimeError(f"captura inesperada no estado {expect}")
            panel = self._prepare(event["image"], expect)
            if panel is None:
                if expect in FINAL_EXPECTS:
                    final = self._check_final(event["image"])
                    if final:
                        return final
                return self._panel_missing(expect)
            self.st["panel_misses"] = 0
            self.st["cap_expect"] = expect
            return handler(panel)
        if etype == "stale":
            # A janela mudou entre a captura e o clique: captura de novo.
            self.log("janela mudou antes do clique; capturando de novo")
            return self.capture(self.st.get("cap_expect") or "identify")
        if etype == "point":
            return self.on_point(event)
        if etype == "point_cancel":
            raise Pause("seta de avançar não definida; avance manualmente")
        if etype == "done":
            handler = getattr(self, f"done_{expect}", None)
            if handler is None:
                raise RuntimeError(f"'done' inesperado no estado {expect}")
            return handler()
        if etype in ("claude", "claude_error"):
            return self.on_claude_result(event)
        raise RuntimeError(f"evento desconhecido: {etype}")

    # ------------------------------------------------------------ identificação

    def _prepare(self, win: str, expect: str) -> str | None:
        """Detecta a página na captura da janela e devolve o recorte do painel."""
        st = self.st
        ox, oy, sc = st["frames"][win]
        img = self.image(win)
        q = self.q
        reuse = None
        if expect in REUSE_EXPECTS and q and q.get("panel_box") and q.get("panel_wsize") == [img.width, img.height]:
            reuse = _unbox(q["panel_box"])
        det = detect.detect(win, sc, self.cfg, reuse=reuse)
        st["dets"][win] = det.to_dict()
        st["last_win"] = win
        if det.panel is None:
            self.log(f"painel não encontrado: {det.reason}")
            return None
        panel = det.panel_path
        st["frames"][panel] = [ox + det.panel.x / sc, oy + det.panel.y / sc, sc]
        st["crops"][panel] = {"win": win, "box": _box(det.panel)}
        st["last_cap"] = panel
        if reuse is None:
            st["last_panel"] = {"box": _box(det.panel), "wsize": [img.width, img.height]}
            if q:
                q["panel_box"], q["panel_wsize"] = _box(det.panel), [img.width, img.height]
            if expect == "identify":
                self.log(f"painel {_box(det.panel)} na janela {img.width}x{img.height}; âncoras: "
                         f"{', '.join(det.anchors or [])}")
        return panel

    def _panel_missing(self, expect: str) -> dict:
        st = self.st
        if expect == "manual":
            return self.capture("manual", delay_ms=1500, manual=True)
        st["panel_misses"] += 1
        if st["panel_misses"] < 2:
            return self.capture(expect, delay_ms=600)
        st["panel_misses"] = 0
        reason = "não encontrei o painel do quiz na janela; role até o topo da questão"
        if self.q is None:
            self.status(f"pausado: {reason}")
            return self.capture("identify", delay_ms=2000, manual=True)
        raise Pause(reason)

    def win_of(self, cap: str) -> str:
        crop = self.st["crops"].get(cap)
        return crop["win"] if crop else cap

    def _check_final(self, win: str, panel: str | None = None, allow_question: bool = False) -> dict | None:
        """Encerra em tela final/resultado ou diante do botão que envia a
        avaliação inteira, lendo a área de conteúdo da janela (sem a lista de
        módulos). Com `allow_question`, uma questão ainda não respondida na
        mesma tela é respondida primeiro (o botão final nunca é clicado; o
        loop encerra na hora do envio)."""
        dd = self.st["dets"].get(win)
        if not dd:
            return None
        det = detect.Detection.from_dict(dd)
        lines = detect.content_lines_outside_modules(det)
        if not lines:
            return None
        view = Page(det.content.w, det.content.h, det.scale, lines, [])
        phrase = locate.end_screen(view, self.cfg["END_WORDS"])
        if phrase:
            return self.end("end_screen", f"tela final detectada ('{phrase}')")
        finals = locate.final_buttons(view, self.cfg["SUBMIT_WORDS_BLOCKLIST"])
        if finals:
            has_question = False
            if panel:
                ppage = self.page(panel)
                has_question = bool(locate.options(ppage)) or \
                    locate.question_signature(ppage, Image(0, 0, bytearray()))["number"] is not None
            if allow_question and has_question:
                self.log(f"botão final '{finals[0].text}' visível; respondendo a questão antes de encerrar")
                return None
            return self.end("final_button", f"avaliação pronta para envio manual ('{finals[0].text}' não é clicado)")
        return None

    def on_identify(self, cap: str) -> dict:
        page = self.page(cap)
        final = self._check_final(self.win_of(cap), cap, allow_question=True)
        if final:
            return final
        sig = locate.question_signature(page, self.image(cap))
        st = self.st
        if st["resume"] and self.q and locate.same_question(sig, self.q["sig"]):
            st["resume"] = False
            self.log("retomando a questão atual")
            if self.q.get("phase") in ("feedback", "next"):
                return self.go_next()
            if self.q.get("answer"):
                self.status(f"{self.qlabel()}: marcando")
                self._reset_progress()
                return self.on_answer(cap)
            self.q["claude_images"] = [cap]
            return self.ask()
        st["resume"] = False
        if st["prev_sig"] and locate.same_question(sig, st["prev_sig"]):
            if st["wait_since"] is None:
                st["wait_since"] = self.now_ms()
            if not st["dry_run"] and self.now_ms() - st["wait_since"] > self.cfg["ADVANCE_TIMEOUT"] * 1000:
                return self.end("no_change", "a página não mudou após avançar")
            if self.st["dry_run"]:
                return self.capture("identify", delay_ms=1000, manual=True)
            return self.capture("identify", delay_ms=400)
        return self._new_question(cap, sig)

    def _new_question(self, cap: str, sig: dict) -> dict:
        st = self.st
        st["wait_since"] = None
        if st["n"] >= self.cfg["MAX_QUESTIONS"]:
            return self.end("max_questions", f"limite de {self.cfg['MAX_QUESTIONS']} questões atingido")
        self._finish_marks()
        st["n"] += 1
        st["stats"]["questions"] += 1
        qdir = Path(st["run_dir"]) / f"q{st['n']:03d}"
        qdir.mkdir(parents=True, exist_ok=True)
        st["q"] = {"n": st["n"], "dir": str(qdir), "sig": sig, "answer": None, "answer_text": "",
                   "claude_images": [], "claude_round": 0, "scrolls": 0, "retried": False, "manual": False,
                   "phase": "ask", "view": 0, "search": None, "progress": {}, "marks": {}}
        if st.get("last_panel"):
            self.q["panel_box"], self.q["panel_wsize"] = st["last_panel"]["box"], st["last_panel"]["wsize"]
        self.q["claude_images"] = [cap]
        self.log(f"nova questão: número={sig['number']} título={sig['title']!r} hash={sig['hash']}")
        return self.ask()

    # ------------------------------------------------------------ Claude

    def on_claude_result(self, event: dict) -> dict:
        q = self.q
        q["claude_round"] += 1
        retry = q.get("asking_retry", False)
        if event["type"] == "claude_error":
            self.log(f"Claude falhou ({event.get('elapsed', 0):.1f}s): {event.get('reason')}")
            err = event.get("reason", "erro")
            answer = None
        else:
            raw = event.get("text", "")
            self.log(f"Claude respondeu em {event.get('elapsed', 0):.1f}s: {raw.strip()[:2000]}")
            try:
                answer = contract.parse(raw)
                err = ""
            except contract.ContractError as exc:
                answer, err = None, str(exc)
        if answer is None:
            if q["claude_round"] < 2:
                self.log(f"resposta inválida ({err}); repetindo a chamada")
                return self.ask(retry=retry)
            raise Pause(f"resposta inválida do Claude: {err}")
        q["claude_round"] = 0
        if answer["type"] == "INCOMPLETE":
            if q["scrolls"] >= self.cfg["MAX_SCROLLS"]:
                raise Pause("questão incompleta mesmo após rolar")
            q["phase"] = "incomplete"
            self.status(f"{self.qlabel()}: rolando (questão incompleta)")
            return self.scroll(-1, "incomplete")
        if retry:
            q["previous_answer"] = q["answer"]
        q["answer"] = answer
        q["answer_text"] = contract.readable(answer)
        q["phase"] = "answer"
        q["search"] = None
        self._reset_progress()
        self.log(f"resposta: {json.dumps(answer, ensure_ascii=False)}")
        self.status(f"{self.qlabel()}: marcando")
        if retry:
            fb_cap = q.get("feedback_cap")
            if fb_cap:
                btn = locate.locate_button(self.page(fb_cap), self.cfg["RESET_WORDS"])
                if btn.ok:
                    self.log(f"usando botão '{btn.text}' antes de refazer")
                    return self.act([self.click(fb_cap, btn.point, btn.text)], "reset", fb_cap)
        return self.capture("answer")

    def done_reset(self) -> dict:
        return self.capture("answer", delay_ms=600)

    def on_incomplete(self, cap: str) -> dict:
        q = self.q
        prev = q["claude_images"][-1]
        if self._unchanged(prev, cap):
            raise Pause("questão incompleta e não há mais o que rolar")
        q["scrolls"] += 1
        q["view"] += 1
        q["claude_images"].append(cap)
        return self.ask()

    # ------------------------------------------------------------ rolagem e busca

    def scroll(self, direction: int, expect: str) -> dict:
        """direction: -1 para baixo, +1 para cima (sinal do ydotool invertido)."""
        cap = self.st["last_cap"]
        img = self.image(cap)
        cx, cy = self.frame(cap).to_global(img.width / 2, img.height / 2)
        step = self.cfg.get("SCROLL_STEP", -3)
        amount = step if direction < 0 else -step
        self.st["after_scroll"] = expect
        self.log(f"rolagem {'para baixo' if direction < 0 else 'para cima'} ({amount})")
        return self.act([{"type": "scroll", "x": cx, "y": cy, "amount": amount}], "scrolled")

    def done_scrolled(self) -> dict:
        if self.q:
            self.q["view"] += 1
        return self.capture(self.st["after_scroll"], delay_ms=300)

    def _unchanged(self, a: str, b: str) -> bool:
        """Mesma tela? Compara as capturas da janela inteira (os recortes do
        painel podem ter tamanhos diferentes entre detecções)."""
        ia, ib = self.image(self.win_of(a)), self.image(self.win_of(b))
        if ia.width != ib.width or ia.height != ib.height:
            return False
        return hamming_hex(ia.dhash(), ib.dhash()) <= 2 and image_change(ia, ib) < 0.002

    def search(self, reason: str, expect: str, cap: str) -> dict:
        """Rola para achar o que falta: primeiro para baixo, depois para cima."""
        q = self.q
        s = q.get("search")
        if s is None:
            s = q["search"] = {"dir": -1, "count": 0, "last": cap, "flipped": False, "reason": reason}
        else:
            if s.get("last") and s["last"] != cap and self._unchanged(s["last"], cap):
                # Chegou ao fim nesta direção.
                if s["flipped"]:
                    raise Pause(reason)
                s.update(dir=1, count=0, flipped=True)
            s["last"] = cap
        if s["count"] >= self.cfg["MAX_SCROLLS"]:
            if s["flipped"]:
                raise Pause(reason)
            s.update(dir=1, count=0, flipped=True)
        if self.st["dry_run"]:
            raise Pause(f"{reason} (dry-run não rola a página)")
        s["count"] += 1
        q["scrolls"] += 1
        return self.scroll(s["dir"], expect)

    # ------------------------------------------------------------ resposta

    def _reset_progress(self) -> None:
        self.q["progress"] = {"done": [], "item": 0, "pair": 0, "last_y": -1, "last_view": -1,
                              "dd": None, "dd_retry": False, "verify": None, "alt_tried": False, "mode": None}

    def on_answer(self, cap: str) -> dict:
        kind = self.q["answer"]["type"]
        if kind in ("SINGLE", "MULTI"):
            return self._answer_choice(cap)
        if kind == "DROPDOWN":
            return self._answer_dropdown(cap)
        return self._answer_match(cap)

    # ---- alternativas

    def _answer_choice(self, cap: str) -> dict:
        q, cfg = self.q, self.cfg
        ans = q["answer"]
        page = self.page(cap)
        opts = locate.options(page) or locate.text_options(page)
        thr = cfg["MATCH_THRESHOLD"]
        mapping = locate.map_answers(ans["answers"], opts, thr)
        if mapping["ambiguous"]:
            raise Pause(f"alternativa ambígua: {mapping['ambiguous'][0]!r}")
        prog = q["progress"]
        offset = self.frame(cap).px(cfg["CLICK_OFFSET_X"])
        actions, verify = [], []
        wanted = set(mapping["found"].values())
        for idx, opt in enumerate(opts):
            desired = idx in wanted
            if ans["type"] == "SINGLE" and not desired:
                continue
            if opt.checked is None:
                if ans["type"] == "MULTI":
                    raise Pause(f"estado do checkbox desconhecido em {opt.text[:40]!r}")
                if not desired:
                    continue
            if opt.checked == desired:
                continue
            point = locate.click_point_for(opt, offset)
            label = ("marcar " if desired else "desmarcar ") + opt.text[:40]
            actions.append(self.click(cap, point, label))
            verify.append({"text": opt.text, "desired": desired})
        for answer_text in mapping["found"]:
            if answer_text not in prog["done"]:
                prog["done"].append(answer_text)
        prog["missing"] = mapping["missing"]
        if actions:
            prog["verify"] = verify
            return self.act(actions, "choice_clicked", cap)
        return self._choice_next(cap)

    def done_choice_clicked(self) -> dict:
        if self.st["dry_run"]:
            return self._choice_next(self.st["last_cap"])
        return self.capture("choice_verify", delay_ms=250)

    def on_choice_verify(self, cap: str) -> dict:
        opts = locate.options(self.page(cap))
        for item in self.q["progress"]["verify"] or []:
            res = best_match(item["text"], [o.text for o in opts], self.cfg["MATCH_THRESHOLD"])
            if not res.ok:
                raise Pause(f"alternativa sumiu após o clique: {item['text'][:40]!r}")
            if opts[res.index].checked is None:
                self.log(f"estado não verificável em {item['text'][:40]!r}; seguindo")
                continue
            if opts[res.index].checked is not item["desired"]:
                raise Pause(f"marcação não confirmada: {item['text'][:40]!r}")
        self.q["progress"]["verify"] = None
        return self._choice_next(cap)

    def _choice_next(self, cap: str) -> dict:
        prog, ans = self.q["progress"], self.q["answer"]
        missing = [a for a in ans["answers"] if a not in prog["done"]]
        if missing:
            return self.search(f"alternativa não encontrada: {missing[0][:50]!r}", "answer", cap)
        if ans["type"] == "MULTI" and len(prog["done"]) != ans["expected"]:
            raise Pause(f"localizadas {len(prog['done'])} de {ans['expected']} alternativas")
        return self.submit()

    # ---- dropdown

    def _answer_dropdown(self, cap: str) -> dict:
        q, cfg = self.q, self.cfg
        prog = q["progress"]
        items = q["answer"]["items"]
        page = self.page(cap)
        thr = cfg["MATCH_THRESHOLD"]
        statements = [it["statement"] for it in items]
        while prog["item"] < len(items):
            i = prog["item"]
            item = items[i]
            below = prog["last_y"] if prog["last_view"] == q["view"] else -1
            stmt = locate.locate_statement(page, item["statement"], thr, below)
            if stmt.status == "ambiguous":
                raise Pause(f"enunciado ambíguo: {item['statement'][:40]!r}")
            if not stmt.ok:
                return self.search(f"enunciado não encontrado: {item['statement'][:40]!r}", "answer", cap)
            others = [s for k, s in enumerate(statements) if k != i]
            dd = locate.locate_dropdown(page, stmt.box, others, thr)
            if not dd.ok:
                raise Pause(f"dropdown do item {i + 1} não encontrado")
            if locate.dropdown_shows(page, dd.line.box, item["answer"]):
                self.log(f"dropdown {i + 1} já mostra {item['answer']!r}")
                prog.update(item=i + 1, last_y=dd.line.box.y2, last_view=q["view"], dd_retry=False)
                continue
            prog["dd"] = {"box": _box(dd.line.box), "before": cap, "index": i}
            if self.st["dry_run"]:
                self._mark(cap, self.click(cap, dd.point, f"abrir dropdown {i + 1}"))
                b = dd.line.box
                pad = round(6 * page.scale)
                self._mark(cap, {"type": "rect", "ix": b.x - pad, "iy": b.y - pad, "w": b.w + 2 * pad,
                                 "h": b.h + 2 * pad, "label": f"escolheria '{item['answer']}' na lista",
                                 "color": "#0a8a3a"})
                self.log(f"(dry-run) dropdown {i + 1}: abriria e escolheria {item['answer']!r}")
                prog.update(item=i + 1, last_y=dd.line.box.y2, last_view=q["view"])
                continue
            return self.act([self.click(cap, dd.point, f"abrir dropdown {i + 1}")], "dd_open_clicked", cap)
        return self.submit()

    def done_dd_open_clicked(self) -> dict:
        return self.capture("dd_opened", delay_ms=self.cfg["DROPDOWN_DELAY_MS"], stable=False)

    def on_dd_opened(self, cap: str) -> dict:
        prog = self.q["progress"]
        dd = prog["dd"]
        item = self.q["answer"]["items"][dd["index"]]
        found = locate.locate_list_option(self.page(dd["before"]), self.page(cap), item["answer"],
                                          _unbox(dd["box"]), self.cfg["MATCH_THRESHOLD"])
        if not found.ok:
            raise Pause(f"opção {item['answer']!r} não localizada na lista ({found.reason})")
        return self.act([self.click(cap, found.point, f"escolher {item['answer']}")], "dd_pick_clicked", cap)

    def done_dd_pick_clicked(self) -> dict:
        return self.capture("dd_picked", delay_ms=self.cfg["DROPDOWN_DELAY_MS"])

    def on_dd_picked(self, cap: str) -> dict:
        prog = self.q["progress"]
        dd = prog["dd"]
        item = self.q["answer"]["items"][dd["index"]]
        if locate.dropdown_shows(self.page(cap), _unbox(dd["box"]), item["answer"]):
            self.log(f"dropdown {dd['index'] + 1} confirmado: {item['answer']!r}")
            prog.update(item=dd["index"] + 1, last_y=dd["box"][1] + dd["box"][3], last_view=self.q["view"],
                        dd_retry=False, dd=None)
            return self._answer_dropdown(cap)
        if not prog["dd_retry"]:
            self.log(f"dropdown {dd['index'] + 1} não confirmou; tentando de novo")
            prog["dd_retry"] = True
            return self._answer_dropdown(cap)
        raise Pause(f"dropdown {dd['index'] + 1} não mostra {item['answer']!r}")

    # ---- associação

    def _answer_match(self, cap: str) -> dict:
        q, cfg = self.q, self.cfg
        prog = q["progress"]
        pairs = q["answer"]["pairs"]
        page, img = self.page(cap), self.image(cap)
        thr = cfg["MATCH_THRESHOLD"]
        layout = locate.match_sources(page, cap, ocr_char)
        excl = layout.header_lines
        while prog["pair"] < len(pairs):
            k = prog["pair"]
            pair = pairs[k]
            tgt = locate.locate_target(page, img, pair["right"], thr, layout.radius,
                                       exclude=[ln.box for ln in excl])
            if tgt.status == "ambiguous":
                raise Pause(f"item da direita ambíguo: {pair['right'][:40]!r}")
            if not tgt.ok:
                return self.search(f"item da direita não encontrado: {pair['right'][:40]!r}", "answer", cap)
            src = locate.locate_source(layout, pair["letter"], pair["left"], thr)
            if src.status == "ambiguous":
                raise Pause(src.reason)
            if not src.ok:
                return self.search(src.reason, "answer", cap)
            if tgt.kind == "filled" and not self.st["dry_run"]:
                letter, conf = ocr_char(cap, tgt.box)
                if letter == pair["letter"] and conf >= 40:
                    self.log(f"par {k + 1} já ligado em {letter}")
                    prog.update(pair=k + 1, alt_tried=False)
                    continue
            mode = prog["mode"] or cfg["MATCH_MODE"]
            label = f"{pair['letter']} -> {pair['right'][:30]}"
            if mode == "drag":
                actions = [self.drag(cap, src.point, tgt.point, label)]
            else:
                actions = [self.click(cap, src.point, f"letra {pair['letter']}"),
                           self.click(cap, tgt.point, f"alvo {pair['right'][:30]}")]
            prog["verify"] = {"box": _box(tgt.box), "before": cap, "mode": mode}
            if self.st["dry_run"]:
                for a in actions:
                    self._mark(cap, a)
                self.log(f"(dry-run) par {k + 1}: {mode} {label}")
                prog.update(pair=k + 1)
                continue
            return self.act(actions, "match_acted", cap)
        return self.submit()

    def done_match_acted(self) -> dict:
        return self.capture("match_verify", delay_ms=300)

    def on_match_verify(self, cap: str) -> dict:
        prog = self.q["progress"]
        v = prog["verify"]
        before = self.image(v["before"])
        after = self.image(cap)
        if locate.target_linked(before, after, _unbox(v["box"])):
            self.log(f"par {prog['pair'] + 1} ligado ({v['mode']})")
            # Mantém o modo que funcionou para os próximos pares desta questão.
            prog.update(pair=prog["pair"] + 1, alt_tried=False, mode=v["mode"], verify=None)
            return self._answer_match(cap)
        if not prog["alt_tried"]:
            other = "click" if v["mode"] == "drag" else "drag"
            self.log(f"ligação não apareceu com {v['mode']}; tentando {other}")
            prog.update(alt_tried=True, mode=other)
            return self._answer_match(cap)
        raise Pause(f"ligação do par {prog['pair'] + 1} não apareceu (drag e click)")

    # ------------------------------------------------------------ Submit e feedback

    def submit(self) -> dict:
        q = self.q
        q["search"] = None
        if not self.cfg["CLICK_SUBMIT"]:
            return self.go_next()
        q["phase"] = "submit"
        self.status(f"{self.qlabel()}: enviando")
        return self.capture("submit", delay_ms=self.cfg["SUBMIT_DELAY_MS"])

    def on_submit(self, cap: str) -> dict:
        res = locate.locate_submit(self.page(cap), self.cfg["OCR_MIN_CONF"], self.cfg["SUBMIT_WORDS_BLOCKLIST"])
        if res.status == "final":
            if not self.q["manual"]:
                self.st["stats"]["auto"] += 1
            return self.end("final_button", f"avaliação pronta para envio manual ({res.reason}; não é clicado)")
        if res.status == "refused":
            self.st["stats"]["refused"] += 1
            self.log(f"Submit recusado: {res.reason}")
            raise Pause(f"Submit recusado: {res.reason}")
        if res.status == "not_found":
            return self.search("Submit não encontrado", "submit", cap)
        self.q["before_submit"] = cap
        self.q["phase"] = "feedback"
        return self.act([self.click(cap, res.point, "Submit")], "submitted", cap)

    def done_submitted(self) -> dict:
        if self.st["dry_run"]:
            return self.go_next()
        return self.capture("feedback", delay_ms=self.cfg["FEEDBACK_DELAY_MS"])

    def on_feedback(self, cap: str) -> dict:
        q, cfg = self.q, self.cfg
        before = self.page(q["before_submit"]) if q.get("before_submit") else None
        fb = locate.detect_feedback(before, self.page(cap), cfg["FEEDBACK_CORRECT_WORDS"],
                                    cfg["FEEDBACK_INCORRECT_WORDS"])
        self.log(f"feedback: {fb or 'nenhum'}")
        q["feedback"] = fb
        if fb == "incorrect":
            if cfg["RETRY_ON_INCORRECT"] and not q["retried"]:
                q["retried"] = True
                self.st["stats"]["retry"] += 1
                q["feedback_cap"] = cap
                q["claude_images"] = [cap]
                q["claude_round"] = 0
                q["phase"] = "retry"
                return self.ask(retry=True)
            if q["retried"]:
                self.st["stats"]["failed"] += 1
                self.log("errada mesmo após o retry; avançando")
        return self.go_next()

    # ------------------------------------------------------------ avançar

    def go_next(self) -> dict:
        self.q["phase"] = "next"
        self.status(f"{self.qlabel()}: avançando")
        return self.capture("next", delay_ms=self.cfg["NEXT_DELAY_MS"])

    def on_next(self, cap: str) -> dict:
        win = self.win_of(cap)
        final = self._check_final(win, cap)
        if final:
            if self.q and not self.q["manual"]:
                self.st["stats"]["auto"] += 1
            return final
        det = detect.Detection.from_dict(self.st["dets"][win])
        arrow, why = detect.find_arrow(det, self.image(win))
        wf = self.frame(win)
        if arrow is not None:
            gx, gy = wf.to_global(*arrow.point)
            self.log(f"seta de avançar: {why} em {gx},{gy}")
            return self._click_next(cap, gx, gy, f"avançar ({why})")
        self.log(f"seta de avançar não encontrada ({why})")
        if self.st.get("manual_next"):
            dx, dy = self.st["manual_next"]
            px, py = wf.to_global(det.panel.x2, det.panel.y)
            return self._click_next(cap, px + dx, py + dy, "avançar (ponto informado)")
        if self.st["dry_run"]:
            self._complete_question()
            self._finish_marks()
            self.status("dry-run: seta não encontrada; avance manualmente")
            return self.capture("identify", delay_ms=1000, manual=True)
        self.st["pending_next"] = cap
        self.st["expect"] = "point"
        self.status("Não achei a seta de avançar. Clique nela uma vez.")
        return self._directive({"do": "ask_point", "message": "Não achei a seta de avançar. Clique nela uma vez."})

    def on_point(self, event: dict) -> dict:
        """Clique do usuário na seta: guardado só em memória (nesta execução),
        relativo ao canto superior direito do painel detectado."""
        cap = self.st.pop("pending_next", None) or self.st["last_cap"]
        win = self.win_of(cap)
        det = detect.Detection.from_dict(self.st["dets"][win])
        px, py = self.frame(win).to_global(det.panel.x2, det.panel.y)
        x, y = int(event["x"]), int(event["y"])
        self.st["manual_next"] = [x - px, y - py]
        self.log(f"seta informada pelo usuário em {x},{y} (relativa ao painel: {x - px},{y - py})")
        return self._click_next(cap, x, y, "avançar (ponto informado)")

    def _click_next(self, cap: str, gx: int, gy: int, label: str) -> dict:
        win = self.win_of(cap)
        ix, iy = self.frame(win).to_image(gx, gy)
        action = {"type": "click_next", "x": gx, "y": gy, "ix": round(ix), "iy": round(iy), "label": label}
        self._complete_question()
        if self.st["dry_run"]:
            self._mark(win, action)
            self._finish_marks()
            self.status("dry-run: avance manualmente para a próxima questão")
        return self.act([action], "advanced")

    def done_advanced(self) -> dict:
        self.st["wait_since"] = self.now_ms()
        if self.st["dry_run"]:
            return self.capture("identify", delay_ms=1000, manual=True)
        return self.capture("identify", delay_ms=500)

    def _complete_question(self) -> None:
        q = self.q
        if not q["manual"]:
            self.st["stats"]["auto"] += 1
        self.st["prev_sig"] = q["sig"]
        q["phase"] = "done"
        self.log("questão concluída")

    # ------------------------------------------------------------ pausa manual

    def _pause(self, reason: str) -> dict:
        q = self.q
        if q is None:
            return self.end("error", reason)
        if not q["manual"]:
            q["manual"] = True
            self.st["stats"]["manual"] += 1
        q["pause_reason"] = reason
        # Assinatura da vista atual (pode estar rolada): a pausa termina quando
        # a tela deixa de ser esta questão, e não quando difere do topo dela.
        cap = self.st.get("last_cap")
        if cap and Path(cap).exists():
            try:
                q["pause_sig"] = locate.question_signature(self.page(cap), self.image(cap))
            except Exception:  # noqa: BLE001
                q["pause_sig"] = None
        self.log(f"pausado: {reason}")
        self._finish_marks()
        self.status(f"pausado: {reason}")
        return self.capture("manual", delay_ms=1500, manual=True)

    def on_manual(self, cap: str) -> dict:
        page = self.page(cap)
        final = self._check_final(self.win_of(cap))
        if final:
            return final
        sig = locate.question_signature(page, self.image(cap))
        if locate.same_question(sig, self.q["sig"]) or locate.same_question(sig, self.q.get("pause_sig")):
            return self.capture("manual", delay_ms=1500, manual=True)
        self.log("questão mudou durante a pausa; retomando")
        self.st["prev_sig"] = self.q["sig"]
        self.q["phase"] = "done"
        return self._new_question(cap, sig)

    # ------------------------------------------------------------ dry-run

    def _finish_marks(self) -> None:
        """Grava a imagem anotada da questão (dry-run).

        No dry-run a página nunca rola nem muda por ação do loop, então todas
        as marcas da questão ficam no mesmo referencial e vão para uma única
        imagem da janela inteira: o retângulo do painel detectado, cruzes nos
        cliques (inclusive a seta de avançar encontrada) e setas nos arrastos,
        numeradas na ordem.
        """
        q = self.q
        if not q or not q.get("marks"):
            return
        caps = [c for c in q["marks"] if q["marks"][c] and Path(c).exists()]
        marks = [m for c in caps for m in q["marks"][c]]
        q["marks"] = {}
        if not caps:
            return
        dd = self.st["dets"].get(caps[-1])
        if dd and dd.get("panel"):
            x, y, w, h = dd["panel"]
            marks.insert(0, {"kind": "rect", "x": x, "y": y, "w": w, "h": h, "label": "painel detectado",
                             "color": "#0a6ebd"})
        idx = len(q.get("annotated", [])) + 1
        out = Path(q["dir"]) / ("dryrun.png" if idx == 1 else f"dryrun-{idx}.png")
        scale = self.st["frames"].get(caps[-1], [0, 0, 1.0])[2]
        try:
            annotmod.annotate(caps[-1], out, marks, scale)
            self.log(f"imagem anotada: {out}")
            q.setdefault("annotated", []).append(str(out))
        except Exception as exc:  # noqa: BLE001
            self.log(f"falha ao anotar {caps[-1]}: {exc}")


def load_state(path: str | Path) -> Session:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("version") != STATE_VERSION:
        raise ValueError("estado de versão diferente")
    return Session(data)


def save_state(session: Session, path: str | Path) -> None:
    p = Path(path)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(session.st, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, p)
