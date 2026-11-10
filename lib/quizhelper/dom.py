"""Leitura do DOM do NetAcad (somente leitura; nada aqui clica).

Estrutura levantada na Fase 0 (ver README, "Como a página é lida"):
- o quiz roda num iframe de mesma origem `www.netacad.com/authoring-resources/
  index.html`, todo em shadow DOM aberto (web components);
- avaliação (Practice Final, Module Exam...): carrossel com TODAS as questões
  no DOM; a atual é a do `block-button.active-block` da faixa Q1..Qn
  (`assessment-block-strip-view`), conferida pelo contador "N of M";
  `finalscreen-view` é a tela de envio da avaliação inteira;
- seção do curso (Check Your Understanding): a seção inteira numa página; o
  item aberto é o bloco cujo cabeçalho tem o nome do item (título da aba).

Componentes de questão: `mcq-view` (única/múltipla), `matching-view` com
`matching-dropdown-view` (dropdown) e `object-matching-view` (associação).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Funções JS comuns, prefixadas em cada `evaluate`.
PRELUDE = r"""
const QH = {
  // Percorre `root` e todos os shadow roots abaixo dele (inclusive o do próprio root).
  all(root, pred) { const out = []; const walk = (r) => { for (const e of r.querySelectorAll('*')) {
      if (pred(e)) out.push(e); if (e.shadowRoot) walk(e.shadowRoot); } };
      walk(root); if (root.shadowRoot) walk(root.shadowRoot); return out; },
  first(root, pred) { let f = null; const walk = (r) => { for (const e of r.querySelectorAll('*')) { if (f) return;
      if (pred(e)) { f = e; return; } if (e.shadowRoot) walk(e.shadowRoot); } };
      walk(root); if (!f && root.shadowRoot) walk(root.shadowRoot); return f; },
  parent(e) { if (e.parentElement) return e.parentElement; const r = e.getRootNode(); return r && r.host ? r.host : null; },
  chain(e) { const out = []; let c = e; while (c) { out.push(c); c = QH.parent(c); } return out; },
  visible(e) { if (!e || !e.isConnected) return false; const r = e.getBoundingClientRect();
      if (r.width <= 0 || r.height <= 0) return false;
      for (const c of QH.chain(e)) { const cs = getComputedStyle(c); if (cs.display === 'none' || cs.visibility === 'hidden') return false; }
      return true; },
  norm(s) { return (s || '').replace(/\s+/g, ' ').trim(); },
  text(e) { let s = ''; const w = (x) => { for (const c of x.childNodes) {
      if (c.nodeType === 3) s += c.textContent;
      else if (c.nodeType === 1 && !['STYLE', 'SCRIPT'].includes(c.tagName)) w(c); }
      if (x.shadowRoot) w(x.shadowRoot); }; w(e); return QH.norm(s); },
  own(e) { return QH.norm(Array.from(e.childNodes).filter(n => n.nodeType === 3).map(n => n.textContent).join(' ')); },
  isQuestionHost(e) { return !!(e.shadowRoot && e.shadowRoot.querySelector(':scope > .is-question, .component.is-question')); },
  q(host) { return host.shadowRoot.querySelector('.is-question'); },
  // No slide atual: visível E dentro da LARGURA da janela. O carrossel da
  // avaliação mantém no DOM a tela inicial (Start, primeiro slide), todas as
  // questões e a tela de envio (último slide), deslocados na horizontal; a
  // rolagem vertical da página não importa.
  onScreen(e) { if (!QH.visible(e)) return false; const r = e.getBoundingClientRect();
      return r.right > 0 && r.left < innerWidth; },
  finalscreen(doc) { return QH.first(doc, e => /(^|-)FINALSCREEN-VIEW$/.test(e.tagName) && QH.onScreen(e)); },
  // A barra da avaliação tem duas variantes de tag: `assessment-` e `secure-` (exame final).
  toolbar(doc) { return QH.first(doc, e => e.tagName === 'ASSESSMENT-TOOLBAR-VIEW' || e.tagName === 'SECURE-TOOLBAR-VIEW'); },
};
"""


def js(body: str) -> str:
    """Função JS `(arg) => {...}` com o PRELUDE disponível."""
    return "(arg) => {" + PRELUDE + body + "}"


# ------------------------------------------------------------------ localização da questão

_LOCATE = js(r"""
  const doc = document;
  const out = {mode: null, final: false, start: false, counter: null, host: null, key: null, reason: ''};
  if (QH.finalscreen(doc)) { out.final = true; out.mode = 'assessment'; return out; }
  const toolbar = QH.toolbar(doc);
  if (toolbar) {
    out.mode = 'assessment';
    const label = QH.first(toolbar.shadowRoot || toolbar, e => e.classList && e.classList.contains('question-label'));
    out.counter = label ? QH.text(label) : null;
    const start = QH.first(doc, e => e.classList && e.classList.contains('start-button') && QH.onScreen(e));
    if (start) { out.start = true; return out; }
    const active = QH.first(doc, e => e.tagName === 'BUTTON' && e.classList.contains('block-button') && e.classList.contains('active-block'));
    if (active && active.classList.contains('review-screen-button')) { out.final = true; return out; }
    let host = null;
    if (active && active.dataset.blockId) {
      const block = QH.first(doc, e => e.tagName === 'DIV' && e.classList.contains('block') && e.classList.contains(active.dataset.blockId));
      if (block) host = QH.first(block, QH.isQuestionHost);
    }
    if (!host) {  // plano B: o componente que está dentro da área visível
      const vw = window.innerWidth;
      host = QH.all(doc, QH.isQuestionHost).find(e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.x >= 0 && r.x < vw; }) || null;
    }
    if (!host) { out.reason = 'nenhuma questão ativa na avaliação'; return out; }
    out.host = host;
  } else {
    out.mode = 'section';
    const item = arg && arg.item ? arg.item.toLowerCase() : null;
    let scope = doc;
    if (item) {
      const head = QH.first(doc, e => e.tagName === 'HEADING-VIEW' && QH.text(e).toLowerCase().includes(item));
      if (!head) { out.reason = `bloco do item não encontrado: ${arg.item}`; return out; }
      let b = head; while (b && b.tagName !== 'BLOCK-VIEW') b = QH.parent(b);
      scope = b || doc;      // cabeçalho fora de bloco = título da página: todas as atividades dela
    }
    const hosts = QH.all(scope, QH.isQuestionHost);
    const pending = hosts.filter(h => !QH.q(h).querySelector('.component__widget.is-complete, .component__widget.is-submitted'));
    out.total = hosts.length; out.pending = pending.length;
    if (!pending.length) { out.done = true; return out; }
    out.host = pending[0];
  }
  const q = QH.q(out.host);
  out.key = q.getAttribute('data-socialgoodpulse-id') || null;
  out.tag = out.host.tagName.toLowerCase();
  return out;
""")


@dataclass
class Located:
    mode: str | None
    host: object | None          # ElementHandle do componente (host do shadow root)
    key: str | None
    tag: str | None = None
    counter: str | None = None
    final: bool = False
    start: bool = False
    done: bool = False
    reason: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def number(self) -> tuple[int, int] | None:
        m = re.search(r"(\d+)\s+of\s+(\d+)", self.counter or "")
        return (int(m.group(1)), int(m.group(2))) if m else None


def locate(frame, item: str | None = None) -> Located:
    """Questão atual no iframe do quiz. `item` (seção do curso): nome do item
    aberto, tirado do título da aba."""
    handle = frame.evaluate_handle(_LOCATE, {"item": item})
    try:
        props = handle.evaluate("o => ({...o, host: undefined})")
        host = handle.get_property("host").as_element()
    finally:
        pass
    return Located(props.get("mode"), host, props.get("key"), props.get("tag"), props.get("counter"),
                   bool(props.get("final")), bool(props.get("start")), bool(props.get("done")),
                   props.get("reason", ""), {k: props.get(k) for k in ("total", "pending") if k in props})


def finalscreen_visible(frame) -> bool:
    return bool(frame.evaluate(js("return !!QH.finalscreen(document);")))


def unanswered_count(frame) -> int | None:
    """Questões sem resposta listadas na tela de envio da avaliação."""
    return frame.evaluate(js(r"""
      const fs = QH.finalscreen(document); if (!fs) return null;
      const box = QH.first(fs.shadowRoot || fs, e => e.classList && e.classList.contains('unanswered-instruction'));
      const m = box ? QH.text(box).match(/(\d+)/) : null;
      return m ? +m[1] : 0;
    """))


def end_phrase(frame, words: list[str]) -> str | None:
    """Tela de resultado (depois do envio): uma frase de fim visível."""
    return frame.evaluate(js(r"""
      const words = arg.map(w => w.toLowerCase());
      for (const e of QH.all(document, e => QH.own(e) && QH.visible(e))) {
        const t = QH.own(e).toLowerCase(); if (t.length > 80) continue;
        const w = words.find(w => t.includes(w)); if (w) return w;
      }
      return null;
    """), words)


# ------------------------------------------------------------------ extração da questão

_EXTRACT = js(r"""
  const host = arg; const q = QH.q(host); const tag = host.tagName;
  const bodyEl = q.querySelector('.component__body-inner') ||
    QH.first(q, e => e.classList && e.classList.contains('component__body-inner'));
  const instrEl = QH.first(q, e => e.classList && e.classList.contains('component__instruction-inner'));
  const titleEl = QH.first(q, e => e.classList && e.classList.contains('component__title-inner'));
  const out = {tag: tag.toLowerCase(), key: q.getAttribute('data-socialgoodpulse-id'),
    title: titleEl ? QH.own(titleEl) : '', stem: bodyEl ? QH.text(bodyEl) : '',
    instruction: instrEl ? QH.text(instrEl) : '', submitted: !!q.querySelector('.component__widget.is-submitted')};
  if (tag === 'MCQ-VIEW') {
    const items = Array.from(q.querySelectorAll('.mcq__item'));
    out.kind = items.some(i => i.getAttribute('role') === 'checkbox') ? 'MULTI' : 'SINGLE';
    out.options = items.map(i => {
      const t = i.querySelector('.mcq__item-text-inner');
      const own = t ? QH.norm(Array.from(t.childNodes).filter(n => n.nodeType === 3 || (n.nodeType === 1 && !n.classList.contains('screenReader-position-text'))).map(n => n.textContent).join(' ')) : '';
      return {pos: +i.getAttribute('aria-posinset'), text: own, checked: i.getAttribute('aria-checked') === 'true'};
    }).sort((a, b) => a.pos - b.pos).map((o, idx) => ({index: idx, text: o.text, checked: o.checked}));
  } else if (tag === 'MATCHING-VIEW') {
    out.kind = 'DROPDOWN';
    out.items = Array.from(q.querySelectorAll('matching-dropdown-view')).map((d, idx) => {
      const s = d.shadowRoot; const title = s.querySelector('.matching__item-title_inner .matching__item-title_inner') || s.querySelector('.matching__item-title');
      const opts = Array.from(s.querySelectorAll('li[role=option]')).map(li => ({index: +li.dataset.index,
        text: QH.norm(Array.from(li.querySelector('.dropdown__item-inner').childNodes).filter(n => n.nodeType === 3).map(n => n.textContent).join(' ')),
        selected: li.getAttribute('aria-selected') === 'true'})).sort((a, b) => a.index - b.index);
      const btn = s.querySelector('button.dropdown__btn');
      return {index: idx, text: title ? QH.text(title) : '', options: opts,
              shown: btn ? QH.text(btn.querySelector('.dropdown__inner') || btn) : ''};
    });
  } else if (tag === 'OBJECT-MATCHING-VIEW') {
    out.kind = 'MATCH';
    const txt = (b, sel) => { const e = b.querySelector(sel); return e ? QH.text(e) : ''; };
    out.left = Array.from(q.querySelectorAll('button.objectMatching-category-item'))
      .map(b => ({letter: txt(b, '.category-item-number'), text: txt(b, '.category-item-text'), itemindex: +b.dataset.itemindex}));
    out.right = Array.from(q.querySelectorAll('button.objectMatching-option-item'))
      .map((b, idx) => ({index: idx, text: txt(b, '.category-item-text'), linked: txt(b, '.category-item-number') || null}));
  } else {
    out.kind = 'UNSUPPORTED';
  }
  const m = (out.stem + ' ' + out.instruction).match(/\bchoose\s+(two|three|four|five|2|3|4|5)\b/i);
  const words = {two: 2, three: 3, four: 4, five: 5};
  out.expected = m ? (words[m[1].toLowerCase()] || +m[1]) : null;
  return out;
""")


def extract(host) -> dict:
    """Modelo da questão (só texto e índices) para o Claude e para as ações."""
    return host.evaluate(_EXTRACT)


# ------------------------------------------------------------------ figuras da questão

FIGURE_WORDS = re.compile(r"\b(refer to the (exhibit|graphic|figure|topology|image)|exhibit|graphic|topology|diagram)\b", re.I)


class FigureError(RuntimeError):
    """A questão depende de uma figura que não pôde ser capturada."""


_FIGURES = js(r"""
  const host = arg, wide = __WIDE__;
  const up = n => n.parentElement || (n.getRootNode && n.getRootNode().host) || null;
  const inside = (n, root) => { for (let c = n; c; c = up(c)) if (c === root) return true; return false; };
  let blk = host; while (blk && !(blk.classList && blk.classList.contains('block'))) blk = up(blk);
  const scope = wide ? (blk || up(host) || host) : host;
  const out = [];
  (function scan(n) {
    if (n.nodeType !== 1) return;
    const t = n.tagName.toLowerCase();
    if (['material-icon', 'button', 'assessment-toolbar-view', 'secure-toolbar-view', 'script', 'style', 'video'].includes(t)) return;
    const own = inside(n, host);
    if (t === 'img' || t === 'picture' || t === 'canvas' || (t === 'svg' && !own)) {
      const r = n.getBoundingClientRect(); const cs = getComputedStyle(n);
      if (r.width >= 60 && r.height >= 60 && cs.visibility !== 'hidden' && cs.display !== 'none') out.push(n);
      return;
    }
    if (n.shadowRoot) for (const ch of n.shadowRoot.children) scan(ch);
    for (const ch of n.children) scan(ch);
  })(scope);
  return out;
""")


def figure_elements(host, wide: bool) -> list:
    arr = host.evaluate_handle(_FIGURES.replace("__WIDE__", "true" if wide else "false"))
    return [h.as_element() for h in arr.get_properties().values() if h.as_element()]


def capture_figures(host, q: dict) -> list[bytes]:
    """PNGs (só dos elementos da figura) da questão. Lista vazia = a questão não tem figura.

    Levanta FigureError se o enunciado manda consultar uma figura e nenhuma foi capturada.
    """
    text = (q.get("stem", "") + " " + q.get("instruction", ""))
    needs = bool(FIGURE_WORDS.search(text))
    els = figure_elements(host, wide=needs)
    shots: list[bytes] = []
    for el in els[:4]:
        try:
            shots.append(el.screenshot(type="png", timeout=5000))
        except Exception:  # noqa: BLE001 - elemento sumiu/ilegível: tratado abaixo
            continue
    if needs and not shots:
        raise FigureError("questão com figura: responda manualmente e aperte SUPER+P")
    return shots


# ------------------------------------------------------------------ elementos de ação (só localiza)

_ELEMENT = js(r"""
  const {host, kind, index, letter} = arg; const q = QH.q(host);
  if (kind === 'mcq') {
    const items = Array.from(q.querySelectorAll('.mcq__item')).sort((a, b) => a.getAttribute('aria-posinset') - b.getAttribute('aria-posinset'));
    return items[index] || null;
  }
  if (kind === 'dd-button') { const d = q.querySelectorAll('matching-dropdown-view')[index]; return d ? d.shadowRoot.querySelector('button.dropdown__btn') : null; }
  if (kind === 'dd-option') { const d = q.querySelectorAll('matching-dropdown-view')[index]; return d ? d.shadowRoot.querySelector(`li[role=option][data-index="${arg.option}"]`) : null; }
  if (kind === 'match-left') return Array.from(q.querySelectorAll('button.objectMatching-category-item')).find(b => QH.text(b.querySelector('.category-item-number') || b) === letter) || null;
  if (kind === 'match-right') return q.querySelectorAll('button.objectMatching-option-item')[index] || null;
  if (kind === 'component-action')  // Submit/Reset do próprio componente (seção do curso)
    return QH.first(q, e => e.tagName === 'BUTTON' && e.classList.contains('js-btn-action'));
  if (kind === 'toolbar-submit') {
    const tb = QH.toolbar(document);
    return tb ? QH.first(tb.shadowRoot || tb, e => e.tagName === 'BUTTON' && e.classList.contains('submit-button')) : null;
  }
  return null;
""")


def element(frame, host, kind: str, index: int | None = None, letter: str | None = None, option: int | None = None):
    """ElementHandle de um alvo de ação (ou None). Não clica: quem age é a guarda."""
    h = frame.evaluate_handle(_ELEMENT, {"host": host, "kind": kind, "index": index, "letter": letter,
                                         "option": option})
    return h.as_element()


_SUBMIT_INFO = js(r"""
  const {host, kind} = arg; const q = QH.q(host);
  let cands;
  if (kind === 'toolbar-submit') {
    const tb = QH.toolbar(document);
    cands = tb ? QH.all(tb.shadowRoot || tb, e => e.tagName === 'BUTTON' && e.classList.contains('submit-button')) : [];
  } else cands = QH.all(q, e => e.tagName === 'BUTTON' && e.classList.contains('js-btn-action'));
  const off = (b) => b.disabled || b.classList.contains('is-disabled') || b.getAttribute('aria-disabled') === 'true';
  return {candidates: cands.length, disabled: cands.filter(off).length};
""")

SUBMIT_SELECTORS = {"toolbar-submit": "(assessment|secure)-toolbar-view >> button.submit-button",
                    "component-action": "questão >> button.js-btn-action"}


def submit_info(frame, host, kind: str) -> dict:
    """Diagnóstico do Submit: seletor usado, nº de candidatos e quantos estão desabilitados."""
    try:
        info = frame.evaluate(_SUBMIT_INFO, {"host": host, "kind": kind})
    except Exception as exc:  # noqa: BLE001 - diagnóstico nunca pode mascarar a pausa
        info = {"candidates": -1, "disabled": -1, "error": str(exc)[:80]}
    return {"selector": SUBMIT_SELECTORS.get(kind, kind), **info}


# ------------------------------------------------------------------ estado após o Submit

_VERDICT = js(r"""
  const q = QH.q(arg);
  const scope = q.parentElement ? q.parentElement : arg.shadowRoot;
  const mark = QH.first(arg.shadowRoot, e => e.classList && e.classList.contains('js-btn-marking'));
  const action = QH.first(arg.shadowRoot, e => e.tagName === 'BUTTON' && e.classList.contains('js-btn-action'));
  return {submitted: !!q.querySelector('.component__widget.is-submitted'),
          correct: !!(mark && mark.classList.contains('is-correct')),
          incorrect: !!(mark && (mark.classList.contains('is-incorrect') || mark.classList.contains('is-partly-correct'))),
          label: mark ? (mark.getAttribute('aria-label') || '') : '',
          action: action ? QH.own(action) || QH.text(action) : '', actionDisabled: action ? action.disabled : null,
          wrong: Array.from(q.querySelectorAll('.is-incorrect')).map(e => QH.text(e)).filter(Boolean).slice(0, 10)};
""")


def verdict(host) -> dict:
    return host.evaluate(_VERDICT)
