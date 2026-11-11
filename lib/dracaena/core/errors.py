"""Exceções tipadas do núcleo: o laço decide pelo tipo, nunca pelo texto da mensagem."""

from __future__ import annotations


class DracaenaError(Exception):
    """Base das falhas esperadas do projeto."""


class AdapterError(DracaenaError):
    """O adaptador não conseguiu ler ou localizar algo na página."""


class PageGone(AdapterError):
    """A aba ou o quadro sumiu, fechou ou está navegando."""


class NotFound(AdapterError):
    """O elemento pedido não existe (mais) na página."""


class Ambiguous(AdapterError):
    """Mais de um elemento serve e o adaptador não consegue escolher com segurança."""


class NoBrowser(DracaenaError):
    """Não há navegador ou aba utilizável para o conector."""


class Pause(DracaenaError):
    """O laço deve pausar com um motivo legível (o usuário retoma ou a questão muda)."""


class ServiceError(DracaenaError):
    """Erro de comando do Service; `code` segue o IPC v0."""

    CODES = ("bad_request", "unknown_cmd", "bad_state", "no_browser", "no_site", "refused", "internal")

    def __init__(self, code: str, msg: str):
        super().__init__(msg)
        self.code, self.msg = code, msg
