"""Localização de alvos numa página analisada (sem cliques, sem Hyprland).

Cada função recebe uma `Page` (texto + gráficos) e, quando precisa olhar
pixels, a `Image` correspondente. Coordenadas devolvidas estão em pixels da
imagem; a conversão para a tela fica em `geometry.Frame`.

Um módulo por capacidade: `choices` (alternativas), `dropdown`, `matching`
(associação) e `buttons` (Submit, botão final, feedback e tela final).
"""

from .base import Located, blocks, match_block, question_signature, same_question, text_lines
from .buttons import detect_feedback, end_screen, final_buttons, locate_button, locate_submit
from .choices import Option, click_point_for, map_answers, options, text_options
from .dropdown import dropdown_shows, locate_dropdown, locate_list_option, locate_statement
from .matching import MatchLayout, locate_source, locate_target, match_sources, target_linked

__all__ = [
    "Located", "blocks", "match_block", "question_signature", "same_question", "text_lines",
    "detect_feedback", "end_screen", "final_buttons", "locate_button", "locate_submit",
    "Option", "click_point_for", "map_answers", "options", "text_options",
    "dropdown_shows", "locate_dropdown", "locate_list_option", "locate_statement",
    "MatchLayout", "locate_source", "locate_target", "match_sources", "target_linked",
]
