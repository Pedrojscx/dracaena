"""`dracaena aprender`: lê a atividade aberta e, se a heurística não bastar, aprende um perfil.

Só lê a página (nenhum clique, nenhuma digitação, nenhuma escolha). Grava o
perfil apenas com --salvar, por `platform.sites.save`, fora do repositório.

Saída: uma linha JSON.
    {"ok": true, "data": {"matches", "questions", "draft_toml", "layer", "confidence", "saved"}}
    {"ok": false, "error": "...", "code": "no_browser|no_site|bad_request|exists|cancelled|internal"}
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable

from ..core import claude
from . import autoprofile


def _say(out: Callable[[str], None], payload: dict) -> int:
    out(json.dumps(payload, ensure_ascii=False))
    return 0 if payload["ok"] else 1


def run(port: int, url_contains: str, *, save: str | None = None, overwrite: bool = False,
        ask: Callable = claude.ask, cfg: dict | None = None, playwright_factory=None,
        out: Callable[[str], None] = print) -> int:
    """As dependências são injetáveis para os testes."""
    from ..platform import sites
    if save is not None:
        try:
            sites.validate(save, "", overwrite)
        except ValueError as exc:
            return _say(out, {"ok": False, "error": str(exc), "code": "bad_request"})
    if playwright_factory is None:
        from playwright.sync_api import sync_playwright as playwright_factory
    try:
        with playwright_factory() as pw:
            try:
                browser = pw.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
            except Exception:  # noqa: BLE001 - qualquer falha de conexão é "sem navegador"
                return _say(out, {"ok": False, "error": "Nenhum navegador com a prática aberta foi encontrado.",
                                  "code": "no_browser"})
            try:
                pages = [p for ctx in browser.contexts for p in ctx.pages if url_contains in p.url]
                if len(pages) != 1:
                    return _say(out, {"ok": False, "code": "no_site",
                                      "error": f"Aba compatível: esperada uma, encontradas {len(pages)}."})
                page = pages[0]
                got = autoprofile.learn(page.main_frame, page.url, ask, cfg)
            finally:
                browser.close()
    except autoprofile.AutoprofileError as exc:
        return _say(out, {"ok": False, "error": exc.msg, "code": exc.code})
    except claude.ClaudeError as exc:
        return _say(out, {"ok": False, "error": f"Falha do Claude ({exc})", "code": "internal"})
    except Exception:  # falhas inesperadas não expõem conteúdo da página
        return _say(out, {"ok": False, "error": "Não foi possível ler a atividade.", "code": "internal"})
    data = {key: got[key] for key in ("matches", "questions", "draft_toml", "layer", "confidence")}
    data["saved"] = None
    if save is not None and got["draft_toml"]:
        try:
            data["saved"] = sites.save(save, got["draft_toml"], overwrite)["path"]
        except sites.SiteExists as exc:
            return _say(out, {"ok": False, "error": str(exc), "code": "exists"})
        except (ValueError, OSError) as exc:
            return _say(out, {"ok": False, "error": str(exc), "code": "bad_request"})
    return _say(out, {"ok": True, "data": data})


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="dracaena aprender",
                                     description="Aprende um perfil para a atividade aberta (só lê a página).")
    endpoint = parser.add_mutually_exclusive_group(required=True)
    endpoint.add_argument("--port", type=int, help="porta CDP do navegador")
    endpoint.add_argument("--profile", help="diretório do perfil do navegador (lê DevToolsActivePort)")
    parser.add_argument("--url-contains", required=True, help="trecho do endereço da aba da atividade")
    parser.add_argument("--salvar", metavar="SLUG", help="grava o perfil em sites/<SLUG>.toml")
    parser.add_argument("--overwrite", action="store_true", help="substitui um perfil já salvo com esse nome")
    args = parser.parse_args(argv)
    port = args.port
    if port is None:
        from ..platform.browser import read_port
        try:
            port = read_port(args.profile)
        except Exception:  # noqa: BLE001 - perfil sem navegador aberto
            return _say(print, {"ok": False, "error": "Nenhum navegador aberto com esse perfil.", "code": "no_browser"})
    return run(port, args.url_contains, save=args.salvar, overwrite=args.overwrite)


if __name__ == "__main__":
    raise SystemExit(main())
