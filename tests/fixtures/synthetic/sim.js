// Simulador do comportamento de um site de prática (fixtures sintéticas; nada de site real).
// - alternativas ARIA ganham o comportamento que o navegador não dá a <div>;
// - Submit mostra o feedback da questão; Reset desfaz;
// - registra cada clique em window.__SIM_CLICKS e envios globais em window.__SIM_GLOBAL.
(function () {
  window.__SIM_CLICKS = [];
  window.__SIM_GLOBAL = false;
  const deep = (root, pred) => { const out = []; const walk = (r) => { for (const e of r.querySelectorAll('*')) {
      if (pred(e)) out.push(e); if (e.shadowRoot) walk(e.shadowRoot); } }; walk(root); return out; };
  const up = (e) => e.parentElement || (e.getRootNode() && e.getRootNode().host) || null;
  const closest = (e, pred) => { for (let c = e; c; c = up(c)) if (pred(c)) return c; return null; };
  const isQ = (e) => e.classList && e.classList.contains('q');
  const choices = (q) => deep(q, (e) => (e.tagName === 'INPUT' && ['radio', 'checkbox'].includes(e.type)) ||
    ['radio', 'checkbox', 'option'].includes(e.getAttribute && e.getAttribute('role')));
  const isOn = (e) => e.tagName === 'INPUT' ? e.checked : e.getAttribute('aria-checked') === 'true' || e.getAttribute('aria-selected') === 'true';
  const setOn = (e, v) => { if (e.tagName === 'INPUT') e.checked = v;
    else { e.setAttribute(e.getAttribute('role') === 'option' ? 'aria-selected' : 'aria-checked', String(v)); } };
  const fb = (q) => deep(q, (e) => e.classList.contains('fb'))[0];
  const btn = (q, what) => deep(q, (e) => e.getAttribute('data-sim') === what)[0];

  function state(q) {
    const out = [];
    const cs = choices(q);
    if (cs.length) out.push(...cs.map((e, i) => (isOn(e) ? i : -1)).filter((i) => i >= 0));
    for (const s of deep(q, (e) => e.tagName === 'SELECT')) out.push(s.selectedIndex);
    return out.join(',');
  }
  function submit(q) {
    const ok = state(q) === q.dataset.correct;
    const f = fb(q);
    f.textContent = ok ? 'Correct! Well done.' : 'Incorrect. Try again.';
    f.className = 'fb ' + (ok ? 'is-correct' : 'is-incorrect');
    q.dataset.result = ok ? 'correct' : 'incorrect';
    btn(q, 'submit').disabled = true;
    const r = btn(q, 'reset'); if (r && !ok) r.hidden = false;
    window.__SIM_SUBMITS = (window.__SIM_SUBMITS || []).concat(q.id);
  }
  function reset(q) {
    for (const e of choices(q)) setOn(e, false);
    for (const s of deep(q, (e) => e.tagName === 'SELECT')) s.selectedIndex = 0;
    const f = fb(q); f.textContent = ''; f.className = 'fb';
    delete q.dataset.result;
    btn(q, 'submit').disabled = false;
    const r = btn(q, 'reset'); if (r) r.hidden = true;
    window.__SIM_RESETS = (window.__SIM_RESETS || []).concat(q.id);
  }

  document.addEventListener('click', (ev) => {
    const t = ev.composedPath()[0];
    window.__SIM_CLICKS.push((t.tagName || '?').toLowerCase() + (t.id ? '#' + t.id : '') + ':' + ((t.textContent || '').trim().slice(0, 30)));
    const q = closest(t, isQ);
    const role = closest(t, (e) => e.getAttribute && ['radio', 'checkbox', 'option'].includes(e.getAttribute('role')));
    if (role && q) {
      const r = role.getAttribute('role');
      if (r === 'checkbox') setOn(role, !isOn(role));
      else if (r === 'radio' || (r === 'option' && !closest(role, (e) => e.getAttribute && e.getAttribute('aria-multiselectable') === 'true'))) {
        const group = choices(q).filter((e) => e.getAttribute('role') === r);
        for (const e of group) setOn(e, false); setOn(role, true);
      } else setOn(role, !isOn(role));
    }
    const act = closest(t, (e) => e.getAttribute && e.getAttribute('data-sim'));
    if (!act) return;
    const what = act.getAttribute('data-sim');
    if (what === 'global') window.__SIM_GLOBAL = true;
    else if (q && !act.disabled && what === 'submit') submit(q);
    else if (q && what === 'reset') reset(q);
  }, true);
})();
