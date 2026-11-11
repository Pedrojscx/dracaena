"""Costura entre bandeja (B1) e telas (B2): callbacks, sem importar um do outro.

A bandeja recebe um `UiHost` e só chama estes métodos; o B2 implementa as telas e
o `app.py` liga as duas pontas. Assim nenhum dos dois toca o código do outro.
"""
from __future__ import annotations

from typing import Protocol


class UiHost(Protocol):
    """Ações que a bandeja pode pedir à UI. Todas rodam na thread da GUI."""

    def open_settings(self) -> None:
        """Abre a janela de configuração (B2)."""

    def open_add_site(self) -> None:
        """Abre direto o fluxo Adicionar site (B2)."""

    def open_shortcut_wizard(self) -> None:
        """Abre o assistente de atalhos (B2)."""

    def quit_app(self) -> None:
        """Encerra só a UI. O daemon continua (decisão a confirmar no CONTRATO)."""
