"""Funções JS comuns (percorrem shadow DOM aberto), prefixadas em cada `evaluate`.

Somente leitura: nada aqui age na página. Quem age é `dracaena.guard`.
"""

from __future__ import annotations

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
  fold(s) { return QH.norm(s).normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase(); },
  text(e) { let s = ''; const w = (x) => { for (const c of x.childNodes) {
      if (c.nodeType === 3) s += c.textContent;
      else if (c.nodeType === 1 && !['STYLE', 'SCRIPT'].includes(c.tagName)) w(c); }
      if (x.shadowRoot) w(x.shadowRoot); }; w(e); return QH.norm(s); },
  own(e) { return QH.norm(Array.from(e.childNodes).filter(n => n.nodeType === 3).map(n => n.textContent).join(' ')); },
  contains(a, b) { for (let c = b; c; c = QH.parent(c)) if (c === a) return true; return false; },
};
"""


def js(body: str) -> str:
    """Função JS `(arg) => {...}` com o PRELUDE disponível."""
    return "(arg) => {" + PRELUDE + body + "}"
