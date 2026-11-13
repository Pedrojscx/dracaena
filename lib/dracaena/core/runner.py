"""Laço local de uma atividade de prática via CDP.

Este módulo só lê pela adaptação, consulta o Claude por índices e entrega
alvos à guarda. Sem ``--real``, a guarda fica em dry-run.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import time
from collections.abc import Callable
from pathlib import Path

from playwright.sync_api import sync_playwright

from ..adapters.heuristic import HeuristicAdapter
from ..guard import Guard, Refused, ResultScreen
from ..platform.browser import read_port
from ..platform.paths import data_dir, private_dir
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


def default_record_path(today=None) -> Path:
    day = today or dt.date.today()
    return data_dir() / "revisao" / f"{day:%Y-%m-%d}.jsonl"


def _rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"registro inválido na linha {number}") from exc
        if not isinstance(row, dict):
            raise ValueError(f"registro inválido na linha {number}")
        rows.append(row)
    return rows


def _chosen(question, answer: dict) -> list[dict]:
    if answer["type"] in ("SINGLE", "MULTI"):
        return [{"index": index, "text": question.options[index].text} for index in answer["answers"]]
    if answer["type"] == "DROPDOWN":
        return [{"item": item["item"], "index": item["option"],
                 "text": question.items[item["item"]].options[item["option"]].text} for item in answer["items"]]
    return []


def record_review(question, answer: dict, path: Path) -> bool:
    """Acrescenta uma revisão dry-run, sem duplicar uma questão já registrada."""
    path = Path(path)
    rows = _rows(path)
    if question.id in {str(row.get("question_id", "")) for row in rows}:
        return False
    private_dir(path.parent)
    row = {"order": len({str(old.get("question_id", "")) for old in rows}) + 1,
           "question_id": question.id, "kind": question.kind, "stem": question.stem,
           "options": [{"index": opt.index, "text": opt.text} for opt in question.options],
           "chosen": _chosen(question, answer), "dry_run": True}
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as out:
        out.write(json.dumps(row, ensure_ascii=False) + "\n")
    return True


def review(path: Path, output: Callable[[str], None] = print) -> int:
    rows = _rows(Path(path))
    output("Nº  Enunciado                                                                          Alternativa")
    for row in rows:
        stem = str(row.get("stem", "")).replace("\n", " ")
        stem = stem[:77] + "..." if len(stem) > 80 else stem
        chosen = "; ".join(str(item.get("text", "")) for item in row.get("chosen", []))
        output(f"{row.get('order', '?'):>2}  {stem:<80} {chosen}")
    count = len({str(row.get("question_id", "")) for row in rows if row.get("question_id")})
    if count != 20:
        output(f"aviso: há {count} questões distintas; esperadas 20")
    return 0


def run(port: int, url_contains: str, *, dry_run: bool = True, max_questions: int = 1,
        ask: Callable = claude.ask, log: Callable[[str], None] = print,
        playwright_factory=sync_playwright, record_path: Path | None = None, wait_seconds: float = 180,
        sleep: Callable[[float], None] = time.sleep, monotonic: Callable[[], float] = time.monotonic) -> int:
    """Executa até ``max_questions``. As dependências são injetáveis para testes."""
    if max_questions < 1 or wait_seconds < 0:
        raise ValueError("--max-questions precisa ser maior que zero e --espera não pode ser negativa")
    with playwright_factory() as pw:
        browser = pw.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
        try:
            page = _tab(browser.contexts, url_contains)
            log(f"aba escolhida: {page.url}")
            adapter = HeuristicAdapter()
            done = 0
            previous_id = None
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
                if question.id == previous_id:
                    deadline = monotonic() + wait_seconds
                    while question.id == previous_id:
                        if Guard(log, dry_run=dry_run).result_visible(page.main_frame):
                            log("parada: fim da atividade")
                            return 0
                        if monotonic() >= deadline:
                            log("parada: sem avanço (a navegação entre questões é do humano)")
                            return 0
                        sleep(min(.2, max(0, deadline - monotonic())))
                        hosts = adapter.locate(page.main_frame)
                        if not hosts:
                            log("parada: fim da atividade" if Guard(log, dry_run=dry_run).result_visible(page.main_frame)
                                else "parada: não suportado")
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
                if dry_run:
                    path = record_path or default_record_path()
                    if record_review(question, answer, path):
                        log(f"revisão local: {path}")
                done += 1
                previous_id = question.id
            log("parada: limite de questões")
            return 0
        finally:
            browser.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Executa uma atividade de prática pelo CDP")
    endpoint = parser.add_mutually_exclusive_group()
    endpoint.add_argument("--port", type=int)
    endpoint.add_argument("--profile")
    parser.add_argument("--url-contains", required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--real", action="store_true")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--max-questions", type=int, default=1)
    parser.add_argument("--espera", type=float, default=180)
    parser.add_argument("--registro")
    parser.add_argument("--revisar", nargs="?", const="")
    args = parser.parse_args(argv)
    record = Path(args.registro) if args.registro else default_record_path()
    if args.revisar is not None:
        return review(Path(args.revisar) if args.revisar else record)
    if args.port is None and args.profile is None:
        parser.error("informe --port ou --profile")
    port = args.port if args.port is not None else read_port(args.profile)
    maximum = 1 if args.once else args.max_questions
    return run(port, args.url_contains, dry_run=not args.real, max_questions=maximum, record_path=record,
               wait_seconds=args.espera)


if __name__ == "__main__":
    raise SystemExit(main())
