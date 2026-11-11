from __future__ import annotations

from PySide6.QtWidgets import QPushButton, QVBoxLayout, QWidget

from .page import AddSitePage


class AddSiteWindow(QWidget):
    def __init__(self, client, state, parent: QWidget | None = None, **page_kwargs) -> None:
        super().__init__(parent)
        self.setWindowTitle("Adicionar site")
        self.resize(620, 600)
        self.page = AddSitePage(client, state, **page_kwargs)
        lay = QVBoxLayout(self)
        lay.addWidget(self.page, 1)
        close = QPushButton("Fechar")
        close.clicked.connect(self.close)
        lay.addWidget(close)
