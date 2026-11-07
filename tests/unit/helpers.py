"""Utilidades comuns dos testes: caminhos, fixtures e gabaritos."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "lib"))

FIXTURES = Path(os.environ.get("FIXTURES", REPO / "tests" / "fixtures" / "out"))
os.environ.setdefault("QV_CACHE_DIR", str(FIXTURES / ".cache"))

HAVE_TOOLS = bool(shutil.which("magick") and shutil.which("tesseract"))
needs_tools = unittest.skipUnless(HAVE_TOOLS, "magick e tesseract são necessários")


def ensure_fixtures() -> None:
    gen = REPO / "tests" / "fixtures" / "make_fixtures.py"
    marker = FIXTURES / "single.png"
    if not marker.exists() or gen.stat().st_mtime > marker.stat().st_mtime:
        subprocess.run([sys.executable, str(gen), str(FIXTURES)], check=True, capture_output=True)


def fixture(name: str) -> str:
    return str(FIXTURES / f"{name}.png")


def truth(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.truth.json").read_text(encoding="utf-8"))


def inside(point, box, pad: float = 0) -> bool:
    x, y = point
    bx, by, bw, bh = box
    return bx - pad <= x <= bx + bw + pad and by - pad <= y <= by + bh + pad
