// Simulador do comportamento do NetAcad sobre fixtures sintéticas,
// injetado pelo servidor de teste. Configuração em
// window.__SIM (pode ser definida depois do carregamento):
//   key: {<data-socialgoodpulse-id>: resposta certa}
//        mcq: [índices internos]; dropdown: [opção por item]; match: {"<índice da direita>": "<letra>"}
//   autoAdvance: true   avaliação avança sozinha depois do Submit da barra
//   attempts: 2         tentativas por componente de seção (Reset depois do erro)
// Registro: window.__SIM_CLICKS (todo clique) e window.__SIM_FINAL_SUBMITTED.
(() => {
  window.__SIM = window.__SIM || {};
  window.__SIM_CLICKS = [];
  window.__SIM_FINAL_SUBMITTED = false;
  const cfg = () => Object.assign({autoAdvance: true, attempts: 2, key: {}}, window.__SIM);
  const all = (root, pred) => { const out = []; const w = (r) => { for (const e of r.querySelectorAll('*')) {
      if (pred(e)) out.push(e); if (e.shadowRoot) w(e.shadowRoot); } }; w(root); return out; };
  const first = (root, pred) => all(root, pred)[0] || null;
  const desc = (e) => `${e.tagName.toLowerCase()}${e.id ? '#' + e.id : ''}.${String(e.className || '').trim().split(/\s+/).join('.')}` +
    ` "${(e.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 40)}"`;
  const qOf = (host) => host.shadowRoot.querySelector('.is-question');
  const toolbar = () => first(document, e => e.tagName === 'ASSESSMENT-TOOLBAR-VIEW');
  const strip = () => first(document, e => e.tagName === 'ASSESSMENT-BLOCK-STRIP-VIEW');
  const blocks = () => all(document, e => e.tagName === 'DIV' && e.classList.contains('block') && /^blk\d+$/.test(e.classList[0] || ''));
  const activeBlock = () => { const a = first(strip().shadowRoot, e => e.classList && e.classList.contains('active-block'));
      return a ? blocks().find(b => b.classList.contains(a.dataset.blockId)) : null; };
  const hostOf = (path) => path.find(e => e.shadowRoot && e.shadowRoot.querySelector && e.shadowRoot.querySelector('.is-question'));

  const setChecked = (item, on) => {
    item.setAttribute('aria-checked', on ? 'true' : 'false');
    const inp = item.querySelector('input'); if (inp) inp.checked = on;
  };
  const toggleItem = (item) => {
    const widget = item.closest('.mcq__widget');
    if (widget.classList.contains('is-submitted')) return;
    if (item.getAttribute('role') === 'radio') widget.querySelectorAll('.mcq__item').forEach(i => setChecked(i, i === item));
    else setChecked(item, item.getAttribute('aria-checked') !== 'true');
    const tb = toolbar();
    if (tb) {
      const btn = tb.shadowRoot.querySelector('button.submit-button');
      const any = !!widget.querySelector('.mcq__item[aria-checked=true]');
      btn.disabled = !any; btn.classList.toggle('is-disabled', !any);
    }
  };

  const advance = () => {
    const bs = blocks(); const cur = activeBlock(); const i = bs.indexOf(cur);
    const sroot = strip().shadowRoot; const inner = sroot.querySelector('.attempted-blocks-inner');
    sroot.querySelectorAll('.block-button').forEach(b => { b.classList.remove('active-block'); b.setAttribute('aria-label', b.getAttribute('aria-label').replace(/^selected /, 'answered ')); });
    const tb = toolbar().shadowRoot; const btn = tb.querySelector('button.submit-button');
    btn.disabled = true; btn.classList.add('is-disabled');
    if (i + 1 < bs.length) {
      const id = bs[i + 1].classList[0]; const n = i + 2;
      inner.insertAdjacentHTML('beforeend', `<button data-index="${n}" class="block-button active-block" data-block-id="${id}" aria-label="selected Question ${n}">Q${n}</button>`);
      tb.querySelector('.question-label').firstChild.textContent = `${n} of ${bs.length}`;
    } else {
      inner.insertAdjacentHTML('beforeend', '<button class="block-button active-block last-block review-screen-button" aria-label="selectedSubmit Page">Submit Page</button>');
      const fs = first(document, e => e.tagName === 'FINALSCREEN-VIEW');
      fs.style.display = '';
      const unanswered = bs.filter(b => !b.dataset.answered).length;
      fs.shadowRoot.querySelector('.unanswered-instruction').textContent = `You have ${unanswered} unanswered questions:`;
    }
  };

  const grade = (host) => {
    const q = qOf(host); const id = q.getAttribute('data-socialgoodpulse-id'); const key = cfg().key[id];
    if (host.tagName === 'MCQ-VIEW') {
      const got = Array.from(q.querySelectorAll('.mcq__item[aria-checked=true]')).map(i => +i.dataset.socialgoodpulseIndex).sort();
      return JSON.stringify(got) === JSON.stringify([...(key || [])].sort());
    }
    if (host.tagName === 'MATCHING-VIEW') {
      const got = Array.from(q.querySelectorAll('matching-dropdown-view')).map(d => { const s = d.shadowRoot.querySelector('li[aria-selected=true]'); return s ? +s.dataset.index : null; });
      return JSON.stringify(got) === JSON.stringify(key || []);
    }
    if (host.tagName === 'OBJECT-MATCHING-VIEW') {
      const got = {}; q.querySelectorAll('button.objectMatching-option-item').forEach((b, i) => { got[i] = b.querySelector('.category-item-number').textContent.trim(); });
      return Object.keys(key || {}).every(k => got[k] === key[k]) && Object.values(got).every(v => v);
    }
    return false;
  };

  const resetComponent = (host) => {
    const q = qOf(host);
    q.querySelectorAll('.component__widget').forEach(w => w.classList.remove('is-submitted', 'is-complete', 'is-disabled'));
    q.querySelectorAll('.mcq__item').forEach(i => setChecked(i, false));
    q.querySelectorAll('matching-dropdown-view').forEach(d => { const s = d.shadowRoot;
      s.querySelectorAll('li').forEach(li => { li.classList.remove('selected'); li.setAttribute('aria-selected', 'false'); });
      s.querySelector('.dropdown__inner').textContent = 'Please select an option'; });
    q.querySelectorAll('button.objectMatching-option-item .category-item-number').forEach(n => { n.textContent = ''; });
    const bv = first(q, e => e.tagName === 'BUTTONS-VIEW').shadowRoot;
    const mark = bv.querySelector('.js-btn-marking'); mark.className = 'btn__marking item-state js-btn-marking'; mark.setAttribute('aria-label', '');
    const act = bv.querySelector('.js-btn-action'); act.textContent = 'Submit'; act.setAttribute('aria-label', 'Submit Your answer will be submitted');
  };

  const pendingLeft = new WeakMap();
  document.addEventListener('click', (ev) => {
    const path = ev.composedPath().filter(e => e instanceof Element);
    if (!path.length) return;
    window.__SIM_CLICKS.push(desc(path[0]));
    const has = (pred) => path.find(pred);
    const adaptive = has(e => e.classList.contains('adaptive-assessment-submit'));
    if (adaptive) { if (!adaptive.classList.contains('is-disabled')) window.__SIM_FINAL_SUBMITTED = true; return; }
    const confirm = has(e => e.id === 'confirm-exam' || e.id === 'confirm-label');
    if (confirm) { const fs = first(document, e => e.tagName === 'FINALSCREEN-VIEW').shadowRoot;
      const btn = fs.querySelector('.adaptive-assessment-submit'); btn.classList.remove('disabled', 'is-disabled'); btn.setAttribute('aria-label', 'Submit'); return; }
    const host = hostOf(path);
    const item = has(e => e.classList.contains('mcq__item'));
    // Clique no <label> gera um segundo clique, sintético, no <input> ligado a ele.
    if (item) { if (path[0].tagName !== 'INPUT') toggleItem(item); return; }
    const ddBtn = has(e => e.classList.contains('dropdown__btn'));
    if (ddBtn) { const list = ddBtn.getRootNode().querySelector('ul[role=listbox]'); const open = list.classList.toggle('hidden') === false;
      ddBtn.setAttribute('aria-expanded', open ? 'true' : 'false'); return; }
    const li = has(e => e.tagName === 'LI' && e.getAttribute('role') === 'option');
    if (li) { const root = li.getRootNode(); root.querySelectorAll('li').forEach(x => { const on = x === li; x.classList.toggle('selected', on); x.setAttribute('aria-selected', on ? 'true' : 'false'); });
      root.querySelector('.dropdown__inner').textContent = li.querySelector('.dropdown__item-inner').firstChild.textContent.trim();
      root.querySelector('ul').classList.add('hidden'); root.querySelector('button.dropdown__btn').setAttribute('aria-expanded', 'false'); return; }
    const cat = has(e => e.classList.contains('objectMatching-category-item'));
    if (cat && host) { pendingLeft.set(host, cat.querySelector('.category-item-number').textContent.trim()); return; }
    const opt = has(e => e.classList.contains('objectMatching-option-item'));
    if (opt && host) { const l = pendingLeft.get(host); if (l) { opt.querySelector('.category-item-number').textContent = l; pendingLeft.delete(host); } return; }
    const tbSubmit = has(e => e.classList.contains('submit-button'));
    if (tbSubmit) { if (tbSubmit.disabled) return; const b = activeBlock(); if (b) b.dataset.answered = '1';
      if (cfg().autoAdvance) setTimeout(advance, 150); return; }
    const act = has(e => e.classList.contains('js-btn-action'));
    if (act && host) {
      const q = qOf(host); const bv = act.getRootNode(); const mark = bv.querySelector('.js-btn-marking');
      if (act.textContent.trim() === 'Reset') { resetComponent(host); return; }
      const ok = grade(host); host.__tries = (host.__tries || 0) + 1;
      setTimeout(() => {
        q.querySelectorAll('.component__widget').forEach(w => w.classList.add('is-submitted'));
        mark.classList.add(ok ? 'is-correct' : 'is-incorrect');
        mark.setAttribute('aria-label', ok ? 'You answered correctly' : 'You answered incorrectly');
        if (ok || host.__tries >= cfg().attempts) {
          q.querySelectorAll('.component__widget').forEach(w => w.classList.add('is-complete', 'is-disabled'));
          act.disabled = true; act.classList.add('is-disabled');
        } else { act.textContent = 'Reset'; act.setAttribute('aria-label', 'Reset'); }
      }, 150);
    }
  }, true);
})();
