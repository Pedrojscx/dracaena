"""Configuração padrão embutida (disponível em wheels e builds congelados).

Os prompts pertencem ao núcleo (dracaena.core.prompts); esta pasta não os duplica.
"""
from importlib.resources import files


def default_config():
    return files(__package__).joinpath("default.json").read_text(encoding="utf-8")
