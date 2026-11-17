"""Explorador CDP só leitura: complemento ADITIVO ao dado de `structure()` (adapters/engine.js).

O motor lê DOM e shadow aberto por quadro. Aqui entra o que a página não mostra ao script:
ouvintes de clique (só em botões e opções), shadow DOM fechado, caixa (bbox) e quadros, com o
caminho de quadros de cada nó, para o perfil derivado sair com [site].frame certo.

Regras:
- LISTA BRANCA: ALLOWED_METHODS é o único conjunto de métodos CDP usado. Um teste de fonte confere
  as chamadas, e _Session recusa qualquer outro método em tempo de execução.
- Só leitura: nada de Input, navegação, avaliação, escrita no DOM ou emulação.
- Nenhum texto de página na saída: só marcação (tag, papel, seletor de id/classe, caminho de quadros),
  nomes de evento de uma lista fixa e números.
- Limites: 10 s, 50.000 nós, 20 níveis de shadow DOM. Estouro = CaptureLimitExceeded.
- Nada vai a disco; o resultado é um dict devolvido a quem chama.
"""

from __future__ import annotations

import re
import time

VERSION = 1
MAX_NODES = 50_000
MAX_SHADOW = 20
MAX_MS = 10_000
MAX_CANDIDATES = 500
OBJECT_GROUP = "dracaena-explorer"

ALLOWED_METHODS = frozenset({
    "DOM.getDocument",
    "DOM.resolveNode",
    "DOMDebugger.getEventListeners",
    "DOMSnapshot.captureSnapshot",
    "Page.getFrameTree",
    "Runtime.releaseObjectGroup",
})

# Prefixos e métodos que jamais podem entrar na lista (o teste de fonte também confere).
FORBIDDEN_PREFIXES = ("Input.", "Emulation.", "Fetch.", "Network.", "Target.", "Browser.", "Storage.")
FORBIDDEN_METHODS = frozenset({
    "Page.navigate", "Page.reload", "Page.handleJavaScriptDialog",
    "Runtime.evaluate", "Runtime.callFunctionOn", "DOM.setAttributeValue", "DOM.setOuterHTML",
    "DOM.removeNode", "DOM.setNodeValue",
})

# Só estes nomes de evento saem; qualquer outro vira contagem em `other_types`.
KNOWN_EVENTS = ("click", "mousedown", "mouseup", "pointerdown", "pointerup", "keydown", "keyup",
                "change", "input", "focus", "submit")
BUTTON_ROLES = ("button", "option")
IMPLICIT_INPUT_TYPES = ("button", "submit", "reset")

_IDENT = re.compile(r"[A-Za-z_][\w-]{0,40}")


class CaptureLimitExceeded(RuntimeError):
    """Estouro de tempo, de nós ou de níveis de shadow DOM: a captura é recusada inteira."""


class ForbiddenMethod(PermissionError):
    """Tentativa de usar um método CDP fora da lista branca."""


def _ident(token: str) -> bool:
    return bool(_IDENT.fullmatch(token)) and not re.search(r"[0-9]{4,}", token)


def _attrs(flat) -> dict:
    flat = list(flat or [])
    return {str(k).lower(): str(v) for k, v in zip(flat[::2], flat[1::2])}


def _selector(tag: str, attrs: dict) -> str:
    ident = attrs.get("id", "")
    if _ident(ident):
        return f"{tag}#{ident}"
    classes = [c for c in attrs.get("class", "").split() if _ident(c)][:2]
    return tag + "".join(f".{c}" for c in classes)


class _Session:
    """Envelope fino sobre a sessão CDP: lista branca, prazo e contagem de chamadas."""

    def __init__(self, cdp, clock, deadline: float):
        self.cdp, self.clock, self.deadline = cdp, clock, deadline

    def ensure_within_limits(self) -> None:
        if self.clock() > self.deadline:
            raise CaptureLimitExceeded("tempo: mais de 10 s")

    def send(self, method: str, params: dict | None = None):
        if method not in ALLOWED_METHODS or method in FORBIDDEN_METHODS or method.startswith(FORBIDDEN_PREFIXES):
            raise ForbiddenMethod(method)
        self.ensure_within_limits()
        return self.cdp.send(method, params or {})


def _frame_origins(tree: dict) -> tuple[dict, str]:
    origins: dict[str, str] = {}
    stack = [tree]
    top = ""
    while stack:
        node = stack.pop()
        frame = node.get("frame", {})
        origins[frame.get("id", "")] = frame.get("securityOrigin", "")
        if not top:
            top = frame.get("securityOrigin", "")
        stack.extend(node.get("childFrames", []))
    return origins, top


def capture(cdp, *, clock=time.monotonic, max_ms: int = MAX_MS) -> dict:
    """Lê ouvintes, shadow fechado, bbox e quadros pela sessão CDP `cdp` (só leitura)."""
    start = clock()
    session = _Session(cdp, clock, start + max_ms / 1000)

    origins, top_origin = _frame_origins(session.send("Page.getFrameTree")["frameTree"])
    root = session.send("DOM.getDocument", {"depth": -1, "pierce": True})["root"]

    seen = 0
    closed_roots = 0
    max_depth = 0
    frames: list[dict] = []
    candidates: list[dict] = []
    stack = [(root, (), True, 0)]
    while stack:
        node, fpath, fsame, depth = stack.pop()
        session.ensure_within_limits()
        seen += 1
        if seen > MAX_NODES:
            raise CaptureLimitExceeded("nós: mais de 50.000")
        if depth > MAX_SHADOW:
            raise CaptureLimitExceeded("shadow DOM: mais de 20 níveis")
        max_depth = max(max_depth, depth)

        if node.get("nodeType") == 1:
            tag = str(node.get("localName") or node.get("nodeName") or "").lower()
            attrs = _attrs(node.get("attributes"))
            if tag in ("iframe", "frame"):
                fid = node.get("frameId", "")
                same = fid in origins and origins[fid] == top_origin
                sel = _selector(tag, attrs)
                frames.append({"selector": sel, "same_origin": same, "readable": "contentDocument" in node,
                               "depth": len(fpath) + 1})
                if "contentDocument" in node:
                    stack.append((node["contentDocument"], fpath + (sel,), fsame and same, depth))
            role = attrs.get("role", "").strip().lower()
            is_button = (role in BUTTON_ROLES if role else
                         tag == "button" or (tag == "input" and attrs.get("type", "").lower() in IMPLICIT_INPUT_TYPES))
            if role in BUTTON_ROLES or (not role and is_button):
                candidates.append({"ref": node.get("backendNodeId"), "tag": tag,
                                   "role": role or "button", "selector": _selector(tag, attrs),
                                   "shadow_depth": depth, "frame_path": list(fpath),
                                   "frame": fpath[-1] if fpath else "", "same_origin": fsame})

        for sr in node.get("shadowRoots", []):
            if sr.get("shadowRootType") == "closed":
                closed_roots += 1
            stack.append((sr, fpath, fsame, depth + 1))
        for child in node.get("children", []):
            stack.append((child, fpath, fsame, depth))

    listeners = {"candidates": 0, "with_click": 0, "unreadable": 0, "other_types": 0, "types": {}, "skipped": 0}
    rects = _rects(session, {c["ref"] for c in candidates[:MAX_CANDIDATES]})
    try:
        for cand in candidates[:MAX_CANDIDATES]:
            try:
                obj = session.send("DOM.resolveNode", {"backendNodeId": cand["ref"], "objectGroup": OBJECT_GROUP})
                object_id = obj["object"]["objectId"]
                found = session.send("DOMDebugger.getEventListeners", {"objectId": object_id, "depth": 0})
            except (CaptureLimitExceeded, ForbiddenMethod):
                raise
            except Exception:  # nó sem objeto (removido, em quadro sem acesso): só conta
                listeners["unreadable"] += 1
                cand["listeners"] = []
                continue
            types = set()
            for item in found.get("listeners", []):
                name = item.get("type", "")
                if name in KNOWN_EVENTS:
                    types.add(name)
                else:
                    listeners["other_types"] += 1
            cand["listeners"] = sorted(types)
            listeners["candidates"] += 1
            for name in types:
                listeners["types"][name] = listeners["types"].get(name, 0) + 1
            if "click" in types:
                listeners["with_click"] += 1
    finally:
        try:
            cdp.send("Runtime.releaseObjectGroup", {"objectGroup": OBJECT_GROUP})
        except Exception:
            pass
    listeners["skipped"] = max(0, len(candidates) - MAX_CANDIDATES)

    nodes = []
    for cand in candidates[:MAX_CANDIDATES]:
        cand["bbox"] = rects.get(cand.pop("ref"))
        nodes.append(cand)
    return {
        "version": VERSION,
        "nodes": nodes,
        "listeners": listeners,
        "shadow": {"closed_roots": closed_roots, "max_depth": max_depth},
        "frames": frames,
        "limits": {"max_nodes": MAX_NODES, "max_shadow": MAX_SHADOW, "max_ms": max_ms,
                   "nodes_seen": seen, "elapsed_ms": int((clock() - start) * 1000)},
    }


def _rects(session: _Session, refs: set) -> dict:
    """bbox (x, y, w, h) inteiros por backendNodeId, do DOMSnapshot. Nó ausente fica sem bbox."""
    rects: dict = {}
    if not refs:
        return rects
    snap = session.send("DOMSnapshot.captureSnapshot", {"computedStyles": [], "includeDOMRects": True})
    for doc in snap.get("documents", []):
        backend = doc.get("nodes", {}).get("backendNodeId", [])
        layout = doc.get("layout", {})
        for index, bounds in zip(layout.get("nodeIndex", []), _quads(layout.get("bounds", []))):
            if index < len(backend) and backend[index] in refs and backend[index] not in rects:
                rects[backend[index]] = bounds
    return rects


def _quads(bounds):
    """Cada caixa do DOMSnapshot é [x, y, w, h]; devolve inteiros arredondados."""
    for box in bounds:
        if len(box) == 4:
            yield [round(v) for v in box]
        else:
            yield None


def attach(structure_out: dict, complement: dict) -> dict:
    """Cópia de `structure_out` com o complemento sob a chave nova `explorer` (o resto não muda)."""
    return {**structure_out, "explorer": complement}
