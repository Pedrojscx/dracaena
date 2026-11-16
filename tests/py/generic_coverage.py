"""Medição somente leitura de variantes sintéticas de prática."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from fx import REPO
from corpus import CorpusServer, ROOTS
from web import launch
from playwright.sync_api import sync_playwright
from dracaena.adapters.general import GeneralAdapter
from dracaena.adapters.heuristic import HeuristicAdapter
from dracaena.core.errors import AdapterError

ROOT = REPO / "tests" / "fixtures" / "generic"
ADAPTERS = {"heuristic": HeuristicAdapter, "general": GeneralAdapter}


def manifest():
    return json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))["fixtures"]


class GenericServer(CorpusServer):
    def __init__(self):
        self.roots_patch = patch.dict(ROOTS, {"generic": ROOT})
        self.roots_patch.start()
        try:
            super().__init__()
        except Exception:
            self.roots_patch.stop()
            raise

    def close(self):
        try:
            super().close()
        finally:
            self.roots_patch.stop()


def snapshot(page):
    return [frame.content() for frame in page.frames]


def inspect(page, server, entry, adapter_name):
    response = page.goto(server.url(entry))
    if response.status != 200:
        raise AssertionError("fixture não carregada")
    before = snapshot(page)
    adapter = ADAPTERS[adapter_name]()
    rows, errors = [], []
    try:
        for host in adapter.locate(page.main_frame):
            try:
                q = adapter.extract(host)
                rows.append({"kind": q.kind, "alternatives": [len(i.options) for i in q.items]
                             if q.kind == "DROPDOWN" else len(q.options),
                             "expected_count": q.expected, "stem_present": bool(q.stem.strip()),
                             "confidence": getattr(q, "confidence", None)})
            except AdapterError as exc:
                errors.append(type(exc).__name__)
    except AdapterError as exc:
        errors.append(type(exc).__name__)
    if snapshot(page) != before:
        raise AssertionError("a leitura alterou o documento")
    negative = entry["expected_type"] == "não suportado"
    if negative:
        status = "ok" if not rows and not errors else "falha"
    elif not rows:
        status = "falha"
    else:
        exact = len(rows) == 1 and not errors and rows[0]["kind"] == entry["expected_type"]
        exact = exact and rows[0]["alternatives"] == entry["alternatives"]
        exact = exact and rows[0]["expected_count"] == entry["expected_count"] and rows[0]["stem_present"]
        exact = exact and (rows[0]["confidence"] is None or rows[0]["confidence"] >= 0.6)
        status = "ok" if exact else "parcial"
    return {"status": status, "questions": rows, "errors": errors}


def report(entries):
    lines = ["# Cobertura sintética genérica", "",
             "Base medida: `e44b6aa`. Adaptadores sem perfil; nenhuma consulta externa ou ação durante a medição.", "",
             "Reproduzir: `PYTHONPATH=lib:tests/py python tests/py/generic_coverage.py`.",
             "Para atualizar a tabela e observações: acrescente `--write`.", "",
             "`ok`: tipo, cardinalidade, contagem MULTI e enunciado presentes (confiança >= 0,6 no generalizado).",
             "`parcial`: encontrou questão, mas algum desses critérios divergiu. `falha`: não encontrou a questão esperada.",
             "Nas negativas, `ok` significa recusa correta: nenhuma questão proposta. Não significa suporte ao controle.",
             "A chamada é `locate(page.main_frame)`: a travessia de iframe deve ser feita pelo próprio adaptador.",
             "A medição não prova resposta correta, navegação nem detecção de fim pela guarda.", "",
             "| Tipo de tela | Fixture | Shadow / iframe | Heurístico | GeneralAdapter | Observação medida |",
             "| --- | --- | --- | --- | --- | --- |"]
    for e in entries:
        observations = e["observed"]
        details = []
        for name, value in observations.items():
            summary = ", ".join(f"{q['kind']}:{q['alternatives']}, contagem={q['expected_count']}" for q in value["questions"])
            details.append(f"{name}: {summary or 'nenhuma questão'}" + (f"; erros={value['errors']}" if value["errors"] else ""))
        lines.append(f"| {e['pattern']} | `{e['file']}` | {'sim' if e['shadow'] else 'não'} / {'sim' if e['iframe'] else 'não'} | "
                     f"{observations['heuristic']['status']} | {observations['general']['status']} | {'; '.join(details)} |")
    lines += ["", "## Diferenças em relação ao corpus existente", "",
              "Os tipos básicos já existem no corpus. Estes arquivos acrescentam variantes estruturais, sem copiar ou alterar o corpus ou compat.", ""]
    lines += [f"- `{e['file']}`: {e['delta']}" for e in entries]
    lines += ["", "O manifesto usa inteiro para alternativas de escolha e lista por lacuna para DROPDOWN; placeholders não contam.",
              "Nas negativas, o número descreve controles candidatos na página, sem afirmar que são alternativas suportadas.",
              "`paginas_locais.html` contém duas etapas, mas a medição inicial considera só a primeira; o botão Próxima não é acionado.",
              "Seleção ARIA é verificada separadamente pelos testes, sempre por Guard.perform.", ""]
    return "\n".join(lines)


def main():
    import sys
    entries = manifest()
    server = GenericServer()
    try:
        with sync_playwright() as pw:
            browser = launch(pw)
            try:
                page = browser.new_page()
                for entry in entries:
                    entry["observed"] = {name: inspect(page, server, entry, name) for name in ADAPTERS}
            finally:
                browser.close()
    finally:
        server.close()
    text = report(entries)
    if "--write" in sys.argv:
        (ROOT / "manifest.json").write_text(json.dumps({"fixtures": entries}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (ROOT / "COBERTURA.md").write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
