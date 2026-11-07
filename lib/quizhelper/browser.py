"""Conexão com o Vivaldi do perfil dedicado (CDP em 127.0.0.1) e a aba do quiz."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

QUIZ_FRAME = "https://www.netacad.com/authoring-resources/index.html"
LAUNCH = "https://www.netacad.com/launch"


class TabError(RuntimeError):
    pass


def connect(pw, port: int):
    return pw.chromium.connect_over_cdp(f"http://127.0.0.1:{port}", timeout=15000)


def find_tab(browser):
    pages = [pg for c in browser.contexts for pg in c.pages if pg.url.startswith(LAUNCH)]
    if not pages:
        raise TabError("nenhuma aba do NetAcad aberta no Vivaldi do quiz-helper (quiz-browser)")
    if len(pages) > 1:
        raise TabError(f"{len(pages)} abas do NetAcad abertas; deixe só a do quiz")
    return pages[0]


def quiz_frame(page):
    for f in page.frames:
        if f.url.startswith(QUIZ_FRAME):
            return f
    return None


@dataclass
class Tab:
    page: object
    frame: object
    title: str
    item: str | None            # nome do item (seção do curso), do título da aba


def attach(browser) -> Tab:
    page = find_tab(browser)
    return revalidate(page)


def revalidate(page) -> Tab:
    """Revalida a aba: aberta, no domínio do NetAcad e com iframe do conteúdo."""
    if page.is_closed():
        raise TabError("a aba do quiz foi fechada")
    host = urlparse(page.url).netloc
    if host != "www.netacad.com":
        raise TabError(f"a aba saiu do NetAcad ({host or page.url[:40]})")
    title = page.title()
    frame = quiz_frame(page)
    if frame is None:
        raise TabError("o quiz ainda não carregou (iframe do conteúdo ausente)")
    item = title.split(" - ", 1)[1].strip() if " - " in title else None
    return Tab(page, frame, title, item)
