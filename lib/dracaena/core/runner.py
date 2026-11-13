"""Laço local de uma atividade de prática via CDP.

Este módulo só lê pela adaptação, consulta o Claude por índices e entrega
alvos à guarda. Sem ``--real``, a guarda fica em dry-run.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable

from playwright.sync_api import sync_playwright

from ..adapters.heuristic import HeuristicAdapter
from ..guard import Guard, Refused, ResultScreen
from ..platform.browser import read_port
from . import claude, contract


def _tab(contexts, contains: str):
    pages = [page for context in contexts for page in context.pages]
    found = [page for page in pages if contains in page.url]
    if len(found) != 1:
        raise RuntimeError(f"aba compatível: esperada uma, encontradas {len(found)}")
    return found[0]


def _answers(adapter, host, answer: dict):
    if answer["type"] in ("SINGLE", "MULTI"):
        return [adapter.target(host, "option", index) for index in answer["answers"]]
    if answer["type"] == "DROPDOWN":
        return [adapter.target(host, "dropdown", (item["item"], item["option"])) for item in answer["items"]]
    raise contract.ContractError(f"tipo de questão não suportado: {answer['type']}")


def run(port: int, url_contains: str, *, dry_run: bool = True, max_questions: int = 1,
        ask: Callable = claude.ask, log: Callable[[str], None] = print,
        playwright_factory=sync_playwright) -> int:
    """Executa até ``max_questions``. As dependências são injetáveis para testes."""
    if max_questions < 1:
        raise ValueError("--max-questions precisa ser maior que zero")
    with playwright_factory() as pw:
        browser = pw.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
        try:
            page = _tab(browser.contexts, url_contains)
            log(f"aba escolhida: {page.url}")
            adapter = HeuristicAdapter()
            done = 0
            while done < max_questions:
                if Guard(log, dry_run=dry_run).result_visible(page.main_frame):
                    log("parada: fim da atividade")
                    return 0
                hosts = adapter.locate(page.main_frame)
                log(f"hosts encontrados: {len(hosts)}")
                if not hosts:
                    log("parada: não suportado")
                    return 0
                host = hosts[0]
                question = adapter.extract(host)
                log(f"tipo da questão: {question.kind}")
                try:
                    prompt = claude.prompt("answer", contract.question_text(question))
                    raw, _ = ask({}, prompt, schema=contract.schema_for(question))
                    answer = contract.parse_validated(raw, question)
                except contract.ContractError as exc:
                    log(f"parada: resposta inválida ({exc})")
                    return 1
                log("resposta validada")
                guard = Guard(log, dry_run=dry_run)
                guard.bind(page.main_frame, host, question.id)
                try:
                    for target in _answers(adapter, host, answer):
                        guard.perform(target, target.label)
                except ResultScreen:
                    log("parada: fim da atividade")
                    return 0
                except Refused as exc:
                    log(f"parada: guarda recusou ({exc.reason})")
                    return 1
                done += 1
            log("parada: limite de questões")
            return 0
        finally:
            browser.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Executa uma atividade de prática pelo CDP")
    endpoint = parser.add_mutually_exclusive_group(required=True)
    endpoint.add_argument("--port", type=int)
    endpoint.add_argument("--profile")
    parser.add_argument("--url-contains", required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--real", action="store_true")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--max-questions", type=int, default=1)
    args = parser.parse_args(argv)
    port = args.port if args.port is not None else read_port(args.profile)
    maximum = 1 if args.once else args.max_questions
    return run(port, args.url_contains, dry_run=not args.real, max_questions=maximum)


if __name__ == "__main__":
    raise SystemExit(main())
