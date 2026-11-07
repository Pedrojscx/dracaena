"""Aplicação da resposta: cada ação passa pela guarda e é conferida no DOM.

Se o estado não refletir a ação, tenta uma vez mais; se ainda não refletir,
levanta Pause (o loop pausa). Nada aqui clica diretamente.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from . import dom


class Pause(Exception):
    """Pausa com motivo (o loop espera o SUPER+P ou a questão mudar)."""


def wait_for(cond: Callable[[], object], timeout_s: float, abort: Callable[[], bool] | None = None,
             interval: float = 0.1):
    """Espera ativa: checa `cond()` a cada `interval` até ser verdadeira ou o teto."""
    end = time.monotonic() + timeout_s
    while True:
        v = cond()
        if v:
            return v
        if time.monotonic() >= end:
            return v
        if abort and abort():
            return v
        time.sleep(interval)


class Actor:
    def __init__(self, frame, guard, cfg: dict, abort: Callable[[], bool]):
        self.frame, self.guard, self.cfg, self.abort = frame, guard, cfg, abort
        self.verify_s = int(cfg.get("VERIFY_TIMEOUT_MS", 1500)) / 1000

    def _q(self, host) -> dict:
        return dom.extract(host)

    def _confirm(self, host, ok: Callable[[dict], bool]) -> bool:
        return bool(wait_for(lambda: ok(self._q(host)), self.verify_s, self.abort))

    def apply(self, host, q: dict, ans: dict) -> list[str]:
        """Marca a resposta; devolve a lista de ações feitas."""
        done: list[str] = []
        kind = ans["type"]
        if kind in ("SINGLE", "MULTI"):
            want = set(ans["answers"])
            targets = [o["index"] for o in q["options"] if o["checked"] != (o["index"] in want)]
            # Única: só marcar a certa (o rádio desmarca as outras sozinho).
            if kind == "SINGLE":
                targets = [i for i in targets if i in want]
            for i in targets:
                label = f"{'marcar' if i in want else 'desmarcar'} [{i}] {q['options'][i]['text'][:50]}"
                for attempt in (1, 2):
                    self.guard.click(dom.element(self.frame, host, "mcq", index=i), host, label)
                    if self._confirm(host, lambda s, i=i: s["options"][i]["checked"] == (i in want)):
                        break
                    if attempt == 2:
                        raise Pause(f"marcação não confirmada: {q['options'][i]['text'][:40]!r}")
                done.append(label)
            if not self._confirm(host, lambda s: {o["index"] for o in s["options"] if o["checked"]} == want):
                raise Pause("as alternativas marcadas não batem com a resposta")
        elif kind == "DROPDOWN":
            for it in ans["items"]:
                i, o = it["item"], it["option"]
                if q["items"][i]["options"][o]["selected"]:
                    continue
                label = f"item [{i}] → [{o}] {q['items'][i]['options'][o]['text']}"
                for attempt in (1, 2):
                    self.guard.click(dom.element(self.frame, host, "dd-button", index=i), host, f"abrir dropdown [{i}]")
                    self.guard.click(dom.element(self.frame, host, "dd-option", index=i, option=o), host, label)
                    if self._confirm(host, lambda s, i=i, o=o: s["items"][i]["options"][o]["selected"]):
                        break
                    if attempt == 2:
                        raise Pause(f"dropdown [{i}] não mostra a opção escolhida")
                done.append(label)
        elif kind == "MATCH":
            for p in ans["pairs"]:
                r, letter = p["right"], p["left"]
                if q["right"][r]["linked"] == letter:
                    continue
                label = f"{letter} → [{r}] {q['right'][r]['text'][:50]}"
                orders = (("match-left", "match-right"), ("match-right", "match-left"))
                for attempt, order in enumerate(orders, 1):
                    for kind_el in order:
                        el = dom.element(self.frame, host, kind_el, index=r, letter=letter)
                        self.guard.click(el, host, f"{label} ({kind_el})")
                    if self._confirm(host, lambda s, r=r, letter=letter: s["right"][r]["linked"] == letter):
                        break
                    if attempt == 2:
                        raise Pause(f"ligação não confirmada: {label}")
                done.append(label)
        else:
            raise Pause(f"tipo não suportado: {kind}")
        return done

    def submit(self, host, mode: str) -> str:
        kind = "toolbar-submit" if mode == "assessment" else "component-action"
        el = dom.element(self.frame, host, kind)
        if el is None:
            raise Pause("botão Submit não encontrado")
        wait_for(lambda: not el.evaluate("b => b.disabled || b.classList.contains('is-disabled')"), self.verify_s,
                 self.abort)
        self.guard.click(el, host, "Submit")
        return "Submit"

    def reset(self, host) -> bool:
        """Reset/Try again do componente (seção do curso), se houver."""
        el = dom.element(self.frame, host, "component-action")
        if el is None:
            return False
        text = el.evaluate("b => b.textContent.replace(/\\s+/g, ' ').trim().toLowerCase()")
        if text not in [w.lower() for w in self.cfg.get("RESET_WORDS", [])]:
            return False
        self.guard.click(el, host, f"{text} (desfazer para o retry)")
        return bool(wait_for(lambda: not self._q(host)["submitted"], self.verify_s * 2, self.abort))
