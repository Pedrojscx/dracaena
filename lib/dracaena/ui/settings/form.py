"""Formulário gerado só a partir de ``config.schema`` (sem listas duplicadas de chaves).

Cada entrada do schema: {key, type, default, description, min?, max?, choices?}.
Tipos tratados: integer, number, boolean, string (com ``choices`` vira lista de opções).
Inteiro com faixa 0..1 vira caixa de seleção (liga/desliga). Tipo desconhecido é tratado
como texto; a validação final é sempre do daemon (``config.set``).
"""
from __future__ import annotations

from typing import Any, Callable

from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QLabel, QLineEdit,
                               QSpinBox, QVBoxLayout, QWidget)

INT_MIN, INT_MAX = -(2**31) + 1, 2**31 - 1


def _label(entry: dict[str, Any]) -> str:
    """``label`` (pt-BR) do schema; sem ele, cai para ``description`` e depois para a chave."""
    text = str(entry.get("label") or entry.get("description") or entry["key"]).strip()
    return text[:1].upper() + text[1:]


def _hint(entry: dict[str, Any]) -> str:
    """Dica sob o campo: ``description`` (só quando há ``label``; senão ela já virou rótulo)."""
    return str(entry.get("description") or "").strip() if entry.get("label") else ""


class _Field:
    """Liga um widget Qt a (get, set) de um valor tipado."""

    def __init__(self, entry: dict[str, Any], on_change: Callable[[], None]) -> None:
        self.entry = entry
        kind = entry.get("type", "string")
        lo, hi = entry.get("min"), entry.get("max")
        if kind == "boolean" or (kind == "integer" and lo == 0 and hi == 1):
            w = QCheckBox()
            self.get = lambda: (w.isChecked() if kind == "boolean" else int(w.isChecked()))
            self.set = lambda v: w.setChecked(bool(v))
            w.toggled.connect(lambda _=None: on_change())
        elif kind == "integer":
            w = QSpinBox()
            w.setRange(int(lo) if lo is not None else INT_MIN, int(hi) if hi is not None else INT_MAX)
            self.get, self.set = w.value, lambda v: w.setValue(int(v))
            w.valueChanged.connect(lambda _=None: on_change())
        elif kind == "number":
            w = QDoubleSpinBox()
            w.setRange(float(lo) if lo is not None else -1e9, float(hi) if hi is not None else 1e9)
            w.setDecimals(3)
            self.get, self.set = w.value, lambda v: w.setValue(float(v))
            w.valueChanged.connect(lambda _=None: on_change())
        elif isinstance(entry.get("choices"), list) and entry["choices"]:
            w = QComboBox()
            choices = [str(c) for c in entry["choices"]]
            for c in choices:
                w.addItem(c if c else "(nenhum)", c)

            def set_choice(v, w=w):
                v = str(v)
                i = w.findData(v)
                if i < 0:  # valor atual fora das opções: mostra, mas não esconde
                    w.addItem(v if v else "(nenhum)", v)
                    i = w.findData(v)
                w.setCurrentIndex(i)
            self.get, self.set = (lambda w=w: w.currentData()), set_choice
            w.currentIndexChanged.connect(lambda _=None: on_change())
        else:
            w = QLineEdit()
            self.get, self.set = w.text, lambda v: w.setText(str(v))
            w.textChanged.connect(lambda _=None: on_change())
        w.setObjectName(f"field_{entry['key']}")
        tip = f"{_hint(entry) or _label(entry)}\n\n{entry['key']} — padrão: {entry.get('default')!r}"
        if lo is not None or hi is not None:
            tip += f" — faixa: {lo}..{hi}"
        w.setToolTip(tip)
        self.widget = w


class SettingsForm(QWidget):
    def __init__(self, schema: list[dict[str, Any]], values: dict[str, Any],
                 on_change: Callable[[], None] = lambda: None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.fields: dict[str, _Field] = {}
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        form = QFormLayout()
        outer.addLayout(form)
        for entry in schema:
            if not isinstance(entry, dict) or "key" not in entry:
                continue
            field = _Field(entry, on_change)
            self.fields[entry["key"]] = field
            row = QWidget()
            col = QVBoxLayout(row)
            col.setContentsMargins(0, 0, 0, 0)
            col.setSpacing(0)
            col.addWidget(field.widget)
            hint = _hint(entry)
            note = QLabel(hint or entry["key"])
            note.setObjectName(f"hint_{entry['key']}" if hint else f"key_{entry['key']}")
            note.setWordWrap(True)
            note.setStyleSheet("color: gray; font-size: 10px;")
            col.addWidget(note)
            form.addRow(_label(entry), row)
            field.set(values.get(entry["key"], entry.get("default")))
        self.baseline = self.values()

    def values(self) -> dict[str, Any]:
        return {k: f.get() for k, f in self.fields.items()}

    def changed(self) -> dict[str, Any]:
        now = self.values()
        return {k: v for k, v in now.items() if v != self.baseline.get(k)}

    def mark_saved(self, keys: list[str] | None = None) -> None:
        now = self.values()
        for k in (keys if keys is not None else list(now)):
            self.baseline[k] = now[k]

    def reset_to_defaults(self) -> None:
        for k, f in self.fields.items():
            if "default" in f.entry:
                f.set(f.entry["default"])
