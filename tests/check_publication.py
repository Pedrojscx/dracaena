#!/usr/bin/env python3
"""Detecta arquivos locais e padrões de credenciais sem imprimir seus valores.

Por padrão analisa rastreados e novos não ignorados. --tracked restringe ao Git.
Não substitui revisão humana nem detecta todos os formatos de segredo.
"""
from __future__ import annotations
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATTERNS = (
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"sk-(?:ant-)?[A-Za-z0-9_-]{20,}|AKIA[A-Z0-9]{16}"),
    re.compile(r"-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----"),
    re.compile(r"(?i)(?:api[_-]?key|password|token|secret)\s*[=:]\s*['\"][A-Za-z0-9_+/=-]{24,}['\"]"),
)


def main():
    args = ['git', 'ls-files', '-z', '--cached']
    if '--tracked' not in sys.argv:
        args += ['--others', '--exclude-standard']
    files = sorted(set(filter(None, subprocess.check_output(args, cwd=ROOT).decode().split('\0'))))
    bad = []
    # As regras também são aplicadas aos já rastreados: .gitignore não os remove.
    ignored = subprocess.run(['git', 'check-ignore', '--no-index', '--stdin'], cwd=ROOT,
                             input='\n'.join(files) + '\n', text=True, capture_output=True)
    bad += [(name, 'arquivo local/gerado coberto pelo .gitignore') for name in ignored.stdout.splitlines()]
    for name in files:
        path = ROOT / name
        if not path.is_file():
            continue
        for line, content in enumerate(path.read_text(errors='replace').splitlines(), 1):
            if any(pattern.search(content) for pattern in PATTERNS):
                bad.append((f'{name}:{line}', 'possível credencial; valor omitido'))
    for name, reason in bad:
        print(f'{name}: {reason}')
    print(f'Publicação: {len(files)} arquivos examinados, {len(bad)} ocorrências.')
    return int(bool(bad))


if __name__ == '__main__':
    raise SystemExit(main())
