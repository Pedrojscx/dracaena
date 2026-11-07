"""O loop: lê a questão do DOM, consulta o Claude, marca pela guarda, envia,
lê o veredito, faz o retry (seção do curso) e segue até o fim.

Controle (SUPER+P via `quiz-loop`): SIGUSR1 alterna pausa/retomada; SIGTERM
para. Pausas automáticas (recusa da guarda, resposta inválida...) também
terminam quando a questão muda (você respondeu à mão). Os cliques via CDP não
movem o cursor: dá para usar o computador enquanto o loop roda.

Fim, sempre sem clicar: tela de envio da avaliação (`finalscreen-view`), tela
de resultado, ou todas as questões do item respondidas (seção do curso).
"""

from __future__ import annotations

import json
import os
import shlex
import signal
import time
import traceback
from datetime import datetime
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

from . import browser as browsermod
from . import claude, contract, dom, private
from . import config as configmod
from .actions import Actor, Pause, wait_for
from .guard import FinalScreen, Guard, Refused
from .notify import notify


class Timer:
    def __init__(self):
        self.t: dict[str, float] = {}

    def add(self, key: str, seconds: float) -> None:
        self.t[key] = round(self.t.get(key, 0.0) + seconds, 3)

    def measure(self, key: str):
        timer = self

        class _M:
            def __enter__(self):
                self.t0 = time.monotonic()

            def __exit__(self, *exc):
                timer.add(key, time.monotonic() - self.t0)
        return _M()

    def table(self) -> dict:
        out = dict(self.t)
        out["fora do Claude"] = round(sum(v for k, v in self.t.items() if not k.startswith("claude")), 3)
        return out


class Loop:
    def __init__(self, cfg: dict, dry_run: bool = False, once: bool = False, run_dir: Path | None = None):
        self.cfg = cfg
        self.dry_run, self.once = dry_run, once
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        self.run_dir = run_dir or configmod.data_dir() / "runs" / (stamp + ("-dryrun" if dry_run else ""))
        private.mkdir(self.run_dir)
        self.stop = False
        self.toggle = False
        self.paused = False
        self.user_paused = False
        self.pause_reason = ""
        self.pause_key = None
        self.last_key = None
        self.n = 0
        self.item = None            # atividade (título da aba) em que o loop começou
        self.recoveries = 0
        self.last_reasoning = False
        self.last_model = ""
        self.images: list[bytes] = []
        self.stats = {"respondidas": 0, "corretas": 0, "erradas": 0, "retry": 0, "pausas": 0}
        self.t0 = time.monotonic()

    # ------------------------------------------------------------ registro

    def log(self, msg: str) -> None:
        line = f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}\n"
        with private.open_file(self.run_dir / "run.log", "a") as fh:
            fh.write(line)
        if os.environ.get("QH_VERBOSE") == "1":
            print(line, end="", flush=True)

    def status(self, text: str, urgency: str = "normal") -> None:
        notify(text, urgency, 0, self.cfg)

    def aborted(self) -> bool:
        return self.stop or self.toggle

    # ------------------------------------------------------------ sinais

    def _signals(self) -> None:
        signal.signal(signal.SIGUSR1, lambda *_: setattr(self, "toggle", True))
        signal.signal(signal.SIGTERM, lambda *_: setattr(self, "stop", True))
        signal.signal(signal.SIGINT, lambda *_: setattr(self, "stop", True))

    # ------------------------------------------------------------ execução

    def run(self) -> int:
        self._signals()
        self.log(f"início ({'dry-run' if self.dry_run else 'real'})")
        with sync_playwright() as pw:
            try:
                br = browsermod.connect(pw, int(self.cfg.get("CDP_PORT", 9222)))
                tab = browsermod.attach(br)
            except (browsermod.TabError, PlaywrightError) as exc:
                msg = str(exc).splitlines()[0]
                self.log(f"não iniciado: {msg}")
                self.status(f"Não iniciado: {msg}", "critical")
                return 1
            self.page = tab.page
            self.log(f"aba: {tab.title}")
            self.status("quiz-loop: iniciando" + (" (dry-run)" if self.dry_run else ""))
            code = self._loop()
        return code

    def _loop(self) -> int:
        while not self.stop:
            if self.toggle:
                self.toggle = False
                self._on_toggle()
            if self.paused:
                self._wait_paused()
                continue
            tab = None
            try:
                tab = browsermod.revalidate(self.page)
                if self._step(tab):
                    return 0
            except FinalScreen:
                self._end_final(tab.frame if tab else None)
                return 0
            except Refused as exc:
                self._pause(f"a guarda recusou: {exc.reason}")
            except Pause as exc:
                self._pause(str(exc))
            except browsermod.TabError as exc:
                if "fechada" in str(exc):
                    self.log(f"fim: {exc}")
                    self.status(f"quiz-loop parado: {exc}", "critical")
                    return 1
                self._handle_page_change(str(exc))
            except claude.Aborted:
                continue
            except (claude.ClaudeError, contract.ContractError) as exc:
                self._pause(f"Claude: {exc}")
            except PlaywrightError as exc:
                self.log("erro do navegador:\n" + traceback.format_exc())
                self._handle_page_change(f"erro do navegador: {str(exc).splitlines()[0][:120]}")
        self.log("parado pelo usuário")
        self.status("quiz-loop parado.")
        return 0

    # ------------------------------------------------------------ troca de página

    def _tab_changed(self, tab_title: str) -> None:
        """Pausa que só o SUPER+P encerra (voltar sozinho ao quiz não retoma)."""
        self._pause(f"a aba mudou para {tab_title}; volte ao quiz e aperte SUPER+P", user=True)

    def _handle_page_change(self, why: str) -> None:
        """Contexto do iframe perdido ou aba navegando: espera estabilizar, reconecta e confere.

        Mesma atividade → o loop segue (uma questão já enviada nunca é reenviada: `last_key`);
        outra atividade → pausa. Só pausa com erro técnico se a página não estabilizar.
        """
        self.recoveries += 1
        if self.recoveries > 3:
            self._pause(why)
            return
        self.log(f"página instável ({why}); aguardando estabilizar (tentativa {self.recoveries}/3)")
        limit = int(self.cfg.get("RECOVER_TIMEOUT_MS", 15000)) / 1000
        end, last, stable, title = time.monotonic() + limit, None, 0, ""
        while time.monotonic() < end and not self.aborted():
            try:
                title = self.page.title()
                if self.page.is_closed():
                    break
                tab = browsermod.revalidate(self.page)
                loc = dom.locate(tab.frame, tab.item)
            except browsermod.TabError as exc:
                if "saiu do NetAcad" in str(exc):
                    self._tab_changed(title or str(exc))
                    return
                sig = None
            except PlaywrightError:
                sig = None
            else:
                if self.item is not None and tab.item != self.item:
                    self._tab_changed(tab.title)
                    return
                sig = (tab.title, loc.key, loc.host is not None)
            stable = stable + 1 if sig is not None and sig == last else 0
            last = sig
            if stable >= 3:
                self.log(f"página estável: {last[0]} (questão {'já enviada' if last[1] == self.last_key else 'a responder'})")
                return
            time.sleep(0.25)
        if not self.aborted():
            self._pause(f"a página não estabilizou em {limit:.0f}s ({why})")

    # ------------------------------------------------------------ pausa

    def _key_now(self):
        try:
            tab = browsermod.revalidate(self.page)
            return dom.locate(tab.frame, tab.item).key
        except (browsermod.TabError, PlaywrightError):
            return None

    def _pause(self, reason: str, user: bool = False) -> None:
        self.paused, self.user_paused, self.pause_reason = True, user, reason
        self.pause_key = self._key_now()
        self.stats["pausas"] += 1
        self.log(f"pausado: {reason}")
        self.status(f"pausado: {reason}\nSUPER+P retoma.", "critical")

    def _resume(self, why: str) -> None:
        self.paused = self.user_paused = False
        if why == "SUPER+P":
            self.item = None        # adota a atividade que estiver aberta agora
        self.log(f"retomando ({why})")
        self.status(f"quiz-loop: retomando ({why})")

    def _on_toggle(self) -> None:
        if self.paused:
            self._resume("SUPER+P")
        else:
            self._pause("pausado pelo usuário", user=True)

    def _wait_paused(self) -> None:
        end = time.monotonic() + 1.0
        while time.monotonic() < end and not (self.toggle or self.stop):
            time.sleep(0.1)
        if not self.user_paused and not self.toggle and not self.stop:
            key = self._key_now()
            if key is not None and key != self.pause_key:
                self._resume("a questão mudou")

    # ------------------------------------------------------------ passo

    def _step(self, tab) -> bool:
        frame = tab.frame
        if self.item is None:
            self.item = tab.item
        elif tab.item != self.item:
            self._tab_changed(tab.title)
            return False
        loc = dom.locate(frame, tab.item)
        if loc.final:
            raise FinalScreen()
        if loc.start:
            raise Pause("a avaliação está na tela inicial: clique em Start")
        if loc.done:
            self._end(f"atividade concluída ({loc.extra.get('total', 0)} questões)")
            return True
        end = dom.end_phrase(frame, self.cfg.get("END_WORDS", []))
        if end and loc.host is None:
            self._end(f"tela de resultado ('{end}')")
            return True
        if loc.host is None:
            found = wait_for(lambda: dom.locate(frame, tab.item).host, 3, self.aborted)
            if not found:
                raise Pause(loc.reason or "questão não encontrada")
            return False
        if loc.key == self.last_key:
            # Já respondida: esperar o avanço (avaliação) sem clicar em nada.
            moved = wait_for(lambda: (lambda l: l.final or l.key != self.last_key)(dom.locate(frame, tab.item)),
                             int(self.cfg.get("ADVANCE_TIMEOUT_MS", 8000)) / 1000, self.aborted)
            if not moved and not self.aborted():
                raise Pause("a questão não mudou depois do Submit")
            return False
        if self.n >= int(self.cfg.get("MAX_QUESTIONS", 80)):
            self._end(f"limite de {self.n} questões")
            return True
        self._answer(frame, loc, tab)
        return self.once

    def _claude_log(self, text: str) -> None:
        """Arquivo por questão com tudo o que foi enviado e recebido do Claude (nada truncado)."""
        d = self.run_dir / "claude"
        private.mkdir(d)
        with private.open_file(d / f"Q{self.n:03d}.txt", "a") as fh:
            fh.write(text)

    def _consult(self, q: dict, timer: Timer, retry_of: dict | None = None, feedback: str = "") -> dict:
        text = contract.question_text(q)
        if self.images:
            text += "\n(A figura da questão está anexada como imagem; use-a para responder.)"
        if retry_of is None:
            prompt = claude.prompt("answer", text)
        else:
            prompt = claude.prompt("retry", text, json.dumps(retry_of, ensure_ascii=False), feedback)
        schema = contract.schema_for(q) if int(self.cfg.get("CLAUDE_SCHEMA", 0)) == 1 else None
        last_err, last_raw = None, ""
        for attempt in (1, 2):
            if attempt == 2:
                prompt = claude.prompt("invalid", text, last_raw, str(last_err))
            model = claude.model_for(self.cfg, retry=attempt == 2 or retry_of is not None)
            self.last_model = model
            stamp = f"{datetime.now():%H:%M:%S}"
            self._claude_log(f"===== {stamp} tentativa {attempt}{' (retry da página)' if retry_of else ''} | modelo: {model} | figuras: {len(self.images)} =====\n"
                             f"--- comando ---\n{shlex.join(claude.build_cmd(self.cfg, prompt, model=model, schema=schema, images=bool(self.images)))}\n"
                             f"--- prompt de sistema ---\n{claude.system_prompt()}\n"
                             f"--- texto enviado ---\n{prompt}\n")
            try:
                out, secs = claude.ask(self.cfg, prompt, self.aborted, model=model, schema=schema,
                                      images=self.images or None)
            except claude.Aborted:
                self._claude_log("--- consulta interrompida ---\n")
                raise
            except claude.ClaudeError as exc:
                self._claude_log(f"--- erro ---\n{exc}\n")
                raise
            timer.add("claude", secs)
            self.log(f"Claude ({model}) respondeu em {secs:.1f}s: {out.strip()[:400]}")
            reasoning = not out.strip().startswith(("{", "```"))
            self._claude_log(f"--- saída bruta ({secs:.1f}s, raciocínio antes do JSON: {'sim' if reasoning else 'não'}) ---\n"
                             f"{out}\n")
            self.last_reasoning = reasoning
            try:
                ans = contract.parse_validated(out, q)
                self._claude_log("--- validação: OK ---\n")
                return ans
            except contract.ContractError as exc:
                last_err, last_raw = exc, out.strip()
                self._claude_log(f"--- validação: REJEITADA ({exc}) ---\n")
                self.log(f"resposta inválida ({exc}); {'repetindo com o motivo' if attempt == 1 else 'desistindo'}")
        raise contract.ContractError(f"resposta inválida duas vezes: {last_err}")

    def _answer(self, frame, loc, tab) -> None:
        self.n += 1
        timer = Timer()
        guard = Guard(frame, self.cfg, self.log, self.dry_run)
        actor = Actor(frame, guard, self.cfg, self.aborted)
        host = loc.host
        with timer.measure("leitura do DOM"):
            q = dom.extract(host)
        label = q.get("title") or (f"Questão {loc.number[0]}" if loc.number else f"Questão {self.n}")
        self.log(f"[Q{self.n}] {label} ({q['kind']}, {loc.mode}) chave={loc.key}")
        if q["kind"] == "UNSUPPORTED":
            raise Pause(f"tipo de componente não suportado: {q['tag']}")
        try:
            self.images = dom.capture_figures(host, q)
        except dom.FigureError as exc:
            raise Pause(str(exc)) from exc
        if self.images:
            self.log(f"[Q{self.n}] figuras capturadas: {len(self.images)} ({sum(map(len, self.images))} bytes)")
            for k, png in enumerate(self.images, 1):
                private.mkdir(self.run_dir / "claude")
                private.write_bytes(self.run_dir / "claude" / f"Q{self.n:03d}-fig{k}.png", png)
        self.status(f"{label}: consultando")
        ans = self._consult(q, timer)
        readable = contract.readable(ans, q)
        self.log(f"[Q{self.n}] resposta: {json.dumps(ans, ensure_ascii=False)}")
        self.status(f"{label}: marcando\n{readable}")
        record = {"q": self.n, "label": label, "key": loc.key, "mode": loc.mode, "kind": q["kind"],
                  "answer": ans, "readable": readable, "actions": [], "verdict": None, "retry": None,
                  "reasoning": self.last_reasoning, "model": self.last_model}
        with timer.measure("ações"):
            record["actions"] += actor.apply(host, q, ans)
        if self.dry_run:
            record["verdict"] = "dry-run (nada enviado)"
            self._record(record, timer)
            raise Pause("dry-run: resposta marcada na tela de forma simulada; nada foi clicado")
        if int(self.cfg.get("CLICK_SUBMIT", 1)) != 1:
            record["verdict"] = "Submit desligado (CLICK_SUBMIT=0)"
            self._record(record, timer)
            self.last_key = loc.key
            raise Pause("CLICK_SUBMIT=0: marque o próximo passo você")
        prev_key, self.last_key = self.last_key, loc.key    # antes do clique: nunca reenviar
        with timer.measure("Submit"):
            try:
                record["actions"].append(actor.submit(host, loc.mode))
            except (Pause, Refused):
                self.last_key = prev_key                     # nada foi enviado
                raise
        verdict = self._after_submit(frame, loc, tab, host, timer)
        record["verdict"] = verdict
        if verdict.get("incorrect") and loc.mode == "section" and int(self.cfg.get("RETRY_ON_INCORRECT", 1)) == 1:
            record["retry"] = self._retry(frame, host, q, ans, verdict, timer, actor)
            verdict = record["retry"]["verdict"]
        self.stats["respondidas"] += 1
        if verdict.get("correct"):
            self.stats["corretas"] += 1
        elif verdict.get("incorrect"):
            self.stats["erradas"] += 1
        self._record(record, timer)
        self.status(f"{label}: {self._verdict_text(verdict)}\n{readable}")

    def _after_submit(self, frame, loc, tab, host, timer: Timer) -> dict:
        if loc.mode == "assessment":
            with timer.measure("espera de avanço"):
                moved = wait_for(lambda: (lambda l: l.final or (l.key and l.key != loc.key))(dom.locate(frame, tab.item)),
                                 int(self.cfg.get("ADVANCE_TIMEOUT_MS", 8000)) / 1000, self.aborted)
            if not moved:
                return {"advanced": False, "text": "a avaliação não avançou"}
            return {"advanced": True, "text": "avançou sozinha"}
        with timer.measure("espera de feedback"):
            v = wait_for(lambda: (lambda d: d if d["submitted"] else None)(dom.verdict(host)),
                         int(self.cfg.get("FEEDBACK_TIMEOUT_MS", 6000)) / 1000, self.aborted)
        if not v:
            raise Pause("a página não mostrou o resultado do Submit")
        return v

    def _retry(self, frame, host, q, ans, verdict, timer: Timer, actor: Actor) -> dict:
        self.stats["retry"] += 1
        q_after = dom.extract(host)
        feedback = verdict.get("label") or "resposta incorreta"
        if verdict.get("wrong"):
            feedback += "; itens marcados como errados: " + " | ".join(verdict["wrong"])
        self.log(f"[Q{self.n}] errada ({feedback}); retry")
        new = self._consult(q_after, timer, retry_of=ans, feedback=feedback)
        self.log(f"[Q{self.n}] nova resposta: {json.dumps(new, ensure_ascii=False)}")
        with timer.measure("ações"):
            if not actor.reset(host):
                raise Pause("errada, mas não há Reset/Try again para refazer")
            q2 = dom.extract(host)
            acts = actor.apply(host, q2, new)
        with timer.measure("Submit"):
            acts.append(actor.submit(host, "section"))
        with timer.measure("espera de feedback"):
            v = wait_for(lambda: (lambda d: d if d["submitted"] else None)(dom.verdict(host)),
                         int(self.cfg.get("FEEDBACK_TIMEOUT_MS", 6000)) / 1000, self.aborted)
        return {"answer": new, "actions": acts, "verdict": v or {"text": "sem resultado"}}

    @staticmethod
    def _verdict_text(v: dict) -> str:
        if v.get("correct"):
            return "correta"
        if v.get("incorrect"):
            return "errada"
        return v.get("text") or v.get("label") or "enviada"

    def _record(self, record: dict, timer: Timer) -> None:
        record["timing"] = timer.table()
        self.recoveries = 0
        with private.open_file(self.run_dir / "questions.jsonl", "a") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        self.log(f"[Q{record['q']}] veredito: {self._verdict_text(record['verdict'] or {})}; tempos: "
                 + ", ".join(f"{k}={v:.2f}s" for k, v in record["timing"].items()))

    # ------------------------------------------------------------ fim

    def _summary(self) -> str:
        s = self.stats
        return (f"respondidas {s['respondidas']} | corretas {s['corretas']} | erradas {s['erradas']} | "
                f"retry {s['retry']} | pausas {s['pausas']} | {(time.monotonic() - self.t0) / 60:.1f} min")

    def _end(self, why: str) -> None:
        self.log(f"fim: {why}; {self._summary()}")
        self.status(f"fim: {why}\n{self._summary()}")

    def _end_final(self, frame) -> None:
        n = dom.unanswered_count(frame) if frame is not None else None
        pend = f"{n} sem resposta" if n is not None else "tela de envio"
        self._end(f"avaliação pronta para envio manual ({pend}); nada foi clicado")


def run(cfg: dict, dry_run: bool = False, once: bool = False) -> int:
    pidfile = configmod.runtime_dir() / "loop.pid"
    try:
        return Loop(cfg, dry_run, once).run()
    finally:
        try:
            if pidfile.exists() and pidfile.read_text().strip() == str(os.getpid()):
                pidfile.unlink()
        except OSError:
            pass
