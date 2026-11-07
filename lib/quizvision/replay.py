"""Simulador do modo `--replay`: telas e respostas do Claude vindas de arquivos.

Um cenário (`scenario.json`) descreve estados (cada um com uma tela de
fixture), transições disparadas pelas ações do loop e as respostas
simuladas do Claude, em ordem. A captura é sempre a janela inteira do
Vivaldi: o estado {"image": "single", "variant": "none"} usa a fixture
win_single__none.png (sem variante: win_single.png).

    {
      "window_at": [x, y],                 posição global da janela (padrão 0,0)
      "manual_next": [x, y],               onde o "usuário" clica quando o loop
                                           pede a seta (pixels da janela);
                                           ausente = Esc
      "start": "q1",
      "states": {"q1": {"image": "single", "variant": "none"}, ...},
      "transitions": [
        {"from": "q1", "on": "click", "target": "opt2", "to": "q1_sel"},
        {"from": "q1", "on": "drag", "source": "LA", "target": "T0", "to": "..."},
        {"from": "q1", "on": "scroll", "dir": "down", "to": "..."},
        {"from": "q1", "on": "next", "to": "q2"},
        {"from": "q1", "on": "wait", "after": 3, "to": "q2"}
      ],
      "forbidden": ["final", "q1:submit"], itens que nunca podem ser clicados
                                           (em qualquer estado ou só em um)
      "claude": [{...}, "texto bruto", ...],
      "config": {"CHAVE": valor},          sobrepõe a configuração
      "expect": {"reason": "...", "stats": {...}, "log_contains": ["..."]}
    }

`target`/`source` são chaves dos itens do `win_<imagem>.truth.json` gerado
pelo make_fixtures. Coordenadas globais = window_at + pixels / escala. Um
clique de avançar que não acerte a seta do gabarito (quando a tela tem uma)
é registrado como violação.
"""

from __future__ import annotations

import json
import math
import shutil
from pathlib import Path


class ReplayError(RuntimeError):
    pass


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def init(scenario_dir: str, fixtures_dir: str, state_path: str) -> dict:
    sdir = Path(scenario_dir)
    scenario = _load(sdir / "scenario.json")
    st = {"scenario_dir": str(sdir), "fixtures": str(Path(fixtures_dir).resolve()), "current": scenario["start"],
          "captures_in_state": 0, "claude_index": 0, "inputs": [], "violations": [], "visited": [scenario["start"]]}
    Path(state_path).write_text(json.dumps(st), encoding="utf-8")
    return st


class World:
    def __init__(self, state_path: str):
        self.path = Path(state_path)
        self.st = _load(self.path)
        self.sc = _load(Path(self.st["scenario_dir"]) / "scenario.json")

    def save(self) -> None:
        self.path.write_text(json.dumps(self.st), encoding="utf-8")

    def image_name(self, state: str | None = None) -> str:
        spec = self.sc["states"][state or self.st["current"]]
        name = f"win_{spec['image']}"
        if spec.get("variant"):
            name += f"__{spec['variant']}"
        return name

    @property
    def origin(self) -> tuple[float, float]:
        ox, oy = self.sc.get("window_at", [0, 0])
        return float(ox), float(oy)

    def truth(self, state: str | None = None) -> dict:
        return _load(Path(self.st["fixtures"]) / f"{self.image_name(state)}.truth.json")

    @property
    def scale(self) -> float:
        return float(self.truth().get("scale", 1.0))

    def _goto(self, to: str, why: str) -> None:
        if to not in self.sc["states"]:
            raise ReplayError(f"estado desconhecido no cenário: {to}")
        self.st["current"] = to
        self.st["captures_in_state"] = 0
        self.st["visited"].append(to)
        self.st["inputs"].append({"goto": to, "why": why})

    def capture(self, out: str) -> dict:
        cur = self.st["current"]
        for t in self.sc["transitions"]:
            if t["from"] == cur and t["on"] == "wait" and self.st["captures_in_state"] >= t.get("after", 1):
                self._goto(t["to"], "wait")
                break
        self.st["captures_in_state"] += 1
        src = Path(self.st["fixtures"]) / f"{self.image_name()}.png"
        if not src.exists():
            raise ReplayError(f"fixture ausente: {src.name}")
        shutil.copyfile(src, out)
        self.save()
        return {"origin": list(self.origin), "scale": self.scale}

    def point(self) -> tuple[int, int]:
        """Clique simulado do usuário na seta (pedido pelo loop)."""
        mp = self.sc.get("manual_next")
        self.st["inputs"].append({"state": self.st["current"], "action": "ask_point", "answered": bool(mp)})
        self.save()
        if not mp:
            raise ReplayError("usuário cancelou (Esc)")
        ox, oy = self.origin
        return round(ox + mp[0] / self.scale), round(oy + mp[1] / self.scale)

    def _hit(self, item: dict, ix: float, iy: float) -> bool:
        s = float(self.truth().get("scale", 1.0))
        if "box" in item:
            x, y, w, h = item["box"]
            pad = 4 * s
            return x - pad <= ix <= x + w + pad and y - pad <= iy <= y + h + pad
        if "control" in item:
            x, y, w, h = item["control"]
            pad = 12 * s
            return x - pad <= ix <= x + w + pad and y - pad <= iy <= y + h + pad
        if "click" in item:
            cx, cy = item["click"]
            return math.hypot(cx - ix, cy - iy) <= 15 * s
        return False

    def _items_at(self, ix: float, iy: float) -> list[str]:
        return [k for k, item in self.truth()["items"].items() if self._hit(item, ix, iy)]

    def input(self, action: dict) -> dict:
        cur = self.st["current"]
        s = self.scale
        kind = action["type"]
        record = {"state": cur, "action": kind}
        ox, oy = self.origin
        if kind in ("click", "drag", "click_next"):
            ix, iy = (action["x"] - ox) * s, (action["y"] - oy) * s
            hits = self._items_at(ix, iy)
            record["hits"] = hits
            forbidden = self.sc.get("forbidden", [])
            for name in hits:
                if name in forbidden or f"{cur}:{name}" in forbidden:
                    self.st["violations"].append(f"clique proibido em {name} no estado {cur}")
            if kind == "drag":
                hits2 = self._items_at((action["x2"] - ox) * s, (action["y2"] - oy) * s)
                record["hits2"] = hits2
            if kind == "click_next" and "next" in self.truth()["items"] and "next" not in hits:
                self.st["violations"].append(
                    f"avançar clicou em {round(ix)},{round(iy)} fora da seta esperada no estado {cur}")
        if kind == "scroll":
            record["dir"] = "down" if action["amount"] < 0 else "up"
        self.st["inputs"].append(record)
        for t in self.sc["transitions"]:
            if t["from"] != cur:
                continue
            on = t["on"]
            if on == "click" and kind == "click" and t["target"] in record["hits"]:
                self._goto(t["to"], f"click {t['target']}")
                break
            if on == "drag" and kind == "drag" and t["source"] in record["hits"] and t["target"] in record["hits2"]:
                self._goto(t["to"], f"drag {t['source']}->{t['target']}")
                break
            if on == "pair" and kind == "click":
                # Modo click da associação: origem e depois alvo.
                pending = self.st.get("pending_source")
                if pending == t["source"] and t["target"] in record["hits"]:
                    self.st["pending_source"] = None
                    self._goto(t["to"], f"click-pair {t['source']}->{t['target']}")
                    break
                if t["source"] in record["hits"]:
                    self.st["pending_source"] = t["source"]
            if on == "scroll" and kind == "scroll" and t.get("dir", "down") == record["dir"]:
                self._goto(t["to"], f"scroll {record['dir']}")
                break
            if on == "next" and kind == "click_next":
                self._goto(t["to"], "next")
                break
        self.save()
        return record

    def claude(self) -> str:
        responses = self.sc.get("claude", [])
        i = self.st["claude_index"]
        if i >= len(responses):
            raise ReplayError("cenário sem mais respostas simuladas do Claude")
        self.st["claude_index"] += 1
        self.save()
        r = responses[i]
        return r if isinstance(r, str) else json.dumps(r, ensure_ascii=False)


def check(state_path: str, end: dict, run_dir: str | None = None) -> list[str]:
    """Compara o fim do loop com `expect` do cenário; devolve falhas."""
    world = World(state_path)
    exp = world.sc.get("expect", {})
    problems = list(world.st["violations"])
    if "reason" in exp and end.get("reason") != exp["reason"]:
        problems.append(f"motivo do fim: esperado {exp['reason']!r}, obtido {end.get('reason')!r}")
    for key, value in exp.get("stats", {}).items():
        got = end.get("summary", {}).get(key)
        if got != value:
            problems.append(f"estatística {key}: esperado {value}, obtido {got}")
    if "visited" in exp:
        missing = [s for s in exp["visited"] if s not in world.st["visited"]]
        if missing:
            problems.append(f"estados não visitados: {missing}")
    if "claude_calls" in exp and world.st["claude_index"] != exp["claude_calls"]:
        problems.append(f"chamadas ao Claude: esperado {exp['claude_calls']}, obtido {world.st['claude_index']}")
    if exp.get("log_contains") and run_dir:
        log_text = ""
        for f in sorted(Path(run_dir).rglob("*.log")) + sorted(Path(run_dir).rglob("log.txt")):
            log_text += f.read_text(encoding="utf-8", errors="replace")
        for phrase in exp["log_contains"]:
            if phrase not in log_text:
                problems.append(f"log sem {phrase!r}")
    if exp.get("annotated") and run_dir:
        if not list(Path(run_dir).rglob("dryrun*.png")):
            problems.append("nenhuma imagem anotada de dry-run")
    return problems
