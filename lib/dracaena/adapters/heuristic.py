"""Adaptador heurístico para HTML padrão (nenhum site específico).

Reconhece, inclusive dentro de shadow DOM aberto:
- <input type=radio> (SINGLE) e <input type=checkbox> (MULTI), agrupados por name/fieldset;
- papéis ARIA radio/checkbox/option (listbox visível), agrupados por radiogroup/group/listbox;
- <select> nativo (DROPDOWN), vários por fieldset/grupo formando uma questão;
- o Submit e o Reset DA questão (rótulos conhecidos, dentro do componente) e o feedback
  (role=status/alert, aria-live, classes feedback/correct/incorrect).

Só lê e propõe alvos: nunca clica, digita nem seleciona (quem age é `dracaena.guard`).
"""

from __future__ import annotations

import re
from pathlib import Path

from ..core.domjs import PRELUDE
from ..core.errors import Ambiguous, NotFound, PageGone
from ..core.model import (CORRECT, DROPDOWN, INCORRECT, MULTI, SINGLE, UNKNOWN, Choice, Item, Option, Question,
                          Target, Verdict)

# ---------------------------------------------------------------- JS (somente leitura)

_HEUR = r"""
const HU = {
  _ids: new WeakMap(), _n: 0,
  id(o) { if (!HU._ids.has(o)) HU._ids.set(o, ++HU._n); return HU._ids.get(o); },
  role(e) { return ((e.getAttribute && e.getAttribute('role')) || '').toLowerCase(); },
  rc(e) { if (e.tagName !== 'INPUT') return null; const t = (e.getAttribute('type') || '').toLowerCase();
          return t === 'radio' || t === 'checkbox' ? t : null; },
  label(e) { if (e.tagName === 'INPUT' || e.tagName === 'SELECT') {
               const l = (e.labels && e.labels[0]) || QH.chain(e).slice(1).find(c => c.tagName === 'LABEL'); return l || null; }
             return null; },
  byId(e, id) { const r = e.getRootNode(); return r && r.getElementById ? r.getElementById(id) : null; },
  owner(e) { return QH.chain(e).slice(1).find(c => c.tagName === 'FIELDSET' || ['group', 'radiogroup', 'listbox'].includes(HU.role(c))) || null; },
  labelShown(l) { if (!l || l.getAttribute('aria-hidden') === 'true' || !QH.visible(l)) return false;
                  const r = l.getBoundingClientRect(); return r.width > 2 && r.height > 2; },
  rcVisible(e) { const l = HU.label(e); return l ? HU.labelShown(l) : QH.visible(e); },
  isBtn(e) { const t = (e.getAttribute('type') || '').toLowerCase();
             return (e.tagName === 'BUTTON' && t !== 'reset') || (e.tagName === 'INPUT' && ['submit', 'button'].includes(t)) || HU.role(e) === 'button'; },
  isFb(e) { const r = HU.role(e), live = e.getAttribute('aria-live');
            return r === 'status' || r === 'alert' || (live && live !== 'off') ||
              /feedback|result|correct|incorrect|explanation/i.test(String(e.className || '') + ' ' + (e.id || '')); },
  flat(s) { return QH.fold(s).replace(/[^a-z0-9 ]+/g, ' ').replace(/\s+/g, ' ').trim(); },
  btnLabel(e) { return HU.flat(QH.text(e) || e.getAttribute('aria-label') || e.value || e.getAttribute('title') || ''); },
  SUBMIT: /^(submit|check|verify|send|answer|enviar|responder|verificar|conferir|checar|corrigir|confirmar)( (my|your|the|a|sua|minha))?( (answer|response|resposta))?$/,
  RESET: /^(reset|try again|retry|clear|start over|tentar novamente|refazer|limpar|reiniciar)( (answer|answers|resposta|respostas))?$/,
  buttons(u, re) { return QH.all(u, e => HU.isBtn(e) && re.test(HU.btnLabel(e))); },
  selectOwner(e) {
    const explicit = HU.owner(e); if (explicit) return explicit;
    // Sem fieldset, agrupa somente numa região semântica com um envio local.
    return QH.chain(e).slice(1).find(c => ['ARTICLE', 'SECTION'].includes(c.tagName)
      && HU.buttons(c, HU.SUBMIT).filter(b => QH.visible(b)).length === 1
      && !QH.all(c, n => HU.rc(n) || ['radio', 'checkbox', 'option'].includes(HU.role(n))).length
      && QH.all(c, n => n.tagName === 'SELECT' && QH.visible(n)).every(n => !HU.owner(n))) || null;
  },
  // ---- átomos: grupos de alternativas ou de selects, na ordem de aparição
  atoms(root) {
    const cand = QH.all(root, e => (HU.rc(e) && HU.rcVisible(e)) ||
      (['radio', 'checkbox', 'option'].includes(HU.role(e)) && e.tagName !== 'INPUT' && e.tagName !== 'OPTION' && QH.visible(e)) ||
      (e.tagName === 'SELECT' && !e.multiple && QH.visible(e)));
    const map = new Map();
    for (const e of cand) {
      let kind, key; const own = HU.owner(e);
      if (e.tagName === 'SELECT') { kind = 'DROPDOWN'; key = 's' + HU.id(HU.selectOwner(e) || e); }
      else {
        const t = HU.rc(e) || HU.role(e);
        if (t === 'option') { kind = own && own.getAttribute('aria-multiselectable') === 'true' ? 'MULTI' : 'SINGLE'; key = 'o' + HU.id(own || QH.parent(e)); }
        else {
          kind = t === 'radio' ? 'SINGLE' : 'MULTI';
          const named = e.name ? 'n' + HU.id(e.form || e.getRootNode()) + ':' + e.name : null;
          key = t + (t === 'radio' && named ? named : own ? 'g' + HU.id(own) : named || 'p' + HU.id(QH.parent(e)));
        }
      }
      if (!map.has(key)) map.set(key, {kind, key, els: []});
      map.get(key).els.push(e);
    }
    return Array.from(map.values()).filter(a => a.kind === 'DROPDOWN' || a.els.length >= 2);
  },
  common(els) { let b = els[0]; for (const e of els.slice(1)) { while (b && !QH.contains(b, e)) b = QH.parent(b); } return b || els[0]; },
  exclusions(atom) { const ex = new Set(atom.els); for (const e of atom.els) { const l = HU.label(e); if (l) ex.add(l); } return ex; },
  // texto do componente fora das alternativas, botões e feedback
  rest(u, atom, extra) {
    const ex = HU.exclusions(atom); for (const x of (extra || [])) if (x) ex.add(x);
    let out = [];
    const walk = (n) => {
      if (n.nodeType === 3) { out.push(n.textContent); return; }
      if (n.nodeType !== 1 || ex.has(n) || ['STYLE', 'SCRIPT', 'OPTION', 'SELECT', 'TEMPLATE'].includes(n.tagName) || HU.isBtn(n) || HU.isFb(n)) return;
      if (n.tagName === 'LABEL' && !HU.labelShown(n)) return;
      if (n.getAttribute('aria-hidden') === 'true') return;
      for (const c of n.childNodes) walk(c);
      if (n.shadowRoot) for (const c of n.shadowRoot.childNodes) walk(c);
    };
    walk(u);
    return QH.norm(out.join(' '));
  },
  // enunciado: legend do fieldset, aria-labelledby/aria-label do grupo ou o texto restante
  head(u, atom) {
    const base = HU.common(atom.els);
    const fs = QH.chain(base).find(c => c.tagName === 'FIELDSET');
    const legend = fs ? Array.from(fs.children).find(c => c.tagName === 'LEGEND') : null;
    if (legend && QH.text(legend)) return {stem: QH.text(legend), via: legend};
    const grp = QH.chain(base).find(c => ['radiogroup', 'group', 'listbox'].includes(HU.role(c)));
    if (grp) {
      const ids = (grp.getAttribute('aria-labelledby') || '').split(/\s+/).filter(Boolean);
      const refs = ids.map(i => HU.byId(grp, i)).filter(Boolean);
      const t = QH.norm(refs.map(r => QH.text(r)).join(' ')) || QH.norm(grp.getAttribute('aria-label') || '');
      if (t) return {stem: t, via: refs[0] || null};
    }
    return null;
  },
  text(u, atom) {
    const h = HU.head(u, atom);
    if (h) { let inst = HU.rest(u, atom, [h.via]); if (h.stem && inst.includes(h.stem)) inst = QH.norm(inst.replace(h.stem, ' '));
             return {stem: h.stem, instruction: inst}; }
    return {stem: HU.rest(u, atom), instruction: ''};
  },
  unit(atom, atoms) {
    const other = (p) => atoms.some(a => a !== atom && QH.contains(p, a.els[0]));
    let cur = atom.els.length > 1 ? HU.common(atom.els) : (QH.parent(atom.els[0]) || atom.els[0]);
    for (let i = 0; i < 12; i++) {
      const stem = HU.text(cur, atom).stem.length >= 3, sub = HU.buttons(cur, HU.SUBMIT).length > 0;
      if (stem && sub) break;
      const p = QH.parent(cur);
      if (!p || p.tagName === 'BODY' || p.tagName === 'HTML' || other(p)) break;
      cur = p;
    }
    return cur;
  },
  hash(s) { let h = 5381; for (let i = 0; i < s.length; i++) h = ((h << 5) + h + s.charCodeAt(i)) >>> 0; return h.toString(36); },
  // átomo da questão dentro do componente
  main(host) { const a = HU.atoms(host); return a.length ? a[0] : null; },
  optText(e) {
    const l = HU.label(e);
    let t = l ? QH.text(l) : '';
    if (!t) { const ids = (e.getAttribute('aria-labelledby') || '').split(/\s+/).filter(Boolean);
              t = QH.norm(ids.map(i => { const r = HU.byId(e, i); return r ? QH.text(r) : ''; }).join(' ')); }
    if (!t && e.tagName !== 'INPUT') t = QH.text(e);
    if (!t) t = QH.norm(e.getAttribute('aria-label') || '');
    if (!t && e.nextSibling && e.nextSibling.nodeType === 3) t = QH.norm(e.nextSibling.textContent);
    return t || QH.norm(e.value || '');
  },
  on(e) { return e.tagName === 'INPUT' ? !!e.checked : (e.getAttribute('aria-checked') === 'true' || e.getAttribute('aria-selected') === 'true'); },
  choices(s) { return Array.from(s.options).filter(o => o.value !== '' && !o.disabled && !o.hidden); },
  itemLabel(s) { const l = HU.label(s); return (l ? QH.text(l) : '') || QH.norm(s.getAttribute('aria-label') || '') || ''; },
};
"""


def _fn(body: str) -> str:
    """Função JS `(host, a) => {...}` com PRELUDE e HU."""
    return "(host, a) => {" + PRELUDE + _HEUR + body + "}"


_LOCATE = "(arg) => {" + PRELUDE + _HEUR + r"""
  const atoms = HU.atoms(document); const units = [];
  for (const a of atoms) { const u = HU.unit(a, atoms); if (!units.includes(u) && QH.visible(u)) units.push(u); }
  return units;
}"""

_EXTRACT = _fn(r"""
  const atom = HU.main(host); if (!atom) return null;
  const t = HU.text(host, atom);
  const key = atom.els[0].name || atom.els[0].id || '';
  const out = {kind: atom.kind, stem: t.stem, instruction: t.instruction, options: [], items: []};
  if (atom.kind === 'DROPDOWN') {
    out.items = atom.els.map(s => ({label: HU.itemLabel(s), options: HU.choices(s).map((o, i) => ({index: i, text: QH.norm(o.textContent), selected: !!o.selected}))}));
  } else {
    out.options = atom.els.map((e, i) => ({index: i, text: HU.optText(e), checked: HU.on(e)}));
  }
  const sig = key + '|' + out.stem + '|' + out.options.map(o => o.text).join('/') + '|' + out.items.map(i => i.label + i.options.map(o => o.text).join('/')).join(';');
  out.id = 'q' + HU.hash(sig);
  const fb = QH.all(host, e => HU.isFb(e) && QH.visible(e) && QH.text(e)).map(e => QH.text(e));
  out.feedback = fb.length ? fb.join(' | ') : null;
  return out;
""")

_FIGURES = _fn(r"""
  const atom = HU.main(host); const ex = atom ? HU.exclusions(atom) : new Set();
  return QH.all(host, e => ['IMG', 'CANVAS', 'svg', 'PICTURE'].includes(e.tagName) && !QH.chain(e).some(c => ex.has(c) || HU.isBtn(c)) && QH.visible(e)
    && e.getBoundingClientRect().width >= 60 && e.getBoundingClientRect().height >= 60).slice(0, 4);
""")

# Elemento-alvo de uma alternativa/dropdown: a entrada, ou o rótulo quando a entrada está coberta/escondida.
_OPTION = _fn(r"""
  const atom = HU.main(host); if (!atom) return null;
  if (a.kind === 'dropdown') {
    const s = atom.els[a.item]; if (!s) return null;
    const o = HU.choices(s)[a.option]; if (!o) return null;
    return {el: s, action: 'select', value: o.index, label: HU.itemLabel(s) + ' → ' + QH.norm(o.textContent)};
  }
  const e = atom.els[a.option]; if (!e) return null;
  let el = e;
  if (HU.rc(e)) {
    const l = HU.label(e);
    const hit = (n) => { const r = n.getBoundingClientRect(); if (r.width <= 0 || r.height <= 0) return false;
      if (r.bottom < 0 || r.top > innerHeight) return true;   // fora da vista: a guarda rola e confere
      let h = document.elementFromPoint(r.left + r.width / 2, r.top + Math.min(r.height / 2, 20));
      while (h && h.shadowRoot) { const i = h.shadowRoot.elementFromPoint(r.left + r.width / 2, r.top + Math.min(r.height / 2, 20)); if (!i || i === h) break; h = i; }
      return !!h && QH.contains(n, h); };
    if (!(QH.visible(e) && hit(e)) && l && QH.visible(l)) el = l;
  }
  return {el, action: 'click', value: null, label: '[' + a.option + '] ' + HU.optText(e).slice(0, 60)};
""")

_BUTTON = _fn(r"""
  const re = a.kind === 'submit' ? HU.SUBMIT : HU.RESET;
  const found = HU.buttons(host, re).filter(b => QH.visible(b));
  return found;
""")

_VERDICT = _fn(r"""
  const fbs = QH.all(host, e => HU.isFb(e) && QH.visible(e) && (QH.text(e) || /correct|incorrect|wrong/i.test(String(e.className || ''))));
  const atom = HU.main(host);
  const marks = atom ? atom.els.filter(e => e.getAttribute('aria-invalid') === 'true' || /(^|[\s_-])(incorrect|wrong|is-incorrect)([\s_-]|$)/i.test(String(e.className || ''))) : [];
  const blob = QH.fold(fbs.map(e => QH.text(e) + ' ' + String(e.className || '')).join(' | '));
  const text = fbs.map(e => QH.text(e)).filter(Boolean).join(' | ');
  const bad = /incorrect|wrong|not correct|try again|errad|incorret|errou|nao esta correto/.test(blob) || marks.length > 0;
  const good = /(^|[^a-z])correct|right answer|well done|good job|congrat|certo|correta|acertou|parabens|success/.test(blob);
  return {result: bad ? 'INCORRECT' : good ? 'CORRECT' : 'UNKNOWN', feedback: text || null};
""")

_EXPECTED = re.compile(r"\b(?:choose|select|pick|escolha|selecione|marque)\s+(two|three|four|five|2|3|4|5|duas|dois|tr[eê]s|quatro|cinco)\b", re.I)
_NUMBERS = {"two": 2, "three": 3, "four": 4, "five": 5, "duas": 2, "dois": 2, "tres": 3, "três": 3, "quatro": 4, "cinco": 5}


def expected_count(text: str) -> int | None:
    m = _EXPECTED.search(text or "")
    if not m:
        return None
    w = m.group(1).lower()
    return _NUMBERS.get(w) or int(w)


def _translate(exc: Exception):
    """Erro do navegador → exceção tipada (o núcleo não casa texto de erro)."""
    msg = str(exc).lower()
    if any(k in msg for k in ("detached", "closed", "context was destroyed", "navigat", "disconnected", "target page")):
        return PageGone(str(exc).splitlines()[0][:160])
    return None


class HeuristicAdapter:
    name = "heuristic"

    def __init__(self, figure_dir: Path | None = None, extra_block: tuple[str, ...] = ()):
        self.figure_dir = Path(figure_dir) if figure_dir else None
        self.extra_block = tuple(extra_block)

    def matches(self, url: str, title: str = "") -> int:
        return 10

    # ---- chamadas ao navegador, com tradução de erros
    def _run(self, fn):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - só traduz o que o Playwright diz sobre a página
            typed = _translate(exc)
            if typed is not None:
                raise typed from exc
            raise

    def _elements(self, frame_or_handle, js: str, arg=None) -> list:
        def go():
            if hasattr(frame_or_handle, "evaluate_handle") and not hasattr(frame_or_handle, "owner_frame"):
                arr = frame_or_handle.evaluate_handle(js)            # Frame
            else:
                arr = frame_or_handle.evaluate_handle(js, arg)       # ElementHandle
            return [h.as_element() for h in arr.get_properties().values() if h.as_element()]
        return self._run(go)

    # ---- interface do adaptador
    def locate(self, frame) -> list:
        return self._elements(frame, _LOCATE)

    def extract(self, handle) -> Question:
        data = self._run(lambda: handle.evaluate(_EXTRACT, None))
        if not data:
            raise NotFound("nenhuma questão reconhecida neste componente")
        text = f"{data['stem']} {data['instruction']}"
        kind = data["kind"]
        options = tuple(Option(o["index"], o["text"], o["checked"]) for o in data["options"])
        items = tuple(Item(i["label"], tuple(Choice(c["index"], c["text"], c["selected"]) for c in i["options"]))
                      for i in data["items"])
        figures = self._figures(handle, data["id"])
        return Question(id=data["id"], kind=kind, stem=data["stem"], instruction=data["instruction"],
                        options=options, expected=expected_count(text) if kind == MULTI else None,
                        items=items, figures=figures, feedback=data["feedback"])

    def _figures(self, handle, qid: str) -> tuple[str, ...]:
        if self.figure_dir is None:
            return ()
        els = self._elements(handle, _FIGURES, None)
        paths = []
        self.figure_dir.mkdir(parents=True, exist_ok=True)
        for n, el in enumerate(els, 1):
            path = self.figure_dir / f"{qid}-{n}.png"
            try:
                path.write_bytes(el.screenshot(type="png", timeout=5000))
            except Exception:  # noqa: BLE001 - figura ilegível: o laço decide se a questão depende dela
                continue
            paths.append(str(path))
        return tuple(paths)

    def target(self, handle, kind: str, index) -> Target:
        if kind == "dropdown":
            item, option = index
            arg = {"kind": "dropdown", "item": int(item), "option": int(option)}
        elif kind == "option":
            arg = {"kind": "option", "option": int(index)}
        else:
            raise NotFound(f"tipo de alvo desconhecido: {kind}")
        data = self._run(lambda: handle.evaluate_handle(_OPTION, arg))
        if data.evaluate("o => o === null"):
            raise NotFound(f"alvo {kind} {index} não encontrado")
        el = data.get_property("el").as_element()
        if el is None:
            raise NotFound(f"alvo {kind} {index} não encontrado")
        props = data.evaluate("o => ({action: o.action, value: o.value, label: o.label})")
        return Target("option", props["action"], el, props["label"], self._qid(handle), props["value"])

    def _qid(self, handle) -> str:
        return self.extract_id(handle)

    def extract_id(self, handle) -> str:
        data = self._run(lambda: handle.evaluate(_EXTRACT, None))
        if not data:
            raise NotFound("nenhuma questão reconhecida neste componente")
        return data["id"]

    def _button(self, handle, kind: str, role: str) -> Target | None:
        found = self._elements(handle, _BUTTON, {"kind": kind})
        if not found:
            return None
        if len(found) > 1:
            raise Ambiguous(f"{len(found)} botões de {kind} na mesma questão")
        el = found[0]
        label = self._run(lambda: el.evaluate("e => (e.textContent || e.value || e.getAttribute('aria-label') || '').replace(/\\s+/g, ' ').trim()"))
        return Target(role, "click", el, label, self._qid(handle))

    def submit_target(self, handle) -> Target | None:
        return self._button(handle, "submit", "submit")

    def reset_target(self, handle) -> Target | None:
        return self._button(handle, "reset", "reset")

    def verdict(self, handle) -> Verdict:
        d = self._run(lambda: handle.evaluate(_VERDICT, None))
        return Verdict(d["result"], d["feedback"])
