#!/usr/bin/env python3
"""Métrica de cobertura: roda o motor de leitura contra o corpus e imprime uma tabela por fixture.

Uso (na raiz do repositório): PYTHONPATH=lib:tests/py python tests/metric.py
Sai com 1 se alguma fixture der um resultado diferente do esperado no manifesto.
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent / "lib"), str(HERE / "py")]

from playwright.sync_api import sync_playwright  # noqa: E402

import corpus  # noqa: E402
from fx import launch  # noqa: E402


def main() -> int:
    server = corpus.CorpusServer()
    rows, wrong = [], []
    try:
        with sync_playwright() as pw:
            browser = launch(pw)
            for entry in corpus.manifest():
                page = browser.new_page()
                try:
                    row = corpus.measure(page, server, entry, log=lambda _msg: None)
                finally:
                    page.close()
                rows.append(row)
                if row["result"] != entry["expect"]["result"]:
                    wrong.append(f"{entry['file']}: {row['result']} (esperado {entry['expect']['result']}) {row['detail']}")
            browser.close()
    finally:
        server.close()
    print(corpus.table(rows))
    count = lambda name: sum(r["result"] == name for r in rows)  # noqa: E731
    print(f"\n{len(rows)} fixtures: {count('respondida')} respondidas, {count('aprendida')} aprendidas por autoperfil, "
          f"{count('lida_guarda_recusa')} lidas com recusa da guarda, {count('nao_suportado')} não suportadas, "
          f"{count('fim')} paradas no fim.")
    for line in wrong:
        print("DIFERENTE DO ESPERADO:", line, file=sys.stderr)
    return 1 if wrong else 0


if __name__ == "__main__":
    raise SystemExit(main())
