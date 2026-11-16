"""Corpus de padrões de quiz: servidor local, Claude simulado e a medição por fixture.

Usado pelos testes (`test_corpus.py`) e pelo comando de métrica (`tests/metric.py`).
"""

from __future__ import annotations

import functools
import io
import json
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from fx import REPO
from web import build_derived

from dracaena.adapters import autoprofile, profile
from dracaena.adapters.flow import answer_visible
from dracaena.adapters.general import THRESHOLD, GeneralAdapter
from dracaena.guard import Guard

CORPUS = REPO / "tests" / "fixtures" / "corpus"
ROOTS = {"corpus": CORPUS, "compat": REPO / "tests" / "fixtures" / "compat",
         "derived": REPO / "tests" / "fixtures" / "out"}
SIM = REPO / "tests" / "fixtures" / "html" / "sim.js"


def manifest() -> list[dict]:
    return json.loads((CORPUS / "manifest.json").read_text(encoding="utf-8"))["fixtures"]


class _Handler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def send_head(self):
        parts = self.path.split("?", 1)[0].strip("/").split("/")
        if parts == ["sim.js"]:
            data, kind = SIM.read_bytes(), "text/javascript"
        elif len(parts) == 2 and parts[0] in ROOTS and (ROOTS[parts[0]] / parts[1]).is_file():
            path = ROOTS[parts[0]] / parts[1]
            text = path.read_text(encoding="utf-8")
            if parts[0] == "derived":   # o comportamento das derivadas vem do simulador
                text = text.replace("</body>", '<script src="/sim.js"></script></body>')
            data, kind = text.encode("utf-8"), "text/html; charset=utf-8"
        else:
            self.send_error(404)
            return None
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        return io.BytesIO(data)


class CorpusServer:
    def __init__(self):
        build_derived()
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(_Handler))
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def url(self, entry: dict) -> str:
        return f"http://127.0.0.1:{self.port}/{entry.get('root', 'corpus')}/{entry['file']}"

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


class FakeClaude:
    """Claude CLI simulada: devolve as respostas do manifesto, na ordem, e guarda o que recebeu."""

    def __init__(self, replies):
        self.replies, self.prompts = list(replies), []

    def __call__(self, cfg, text, **kwargs):
        self.prompts.append(text)
        if not self.replies:
            raise AssertionError("consulta inesperada ao Claude")
        reply = self.replies.pop(0)
        return (reply if isinstance(reply, str) else json.dumps(reply, ensure_ascii=False)), 0.0


def marked(question) -> list:
    """O que está marcado na página, no formato da resposta do contrato."""
    if question.kind in ("SINGLE", "MULTI"):
        return [o.index for o in question.options if o.checked]
    if question.kind == "DROPDOWN":
        return [next((c.index for c in item.options if c.selected), None) for item in question.items]
    return [side.linked for side in question.right]


def wanted(answer: dict) -> list:
    if answer["type"] in ("SINGLE", "MULTI"):
        return sorted(answer["answers"])
    if answer["type"] == "DROPDOWN":
        return [it["option"] for it in sorted(answer["items"], key=lambda it: it["item"])]
    return [p["left"] for p in sorted(answer["pairs"], key=lambda p: p["right"])]


def measure(page, server: CorpusServer, entry: dict, log=None) -> dict:
    """Roda o motor e o laço de resposta numa fixture. Devolve a linha da tabela de cobertura."""
    logs: list[str] = []
    log = log or logs.append
    page.goto(server.url(entry))
    frame = page.main_frame
    adapter = GeneralAdapter()
    diag = adapter.diagnose(frame)
    row = {"file": entry["file"], "pattern": entry["pattern"], "kinds": [q["kind"] for q in diag["questions"]],
           "confidence": diag["confidence"], "layer": diag["layer"], "result": "", "detail": ""}
    if not diag["supported"]:
        ended = Guard(log, dry_run=True).result_visible(frame)
        row["result"] = "fim" if ended else "nao_suportado"
        row["detail"] = "tela de resultado: nada é clicado" if ended else diag["reason"]
        row["code"] = None if ended else diag["code"]
        return row
    answers = FakeClaude(entry.get("answers", ()))
    if diag["confidence"] < THRESHOLD:
        teacher = FakeClaude([{"toml": entry["profile"]}] if entry.get("profile") else [])
        try:
            got = autoprofile.learn(frame, page.url, teacher)
        except (autoprofile.AutoprofileError, AssertionError) as exc:
            row["result"], row["detail"] = "nao_suportado", f"confiança {diag['confidence']:.2f}, sem perfil ({exc})"
            return row
        adapter = GeneralAdapter(profile=profile.parse(got["draft_toml"]))
        row.update(layer=got["layer"], confidence=got["confidence"], draft_toml=got["draft_toml"],
                   teacher_prompts=teacher.prompts)
    outcomes = answer_visible(frame, adapter, answers, log, dry_run=False)
    row["outcomes"] = [o.status for o in outcomes]
    row["prompts"] = answers.prompts
    if any(o.status == "refused" for o in outcomes):
        row["result"], row["detail"] = "lida_guarda_recusa", next(o.reason for o in outcomes if o.status == "refused")
        return row
    state = [marked(adapter.extract(host)) for host in adapter.locate(frame)]
    expected = [wanted(a) for a in entry.get("answers", ())]
    ok = outcomes and all(o.status == "answered" for o in outcomes) and state == expected
    row["result"] = ("aprendida" if row["layer"] == "profile" else "respondida") if ok else "falhou"
    row["detail"] = "" if ok else f"marcado {state}, esperado {expected}, passos {row['outcomes']}"
    return row


def table(rows: list[dict]) -> str:
    """Tabela Markdown de cobertura."""
    lines = ["| Fixture | Padrão | Tipo detectado | Confiança | Camada | Resultado |",
             "|---|---|---|---|---|---|"]
    names = {"respondida": "respondida", "aprendida": "aprendida por autoperfil e respondida",
             "lida_guarda_recusa": "lida; a guarda recusa a ação", "nao_suportado": "não suportado", "fim": "para (fim)",
             "falhou": "FALHOU"}
    for r in rows:
        detail = f" ({r['detail']})" if r["detail"] and r["result"] in ("nao_suportado", "lida_guarda_recusa", "falhou") else ""
        lines.append(f"| {r['file']} | {r['pattern']} | {', '.join(r['kinds']) or '-'} | "
                     f"{r['confidence']:.2f} | {r['layer']} | {names[r['result']]}{detail} |")
    return "\n".join(lines)
