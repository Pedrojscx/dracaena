"""A guarda: a ÚNICA função que age na página.

Toda ação (clicar numa alternativa, abrir/escolher num dropdown, ligar uma
associação, Submit, Reset) passa por `Guard.click`. Nenhum outro módulo chama
`.click()`, `.check()`, `.select_option()`, `.drag_to()`, `.press()` ou
`.dispatch_event()` (um teste confere isso no código-fonte).

Ordem das verificações, a cada ação:
1. `finalscreen-view` visível (tela de envio da avaliação) → encerra, sem clicar;
2. bloqueios explícitos (valem mesmo para elementos que pareçam permitidos):
   qualquer coisa dentro de `finalscreen-view`; `.adaptive-assessment-submit`;
   `#confirm-exam`, `#confirm-label` e qualquer `<input>`/`<label>` (o loop
   nunca clica em inputs: alternativas são o `div[role=radio|checkbox]`);
   "Submit Page", "Submit My Assessment", "Skip All", "Skip Question",
   "Go To ..." (troca de item do currículo), "Scroll Question strip",
   botões da faixa Q1..Qn; e a blocklist da configuração junto de "submit";
3. lista de permissão — só passa:
   a) dentro do componente da questão atual: `div.mcq__item[role=radio|checkbox]`,
      `button.dropdown__btn`, `li[role=option]`, botões da associação, e o
      `button.js-btn-action` com texto exatamente "Submit" (aria-label
      "Submit Your answer will be submitted"/"submit") ou um rótulo de
      RESET_WORDS ("Reset", "Try again", "Retry");
   b) `button.submit-button` dentro de `assessment-toolbar-view` ou `secure-toolbar-view`, texto
      exatamente "Submit", aria-label "submit";
   c) seta de avançar da navegação de questões: NENHUM elemento se qualifica
      (Fase 0: as setas da página são "Scroll Question strip" e "Go To ...",
      não avançam a questão; a avaliação avança sozinha após o Submit).
Qualquer outra coisa é recusada: o loop pausa e o log registra o seletor.
"""

from __future__ import annotations

from collections.abc import Callable

from .dom import js

ALLOWED_SUBMIT_LABELS = {"submit your answer will be submitted", "submit"}
BLOCK_PHRASES = ("submit page", "submit my assessment", "skip all", "skip question",
                 "confirm my submission", "selectedsubmit page")


class Refused(Exception):
    """Ação recusada pela guarda (o loop pausa)."""

    def __init__(self, reason: str, desc: str = ""):
        super().__init__(f"{reason}: {desc}" if desc else reason)
        self.reason, self.desc = reason, desc


class FinalScreen(Exception):
    """A tela de envio da avaliação apareceu: encerrar sem clicar."""


_CHECK = js(r"""
  const {el, host, block, resets} = arg;
  const lo = (s) => QH.norm(s).toLowerCase();
  const desc = (e) => { if (!e) return '(nenhum)';
    const cls = String(e.className || '').trim().split(/\s+/).filter(Boolean).slice(0, 4).join('.');
    const chainTags = QH.chain(e).slice(1, 6).map(c => c.tagName.toLowerCase()).join('<');
    return `${e.tagName.toLowerCase()}${e.id ? '#' + e.id : ''}${cls ? '.' + cls : ''}` +
           ` texto=${JSON.stringify(QH.text(e).slice(0, 60))} aria=${JSON.stringify(e.getAttribute('aria-label') || '')}` +
           ` em ${chainTags}`; };
  const no = (reason) => ({ok: false, reason, desc: desc(el)});
  if (!el || !el.isConnected) return no('elemento ausente ou desconectado');
  const chain = QH.chain(el);
  const tags = chain.map(c => c.tagName);
  const text = lo(QH.text(el)), aria = lo(el.getAttribute('aria-label') || '');
  const cls = (c) => el.classList.contains(c);
  // 1. tela de envio da avaliação
  if (QH.finalscreen(document)) return no('tela de envio da avaliação visível');
  if (tags.some(t => /(^|-)FINALSCREEN-VIEW$/.test(t))) return no('dentro de finalscreen-view');
  // 2. bloqueios explícitos
  if (cls('adaptive-assessment-submit')) return no('botão de envio da avaliação');
  if (el.id === 'confirm-exam' || el.id === 'confirm-label') return no('confirmação de envio');
  if (el.tagName === 'INPUT' || el.tagName === 'LABEL') return no('input/label nunca é clicado');
  if (el.matches('[type=checkbox]') && /confirm/.test(el.id + ' ' + aria + ' ' + text)) return no('checkbox de confirmação');
  if (cls('review-screen-button') || cls('block-button')) return no('faixa de questões');
  if (Array.from(el.classList).some(c => /^moduleNavBtn/.test(c))) return no('navegação entre itens do currículo');
  for (const p of %(phrases)s) if (text.includes(p) || aria.includes(p)) return no(`texto bloqueado (${p.trim()})`);
  for (const p of ['go to ', 'scroll question strip']) if (aria.startsWith(p)) return no(`navegação bloqueada (${p.trim()})`);
  const isButton = el.tagName === 'BUTTON' || el.getAttribute('role') === 'button';
  const words = (text + ' ' + aria).split(/[^a-z0-9]+/).filter(Boolean);
  if (isButton && words.includes('submit') && block.some(b => words.includes(b))) return no('Submit com palavra da blocklist');
  if (isButton && words.length && words.every(w => block.includes(w))) return no('rótulo da blocklist');
  // 3. lista de permissão
  const inHost = host && chain.includes(host);
  if (inHost) {
    if (el.tagName === 'DIV' && cls('mcq__item') && ['radio', 'checkbox'].includes(el.getAttribute('role'))) return {ok: true, kind: 'alternativa', desc: desc(el)};
    if (el.tagName === 'BUTTON' && cls('dropdown__btn')) return {ok: true, kind: 'abrir dropdown', desc: desc(el)};
    if (el.tagName === 'LI' && el.getAttribute('role') === 'option' && tags.includes('MATCHING-DROPDOWN-VIEW')) return {ok: true, kind: 'opção do dropdown', desc: desc(el)};
    if (el.tagName === 'BUTTON' && (cls('objectMatching-category-item') || cls('objectMatching-option-item'))) return {ok: true, kind: 'associação', desc: desc(el)};
    if (el.tagName === 'BUTTON' && cls('js-btn-action')) {
      const own = lo(QH.text(el));
      if (own === 'submit' && %(labels)s.includes(aria)) return {ok: true, kind: 'submit', desc: desc(el)};
      if (resets.includes(own)) return {ok: true, kind: 'reset', desc: desc(el)};
      return no('botão do componente com rótulo não permitido');
    }
    return no('elemento do componente fora da lista de permissão');
  }
  if (el.tagName === 'BUTTON' && cls('submit-button') && (tags.includes('ASSESSMENT-TOOLBAR-VIEW') || tags.includes('SECURE-TOOLBAR-VIEW'))) {
    if (lo(QH.text(el)) === 'submit' && aria === 'submit') return {ok: true, kind: 'submit', desc: desc(el)};
    return no('submit da barra com rótulo inesperado');
  }
  return no('fora da lista de permissão');
""".replace("%(phrases)s", repr(list(BLOCK_PHRASES)).replace("'", '"'))
   .replace("%(labels)s", repr(sorted(ALLOWED_SUBMIT_LABELS)).replace("'", '"')))


# Clique no DOM sobre o elemento que está de fato no centro do alvo: rola o
# alvo para a vista, acha o elemento visível naquele ponto (atravessando
# shadow roots) e só clica se ele for o próprio alvo ou um descendente dele
# (nada por cima). Não depende de a aba estar sendo desenhada: o "estável"
# do Playwright espera quadros de animação, que o Chromium suspende quando a
# janela está em outro workspace ou coberta.
_DOM_CLICK = js(r"""
  const el = arg;
  el.scrollIntoView({block: 'center', inline: 'nearest'});
  const r = el.getBoundingClientRect();
  if (r.width <= 0 || r.height <= 0) return {ok: false, why: 'alvo sem tamanho'};
  const x = r.left + r.width / 2, y = r.top + Math.min(r.height / 2, 20);
  let hit = document.elementFromPoint(x, y);
  while (hit && hit.shadowRoot) { const inner = hit.shadowRoot.elementFromPoint(x, y); if (!inner || inner === hit) break; hit = inner; }
  if (!hit) return {ok: false, why: 'nada no ponto do alvo'};
  if (!QH.chain(hit).includes(el)) return {ok: false, why: `outro elemento por cima: ${hit.tagName.toLowerCase()}.${String(hit.className || '').trim().split(/\s+/).join('.')}`};
  hit.click();
  return {ok: true};
""")


class Guard:
    """Única porta de ação na página. `log(msg)` registra cada decisão."""

    def __init__(self, frame, cfg: dict, log: Callable[[str], None], dry_run: bool = False):
        self.frame = frame
        self.block = [w.lower() for w in cfg.get("SUBMIT_WORDS_BLOCKLIST", [])]
        self.resets = [w.lower() for w in cfg.get("RESET_WORDS", [])]
        self.log = log
        self.dry_run = dry_run
        self.timeout_ms = int(cfg.get("ACTION_TIMEOUT_MS", 3000))
        self.clicks = 0

    def check(self, el, host) -> dict:
        if el is None:
            return {"ok": False, "reason": "alvo não encontrado", "desc": "(nenhum)"}
        return self.frame.evaluate(_CHECK, {"el": el, "host": host, "block": self.block, "resets": self.resets})

    def click(self, el, host, why: str) -> str:
        """Clica em `el` se a guarda permitir. Devolve o tipo permitido.

        Levanta FinalScreen se a tela de envio estiver visível e Refused em
        qualquer recusa (nada é clicado nesses casos)."""
        verdict = self.check(el, host)
        if not verdict.get("ok"):
            if verdict.get("reason", "").startswith("tela de envio"):
                self.log(f"guarda: tela de envio visível; nenhum clique ({why})")
                raise FinalScreen()
            self.log(f"guarda RECUSOU ({why}): {verdict['reason']} — {verdict['desc']}")
            raise Refused(verdict["reason"], verdict["desc"])
        if self.dry_run:
            self.log(f"(dry-run) clicaria: {why} [{verdict['kind']}] {verdict['desc']}")
            return verdict["kind"]
        done = el.evaluate(_DOM_CLICK)
        if not done.get("ok"):
            self.log(f"guarda RECUSOU ({why}): {done['why']} — {verdict['desc']}")
            raise Refused(done["why"], verdict["desc"])
        self.clicks += 1
        self.log(f"clique: {why} [{verdict['kind']}]")
        return verdict["kind"]
