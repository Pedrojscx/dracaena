#!/usr/bin/env python3
"""Verificação de 12 casos do AppImage fase 1 (CLI e daemon).

Uso (da raiz do repositório):
    python3 -I packaging/appimage/check-cases.py [caminho/do/arquivo.AppImage]

Sem argumento, usa dist/appimage/dracaena-x86_64.AppImage.
Cada caso roda com `env -i`: PATH só com `fusermount` (se existir), HOME e
TMPDIR em diretório temporário novo. Casos: 2 modos (FUSE e
--appimage-extract-and-run) x 2 alvos (arquivo direto e link simbólico) x 3
comandos (--help, --version, doctor). Também confere o resíduo da extração em
TMPDIR e imprime HEAD e SHA-256 do artefato verificado. Sai com 0 só se tudo passar.
"""
import hashlib
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile

SUBCOMANDOS = {"daemon", "install-browser", "loop", "ask", "toggle", "stop", "status", "doctor", "probe", "once"}
ESPERADO = {"--help": 0, "--version": 0, "doctor": 1}


def main():
    raiz_repo = pathlib.Path(__file__).resolve().parents[2]
    padrao = raiz_repo / "dist" / "appimage" / "dracaena-x86_64.AppImage"
    app = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else padrao).resolve()
    if not app.is_file():
        sys.exit(f"artefato não encontrado: {app}")

    tmp = pathlib.Path(tempfile.mkdtemp(prefix="appimage-check-"))
    try:
        return rodar(app, raiz_repo, tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def rodar(app, raiz_repo, tmp):
    (tmp / "bin").mkdir()
    (tmp / "home").mkdir()
    (tmp / "tmp").mkdir()
    fusermount = shutil.which("fusermount") or shutil.which("fusermount3")
    if fusermount:
        (tmp / "bin" / "fusermount").symlink_to(fusermount)
    link = tmp / "dracaena"
    link.symlink_to(app)

    falhas = []
    n = 0
    for modo in ("fuse", "extract"):
        for rotulo, alvo in (("direto", app), ("link", link)):
            for arg in ("--help", "--version", "doctor"):
                env = ["PATH=" + str(tmp / "bin"), "HOME=" + str(tmp / "home"), "TMPDIR=" + str(tmp / "tmp")]
                cmd = ["/usr/bin/env", "-i", *env, str(alvo)]
                if modo == "extract":
                    cmd.append("--appimage-extract-and-run")
                cmd.append(arg)
                p = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
                n += 1
                erro = None
                if p.returncode != ESPERADO[arg]:
                    erro = f"exit {p.returncode}, esperado {ESPERADO[arg]}"
                elif p.stderr:
                    erro = "stderr não vazio: " + p.stderr[:200]
                elif arg == "--help":
                    linhas = [x.strip() for x in p.stdout.splitlines()]
                    faltam = sorted(s for s in SUBCOMANDOS if not any(x.startswith(s + " ") for x in linhas))
                    if faltam:
                        erro = "subcomandos ausentes no --help: " + ", ".join(faltam)
                elif arg == "--version":
                    if not p.stdout.startswith("dracaena ") or len(p.stdout.split()) != 2:
                        erro = "saída inesperada: " + p.stdout[:80]
                else:
                    try:
                        if json.loads(p.stdout).get("ok") is not False:
                            erro = "doctor deveria ter ok=false"
                    except ValueError:
                        erro = "doctor não devolveu JSON"
                print(f"{'FALHA' if erro else 'OK   '} {n:2d} {modo:7s} {rotulo:6s} {arg:9s} exit {p.returncode}"
                      + (f"  {erro}" if erro else ""), flush=True)
                if erro:
                    falhas.append((n, erro))

    residuo = list((tmp / "tmp").glob("appimage_extracted_*"))
    print(f"resíduo em TMPDIR após --appimage-extract-and-run: {len(residuo)} diretório(s)")
    if not residuo:
        falhas.append((0, "esperava resíduo appimage_extracted_* em TMPDIR"))

    head = subprocess.run(["git", "-C", str(raiz_repo), "rev-parse", "--short", "HEAD"],
                          capture_output=True, text=True).stdout.strip() or "?"
    sha = hashlib.sha256(app.read_bytes()).hexdigest()
    print(f"HEAD {head}  sha256 {sha}  bytes {app.stat().st_size}")
    print(f"RESULTADO: {'OK' if not falhas else 'FALHOU'} ({n - len([f for f in falhas if f[0]])}/{n} casos)")
    return 0 if not falhas else 1


if __name__ == "__main__":
    sys.exit(main())
