"""Adaptador generalizado: o Adapter v0 em cima do motor de leitura `engine.js`.

O motor lê a página em três camadas (perfil salvo, heurística semântica, "não
suportado" com motivo) e devolve uma confiança por questão. Este módulo só
traduz: chama o motor em cada quadro (inclusive iframes), monta `Question` e
propõe `Target`. Nunca clica, digita nem seleciona (quem age é `dracaena.guard`).

Aditivo ao contrato v0:
- `ScoredQuestion` = `Question` + `confidence`, `layer`, `notes`, `actionable`;
- `target(handle, "match", (direita, letra))` para MATCH por select ou grade de rádio;
- `targets(handle, answer)`: os alvos de uma resposta já validada;
- `diagnose(frame)`: camada, confiança e motivo do "não suportado".
"""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass
from pathlib import Path

from ..core.errors import Ambiguous, NotFound, PageGone
from ..core.model import DROPDOWN, MATCH, MULTI, Choice, Item, Option, Question, Side, Target, Verdict
from .heuristic import expected_count

ENGINE = Path(__file__).with_name("engine.js").read_text(encoding="utf-8")
THRESHOLD = 0.6     # abaixo disso a leitura heurística pede um perfil (autoperfil)


def _frame_fn(call: str) -> str:
    return "(a) => {" + ENGINE + "\nreturn DracaenaEngine." + call + ";}"


def _host_fn(call: str) -> str:
    return "(host, a) => {" + ENGINE + "\nreturn DracaenaEngine." + call + ";}"


_LOCATE = _frame_fn("locate(a.profile)")
_DIAGNOSE = _frame_fn("diagnose(a.profile)")
_REGION = _frame_fn("region(a.limit)")
_EXTRACT = _host_fn("extract(host, a.profile)")
_OPTION = _host_fn("option(host, a, a.profile)")
_BUTTONS = _host_fn("buttons(host, a.kind, a.profile)")
_VERDICT = _host_fn("verdict(host, a.profile)")
_FIGURES = _host_fn("figures(host, a.profile)")


@dataclass(frozen=True)
class ScoredQuestion(Question):
    """`Question` do contrato v0 mais os campos aditivos do motor."""
    confidence: float = 0.0
    layer: str = "heuristic"            # heuristic | profile
    notes: tuple[str, ...] = ()
    actionable: bool = True             # False: lida, mas a guarda v0 recusa o tipo de elemento


def _translate(exc: Exception):
    """Erro do navegador → exceção tipada (o núcleo não casa texto de erro)."""
    msg = str(exc).lower()
    if any(k in msg for k in ("detached", "closed", "context was destroyed", "navigat", "disconnected", "target page")):
        return PageGone(str(exc).splitlines()[0][:160])
    return None


def frames_of(frame) -> list:
    """O quadro e os quadros filhos (iframes), em ordem."""
    out = [frame]
    for child in list(getattr(frame, "child_frames", None) or ()):
        out.extend(frames_of(child))
    return out


class GeneralAdapter:
    """Sem perfil: heurística (matches = 10). Com perfil: vale para as URLs dele (matches = 80)."""

    def __init__(self, figure_dir: Path | None = None, extra_block: tuple[str, ...] = (), profile=None):
        self.figure_dir = Path(figure_dir) if figure_dir else None
        self.profile = profile
        self._data = profile.to_engine() if profile is not None else None
        self.name = profile.name if profile is not None else "general"
        self.extra_block = tuple(extra_block) + (tuple(profile.block_labels) if profile is not None else ())

    def matches(self, url: str, title: str = "") -> int:
        if self.profile is None:
            return 10
        if not any(fnmatch.fnmatchcase(url, glob) for glob in self.profile.match):
            return 0
        if self.profile.title and not re.search(self.profile.title, title or ""):
            return 0
        return 80

    # ---- chamadas ao navegador, com tradução de erros
    def _run(self, fn):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - só traduz o que o Playwright diz sobre a página
            typed = _translate(exc)
            if typed is not None:
                raise typed from exc
            raise

    def _arg(self, **extra) -> dict:
        return {"profile": self._data, **extra}

    def _elements(self, where, js: str, arg: dict) -> list:
        def go():
            arr = where.evaluate_handle(js, arg)
            return [h.as_element() for h in arr.get_properties().values() if h.as_element()]
        return self._run(go)

    def _frames(self, frame) -> list:
        frames = frames_of(frame)
        wanted = self.profile.frame if self.profile is not None else ""
        if wanted:
            picked = [f for f in frames if fnmatch.fnmatchcase(getattr(f, "url", ""), wanted) or wanted in getattr(f, "url", "")]
            return picked
        return frames

    # ---- interface do adaptador (v0)
    def locate(self, frame) -> list:
        hosts = []
        for one in self._frames(frame):
            try:
                hosts.extend(self._elements(one, _LOCATE, self._arg()))
            except PageGone:
                if one is frame:
                    raise           # um iframe que sumiu não derruba a leitura do resto
        return hosts

    def _raw(self, handle) -> dict:
        data = self._run(lambda: handle.evaluate(_EXTRACT, self._arg()))
        if not data:
            raise NotFound("nenhuma questão reconhecida neste componente")
        return data

    def extract(self, handle) -> ScoredQuestion:
        data = self._raw(handle)
        kind = data["kind"]
        text = f"{data['stem']} {data['instruction']}"
        sides = lambda rows: tuple(Side(s["index"], s["text"], s["letter"], s["linked"]) for s in rows)  # noqa: E731
        return ScoredQuestion(
            id=data["id"], kind=kind, stem=data["stem"], instruction=data["instruction"],
            options=tuple(Option(o["index"], o["text"], o["checked"]) for o in data["options"]),
            expected=expected_count(text) if kind == MULTI else None,
            items=tuple(Item(i["label"], tuple(Choice(c["index"], c["text"], c["selected"]) for c in i["options"]))
                        for i in data["items"]),
            figures=self._figures(handle, data["id"]), feedback=data["feedback"],
            left=sides(data["left"]), right=sides(data["right"]),
            confidence=float(data["confidence"]), layer=data["layer"], notes=tuple(data["notes"]),
            actionable=bool(data["actionable"]))

    def _figures(self, handle, qid: str) -> tuple[str, ...]:
        if self.figure_dir is None:
            return ()
        paths = []
        self.figure_dir.mkdir(parents=True, exist_ok=True)
        for n, el in enumerate(self._elements(handle, _FIGURES, self._arg()), 1):
            path = self.figure_dir / f"{qid}-{n}.png"
            try:
                path.write_bytes(el.screenshot(type="png", timeout=5000))
            except Exception:  # noqa: BLE001 - figura ilegível: o laço decide se a questão depende dela
                continue
            paths.append(str(path))
        return tuple(paths)

    def extract_id(self, handle) -> str:
        return self._raw(handle)["id"]

    def target(self, handle, kind: str, index) -> Target:
        """kind: option (index = int) | dropdown (index = (item, opção)) | match (index = (direita, letra))."""
        if kind == "dropdown":
            arg = self._arg(kind="dropdown", item=int(index[0]), option=int(index[1]))
        elif kind == "match":
            arg = self._arg(kind="match", right=int(index[0]), letter=str(index[1]))
        elif kind == "option":
            arg = self._arg(kind="option", option=int(index))
        else:
            raise NotFound(f"tipo de alvo desconhecido: {kind}")
        data = self._run(lambda: handle.evaluate_handle(_OPTION, arg))
        if data.evaluate("o => o === null"):
            raise NotFound(f"alvo {kind} {index} não encontrado")
        el = data.get_property("el").as_element()
        if el is None:
            raise NotFound(f"alvo {kind} {index} não encontrado")
        props = data.evaluate("o => ({action: o.action, value: o.value, label: o.label})")
        qid = self.extract_id(handle)
        opener_el = data.get_property("opener").as_element()
        opener = Target("option", "click", opener_el, f"abrir {props['label']}", qid) if opener_el else None
        return Target("option", props["action"], el, props["label"], qid, props["value"], opener)

    def targets(self, handle, answer: dict) -> list[Target]:
        """Os alvos de uma resposta validada pelo contrato, na ordem em que a guarda deve executá-los."""
        kind = answer["type"]
        if kind in ("SINGLE", "MULTI"):
            return [self.target(handle, "option", i) for i in answer["answers"]]
        if kind == DROPDOWN:
            return [self.target(handle, "dropdown", (it["item"], it["option"])) for it in answer["items"]]
        if kind == MATCH:
            return [self.target(handle, "match", (p["right"], p["left"])) for p in answer["pairs"]]
        raise NotFound(f"tipo de resposta desconhecido: {kind}")

    def _button(self, handle, kind: str) -> Target | None:
        found = self._elements(handle, _BUTTONS, self._arg(kind=kind))
        if not found:
            return None
        if len(found) > 1:
            raise Ambiguous(f"{len(found)} botões de {kind} na mesma questão")
        el = found[0]
        label = self._run(lambda: el.evaluate(
            "e => (e.textContent || e.value || e.getAttribute('aria-label') || '').replace(/\\s+/g, ' ').trim()"))
        return Target(kind, "click", el, label, self.extract_id(handle))

    def submit_target(self, handle) -> Target | None:
        return self._button(handle, "submit")

    def reset_target(self, handle) -> Target | None:
        return self._button(handle, "reset")

    def verdict(self, handle) -> Verdict:
        d = self._run(lambda: handle.evaluate(_VERDICT, self._arg()))
        return Verdict(d["result"], d["feedback"])

    # ---- aditivo: diagnóstico e recorte (somente leitura)
    def diagnose(self, frame) -> dict:
        """Resumo de todos os quadros: camada, confiança mínima, questões e motivo do "não suportado"."""
        parts = []
        for one in self._frames(frame):
            try:
                parts.append(self._run(lambda one=one: one.evaluate(_DIAGNOSE, self._arg())))
            except PageGone:
                if one is frame:
                    raise
        questions = [q for p in parts for q in p["questions"]]
        matches: dict[str, int] = {}
        for p in parts:
            for sel, n in p["matches"].items():
                matches[sel] = n if n < 0 or matches.get(sel, 0) < 0 else matches.get(sel, 0) + n
        if not questions:
            order = ("typed", "custom-dropdown", "plain-buttons", "drag", "empty")
            if not parts:
                return {"layer": "none", "supported": False, "reason": "nenhum quadro corresponde ao perfil",
                        "code": "empty", "questions": [], "matches": {}, "confidence": 0.0}
            first = min(parts, key=lambda p: order.index(p["code"]) if p["code"] in order else len(order))
            return {"layer": "none", "supported": False, "reason": first["reason"], "code": first["code"],
                    "questions": [], "matches": matches, "confidence": 0.0}
        layer = "profile" if any(q["layer"] == "profile" for q in questions) else "heuristic"
        return {"layer": layer, "supported": True, "reason": None, "code": None, "questions": questions,
                "matches": matches, "confidence": min(q["confidence"] for q in questions)}

    def region(self, frame, limit: int = 24000) -> dict:
        """Recorte estrutural da região da atividade (sem texto de conteúdo), do quadro com mais elementos."""
        best = {"outline": "", "truncated": False, "elements": 0}
        for one in self._frames(frame):
            try:
                got = self._run(lambda one=one: one.evaluate(_REGION, {"limit": limit}))
            except PageGone:
                continue
            if got["elements"] > best["elements"]:
                best = got
        return best


def default_registry(sites_dir: Path | None = None, warn=None):
    """Perfis salvos (cada um com matches = 80 nas URLs dele) e o adaptador generalizado (10)."""
    from .base import Registry
    from .profile import load_all
    if sites_dir is None:
        from ..platform.sites import sites_dir as default_dir
        sites_dir = default_dir()
    adapters = [GeneralAdapter(profile=p) for p in load_all(sites_dir, warn=warn)]
    return Registry(adapters + [GeneralAdapter()])
