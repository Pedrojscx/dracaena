"""Diagnóstico DOM somente leitura, sem expor dados da conta ou da questão."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from . import browser, cdp, claude, config, dom


def run() -> int:
    failures = 0

    def report(ok, label, remedy=""):
        nonlocal failures
        failures += not ok
        print(f"[{'OK' if ok else 'FALHA'}] {label}" + (f"; {remedy}" if not ok and remedy else ""))

    report(sys.version_info >= (3, 10), "Python 3.10+")
    report(sys.prefix != sys.base_prefix, "ambiente virtual", "execute ./install.sh")
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        report(False, "Playwright", "execute ./install.sh")
        return 1
    report(True, "Playwright importável")
    try:
        cfg = config.load()
        port = int(cfg.get("CDP_PORT", 9222))
        if not 1 <= port <= 65535:
            raise ValueError()
    except (OSError, ValueError):
        report(False, "configuração inválida (valores omitidos)", "revise a configuração pessoal")
        return 1
    report(True, "configuração")
    for name in ("system", "answer", "retry", "invalid"):
        report((config.REPO / "prompts" / f"{name}.txt").is_file(), f"prompt {name}")
    for name in ("quiz-loop", "quiz-ask", "quiz-doctor", "quiz-browser"):
        target = config.REPO / "bin" / name
        link = Path.home() / ".local/bin" / name
        report(target.is_file() and os.access(target, os.X_OK), f"comando {name}")
        report(link.is_symlink() and link.resolve() == target, f"symlink {name}", "execute ./install.sh")
    for name in ("notify-send", "wl-copy"):
        print(f"[{'OK' if shutil.which(name) else 'OPCIONAL'}] {name}")
    try:
        executable = claude.claude_bin(cfg)
        report(True, "Claude Code")
        status = subprocess.run([executable, "auth", "status", "--json"], capture_output=True, text=True, timeout=10)
        logged = status.returncode == 0 and json.loads(status.stdout).get("loggedIn") is True
        report(logged, "autenticação Claude", "execute claude auth login e repita o diagnóstico")
    except (claude.ClaudeError, OSError, ValueError, subprocess.SubprocessError):
        report(False, "Claude Code/autenticação indisponível (saída omitida)", "verifique instalação e claude auth login")
    profile = config.data_dir() / "vivaldi-profile"
    report(profile.is_dir(), "diretório do perfil dedicado", "execute quiz-browser")
    # Confere o processo local que foi lançado com esse perfil e essa porta.
    dedicated = False
    for proc in Path('/proc').glob('[0-9]*/cmdline'):
        try:
            args = proc.read_bytes().decode(errors='replace').split('\0')
            dedicated |= f"--user-data-dir={profile}" in args and f"--remote-debugging-port={port}" in args
        except OSError:
            continue
    report(dedicated, "navegador com perfil dedicado e porta configurada", "abra pelo quiz-browser")
    try:
        result = subprocess.run([str(config.REPO / "bin/quiz-browser"), "--status"],
                                capture_output=True, text=True, timeout=10)
        report(result.returncode == 0, "porta CDP somente em loopback", "execute quiz-browser --status")
        if result.returncode != 0:
            return 1
        cdp.version(port)
        report(True, "resposta válida de /json/version")
        with sync_playwright() as pw:
            br = browser.connect(pw, port)
            report(True, "conexão CDP")
            page = browser.find_tab(br)
            report(True, "uma aba compatível do NetAcad")
            tab = browser.revalidate(page)
            report(True, "iframe da atividade acessível")
            loc = dom.locate(tab.frame, tab.item)
            if loc.host is not None:
                q = dom.extract(loc.host)
                report(q.get("kind") != "UNSUPPORTED" and bool(q.get("stem")), "leitura da questão atual (conteúdo omitido)")
            elif loc.final or loc.start or loc.done:
                print("[AVISO] atividade na tela inicial/final ou concluída; nenhuma questão lida")
            else:
                report(False, "questão atual não encontrada", "abra uma atividade suportada")
            # Sair do Playwright desconecta o cliente; não fecha o navegador do usuário.
    except Exception:
        report(False, "conexão, aba ou iframe indisponível (dados omitidos)", "abra a atividade no quiz-browser e faça login no NetAcad")
    print("OCR/Tesseract/grim/slurp/ydotool: dependências do modo legado, não exigidas pelo DOM.")
    return int(failures > 0)
