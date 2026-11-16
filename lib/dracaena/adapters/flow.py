"""Responder as questões visíveis com o adaptador generalizado, sempre pela guarda.

Mesma semântica do Service: uma questão por vez, só marca a resposta, não
navega, não envia e para na tela de resultado. A diferença é escolher o
primeiro componente ainda não respondido (página com várias questões) e
prender a guarda ao quadro do componente (questão dentro de iframe).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from ..core import claude, contract
from ..core.errors import AdapterError
from ..core.model import Question
from ..guard import Guard, Refused, ResultScreen
from .general import THRESHOLD, frames_of


@dataclass(frozen=True)
class Outcome:
    """status: answered | low_confidence | invalid | refused | end | unsupported"""
    status: str
    question: Question | None = None
    reason: str = ""


def answer_visible(frame, adapter, ask: Callable, log: Callable[[str], None] = print, *, dry_run: bool = True,
                   cfg: dict | None = None, threshold: float = THRESHOLD, limit: int = 50) -> list[Outcome]:
    """Marca a resposta de cada questão visível. Devolve um resultado por questão (ou um único, de parada)."""
    extra = tuple(getattr(adapter, "extra_block", ()) or ())
    done: list[Outcome] = []
    seen: set[str] = set()
    while len(done) < limit:
        if any(Guard(log, dry_run=True, extra_block=extra).result_visible(one) for one in frames_of(frame)) \
                and not adapter.locate(frame):
            log("parada: fim da atividade")
            return done + [Outcome("end")]
        pending = None
        for host in adapter.locate(frame):
            question = adapter.extract(host)
            if question.id not in seen:
                pending = (host, question)
                break
        if pending is None:
            if not done:
                why = adapter.diagnose(frame).get("reason") or "nenhuma questão reconhecida"
                log(f"parada: não suportado ({why})")
                return [Outcome("unsupported", reason=why)]
            return done
        host, question = pending
        seen.add(question.id)
        log(f"tipo da questão: {question.kind} (camada {question.layer}, confiança {question.confidence:.2f})")
        if question.confidence < threshold:
            why = "; ".join(question.notes) or "leitura incerta"
            log(f"confiança abaixo do limite: {why}; nenhuma ação (rode dracaena aprender)")
            done.append(Outcome("low_confidence", question, why))
            continue
        try:
            prompt = claude.prompt("answer", contract.question_text(question))
            raw, _ = ask(cfg or {}, prompt, schema=contract.schema_for(question))
            answer = contract.parse_validated(raw, question)
        except contract.ContractError as exc:
            log(f"resposta inválida ({exc})")
            done.append(Outcome("invalid", question, str(exc)))
            continue
        guard = Guard(log, dry_run=dry_run, extra_block=extra)
        guard.bind(host.owner_frame() or frame, host, question.id)
        try:
            for target in adapter.targets(host, answer):
                guard.perform(target, target.label)
        except ResultScreen:
            log("parada: fim da atividade")
            return done + [Outcome("end", question)]
        except Refused as exc:
            log(f"guarda recusou ({exc.reason})")
            done.append(Outcome("refused", question, exc.reason))
            continue
        except AdapterError as exc:
            done.append(Outcome("invalid", question, str(exc)))
            continue
        done.append(Outcome("answered", question))
    return done
