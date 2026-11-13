"""A guarda: a ÚNICA função que age na página.

Toda ação (marcar uma alternativa, escolher num dropdown, Submit, Reset) é um
`Target` proposto pelo adaptador e executado só por `Guard.perform`. Nenhum
outro módulo chama `.click()`, `.check()`, `.select_option()`, `.drag_to()`,
`.press()` ou `.dispatch_event()` (um teste confere isso no código-fonte).

Invariantes (em código, nenhum perfil ou configuração os relaxa):
1. Uma questão por vez: a guarda é presa (`bind`) a uma questão e recusa alvo
   de outra questão ou fora do componente dela.
2. Nunca envio global: rótulos de Submit/Reset com termos da blocklist
   (all, assessment, exam, finish, end e variantes) são recusados; um perfil
   só ACRESCENTA termos. Um Submit de formulário que enviaria outras questões
   também é recusado.
3. Para em tela de resultado: sem a questão visível e com frase de resultado
   na página, levanta `ResultScreen`; nada é clicado.
4. Só o Submit da questão: papel `submit` exige botão dentro do componente.
5. Só elementos de resposta reconhecíveis por tipo/papel ARIA (radio, checkbox,
   option, <select>, botão); nada de inputs de confirmação, links ou formulários.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Callable, Iterable

from .core.domjs import js
from .core.model import Target

# Termos que, no rótulo de um Submit/Reset, indicam envio ou reinício GLOBAL.
BLOCK_WORDS = frozenset({
    "all", "assessment", "exam", "finish", "end", "final", "page", "quiz", "test", "entire", "whole",
    "complete", "done", "skip", "global",
    "tudo", "todas", "todos", "avaliacao", "prova", "exame", "fim", "finalizar", "encerrar", "terminar",
    "concluir", "pular",
})
# Frases bloqueadas em qualquer papel (inclusive alternativas).
BLOCK_PHRASES = ("submit page", "submit my", "submit all", "submit quiz", "submit test", "submit exam",
                 "submit assessment", "skip all", "skip question", "confirm my submission",
                 "enviar tudo", "enviar prova", "enviar avaliacao", "enviar todas", "finalizar")
# Frases de tela de resultado (sem a questão visível, o laço encerra sem clicar).
RESULT_PHRASES = ("quiz complete", "assessment complete", "exam complete", "activity complete",
                  "your score", "you scored", "your result", "results", "resultado", "pontuacao",
                  "atividade concluida", "revisao da atividade", "revisao da tentativa", "resumo da tentativa",
                  "attempt summary", "attempt review")

ROLES = ("option", "submit", "reset")
ACTIONS = ("click", "select")


def fold(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn").lower().strip()


class Refused(Exception):
    """Ação recusada pela guarda (o laço pausa)."""

    def __init__(self, reason: str, desc: str = ""):
        super().__init__(f"{reason}: {desc}" if desc else reason)
        self.reason, self.desc = reason, desc


class ResultScreen(Exception):
    """A tela de resultado apareceu: encerrar sem clicar."""


_RESULT_VISIBLE = js(r"""
  const results = arg;
  return QH.all(document, e => QH.own(e) && QH.visible(e)).some(e => {
    const t = QH.fold(QH.own(e)); return t.length <= 80 && results.some(w => t.includes(w)); });
""")

_CHECK = js(r"""
  const {el, host, role, action, block, phrases, results} = arg;
  const desc = (e) => { if (!e) return '(nenhum)';
    const cls = String(e.className || '').trim().split(/\s+/).filter(Boolean).slice(0, 3).join('.');
    return `${e.tagName.toLowerCase()}${e.id ? '#' + e.id : ''}${cls ? '.' + cls : ''}` +
           ` texto=${JSON.stringify(QH.text(e).slice(0, 50))} aria=${JSON.stringify(e.getAttribute('aria-label') || '')}`; };
  const no = (reason, extra) => Object.assign({ok: false, reason, desc: desc(el)}, extra || {});
  if (!el || !el.isConnected) return no('elemento ausente ou desconectado');
  // 3. tela de resultado / questão fora da vista
  if (!host || !QH.visible(host)) {
    const shown = QH.all(document, e => QH.own(e) && QH.visible(e)).some(e => {
      const t = QH.fold(QH.own(e)); return t.length <= 80 && results.some(w => t.includes(w)); });
    return no(shown ? 'tela de resultado visível' : 'a questão atual não está visível', {result: shown});
  }
  // 1. uma questão por vez: o alvo precisa estar dentro do componente
  if (!QH.contains(host, el)) return no('fora da questão atual');
  const tag = el.tagName, type = (el.getAttribute('type') || '').toLowerCase(), r = (el.getAttribute('role') || '').toLowerCase();
  const isRC = (n) => !!n && n.tagName === 'INPUT' && ['radio', 'checkbox'].includes((n.getAttribute('type') || '').toLowerCase());
  const ctl = tag === 'LABEL' ? (el.control || QH.first(el, isRC)) : null;
  const ariaOpt = ['radio', 'checkbox', 'option', 'menuitemradio', 'menuitemcheckbox'].includes(r);
  const isBtn = (tag === 'BUTTON' && type !== 'reset') || (tag === 'INPUT' && ['submit', 'button'].includes(type)) || r === 'button';
  const isOpener = (tag === 'BUTTON' || r === 'combobox' || r === 'button') &&
    (el.hasAttribute('aria-haspopup') || el.hasAttribute('aria-expanded') || r === 'combobox');
  // 5. tipo do elemento por papel/ação
  let kind = null;
  if (role === 'option' && action === 'select') {
    if (tag === 'SELECT' && !el.multiple) kind = 'dropdown nativo';
  } else if (role === 'option' && action === 'click') {
    if (isRC(el) || ariaOpt || isRC(ctl)) kind = 'alternativa';
    else if (isOpener) kind = 'abrir dropdown';
  } else if ((role === 'submit' || role === 'reset') && action === 'click') {
    if (isBtn) kind = role;
  }
  if (!kind) return no(`elemento não permitido para ${role}/${action}`);
  // habilitado e visível
  const isOff = (n) => !!n && (n.disabled === true || n.getAttribute('aria-disabled') === 'true' ||
    /(^|\s)(disabled|is-disabled)(\s|$)/.test(String(n.className || '')));
  if (isOff(el) || isOff(ctl) || QH.chain(el).some(c => c.tagName === 'FIELDSET' && c.hasAttribute('disabled'))) return no('desabilitado');
  if (!QH.visible(el)) return no('invisível');
  // rótulo vindo do próprio elemento (nunca do que o adaptador diz)
  const labels = tag === 'INPUT' ? Array.from(el.labels || []).map((l) => QH.text(l)) : [];
  const parts = [QH.text(el), el.getAttribute('aria-label') || '', el.getAttribute('title') || '',
                 tag === 'INPUT' ? (el.value || '') : '', ctl ? (ctl.getAttribute('aria-label') || '') : '', ...labels];
  const blob = QH.fold(parts.join(' | '));
  const words = blob.split(/[^a-z0-9]+/).filter(Boolean);
  // 2. nunca envio global
  const bad = phrases.find(p => blob.includes(p));
  if (bad) return no(`texto bloqueado (${bad})`);
  if ((isRC(el) || isRC(ctl)) && blob.includes('confirm') && (blob.includes('submi') || blob.includes('envi'))) return no('checkbox de confirmação de envio');
  if (role === 'submit' || role === 'reset') {
    if (!words.length) return no('botão sem rótulo');
    const w = block.find(b => words.includes(b));
    if (w) return no(`rótulo na blocklist (${w})`);
  }
  if (role === 'submit' && el.form) {
    const others = Array.from(el.form.querySelectorAll('input[type=radio], input[type=checkbox], select')).filter(n => !QH.contains(host, n));
    if (others.length) return no('o Submit enviaria outras questões do formulário');
  }
  return {ok: true, kind, desc: desc(el)};
""")

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

# Escolha numa <select> nativa: opção existente, habilitada e visível.
_DOM_SELECT = r"""
  (el, value) => {
    const opt = el.options[value];
    if (!opt) return {ok: false, why: 'opção inexistente'};
    if (opt.disabled || opt.hidden) return {ok: false, why: 'opção desabilitada'};
    el.selectedIndex = value;
    el.dispatchEvent(new Event('input', {bubbles: true, composed: true}));
    el.dispatchEvent(new Event('change', {bubbles: true, composed: true}));
    return {ok: true};
  }
"""


class Guard:
    """Única porta de ação na página. `log(msg)` registra cada decisão."""

    def __init__(self, log: Callable[[str], None], dry_run: bool = False, extra_block: Iterable[str] = ()):
        words, phrases = set(BLOCK_WORDS), list(BLOCK_PHRASES)
        for term in (fold(t) for t in extra_block if t and t.strip()):      # o perfil só ACRESCENTA
            if " " in term:
                phrases.append(term)
            else:
                words.add(term)
        self.block = sorted(words)
        self.phrases = phrases
        self.log = log
        self.dry_run = dry_run
        self.frame = None
        self.host = None
        self.qid = ""
        self.clicks = 0

    def bind(self, frame, host, qid: str) -> None:
        """Prende a guarda a UMA questão (frame, componente e id)."""
        self.frame, self.host, self.qid = frame, host, qid

    def result_visible(self, frame=None) -> bool:
        return bool((frame or self.frame).evaluate(_RESULT_VISIBLE, list(RESULT_PHRASES)))

    def check(self, target: Target) -> dict:
        if target is None or target.element is None:
            return {"ok": False, "reason": "alvo não encontrado", "desc": "(nenhum)"}
        if target.role not in ROLES or target.action not in ACTIONS:
            return {"ok": False, "reason": f"papel/ação inválido: {target.role}/{target.action}", "desc": target.label}
        if self.frame is None or self.host is None:
            return {"ok": False, "reason": "guarda sem questão ativa", "desc": target.label}
        if target.qid != self.qid:
            return {"ok": False, "reason": "alvo de outra questão", "desc": target.label}
        return self.frame.evaluate(_CHECK, {"el": target.element, "host": self.host, "role": target.role,
                                            "action": target.action, "block": self.block,
                                            "phrases": self.phrases, "results": list(RESULT_PHRASES)})

    def perform(self, target: Target, why: str = "") -> str:
        """Executa o alvo se a guarda permitir. Devolve o tipo permitido.

        Levanta ResultScreen se a tela de resultado estiver visível e Refused em
        qualquer recusa (nada é feito nesses casos)."""
        if target is not None and target.opener is not None:
            self.perform(target.opener, f"abrir para {why}")
        verdict = self.check(target)
        label = target.label if target is not None else why
        if not verdict.get("ok"):
            if verdict.get("result"):
                self.log(f"guarda: tela de resultado visível; nada feito ({why or label})")
                raise ResultScreen()
            self.log(f"guarda RECUSOU ({why or label}): {verdict['reason']} — {verdict['desc']}")
            raise Refused(verdict["reason"], verdict["desc"])
        if self.dry_run:
            self.log(f"(dry-run) faria: {why or label} [{verdict['kind']}] {verdict['desc']}")
            return verdict["kind"]
        if target.action == "select":
            done = target.element.evaluate(_DOM_SELECT, target.value)
        else:
            done = target.element.evaluate(_DOM_CLICK)
        if not done.get("ok"):
            self.log(f"guarda RECUSOU ({why or label}): {done['why']} — {verdict['desc']}")
            raise Refused(done["why"], verdict["desc"])
        self.clicks += 1
        self.log(f"ação: {why or label} [{verdict['kind']}]")
        return verdict["kind"]
