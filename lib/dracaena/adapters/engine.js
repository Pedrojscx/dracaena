// Motor de leitura do Dracaena (v1). Um único módulo, sem dependências.
//
// SOMENTE LEITURA: nada aqui clica, digita, seleciona, envia ou altera a página.
// Quem age é a guarda. O motor devolve dados e os elementos que o adaptador
// propõe como alvo.
//
// Uso pelo Python: o texto deste arquivo é prefixado em cada `evaluate`.
// Uso numa extensão: o mesmo arquivo, sem mudanças, como script de conteúdo
// (um por quadro); a constante `DracaenaEngine` fica visível aos demais scripts.
//
// Camadas, por questão:
//   perfil     perfil declarativo salvo para a origem, quando o contêiner dele existe na página;
//   heuristic  HTML semântico: rádio, checkbox, select, papéis ARIA, botões-alternativa, shadow DOM aberto;
//   none       "não suportado", com o motivo.
// Cada quadro (iframe) é lido em separado: o chamador roda o motor em cada um.
const DracaenaEngine = (() => {
  'use strict';

  const LETTERS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ';
  const ARIA_OPT = ['radio', 'checkbox', 'option'];
  const SUBMIT = /^(submit|check|verify|send|answer|enviar|responder|verificar|conferir|checar|corrigir|confirmar)( (my|your|the|a|sua|minha))?( (answer|response|resposta))?$/;
  const RESET = /^(reset|try again|retry|clear|start over|tentar novamente|refazer|limpar|reiniciar)( (answer|answers|resposta|respostas))?$/;

  // ------------------------------------------------------------ DOM (atravessa shadow DOM aberto)
  const QH = {
    all(root, pred) { const out = []; const walk = (r) => { for (const e of r.querySelectorAll('*')) {
        if (pred(e)) out.push(e); if (e.shadowRoot) walk(e.shadowRoot); } };
        walk(root); if (root.shadowRoot) walk(root.shadowRoot); return out; },
    parent(e) { if (e.parentElement) return e.parentElement; const r = e.getRootNode(); return r && r.host ? r.host : null; },
    chain(e) { const out = []; let c = e; while (c) { out.push(c); c = QH.parent(c); } return out; },
    visible(e) { if (!e || !e.isConnected) return false; const r = e.getBoundingClientRect();
        if (r.width <= 0 || r.height <= 0) return false;
        for (const c of QH.chain(e)) { const cs = getComputedStyle(c); if (cs.display === 'none' || cs.visibility === 'hidden') return false; }
        return true; },
    norm(s) { return (s || '').replace(/\s+/g, ' ').trim(); },
    fold(s) { return QH.norm(s).normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase(); },
    contains(a, b) { for (let c = b; c; c = QH.parent(c)) if (c === a) return true; return false; },
  };
  const ids = new WeakMap(); let seq = 0;
  const uid = (o) => { if (!ids.has(o)) ids.set(o, ++seq); return ids.get(o); };
  const role = (e) => ((e.getAttribute && e.getAttribute('role')) || '').toLowerCase();
  const rc = (e) => { if (e.tagName !== 'INPUT') return null; const t = (e.getAttribute('type') || '').toLowerCase();
    return t === 'radio' || t === 'checkbox' ? t : null; };
  const attrOn = (e, name) => { const v = e.getAttribute(name); return v === 'true' || v === 'mixed'; };

  // Oculto para a leitura: display/visibility, aria-hidden ou recortado (texto só para leitor de tela).
  const hiddenBox = (e) => {
    if (e.getAttribute('aria-hidden') === 'true') return true;
    const cs = getComputedStyle(e);
    if (cs.display === 'none' || cs.visibility === 'hidden') return true;
    if (cs.position === 'absolute' || cs.position === 'fixed') {
      const r = e.getBoundingClientRect();
      if (r.width <= 2 && r.height <= 2 && cs.overflow !== 'visible') return true;
    }
    return false;
  };
  // Texto visível de um elemento (ignora o que está oculto e o que estiver em `skip`).
  const vtext = (e, skip) => {
    let s = '';
    const walk = (x) => {
      for (const c of x.childNodes) {
        if (c.nodeType === 3) s += c.textContent;
        else if (c.nodeType === 1 && !['STYLE', 'SCRIPT', 'TEMPLATE'].includes(c.tagName) && !(skip && skip(c)) && !hiddenBox(c)) walk(c);
      }
      if (x.shadowRoot) walk(x.shadowRoot);
    };
    walk(e);
    return QH.norm(s);
  };
  const labelOf = (e) => { if (e.tagName === 'INPUT' || e.tagName === 'SELECT') {
      return (e.labels && e.labels[0]) || QH.chain(e).slice(1).find((c) => c.tagName === 'LABEL') || null; }
    return null; };
  const byId = (e, id) => { const r = e.getRootNode(); return r && r.getElementById ? r.getElementById(id) : null; };
  const refText = (e, attr) => { const list = (e.getAttribute(attr) || '').split(/\s+/).filter(Boolean);
    return QH.norm(list.map((i) => { const r = byId(e, i); return r ? vtext(r) : ''; }).join(' ')); };
  const owner = (e) => QH.chain(e).slice(1).find((c) => c.tagName === 'FIELDSET' || ['group', 'radiogroup', 'listbox'].includes(role(c))) || null;
  const labelShown = (l) => { if (!l || l.getAttribute('aria-hidden') === 'true' || !QH.visible(l)) return false;
    const r = l.getBoundingClientRect(); return r.width > 2 && r.height > 2; };
  // Recortado por um ancestral (bloco de 1px só para leitor de tela) ou marcado aria-hidden.
  const clipped = (e) => QH.chain(e).some((c) => { if (c.getAttribute('aria-hidden') === 'true') return true;
    const cs = getComputedStyle(c); if (cs.position !== 'absolute' && cs.position !== 'fixed') return false;
    const r = c.getBoundingClientRect(); return r.width <= 2 && r.height <= 2 && cs.overflow !== 'visible'; });
  const rcVisible = (e) => { const l = labelOf(e); return l ? labelShown(l) && !clipped(l) : QH.visible(e) && !clipped(e); };
  const isBtn = (e) => { const t = (e.getAttribute('type') || '').toLowerCase();
    return (e.tagName === 'BUTTON' && t !== 'reset') || (e.tagName === 'INPUT' && ['submit', 'button'].includes(t)) || role(e) === 'button'; };
  // Botão que funciona como alternativa: estado em aria-pressed ou aria-checked, sem papel de opção.
  const isToggle = (e) => (e.tagName === 'BUTTON' || role(e) === 'button') && !ARIA_OPT.includes(role(e)) &&
    (e.hasAttribute('aria-pressed') || e.hasAttribute('aria-checked')) &&
    !e.hasAttribute('aria-haspopup') && !e.hasAttribute('aria-expanded') &&
    !QH.chain(e).some((c) => ['NAV', 'HEADER', 'FOOTER'].includes(c.tagName) || ['toolbar', 'menubar', 'tablist', 'navigation'].includes(role(c)));
  const isFb = (e) => { const r = role(e), live = e.getAttribute('aria-live');
    return r === 'status' || r === 'alert' || (live && live !== 'off') ||
      /feedback|result|correct|incorrect|explanation/i.test(String(e.className || '') + ' ' + (e.id || '')); };
  const flat = (s) => QH.fold(s).replace(/[^a-z0-9 ]+/g, ' ').replace(/\s+/g, ' ').trim();
  const btnLabel = (e) => flat(vtext(e) || e.getAttribute('aria-label') || e.value || e.getAttribute('title') || '');
  const buttonsIn = (u, re) => QH.all(u, (e) => isBtn(e) && !isToggle(e) && re.test(btnLabel(e)));
  const choices = (s) => Array.from(s.options).filter((o) => o.value !== '' && !o.disabled && !o.hidden);
  const itemLabel = (s) => { const l = labelOf(s);
    return (l ? vtext(l, (c) => c === s) : '') || refText(s, 'aria-labelledby') || QH.norm(s.getAttribute('aria-label') || ''); };
  const common = (els) => { let b = els[0]; for (const e of els.slice(1)) { while (b && !QH.contains(b, e)) b = QH.parent(b); } return b || els[0]; };
  const hash = (s) => { let h = 5381; for (let i = 0; i < s.length; i++) h = ((h << 5) + h + s.charCodeAt(i)) >>> 0; return h.toString(36); };

  // ------------------------------------------------------------ camada heurística
  const selectOwner = (e) => {
    const explicit = owner(e); if (explicit) return explicit;
    // Sem fieldset: uma região semântica com um envio local e só selects.
    const region = QH.chain(e).slice(1).find((c) => ['ARTICLE', 'SECTION'].includes(c.tagName)
      && buttonsIn(c, SUBMIT).filter((b) => QH.visible(b)).length === 1
      && !QH.all(c, (n) => rc(n) || ARIA_OPT.includes(role(n))).length
      && QH.all(c, (n) => n.tagName === 'SELECT' && QH.visible(n)).every((n) => !owner(n)));
    if (region) return region;
    // Select dentro de frase: o bloco de texto que o contém agrupa as lacunas da mesma frase.
    return QH.chain(e).slice(1, 4).find((c) => c.tagName !== 'LABEL' && ['P', 'LI', 'DIV', 'TD', 'BLOCKQUOTE'].includes(c.tagName)
      && Array.from(c.childNodes).some((n) => n.nodeType === 3 && QH.norm(n.textContent).length >= 2)) || null;
  };

  // Texto de uma alternativa e de onde ele veio (a origem entra na confiança).
  const optInfo = (e) => {
    const l = labelOf(e);
    let t = l ? vtext(l) : '';
    if (t) return { text: t, src: 'label' };
    t = refText(e, 'aria-labelledby'); if (t) return { text: t, src: 'aria' };
    if (e.tagName !== 'INPUT') { t = vtext(e); if (t) return { text: t, src: 'own' }; }
    t = QH.norm(e.getAttribute('aria-label') || ''); if (t) return { text: t, src: 'aria' };
    if (e.nextSibling && e.nextSibling.nodeType === 3) { t = QH.norm(e.nextSibling.textContent); if (t) return { text: t, src: 'sibling' }; }
    // Sem rótulo associado: o texto da linha/célula vizinha é só um palpite.
    for (const c of QH.chain(e).slice(1, 4)) {
      if (QH.all(c, (n) => rc(n) || ARIA_OPT.includes(role(n))).length > 1) break;
      t = vtext(c); if (t) return { text: t, src: 'row' };
    }
    return { text: QH.norm(e.value || ''), src: 'value' };
  };
  const isOn = (e) => (e.tagName === 'INPUT' ? !!e.checked
    : (attrOn(e, 'aria-checked') || attrOn(e, 'aria-selected') || attrOn(e, 'aria-pressed')));

  // Grade de rádios (uma linha por item, colunas iguais) vira uma associação.
  const gridOf = (a) => {
    if (a.kind !== 'SINGLE' || !a.els.every((e) => rc(e) === 'radio')) return null;
    const row = QH.chain(common(a.els)).find((c) => c.tagName === 'TR' || role(c) === 'row');
    if (!row) return null;
    const grid = QH.chain(row).find((c) => c.tagName === 'TABLE' || ['grid', 'table'].includes(role(c)));
    return grid ? { row, grid } : null;
  };
  const cellOf = (e) => QH.chain(e).find((c) => c.tagName === 'TD' || c.tagName === 'TH' || ['cell', 'gridcell'].includes(role(c)));
  const mergeGrids = (atoms) => {
    const groups = new Map();
    for (const a of atoms) { const g = gridOf(a); if (!g) continue; a._g = g;
      if (!groups.has(g.grid)) groups.set(g.grid, []); groups.get(g.grid).push(a); }
    for (const [grid, list] of groups) {
      const n = list[0].els.length;
      if (list.length < 2 || n < 2 || n > LETTERS.length || list.some((a) => a.els.length !== n)) continue;
      const rowsEls = QH.all(grid, (c) => c.tagName === 'TR' || role(c) === 'row');
      const head = rowsEls.find((r) => !QH.all(r, (x) => !!rc(x)).length && vtext(r));
      const headCells = head ? Array.from(head.children) : [];
      const cols = list[0].els.map((e) => { const cell = cellOf(e);
        const idx = cell && cell.parentElement ? Array.from(cell.parentElement.children).indexOf(cell) : -1;
        const h = idx >= 0 && headCells[idx] ? vtext(headCells[idx]) : '';
        if (h) return h; const o = optInfo(e); return ['row', 'value'].includes(o.src) ? '' : o.text; });
      const rows = list.map((a) => { const row = a._g.row;
        const cell = Array.from(row.children).find((c) => !QH.all(c, (x) => !!rc(x)).length && vtext(c));
        return { els: a.els, label: (cell ? vtext(cell) : '') || refText(row, 'aria-labelledby') || QH.norm(row.getAttribute('aria-label') || '') }; });
      if (cols.some((c) => !c) || new Set(cols).size !== cols.length || rows.some((r) => !r.label)) continue;
      const merged = { kind: 'MATCH', form: 'grid', key: 'm' + uid(grid), grid, rows, cols, els: [].concat(...list.map((a) => a.els)) };
      atoms.splice(atoms.indexOf(list[0]), 1, merged);
      for (const a of list.slice(1)) atoms.splice(atoms.indexOf(a), 1);
    }
    return atoms;
  };
  // Selects com rótulo e as mesmas opções: associação por select.
  const matchSelects = (a) => {
    if (a.kind !== 'DROPDOWN' || a.els.length < 2) return a;
    const lists = a.els.map((s) => choices(s).map((o) => QH.norm(o.textContent)));
    const first = lists[0].join('\u0001');
    if (lists[0].length < 2 || lists[0].length > LETTERS.length || lists.some((l) => l.join('\u0001') !== first)) return a;
    const labels = a.els.map((s) => itemLabel(s));
    if (labels.some((l) => !l)) return a;
    return Object.assign(a, { kind: 'MATCH', form: 'select', cols: lists[0], rows: a.els.map((s, i) => ({ els: [s], label: labels[i] })) });
  };

  // Átomos: grupos de alternativas ou de selects, na ordem em que aparecem.
  const atomsIn = (root) => {
    const inOpt = (e) => QH.chain(e).slice(1).some((c) => ARIA_OPT.includes(role(c)));
    const cand = QH.all(root, (e) => (rc(e) && !inOpt(e) && rcVisible(e)) ||
      (ARIA_OPT.includes(role(e)) && e.tagName !== 'INPUT' && e.tagName !== 'OPTION' && QH.visible(e)) ||
      (isToggle(e) && QH.visible(e)) ||
      (e.tagName === 'SELECT' && !e.multiple && QH.visible(e)));
    const map = new Map();
    for (const e of cand) {
      let kind, key, form = 'native'; const own = owner(e);
      if (e.tagName === 'SELECT') { kind = 'DROPDOWN'; key = 's' + uid(selectOwner(e) || e); }
      else if (isToggle(e)) { kind = 'SINGLE'; form = 'toggle'; key = 'b' + uid(own || QH.parent(e)); }
      else {
        const t = rc(e) || role(e);
        if (!rc(e)) form = 'aria';
        if (t === 'option') { kind = own && own.getAttribute('aria-multiselectable') === 'true' ? 'MULTI' : 'SINGLE'; key = 'o' + uid(own || QH.parent(e)); }
        else {
          kind = t === 'radio' ? 'SINGLE' : 'MULTI';
          const named = e.name ? 'n' + uid(e.form || e.getRootNode()) + ':' + e.name : null;
          key = t + (t === 'radio' && named ? named : own ? 'g' + uid(own) : named || 'p' + uid(QH.parent(e)));
        }
      }
      if (!map.has(key)) map.set(key, { kind, key, form, els: [] });
      map.get(key).els.push(e);
    }
    const atoms = Array.from(map.values()).filter((a) => a.kind === 'DROPDOWN' || a.els.length >= 2);
    return mergeGrids(atoms).map(matchSelects);
  };
  const exclusions = (atom) => { const ex = new Set(atom.els);
    for (const e of atom.els) { const l = labelOf(e); if (l) ex.add(l); }
    if (atom.grid) ex.add(atom.grid);
    return ex; };
  // Lacuna de frase: select sem rótulo, lido no ponto em que aparece no texto.
  const blanks = (atom) => (atom.kind === 'DROPDOWN' ? atom.els.map((s) => !itemLabel(s)) : []);
  // Texto do componente fora das alternativas, botões, retorno e controles ocultos.
  const rest = (u, atom, extra) => {
    const ex = exclusions(atom); for (const x of (extra || [])) if (x) ex.add(x);
    const gaps = blanks(atom);
    const out = [];
    const walk = (n) => {
      if (n.nodeType === 3) { out.push(n.textContent); return; }
      if (n.nodeType !== 1) return;
      if (n.tagName === 'SELECT') { const i = atom.els.indexOf(n); if (i >= 0 && gaps[i]) out.push(' [lacuna ' + (i + 1) + '] '); return; }
      if (ex.has(n) || ['STYLE', 'SCRIPT', 'OPTION', 'TEMPLATE'].includes(n.tagName) || isBtn(n) || isFb(n)) return;
      if (n.tagName === 'LABEL' && !labelShown(n)) return;
      if (hiddenBox(n)) return;
      for (const c of n.childNodes) walk(c);
      if (n.shadowRoot) for (const c of n.shadowRoot.childNodes) walk(c);
    };
    walk(u);
    return QH.norm(out.join(' '));
  };
  // Enunciado explícito: legend, caption, aria-labelledby ou aria-label do grupo.
  const head = (u, atom) => {
    const base = common(atom.els);
    if (atom.grid) { const cap = QH.all(atom.grid, (c) => c.tagName === 'CAPTION')[0];
      const t = (cap ? vtext(cap) : '') || refText(atom.grid, 'aria-labelledby') || QH.norm(atom.grid.getAttribute('aria-label') || '');
      if (t) return { stem: t, via: cap || null }; }
    const fs = QH.chain(base).find((c) => c.tagName === 'FIELDSET');
    const legend = fs ? Array.from(fs.children).find((c) => c.tagName === 'LEGEND') : null;
    if (legend && vtext(legend)) return { stem: vtext(legend), via: legend };
    const grp = QH.chain(base).find((c) => ['radiogroup', 'group', 'listbox'].includes(role(c)));
    if (grp) {
      const refs = (grp.getAttribute('aria-labelledby') || '').split(/\s+/).filter(Boolean).map((i) => byId(grp, i)).filter(Boolean);
      const t = QH.norm(refs.map((r) => vtext(r)).join(' ')) || QH.norm(grp.getAttribute('aria-label') || '');
      if (t) return { stem: t, via: refs[0] || null };
    }
    return null;
  };
  const textOf = (u, atom) => {
    const h = head(u, atom);
    if (h) { let inst = rest(u, atom, [h.via]); if (h.stem && inst.includes(h.stem)) inst = QH.norm(inst.replace(h.stem, ' '));
      return { stem: h.stem, instruction: inst, explicit: true }; }
    return { stem: rest(u, atom), instruction: '', explicit: false };
  };
  const unitOf = (atom, atoms) => {
    const other = (p) => atoms.some((a) => a !== atom && QH.contains(p, a.els[0]));
    let cur = atom.els.length > 1 ? common(atom.els) : (QH.parent(atom.els[0]) || atom.els[0]);
    for (let i = 0; i < 12; i++) {
      const stem = textOf(cur, atom).stem.length >= 3, sub = buttonsIn(cur, SUBMIT).length > 0;
      if (stem && sub) break;
      const p = QH.parent(cur);
      if (!p || p.tagName === 'BODY' || p.tagName === 'HTML' || other(p)) break;
      cur = p;
    }
    return cur;
  };
  const mainAtom = (host) => { const a = atomsIn(host); return a.length ? a[0] : null; };

  // Confiança 0..1 da leitura heurística, com os motivos de cada desconto.
  const confidence = (host, atom, t, texts, sources) => {
    let c = 0.45; const notes = [];
    if (t.explicit) c += 0.2;
    else if (t.stem.length >= 8) c += 0.1;
    if (t.stem.length < 3) { c -= 0.3; notes.push('sem enunciado'); }
    if (t.stem.length > 700) { c -= 0.15; notes.push('enunciado longo demais: região mal isolada'); }
    if (texts.length >= 2 && texts.every(Boolean) && new Set(texts).size === texts.length) c += 0.15;
    else { c -= 0.2; notes.push('alternativas sem texto ou repetidas'); }
    if (sources.some((s) => s === 'row' || s === 'value' || s === 'none')) { c -= 0.3; notes.push('rótulos não associados às alternativas'); }
    else if (!sources.includes('sibling')) c += 0.1;
    if (atom.form === 'native' || atom.form === 'select' || atom.form === 'grid') c += 0.1;
    else if (atom.form === 'aria') c += 0.05;
    else { c -= 0.1; notes.push('alternativas em botão simples'); }
    if (texts.length <= 12) c += 0.05; else { c -= 0.1; notes.push('alternativas demais'); }
    if (host.tagName === 'BODY' || host.tagName === 'HTML') { c -= 0.1; notes.push('questão sem região própria'); }
    return { value: Math.round(Math.max(0.05, Math.min(0.99, c)) * 100) / 100, notes };
  };

  const feedbackOf = (host) => {
    const fb = QH.all(host, (e) => isFb(e) && QH.visible(e) && vtext(e)).map((e) => vtext(e));
    return fb.length ? fb.join(' | ') : null;
  };
  const finish = (out, key) => {
    const sig = key + '|' + out.stem + '|' + out.options.map((o) => o.text).join('/') + '|' +
      out.items.map((i) => i.label + i.options.map((o) => o.text).join('/')).join(';') +
      (out.right.length ? '|' + out.left.map((s) => s.text).join('/') + '|' + out.right.map((s) => s.text).join('/') : '');
    out.id = 'q' + hash(sig);
    return out;
  };
  const blank = (kind) => ({ kind, stem: '', instruction: '', options: [], items: [], left: [], right: [], feedback: null,
    layer: 'heuristic', confidence: 0, notes: [], actionable: true });

  const extractHeuristic = (host) => {
    const atom = mainAtom(host); if (!atom) return null;
    const t = textOf(host, atom);
    const out = blank(atom.kind); out.stem = t.stem; out.instruction = t.instruction;
    let texts = [], sources = [];
    if (atom.kind === 'MATCH') {
      out.left = atom.cols.map((text, i) => ({ index: i, text, letter: LETTERS[i], linked: null }));
      out.right = atom.rows.map((r, i) => {
        let linked = null;
        if (atom.form === 'select') { const k = choices(r.els[0]).findIndex((o) => o.selected); if (k >= 0) linked = LETTERS[k]; }
        else { const k = r.els.findIndex((e) => e.checked); if (k >= 0) linked = LETTERS[k]; }
        return { index: i, text: r.label, letter: '', linked }; });
      texts = atom.cols; sources = ['label'];
      if (new Set(out.right.map((r) => r.text)).size !== out.right.length) sources = ['none'];
    } else if (atom.kind === 'DROPDOWN') {
      const gaps = blanks(atom);
      out.items = atom.els.map((s, n) => ({ label: gaps[n] ? 'lacuna ' + (n + 1) : itemLabel(s),
        options: choices(s).map((o, i) => ({ index: i, text: QH.norm(o.textContent), selected: !!o.selected })) }));
      texts = [].concat(...out.items.map((i, n) => i.options.map((o) => n + ':' + o.text)));
      sources = gaps.map((g, n) => (g && !t.stem.includes('[lacuna ' + (n + 1) + ']') ? 'none' : 'label'));
      if (out.items.some((i) => i.options.length < 2)) sources.push('none');
    } else {
      const info = atom.els.map(optInfo);
      out.options = atom.els.map((e, i) => ({ index: i, text: info[i].text, checked: isOn(e) }));
      texts = info.map((i) => i.text); sources = info.map((i) => i.src);
      if (atom.form === 'toggle') out.actionable = false;
    }
    const conf = confidence(host, atom, t, texts, sources);
    out.confidence = conf.value; out.notes = conf.notes;
    if (!out.actionable) out.notes.push('a guarda v0 não aceita botão simples como alternativa');
    out.feedback = feedbackOf(host);
    return finish(out, atom.els[0].name || atom.els[0].id || '');
  };

  // ------------------------------------------------------------ camada de perfil (declarativo, sem código)
  // Seletor CSS aplicado em cada árvore (documento e shadow roots) sob `scope`; inválido devolve null.
  const qsa = (scope, sel) => {
    if (!sel || typeof sel !== 'string') return [];
    const out = [];
    try { if (scope.matches && scope.matches(sel)) out.push(scope);
      for (const e of QH.all(scope, (x) => x.matches(sel))) if (!out.includes(e)) out.push(e); }
    catch (err) { return null; }
    return out;
  };
  const q = (scope, sel) => qsa(scope, sel) || [];
  const section = (p, name) => (p && p[name] && typeof p[name] === 'object' ? p[name] : {});
  const profileHosts = (p) => q(document, section(p, 'question').container).filter((e) => QH.visible(e));
  const usesProfile = (host, p) => { const sel = section(p, 'question').container; if (!sel) return false;
    try { return host.matches(sel); } catch (err) { return false; } };
  const joined = (host, sel) => QH.norm(q(host, sel).filter((e) => !hiddenBox(e)).map((e) => vtext(e)).join(' '));
  const profItems = (host, p) => q(host, section(p, 'options').item).filter((e) => QH.visible(e));
  // O elemento que a guarda aciona: a entrada indicada pelo perfil, a própria alternativa ou a entrada dentro dela.
  const profControl = (item, p) => { const sel = section(p, 'options').input;
    if (sel) { const f = q(item, sel)[0]; if (f) return f; }
    if (rc(item) || ARIA_OPT.includes(role(item))) return item;
    return QH.all(item, (e) => !!rc(e) || ARIA_OPT.includes(role(e)))[0] || item; };
  const profDrops = (host, p) => q(host, section(p, 'dropdown').item).filter((e) => QH.visible(e));
  const profSelect = (item) => (item.tagName === 'SELECT' ? item : QH.all(item, (e) => e.tagName === 'SELECT')[0] || null);
  const guardOk = (e) => { const l = e.tagName === 'LABEL' ? (e.control || QH.all(e, (x) => !!rc(x))[0]) : null;
    return !!rc(e) || ARIA_OPT.includes(role(e)) || ['menuitemradio', 'menuitemcheckbox'].includes(role(e)) || !!(l && rc(l)); };

  const extractProfile = (host, p) => {
    const o = section(p, 'options'), d = section(p, 'dropdown'), qs = section(p, 'question');
    const out = blank('SINGLE'); out.layer = 'profile';
    out.stem = joined(host, qs.stem); out.instruction = qs.instruction ? joined(host, qs.instruction) : '';
    const drops = d.item ? profDrops(host, p) : [];
    if (drops.length) {
      out.kind = 'DROPDOWN';
      out.items = drops.map((item) => {
        const s = d.native !== false ? profSelect(item) : null;
        const label = vtext(item, (c) => c === s || (d.option && q(item, d.option).includes(c)) || (d.button && q(item, d.button).includes(c)))
          || (s ? itemLabel(s) : '');
        const opts = s ? choices(s).map((x, i) => ({ index: i, text: QH.norm(x.textContent), selected: !!x.selected }))
          : q(item, d.option).map((x, i) => ({ index: i, text: vtext(x) || QH.norm(x.textContent), selected: isOn(x) }));
        return { label, options: opts }; });
      if (out.items.some((i) => i.options.length < 2)) out.notes.push('item sem opções');
    } else {
      const items = profItems(host, p);
      const ctl = items.map((i) => profControl(i, p));
      const multi = ctl.some((c) => rc(c) === 'checkbox' || role(c) === 'checkbox') ||
        QH.chain(ctl[0] || host).some((c) => c.getAttribute && c.getAttribute('aria-multiselectable') === 'true');
      out.kind = multi ? 'MULTI' : 'SINGLE';
      out.options = items.map((item, i) => {
        const text = o.text ? joined(item, o.text) : vtext(item);
        const on = o.selected_attr ? [item, ctl[i]].some((e) => { const v = e.getAttribute(o.selected_attr); return v !== null && v !== 'false'; }) : isOn(ctl[i]);
        return { index: i, text, checked: !!on }; });
      if (items.length < 2) out.notes.push('menos de duas alternativas');
      if (ctl.some((c) => !guardOk(c))) { out.actionable = false; out.notes.push('a guarda v0 não aceita este elemento como alternativa'); }
    }
    if (!out.stem) out.notes.push('sem enunciado');
    const texts = out.kind === 'DROPDOWN' ? out.items.map((i) => i.label) : out.options.map((x) => x.text);
    if (texts.some((t) => !t)) out.notes.push('alternativas sem texto');
    out.confidence = out.notes.length ? 0.4 : 0.95;
    out.feedback = feedbackOf(host);
    const fb = section(p, 'feedback');
    if (fb.text) { const t = joined(host, fb.text); if (t) out.feedback = t; }
    return finish(out, 'p');
  };

  // ------------------------------------------------------------ API
  // Componentes de questão visíveis neste quadro, em ordem.
  const locate = (profile) => {
    if (profile) { const hosts = profileHosts(profile); if (hosts.length) return hosts; }
    const atoms = atomsIn(document); const units = [];
    for (const a of atoms) { const u = unitOf(a, atoms); if (!units.includes(u) && QH.visible(u)) units.push(u); }
    return units;
  };
  const extract = (host, profile) => (profile && usesProfile(host, profile) ? extractProfile(host, profile) : extractHeuristic(host));

  // Alvo proposto para uma resposta. a = {kind: option|dropdown|match, option, item, right, letter}.
  const clickable = (e) => {
    if (!rc(e)) return e;
    const l = labelOf(e);
    const hit = (n) => { const r = n.getBoundingClientRect(); if (r.width <= 0 || r.height <= 0) return false;
      if (r.bottom < 0 || r.top > innerHeight) return true;   // fora da vista: a guarda rola e confere
      const x = r.left + r.width / 2, y = r.top + Math.min(r.height / 2, 20);
      let h = document.elementFromPoint(x, y);
      while (h && h.shadowRoot) { const i = h.shadowRoot.elementFromPoint(x, y); if (!i || i === h) break; h = i; }
      return !!h && QH.contains(n, h); };
    return !(QH.visible(e) && hit(e)) && l && QH.visible(l) ? l : e;
  };
  const option = (host, a, profile) => {
    if (profile && usesProfile(host, profile)) {
      const d = section(profile, 'dropdown');
      if (a.kind === 'dropdown') {
        const item = profDrops(host, profile)[a.item]; if (!item) return null;
        const s = d.native !== false ? profSelect(item) : null;
        if (s) { const o = choices(s)[a.option]; if (!o) return null;
          return { el: s, action: 'select', value: o.index, label: itemLabel(s) + ' → ' + QH.norm(o.textContent), opener: null }; }
        const o = q(item, d.option)[a.option]; if (!o) return null;
        return { el: o, action: 'click', value: null, label: '[' + a.item + '] → ' + vtext(o).slice(0, 60), opener: q(item, d.button)[0] || null };
      }
      if (a.kind !== 'option') return null;
      const item = profItems(host, profile)[a.option]; if (!item) return null;
      const o = section(profile, 'options');
      return { el: clickable(profControl(item, profile)), action: 'click', value: null, opener: null,
        label: '[' + a.option + '] ' + (o.text ? joined(item, o.text) : vtext(item)).slice(0, 60) };
    }
    const atom = mainAtom(host); if (!atom) return null;
    if (a.kind === 'match') {
      if (atom.kind !== 'MATCH') return null;
      const row = atom.rows[a.right], col = LETTERS.indexOf(String(a.letter || '').toUpperCase());
      if (!row || col < 0 || col >= atom.cols.length) return null;
      const label = row.label.slice(0, 40) + ' → ' + atom.cols[col].slice(0, 40);
      if (atom.form === 'select') { const o = choices(row.els[0])[col]; if (!o) return null;
        return { el: row.els[0], action: 'select', value: o.index, label, opener: null }; }
      return { el: clickable(row.els[col]), action: 'click', value: null, label, opener: null };
    }
    if (a.kind === 'dropdown') {
      if (atom.kind !== 'DROPDOWN') return null;
      const s = atom.els[a.item]; if (!s) return null;
      const o = choices(s)[a.option]; if (!o) return null;
      return { el: s, action: 'select', value: o.index, label: (itemLabel(s) || 'lacuna ' + (a.item + 1)) + ' → ' + QH.norm(o.textContent), opener: null };
    }
    if (a.kind !== 'option' || atom.kind === 'DROPDOWN' || atom.kind === 'MATCH') return null;
    const e = atom.els[a.option]; if (!e) return null;
    return { el: clickable(e), action: 'click', value: null, label: '[' + a.option + '] ' + optInfo(e).text.slice(0, 60), opener: null };
  };

  // Botões DA questão (kind: submit | reset). O rótulo é conferido de novo pela guarda.
  const buttons = (host, kind, profile) => {
    if (profile && usesProfile(host, profile)) {
      const sel = section(profile, kind).button;
      return sel ? q(host, sel).filter((b) => QH.visible(b)) : [];
    }
    return buttonsIn(host, kind === 'submit' ? SUBMIT : RESET).filter((b) => QH.visible(b));
  };

  const verdict = (host, profile) => {
    if (profile && usesProfile(host, profile)) {
      const fb = section(profile, 'feedback');
      const seen = (sel) => q(host, sel).some((e) => QH.visible(e));
      const text = fb.text ? joined(host, fb.text) : '';
      if (fb.incorrect && seen(fb.incorrect)) return { result: 'INCORRECT', feedback: text || null };
      if (fb.correct && seen(fb.correct)) return { result: 'CORRECT', feedback: text || null };
      if (fb.correct || fb.incorrect) return { result: 'UNKNOWN', feedback: text || null };
    }
    const fbs = QH.all(host, (e) => isFb(e) && QH.visible(e) && (vtext(e) || /correct|incorrect|wrong/i.test(String(e.className || ''))));
    const atom = mainAtom(host);
    const marks = atom ? atom.els.filter((e) => e.getAttribute('aria-invalid') === 'true' || /(^|[\s_-])(incorrect|wrong|is-incorrect)([\s_-]|$)/i.test(String(e.className || ''))) : [];
    const blob = QH.fold(fbs.map((e) => vtext(e) + ' ' + String(e.className || '')).join(' | '));
    const text = fbs.map((e) => vtext(e)).filter(Boolean).join(' | ');
    const bad = /incorrect|wrong|not correct|try again|errad|incorret|errou|nao esta correto/.test(blob) || marks.length > 0;
    const good = /(^|[^a-z])correct|right answer|well done|good job|congrat|certo|correta|acertou|parabens|success/.test(blob);
    return { result: bad ? 'INCORRECT' : good ? 'CORRECT' : 'UNKNOWN', feedback: text || null };
  };

  const figures = (host, profile) => {
    if (profile && usesProfile(host, profile) && section(profile, 'question').figure) {
      return q(host, section(profile, 'question').figure).filter((e) => QH.visible(e)).slice(0, 4);
    }
    const atom = mainAtom(host); const ex = atom ? exclusions(atom) : new Set();
    return QH.all(host, (e) => ['IMG', 'CANVAS', 'svg', 'PICTURE'].includes(e.tagName) && !QH.chain(e).some((c) => ex.has(c) || isBtn(c)) && QH.visible(e)
      && e.getBoundingClientRect().width >= 60 && e.getBoundingClientRect().height >= 60).slice(0, 4);
  };

  // Por que este quadro não tem questão legível (camada "none").
  const typed = () => QH.all(document, (e) => QH.visible(e) && (e.tagName === 'TEXTAREA' || e.isContentEditable ||
    (e.tagName === 'INPUT' && ['text', 'number', ''].includes((e.getAttribute('type') || '').toLowerCase()))) &&
    !QH.chain(e).some((c) => ['NAV', 'HEADER', 'FOOTER'].includes(c.tagName) || role(c) === 'search'));
  const plainButtons = () => { const groups = new Map();
    for (const b of QH.all(document, (e) => e.tagName === 'BUTTON' && !isToggle(e) && !ARIA_OPT.includes(role(e)) && QH.visible(e)
      && !SUBMIT.test(btnLabel(e)) && !RESET.test(btnLabel(e)))) {
      const p = QH.parent(b); if (!groups.has(p)) groups.set(p, 0); groups.set(p, groups.get(p) + 1); }
    return Math.max(0, ...groups.values()); };
  const why = () => {
    if (typed().length) return { code: 'typed', text: 'resposta digitada (resposta curta ou dissertativa): digitar está fora do contrato v0' };
    if (QH.all(document, (e) => QH.visible(e) && (role(e) === 'combobox' || ['listbox', 'true'].includes(e.getAttribute('aria-haspopup') || ''))).length)
      return { code: 'custom-dropdown', text: 'lista suspensa personalizada (botão que abre uma lista): só um perfil a descreve' };
    if (plainButtons() >= 3) return { code: 'plain-buttons', text: 'alternativas em botões sem papel nem estado ARIA: a guarda v0 não as aceita' };
    if (QH.all(document, (e) => e.getAttribute('draggable') === 'true' && QH.visible(e)).length >= 2)
      return { code: 'drag', text: 'arrastar e soltar não é suportado' };
    return { code: 'empty', text: 'nenhum controle de resposta reconhecível neste quadro' };
  };

  // Resumo do quadro: camada, questões com confiança e quantos elementos cada seletor do perfil achou.
  const diagnose = (profile) => {
    const hosts = locate(profile);
    const questions = hosts.map((h) => extract(h, profile)).filter(Boolean)
      .map((d) => ({ id: d.id, kind: d.kind, layer: d.layer, confidence: d.confidence, notes: d.notes, actionable: d.actionable,
        options: d.options.length, items: d.items.length, pairs: d.right.length, stem: d.stem.length }));
    const matches = {};
    if (profile) {
      for (const name of Object.keys(profile)) {
        if (name === 'site' || name === 'guard' || !profile[name] || typeof profile[name] !== 'object') continue;
        for (const key of Object.keys(profile[name])) {
          const sel = profile[name][key];
          if (typeof sel !== 'string' || key === 'selected_attr') continue;
          const found = qsa(document, sel);
          matches[sel] = found === null ? -1 : found.length;   // -1: seletor inválido
        }
      }
    }
    const layer = !questions.length ? 'none' : questions.some((x) => x.layer === 'profile') ? 'profile' : 'heuristic';
    const reason = questions.length ? null : why();
    return { layer, supported: questions.length > 0, reason: reason ? reason.text : null, code: reason ? reason.code : null,
      questions, matches, confidence: questions.length ? Math.min(...questions.map((x) => x.confidence)) : 0 };
  };

  // Recorte da região da atividade para o autoperfil: só a ESTRUTURA. O texto do conteúdo é
  // trocado pelo seu tamanho; valores de campos, endereços e atributos fora da lista não saem.
  const KEEP = ['id', 'class', 'role', 'type', 'for', 'name', 'hidden', 'disabled', 'tabindex'];
  const regionRoot = () => {
    const hosts = locate(null);
    if (hosts.length) { const c = common(hosts); return c.tagName === 'HTML' ? document.body : c; }
    const pool = QH.all(document, (e) => (['MAIN', 'FORM', 'ARTICLE', 'SECTION'].includes(e.tagName) || role(e) === 'main') && QH.visible(e));
    const score = (e) => QH.all(e, (x) => ['BUTTON', 'INPUT', 'SELECT', 'TEXTAREA'].includes(x.tagName) || !!role(x)).length;
    const best = pool.map((e) => [score(e), e]).filter((x) => x[0] > 0).sort((a, b) => b[0] - a[0])[0];
    return best ? best[1] : document.body;
  };
  const region = (limit) => {
    const max = limit || 24000; let size = 0, count = 0, cut = false;
    const out = [];
    const put = (s) => { size += s.length; out.push(s); };
    const walk = (n, depth) => {
      if (cut) return;
      if (size > max || count > 700 || depth > 40) { cut = true; return; }
      if (n.nodeType === 3) { const t = QH.norm(n.textContent); if (t) put('  '.repeat(depth) + 'texto(' + t.length + ')\n'); return; }
      if (n.nodeType !== 1 || ['SCRIPT', 'STYLE', 'TEMPLATE', 'NOSCRIPT', 'LINK', 'META'].includes(n.tagName)) return;
      count++;
      const tag = n.tagName.toLowerCase();
      const attrs = [];
      for (const a of Array.from(n.attributes)) {
        const k = a.name.toLowerCase();
        if (tag === 'input' && (n.getAttribute('type') || '').toLowerCase() === 'hidden') { if (k === 'type') attrs.push('type="hidden"'); continue; }
        if (k === 'aria-label' || k === 'aria-description' || k === 'aria-valuetext' || k === 'aria-roledescription') attrs.push(k + '="texto(' + a.value.length + ')"');
        else if (KEEP.includes(k) || k.startsWith('aria-')) attrs.push(k + '="' + String(a.value).slice(0, 80).replace(/"/g, "'") + '"');
        else if (k.startsWith('data-')) attrs.push(k);
      }
      const shown = QH.visible(n) ? '' : ' oculto';
      const line = '  '.repeat(depth) + '<' + tag + (attrs.length ? ' ' + attrs.join(' ') : '') + '>' + shown;
      if (tag === 'svg' || tag === 'canvas' || tag === 'img' || tag === 'iframe') { put(line + '\n'); return; }
      if (isBtn(n)) { put(line + ' rotulo="' + (vtext(n) || n.getAttribute('aria-label') || n.value || '').slice(0, 40).replace(/"/g, "'") + '"\n'); return; }
      if (tag === 'select') { put(line + ' opcoes=' + n.options.length + '\n'); return; }
      put(line + '\n');
      for (const c of n.childNodes) walk(c, depth + 1);
      if (n.shadowRoot) { put('  '.repeat(depth + 1) + '#shadow-root\n'); for (const c of n.shadowRoot.childNodes) walk(c, depth + 2); }
    };
    walk(regionRoot(), 0);
    return { outline: out.join(''), truncated: cut, elements: count };
  };

  // ------------------------------------------------------------ estrutura (modo aprender, sem consulta externa)
  // Mapa ESTRUTURAL do quadro e um perfil candidato com confiança por campo. Sai só marcação:
  // seletores, papéis, contagens e o rótulo de botões de conferir, refazer ou avançar. Nenhum
  // texto de enunciado ou alternativa, nenhum valor de campo, nenhum endereço, nenhum id.
  // O que a página não mostra ao script (ouvintes de clique, shadow DOM fechado, quadros de
  // outra origem) fica com quem chama: aqui `listeners` é sempre null.
  //
  // FORMATO (version 1; campos novos só entram como acréscimo):
  //   status       'verified' (global >= 0.85) | 'unverified' (0.5 a 0.85) | 'pause' (< 0.5) |
  //                'experimental' (tipo fora do perfil v0: TEXT, ORDER, MATCH) | 'none' | 'limit'
  //   kind, kinds  tipo principal (SINGLE > MULTI > DROPDOWN > MATCH; TEXT e ORDER só sem os outros) e todos os vistos
  //   ambiguous    mais de um grupo de resposta, ou controle solto, na mesma região
  //   truncated, elements, shadow_depth     limites: 50000 elementos, 20 níveis de shadow DOM, 8 s
  //   interactive  { total, tag, role, signal, listeners: null }
  //   groups[]     { key, selector, parent, tag, role, type, via: 'tag'|'role'|'signal', count, visible, shadow_depth,
  //                  label: 'wrap'|'for'|'labelledby'|'aria-label'|'describedby'|'own'|'sibling'|'none',
  //                  group_label: 'legend'|'labelledby'|'aria-label'|'none' }       (até 60, do maior para o menor)
  //   controls     { submit[], reset[], next[]: { selector, hint, count }; feedback: { correct[], incorrect[], text[]: { selector, count } } }
  //                `next` é só informação: avançar nunca entra no perfil.
  //   candidates   { '<tabela>.<campo>': [ { selector, count, exact, confidence } ] }   (até 3 por campo, o melhor primeiro)
  //   profile      tabelas do PERFIL TOML v0 sem [site] (question, options, dropdown, submit, reset, feedback) ou null
  //   confidence   { fields: { '<tabela>.<campo>': 0..1 }, global }   global = menor entre question.container,
  //                question.stem, options.item ou dropdown.item e submit.button (este, só quando há botão)
  //   check        { hosts, agree }: o perfil candidato lê as mesmas questões que a heurística? (null sem perfil)
  //   notes[]      motivos, em texto fixo
  //   fingerprint  resumo de (pai, marca, papel, tipo) dos grupos; não usa contagens nem texto
  const MAX_NODES = 50000, MAX_SHADOW = 20, MAX_MS = 8000;
  const NEXT = /^(next|continue|proximo|proxima|continuar|avancar|seguinte)( (question|questao|pergunta|item|page|pagina))?$/;
  const FB_OK = /(^|[-_])(correct|right|correto|correta|certo|certa|acerto|success)($|[-_])/i;
  const FB_BAD = /(^|[-_])(incorrect|wrong|incorreto|incorreta|errado|errada|erro|error)($|[-_])/i;
  const STATE = /(^|[-_])(selected|active|checked|chosen|pressed|hover|focus|focused|disabled|current|open)($|[-_])/i;
  const NATIVE = ['INPUT', 'TEXTAREA', 'SELECT', 'BUTTON'];
  const ROLES = ['radio', 'checkbox', 'option', 'button', 'textbox', 'combobox', 'listbox', 'menuitem', 'tab', 'switch', 'slider', 'spinbutton'];
  // Classe com cara de identificador gerado (dígitos longos ou trecho que mistura letra e dígito) não entra em seletor.
  const noisy = (c) => /\d{4,}/.test(c) || c.split(/[-_]+/).some((p) => p.length >= 5 && /\d/.test(p) && /[a-z]/i.test(p));
  const cls = (e, fb) => (e.getAttribute('class') || '').split(/\s+/).filter((c) => /^[A-Za-z_][\w-]{0,40}$/.test(c)
    && !noisy(c) && !STATE.test(c) && (fb || !(FB_OK.test(c) || FB_BAD.test(c))));
  const tagOf = (e) => { const t = e.tagName.toLowerCase(); return /^[a-z][a-z0-9-]*$/.test(t) ? t : '*'; };
  const base = (e) => { const t = e.tagName === 'INPUT' ? (e.getAttribute('type') || '').toLowerCase() : '', r = role(e);
    return tagOf(e) + (/^[a-z]+$/.test(t) ? '[type="' + t + '"]' : '') + (/^[a-z]+$/.test(r) ? '[role="' + r + '"]' : ''); };
  // Seletores estruturais de um elemento, do mais específico ao mais geral.
  const variants = (e, fb) => { const tag = tagOf(e), b = base(e), c = cls(e, fb), out = [];
    if (c.length > 1) out.push(tag + '.' + c[0] + '.' + c[1]);
    for (const x of c.slice(0, 3)) out.push(tag + '.' + x);
    if (b !== tag) out.push(b);
    out.push(tag);
    return Array.from(new Set(out)); };
  const interactive = (e) => {
    if (NATIVE.includes(e.tagName)) return e.tagName === 'INPUT' && (e.getAttribute('type') || '').toLowerCase() === 'hidden' ? '' : 'tag';
    if (e.tagName === 'A' && e.hasAttribute('href')) return 'tag';
    if (e.hasAttribute('contenteditable') && e.getAttribute('contenteditable') !== 'false') return 'tag';
    if (ROLES.includes(role(e))) return 'role';
    const ti = e.getAttribute('tabindex'); if (ti !== null && parseInt(ti, 10) >= 0) return 'signal';
    if (getComputedStyle(e).cursor === 'pointer') { const p = QH.parent(e); if (!p || getComputedStyle(p).cursor !== 'pointer') return 'signal'; }
    return '';
  };
  // De onde vem o rótulo de um controle (a origem, nunca o texto).
  const labelSrc = (e) => { const l = labelOf(e);
    if (l) return QH.contains(l, e) ? 'wrap' : 'for';
    if (e.getAttribute('aria-labelledby')) return 'labelledby';
    if (e.getAttribute('aria-label')) return 'aria-label';
    if (e.getAttribute('aria-describedby')) return 'describedby';
    if (e.tagName !== 'INPUT' && e.tagName !== 'SELECT' && e.tagName !== 'TEXTAREA' && vtext(e)) return 'own';
    if (e.nextSibling && e.nextSibling.nodeType === 3 && QH.norm(e.nextSibling.textContent)) return 'sibling';
    return 'none'; };
  const groupLabel = (e) => { const g = owner(e); if (!g) return 'none';
    if (g.tagName === 'FIELDSET' && Array.from(g.children).some((c) => c.tagName === 'LEGEND')) return 'legend';
    return g.getAttribute('aria-labelledby') ? 'labelledby' : g.getAttribute('aria-label') ? 'aria-label' : 'none'; };
  const inView = (e) => QH.visible(e) && !clipped(e);
  const top = (counts) => Object.keys(counts).sort((a, b) => counts[b] - counts[a])[0] || 'none';
  // Para cada candidato: quantos elementos visíveis acha e se, em cada escopo, acha exatamente os esperados.
  const fit = (cands, scopes, want) => cands.map((s) => { let exact = true, count = 0;
      scopes.forEach((sc, i) => { const got = q(sc, s).filter(inView); count += got.length;
        if (got.length !== want[i].length || got.some((x) => !want[i].includes(x))) exact = false; });
      return { selector: s, count, exact }; })
    .sort((a, b) => (b.exact ? 1 : 0) - (a.exact ? 1 : 0)).slice(0, 3);
  const uniq = (list) => Array.from(new Set(list));
  const round = (n) => Math.round(n * 100) / 100;

  const structure = () => {
    const t0 = performance.now(); let elements = 0, deep = 0, cut = false;
    const found = [];
    const scan = (r, d) => {
      if (d > MAX_SHADOW) { cut = true; return; }
      if (d > deep) deep = d;
      for (const e of r.querySelectorAll('*')) {
        if (++elements > MAX_NODES || (elements % 500 === 0 && performance.now() - t0 > MAX_MS)) { cut = true; return; }
        const via = interactive(e); if (via) found.push({ e, via, depth: d });
        if (e.shadowRoot) { scan(e.shadowRoot, d + 1); if (cut) return; }
      }
    };
    scan(document, 0);
    const out = { version: 1, status: 'none', kind: null, kinds: [], ambiguous: false, truncated: cut, elements, shadow_depth: deep,
      interactive: { total: found.length, tag: 0, role: 0, signal: 0, listeners: null }, groups: [],
      controls: { submit: [], reset: [], next: [], feedback: { correct: [], incorrect: [], text: [] } },
      candidates: {}, profile: null, confidence: { fields: {}, global: 0 }, check: null, notes: [], fingerprint: '' };
    if (cut) { out.status = 'limit'; out.notes.push('limite de captura excedido'); return out; }

    // ---- grupos: mesmo pai (pela assinatura), mesmo papel, mesma marca e classes equivalentes
    const gmap = new Map();
    for (const n of found) {
      out.interactive[n.via]++;
      const p = QH.parent(n.e), parent = p ? variants(p)[0] : '';
      const sig = [parent, role(n.e), base(n.e), cls(n.e).join('.')].join('|');
      if (!gmap.has(sig)) gmap.set(sig, { key: 'g' + hash(sig), selector: variants(n.e)[0], parent, tag: tagOf(n.e), role: role(n.e) || null,
        type: n.e.tagName === 'INPUT' ? (n.e.getAttribute('type') || '').toLowerCase() || null : null, via: n.via,
        count: 0, visible: 0, shadow_depth: 0, _l: {}, _g: {} });
      const g = gmap.get(sig); g.count++;
      if (QH.visible(n.e)) g.visible++;
      if (n.depth > g.shadow_depth) g.shadow_depth = n.depth;
      const l = labelSrc(n.e), gl = groupLabel(n.e);
      g._l[l] = (g._l[l] || 0) + 1; g._g[gl] = (g._g[gl] || 0) + 1;
    }
    out.groups = Array.from(gmap.values()).sort((a, b) => b.count - a.count).slice(0, 60)
      .map((g) => { const r = Object.assign({}, g, { label: top(g._l), group_label: top(g._g) }); delete r._l; delete r._g; return r; });
    out.fingerprint = 'f' + hash(uniq(Array.from(gmap.values()).filter((g) => g.via !== 'signal')
      .map((g) => [g.parent, g.tag, g.role || '', g.type || ''].join('|'))).sort().join('\n'));

    // ---- controles de fluxo e retorno
    const ctl = (list) => { const seen = new Map();
      for (const b of list) { const s = variants(b)[0]; if (!seen.has(s)) seen.set(s, { selector: s, hint: btnLabel(b).slice(0, 64), count: 0 }); seen.get(s).count++; }
      return Array.from(seen.values()).slice(0, 3); };
    const shown = (re) => buttonsIn(document, re).filter((b) => QH.visible(b));
    out.controls.submit = ctl(shown(SUBMIT)); out.controls.reset = ctl(shown(RESET)); out.controls.next = ctl(shown(NEXT));
    const marks = (re) => { const seen = new Map();
      for (const e of QH.all(document, (x) => cls(x, true).some((c) => re.test(c)))) {
        const s = tagOf(e) + '.' + cls(e, true).find((c) => re.test(c)); seen.set(s, (seen.get(s) || 0) + 1); }
      return Array.from(seen, (x) => ({ selector: x[0], count: x[1] })).slice(0, 3); };
    out.controls.feedback.correct = marks(FB_OK); out.controls.feedback.incorrect = marks(FB_BAD);
    const live = new Map();
    for (const e of QH.all(document, (x) => ['status', 'alert'].includes(role(x)) || ['polite', 'assertive'].includes(x.getAttribute('aria-live') || ''))) {
      const s = variants(e, true)[0]; live.set(s, (live.get(s) || 0) + 1); }
    out.controls.feedback.text = Array.from(live, (x) => ({ selector: x[0], count: x[1] })).slice(0, 3);

    // ---- tipo (H1 a H6) a partir dos mesmos átomos da leitura heurística
    const atoms = atomsIn(document), units = atoms.map((a) => unitOf(a, atoms));
    out.kinds = uniq(atoms.map((a) => a.kind));
    out.kind = ['SINGLE', 'MULTI', 'DROPDOWN', 'MATCH'].find((k) => out.kinds.includes(k)) || null;
    if (!out.kind) {
      if (typed().length) out.kind = 'TEXT';
      else if (QH.all(document, (e) => QH.visible(e) && (e.getAttribute('draggable') === 'true' || e.hasAttribute('aria-grabbed'))).length >= 2) out.kind = 'ORDER';
      if (out.kind) { out.status = 'experimental'; out.kinds = [out.kind]; out.notes.push('tipo fora do contrato v0: lido, sem ação'); }
      return out;
    }
    const used = atoms.map((a, i) => ({ a, u: units[i] })).filter((x) => x.a.kind !== 'MATCH' && QH.visible(x.u));
    if (!used.length) { out.status = 'experimental'; out.notes.push('associação: o perfil v0 não a descreve; a leitura heurística cobre'); return out; }
    if (out.kinds.includes('MATCH')) out.notes.push('há associação na página: fica com a leitura heurística');
    const hosts = uniq(used.map((x) => x.u));
    const mine = (h) => used.filter((x) => x.u === h).map((x) => x.a);
    // Controle de resposta solto na região (fora de qualquer grupo lido) também deixa a leitura ambígua.
    const grouped = new Set([].concat(...atoms.map((a) => a.els)));
    const stray = [].concat(...hosts.map((h) => QH.all(h, (e) => !grouped.has(e) && ((rc(e) && rcVisible(e) && !QH.chain(e).slice(1).some((c) => ARIA_OPT.includes(role(c)))) ||
      (ARIA_OPT.includes(role(e)) && e.tagName !== 'INPUT' && e.tagName !== 'OPTION' && QH.visible(e)) || (e.tagName === 'SELECT' && QH.visible(e))))));
    for (const e of stray) { const t = rc(e) || role(e), k = e.tagName === 'SELECT' ? 'DROPDOWN' : t === 'checkbox' ? 'MULTI' : 'SINGLE';
      if (!out.kinds.includes(k)) out.kinds.push(k); }
    out.ambiguous = stray.length > 0 || hosts.some((h) => atoms.filter((a) => QH.contains(h, a.els[0])).length > 1);
    if (out.ambiguous) out.notes.push('mais de um grupo de resposta na mesma região');
    const fields = out.confidence.fields, prof = { question: {} };
    const put = (name, list, conf) => { out.candidates[name] = list.map((c, i) => Object.assign(c, { confidence: i ? round(conf * 0.8) : conf }));
      fields[name] = list.length ? conf : 0; return list.length ? list[0].selector : null; };

    // question.container
    const bare = hosts.some((h) => h.tagName === 'BODY' || h.tagName === 'HTML');
    const cc = fit(uniq([].concat(...hosts.map((h) => variants(h)))), [document], [hosts]);
    prof.question.container = put('question.container', cc, !cc.length ? 0 : !cc[0].exact ? 0.4 : bare ? 0.6 : 0.9);
    if (bare) out.notes.push('questão sem região própria');

    // options.item e dropdown.item
    const itemOf = (e) => { const l = rc(e) ? labelOf(e) : null; return l && labelShown(l) ? l : e; };
    const table = (name, pick, sure) => {
      const hs = hosts.filter((h) => mine(h).some(pick)); if (!hs.length) return;
      const want = hs.map((h) => [].concat(...mine(h).filter(pick).map((a) => a.els.map(itemOf))));
      const cand = fit(uniq([].concat(...want.map((w) => variants(w[0])))), hs, want);
      const least = Math.min(...want.map((w) => w.length));
      const conf = !cand.length || !cand[0].exact ? 0.3 : sure(want) ? (name === 'dropdown.item' || least >= 3 ? 0.9 : 0.8) : 0.6;
      const sel = put(name, cand, conf);
      if (sel && name === 'options.item') prof.options = { item: sel };
      if (sel && name === 'dropdown.item') prof.dropdown = { item: sel, native: true };
    };
    table('options.item', (a) => a.kind === 'SINGLE' || a.kind === 'MULTI',
      () => used.every((x) => x.a.kind === 'DROPDOWN' || x.a.form === 'native' || x.a.form === 'aria'));
    table('dropdown.item', (a) => a.kind === 'DROPDOWN', () => true);

    // question.stem: o enunciado explícito do grupo ou um bloco de texto antes das alternativas
    const stemEls = (h) => { const a = mine(h)[0], hd = head(h, a);
      if (hd && hd.via) return { els: [hd.via], explicit: true };
      const all = QH.all(h, () => true), first = all.indexOf(a.els[0]), ex = exclusions(a);
      const ok = all.filter((e, i) => (first < 0 || i < first) && inView(e) && !isBtn(e) && !isFb(e) && !ex.has(e)
        && !QH.chain(e).some((c) => ex.has(c) || c.tagName === 'LABEL')
        && Array.from(e.childNodes).some((n) => n.nodeType === 3 && QH.norm(n.textContent).length >= 3));
      // O bloco de texto mais longo antes das alternativas (o tamanho serve só para ordenar; não sai daqui).
      const size = (e) => Array.from(e.childNodes).filter((n) => n.nodeType === 3).reduce((t, n) => t + QH.norm(n.textContent).length, 0);
      return { els: ok.slice().sort((x, y) => size(y) - size(x)).slice(0, 3), explicit: false }; };
    const s0 = stemEls(hosts[0]);
    const sc = uniq([].concat(...s0.els.map((e) => variants(e)))).map((s) => { let exact = true, count = 0;
        for (const h of hosts) { const got = q(h, s).filter((x) => inView(x) && vtext(x)); count += got.length; if (got.length !== 1) exact = false; }
        return { selector: s, count, exact }; })
      .sort((a, b) => (b.exact ? 1 : 0) - (a.exact ? 1 : 0)).slice(0, 3);
    prof.question.stem = put('question.stem', sc, !sc.length ? 0 : !sc[0].exact ? 0.4
      : s0.explicit || /^(h[1-6]|legend)\b|role="heading"/.test(sc[0].selector) ? 0.9 : 0.7);
    if (!sc.length) out.notes.push('sem enunciado reconhecível');

    // submit.button e reset.button: um único botão por região
    const flow = (name, re) => {
      const per = hosts.map((h) => buttonsIn(h, re).filter((b) => QH.visible(b)));
      if (per.every((l) => !l.length)) return;
      const cand = fit(uniq([].concat(...per.filter((l) => l.length).map((l) => variants(l[0])))), hosts, per);
      const sel = put(name, cand, cand.length && cand[0].exact && per.every((l) => l.length === 1) ? 0.9 : 0.4);
      if (sel && fields[name] >= 0.5) prof[name.split('.')[0]] = { button: sel };
    };
    flow('submit.button', SUBMIT); flow('reset.button', RESET);

    // feedback: só marcas de classe ou região viva, quando existem
    const fbk = {}, fc = out.controls.feedback;
    if (fc.correct.length) fbk.correct = fc.correct[0].selector;
    if (fc.incorrect.length) fbk.incorrect = fc.incorrect[0].selector;
    if (fc.text.length) fbk.text = fc.text[0].selector;
    if (Object.keys(fbk).length) { prof.feedback = fbk; for (const k of Object.keys(fbk)) fields['feedback.' + k] = 0.85; }

    // ---- confiança global: o menor entre os campos obrigatórios (e o envio, quando há)
    const need = ['question.container', 'question.stem'].concat(Object.keys(fields).filter((k) => /^(options|dropdown)\.item$|^submit\.button$/.test(k)));
    let global = Math.min(...need.map((k) => fields[k]));
    if (out.ambiguous) global = Math.min(global, 0.4);
    const whole = !!prof.question.container && !!prof.question.stem && !!(prof.options || prof.dropdown);
    if (whole) {
      // Conferência por leitura: o perfil candidato lê as mesmas questões que a heurística?
      const ph = profileHosts(prof);
      const agree = ph.length === hosts.length && ph.every((h) => { const a = extractProfile(h, prof), b = extractHeuristic(h);
        return !!b && a.kind === b.kind && a.options.length === b.options.length && a.items.length === b.items.length && !!a.stem && !a.notes.length; });
      out.check = { hosts: ph.length, agree };
      if (!agree) { global = Math.min(global, 0.45); out.notes.push('o perfil candidato não leu as mesmas questões que a heurística'); }
      out.profile = prof;
    } else { global = Math.min(global, 0.3); out.notes.push('perfil incompleto'); }
    out.confidence.global = round(Math.max(0, global));
    out.status = out.confidence.global >= 0.85 ? 'verified' : out.confidence.global >= 0.5 ? 'unverified' : 'pause';
    return out;
  };

  return { version: 1, locate, extract, option, buttons, verdict, figures, diagnose, region, structure };
})();
