"""quizvision: lógica de visão e decisão do quiz-helper (somente stdlib).

Não depende de Hyprland nem executa cliques; recebe imagens e devolve
coordenadas e diretivas. Os únicos programas externos usados são o
`tesseract` (OCR) e o `magick` (pré-processamento e anotação).
"""

__version__ = "1.0.0"
