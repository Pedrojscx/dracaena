"""Linha de comando (chamada pelos scripts em bin/ com o Python do venv)."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

from . import config as configmod
from . import private, redact


def cmd_loop(a) -> int:
    from . import loop
    return loop.run(configmod.load(), dry_run=a.dry_run, once=a.once)


def cmd_ask(a) -> int:
    """Responde a questão atual da aba e só notifica (nenhum clique)."""
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import sync_playwright

    from . import browser, claude, contract, dom
    from .notify import notify
    cfg = configmod.load()
    with sync_playwright() as pw:
        try:
            tab = browser.attach(browser.connect(pw, int(cfg.get("CDP_PORT", 9222))))
            loc = dom.locate(tab.frame, tab.item)
            if loc.final or loc.host is None:
                raise browser.TabError(loc.reason or "nenhuma questão aberta")
            q = dom.extract(loc.host)
            images = dom.capture_figures(loc.host, q)
        except (browser.TabError, PlaywrightError, dom.FigureError) as exc:
            notify(f"quiz-ask: {str(exc).splitlines()[0]}", "critical", 8000, cfg)
            return 1
    if q["kind"] == "UNSUPPORTED":
        notify(f"quiz-ask: componente não suportado ({q['tag']})", "critical", 8000, cfg)
        return 1
    notify("quiz-ask: consultando o Claude...", "normal", 0, cfg)
    text = contract.question_text(q)
    try:
        out, secs = claude.ask(cfg, claude.prompt("answer", text), images=images or None)
        ans = contract.parse_validated(out, q)
    except (claude.ClaudeError, contract.ContractError) as exc:
        notify(f"quiz-ask: {exc}", "critical", 10000, cfg)
        return 1
    readable = contract.readable(ans, q)
    if shutil.which("wl-copy"):
        subprocess.run(["wl-copy"], input=readable, text=True, check=False)
    notify(f"{q.get('title') or 'Resposta'} ({secs:.1f}s)\n{readable}", "normal", 30000, cfg)
    print(readable)
    return 0


# Exemplos sintéticos de diagnóstico; não são questões de curso ou avaliação.
ENV_SAMPLES = {
    "conceitual": {"kind": "SINGLE", "title": "Teste sintético",
                   "stem": "In this invented example, the blue box contains a circle. Which box contains the circle?",
                   "options": [{"index": 0, "text": "red"}, {"index": 1, "text": "blue"},
                               {"index": 2, "text": "green"}, {"index": 3, "text": "yellow"}],
                   "expect": [1]},
    "cálculo": {"kind": "SINGLE", "title": "Teste sintético",
                "stem": "An invented counter starts at 12 and gains 7 units. What is its new value?",
                "options": [{"index": i, "text": str(n)} for i, n in enumerate((5, 7, 12, 18, 19, 20))],
                "expect": [4]},
}
ENV_KEYS = ("CLAUDE_CODE_TMPDIR", "XDG_RUNTIME_DIR", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "HOME",
            "WAYLAND_DISPLAY", "DISPLAY", "SHELL", "LANG", "ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL",
            "CLAUDE_CONFIG_DIR", "CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT")


def cmd_envquery(a) -> int:
    """(interno) Roda a etapa de consulta ao Claude e grava um relatório JSON; usado por envcheck."""
    import os
    import time
    from . import claude, contract
    rec: dict = {"cwd": os.getcwd(), "env": redact.environment(ENV_KEYS),
                 "claude_in_path": __import__("shutil").which("claude")}
    t0 = time.monotonic()
    try:
        try:
            cfg = configmod.load()
        except (OSError, ValueError):
            raise RuntimeError("configuração inválida; valores omitidos") from None
        q = ENV_SAMPLES[a.sample]
        prompt = claude.prompt("answer", contract.question_text(q))
        env, ccwd, _ = claude.claude_env(cfg)
        rec["claude_cwd"] = str(ccwd)
        rec["claude_tmp"] = env["CLAUDE_CODE_TMPDIR"]
        rec["cmd_flags"] = [c for c in claude.build_cmd(cfg, "<texto>")[:-1] if c.startswith("--") or c == "-p"]
        raw, secs = claude.ask(cfg, prompt)
        rec.update(raw=raw, secs=secs, reasoning=not raw.strip().startswith(("{", "```")))
        try:
            rec["answer"] = contract.parse_validated(raw, q)
        except contract.ContractError as exc:
            rec["invalid"] = str(exc)
    except Exception as exc:  # relatório sanitizado, inclusive falhas de preparação
        rec.update(error=f"{type(exc).__name__}: {exc}", secs=time.monotonic() - t0)
    private.write_text(Path(a.out), json.dumps(redact.data(rec), ensure_ascii=False, indent=1))
    return 0


def cmd_envcheck(a) -> int:
    """Roda a consulta ao Claude pelo terminal e por `hyprctl dispatch "hl.dsp.exec_cmd(...)"` e compara."""
    import os
    import subprocess
    import tempfile
    import time
    try:
        cfg = configmod.load()
    except (OSError, ValueError):
        print("[FALHA] configuração inválida; valores omitidos")
        return 1
    ok = True
    py = sys.executable
    lib = str(Path(__file__).resolve().parents[1])
    tmpd = Path(tempfile.mkdtemp(prefix="qh-envcheck-"))
    if "'" in py + lib + str(tmpd):
        print("caminho com aspas simples não é suportado pelo dispatch em Lua")
        return 2
    for name in ENV_SAMPLES:
        out_t, out_h = tmpd / f"{name}-terminal.json", tmpd / f"{name}-hyprctl.json"
        subprocess.run([py, "-m", "quizhelper", "envquery", name, str(out_t)], check=False,
                       env={**os.environ, "PYTHONPATH": lib}, stdin=subprocess.DEVNULL,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        shell = f"env PYTHONPATH={lib} {py} -m quizhelper envquery {name} {out_h}"
        r = subprocess.run(["hyprctl", "dispatch", f"hl.dsp.exec_cmd('{shell}')"], capture_output=True, text=True)
        if r.returncode != 0 or "ok" not in r.stdout:
            print(f"[FALHA] hyprctl dispatch: {redact.text((r.stdout + r.stderr).strip())}")
            return 1
        limit = time.monotonic() + float(cfg.get("CLAUDE_TIMEOUT", 45)) + 15
        while not out_h.exists() and time.monotonic() < limit:
            time.sleep(0.2)
        if not out_h.exists():
            print(f"[FALHA] {name}: a consulta via hyprctl não terminou")
            ok = False
            continue
        t, h = (redact.data(json.loads(p.read_text(encoding="utf-8"))) for p in (out_t, out_h))
        print(f"\n== questão {name}")
        for label, d in (("terminal", t), ("hyprctl ", h)):
            res = d.get("error") or d.get("invalid") or d.get("answer")
            print(f"  {label}: {d.get('secs', 0):.1f}s  raciocínio={'sim' if d.get('reasoning') else 'não'}  "
                  f"cwd={d['cwd']}  resultado={res}")
        diffs = {k: (t["env"].get(k), h["env"].get(k)) for k in sorted(set(t["env"]) | set(h["env"]))
                 if t["env"].get(k) != h["env"].get(k)}
        for k, (x, y) in diffs.items():
            print(f"  [AVISO] variável {k}: terminal={x!r} hyprctl={y!r}")
        for k in ("claude_in_path", "claude_cwd", "claude_tmp", "cmd_flags"):
            if t.get(k) != h.get(k):
                print(f"  [AVISO] {k} difere: terminal={t.get(k)!r} hyprctl={h.get(k)!r}")
        good = all("answer" in d for d in (t, h))
        same = t.get("answer") == h.get("answer")
        if not good:
            ok = False
            print("  [FALHA] alguma consulta não devolveu resposta válida (raw em " + str(tmpd) + ")")
        elif not same:
            ok = False
            print("  [FALHA] respostas diferentes entre terminal e hyprctl")
        elif ENV_SAMPLES[name]["expect"] != t["answer"]["answers"]:
            print(f"  [AVISO] resposta {t['answer']['answers']}, esperada {ENV_SAMPLES[name]['expect']}")
        else:
            print("  [  OK  ] mesma resposta válida pelos dois caminhos")
    print(f"\nrelatórios brutos: {tmpd}")
    print("RESULTADO:", "OK" if ok else "FALHA")
    return 0 if ok else 1


def cmd_bench_schema(a) -> int:
    """Compara texto livre (prompt com até 3 linhas de raciocínio) e --json-schema, sem clicar em nada."""
    from . import claude, contract
    cfg = configmod.load()
    rows = []
    for name, q in ENV_SAMPLES.items():
        text = contract.question_text(q)
        for mode in ("texto", "schema"):
            for i in range(a.n):
                schema = contract.schema_for(q) if mode == "schema" else None
                try:
                    raw, secs = claude.ask(cfg, claude.prompt("answer", text), schema=schema)
                    ans = contract.parse_validated(raw, q)
                    rows.append((name, mode, secs, ans["answers"] == q["expect"], "sim" if not raw.strip().startswith("{") else "não"))
                except Exception as exc:  # noqa: BLE001
                    rows.append((name, mode, 0.0, False, f"erro: {str(exc)[:60]}"))
    print("| questão | modo | n | tempo médio (s) | acertos | raciocínio antes do JSON |\n|---|---|---|---|---|---|")
    for name in ENV_SAMPLES:
        for mode in ("texto", "schema"):
            rs = [r for r in rows if r[0] == name and r[1] == mode]
            avg = sum(r[2] for r in rs) / len(rs)
            print(f"| {name} | {mode} | {len(rs)} | {avg:.1f} | {sum(r[3] for r in rs)}/{len(rs)} | "
                  f"{sum(r[4] == 'sim' for r in rs)}/{len(rs)} |")
    return 0


def cmd_config(a) -> int:
    print(json.dumps(configmod.load(), ensure_ascii=False))
    return 0


def cmd_timings(a) -> int:
    """Tabela (markdown) dos tempos por etapa de cada questão de uma execução."""
    path = Path(a.run_dir) / "questions.jsonl"
    rows = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()] if path.exists() else []
    if not rows:
        print("sem questões registradas")
        return 1
    keys: list[str] = []
    for r in rows:
        keys += [k for k in r["timing"] if k not in keys]
    keys.sort(key=lambda k: (k == "fora do Claude", k))
    print("| etapa | " + " | ".join(f"Q{r['q']}" for r in rows) + " |")
    print("|---|" + "---|" * len(rows))
    for k in keys:
        print(f"| {k} | " + " | ".join(f"{r['timing'][k]:.2f}" if k in r["timing"] else "" for r in rows) + " |")
    return 0


def cmd_summary(a) -> int:
    """Resumo de um run (por tipo, raciocínio, tempos, pausas) e `answers.json` com todas as respostas."""
    import re
    from collections import defaultdict
    run = Path(a.run_dir)
    rows = [json.loads(x) for x in (run / "questions.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    answers = []
    for r in rows:
        f = run / "claude" / f"Q{r['q']:03d}.txt"
        sent = ""
        if f.exists():
            m = re.search(r"--- texto enviado ---\n(.*?)\n--- saída bruta", f.read_text(encoding="utf-8"), re.S)
            sent = m.group(1) if m else ""
            m2 = re.search(r"\nTipo: .*", sent, re.S)
            sent = m2.group(0).strip() if m2 else sent
        answers.append({"q": r["q"], "label": r["label"], "key": r["key"], "kind": r["kind"], "answer": r["answer"],
                        "readable": r["readable"], "reasoning": r.get("reasoning"), "model": r.get("model"), "verdict": r["verdict"],
                        "question_text": sent})
    private.write_text(run / "answers.json", json.dumps(answers, ensure_ascii=False, indent=1))
    by = defaultdict(list)
    for r in rows:
        by[r["kind"]].append(r)
    print(f"{len(rows)} questões respondidas; respostas em {run / 'answers.json'}\n")
    print("| tipo | questões | com raciocínio | tempo médio do Claude (s) | máx (s) |\n|---|---|---|---|---|")
    for k, rs in sorted(by.items()):
        ts = [r["timing"].get("claude", 0) for r in rs]
        print(f"| {k} | {len(rs)} | {sum(bool(r.get('reasoning')) for r in rs)} | {sum(ts) / len(ts):.1f} | {max(ts):.1f} |")
    allt = [r["timing"].get("claude", 0) for r in rows]
    print(f"| todas | {len(rows)} | {sum(bool(r.get('reasoning')) for r in rows)} | {sum(allt) / len(allt):.1f} | {max(allt):.1f} |")
    sc = run / "score.json"
    if sc.exists():
        d = json.loads(sc.read_text(encoding="utf-8"))
        print(f"\nnota: {d['score_percent']}% ({'aprovado' if d.get('passed') else 'reprovado'}); por objetivo: "
              f"{d.get('by_objective_percent')}")
    log = (run / "run.log").read_text(encoding="utf-8")
    pauses = re.findall(r"^(\d{4}-\d\d-\d\d (\d\d:\d\d:\d\d)) pausado: (.*)$", log, re.M)
    print(f"\npausas: {len(pauses)}")
    for _, hhmm, why in pauses:
        print(f"  {hhmm} {why[:150]}")
    invalid = len(re.findall(r"resposta inválida \(", log))
    print(f"respostas inválidas (reparadas ou não): {invalid}")
    return 0


def cmd_doctor(a) -> int:
    from .doctor import run
    return run()


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="quizhelper")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("doctor", help="diagnóstico DOM/CDP somente leitura")
    c.set_defaults(func=cmd_doctor)
    c = sub.add_parser("loop", help="responde as questões da aba do quiz até o fim")
    c.add_argument("--dry-run", action="store_true", help="lê e consulta, mas a guarda não clica")
    c.add_argument("--once", action="store_true", help="só uma questão")
    c.set_defaults(func=cmd_loop)
    c = sub.add_parser("ask", help="responde a questão atual e só notifica")
    c.set_defaults(func=cmd_ask)
    c = sub.add_parser("envquery", help="(interno) consulta de teste do envcheck")
    c.add_argument("sample", choices=sorted(ENV_SAMPLES))
    c.add_argument("out")
    c.set_defaults(func=cmd_envquery)
    c = sub.add_parser("envcheck", help="consulta ao Claude pelo terminal e pelo hyprctl, comparadas")
    c.set_defaults(func=cmd_envcheck)
    c = sub.add_parser("bench-schema", help="texto livre x --json-schema (tempo e acerto)")
    c.add_argument("-n", type=int, default=3)
    c.set_defaults(func=cmd_bench_schema)
    c = sub.add_parser("summary", help="resumo de um run e answers.json")
    c.add_argument("run_dir")
    c.set_defaults(func=cmd_summary)
    c = sub.add_parser("config", help="configuração efetiva em JSON")
    c.set_defaults(func=cmd_config)
    c = sub.add_parser("timings", help="tabela de tempos por etapa de uma execução")
    c.add_argument("run_dir")
    c.set_defaults(func=cmd_timings)
    return p


def main(argv: list[str] | None = None) -> int:
    a = build_parser().parse_args(argv)
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
