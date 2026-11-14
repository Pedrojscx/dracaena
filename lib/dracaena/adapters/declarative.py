"""Adapter v0 restrito aos seletores de um perfil TOML validado."""
from pathlib import Path

from ..core.domjs import js
from .base import NotFound, PageGone
from .general import GeneralAdapter
from .profile import Profile, parse


_LOCATE = js("return QH.all(document, e => e.matches(arg)).filter(e => QH.visible(e));")


class DeclarativeAdapter(GeneralAdapter):
    """Reutiliza o motor de leitura, sem recorrer à heurística sem perfil.

    Recebe Profile validado ou texto TOML; from_file lê um arquivo local.
    extra_block só acrescenta termos aos que a guarda mantém em código.
    """

    def __init__(self, profile: Profile | str, figure_dir=None, extra_block=()):
        if isinstance(profile, str):
            profile = parse(profile)
        if not isinstance(profile, Profile):
            raise TypeError("esperado Profile validado ou texto TOML")
        super().__init__(figure_dir=figure_dir, extra_block=extra_block, profile=profile)
        # Um perfil sem feedback não autoriza inferir o resultado por texto.
        feedback = self._data.setdefault("feedback", {})
        feedback.setdefault("correct", ":not(*)")
        feedback.setdefault("incorrect", ":not(*)")

    @classmethod
    def from_file(cls, path, **kwargs):
        return cls(parse(Path(path).read_text(encoding="utf-8")), **kwargs)

    def locate(self, frame):
        hosts = []
        for one in self._frames(frame):
            try:
                hosts.extend(self._elements(one, _LOCATE, self._data["question"]["container"]))
            except PageGone:
                if one is frame:
                    raise
        return hosts

    def _require_host(self, handle):
        valid = self._run(lambda: handle.evaluate(
            "(e, selector) => e.isConnected && e.matches(selector)",
            self._data["question"]["container"]))
        if not valid:
            raise NotFound("componente fora do perfil")

    def _raw(self, handle):
        self._require_host(handle)
        data = super()._raw(handle)
        data["feedback"] = self.verdict(handle).feedback
        return data

    def target(self, handle, kind, index):
        self._require_host(handle)
        if kind not in ("option", "dropdown"):
            raise NotFound("tipo de alvo fora do contrato v0")
        return super().target(handle, kind, index)

    def _button(self, handle, kind):
        self._require_host(handle)
        return super()._button(handle, kind)

    def verdict(self, handle):
        self._require_host(handle)
        return super().verdict(handle)
