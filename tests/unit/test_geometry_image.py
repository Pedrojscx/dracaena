"""Geometria (janela, monitor, escala) e decodificação de imagens."""

import subprocess
import tempfile
import unittest
from pathlib import Path

from helpers import fixture, ensure_fixtures, needs_tools

from quizvision import geometry, image, ocr, page, widgets
from quizvision.ocr import Box

MONITORS = [
    {"id": 0, "name": "eDP-1", "x": 2560, "y": 0, "width": 1920, "height": 1080, "scale": 1.25},
    {"id": 1, "name": "HDMI-A-1", "x": 0, "y": 0, "width": 2560, "height": 1440, "scale": 1.0},
]


def active(monitor=0, at=(2600, 40), size=(1200, 800), cls="vivaldi-stable"):
    return {"class": cls, "title": "NetAcad", "monitor": monitor, "at": list(at), "size": list(size)}


class GeometryTests(unittest.TestCase):
    def test_window_info_crosses_monitor(self):
        win = geometry.window_info(active(), MONITORS)
        self.assertEqual((win.monitor, win.scale, win.x, win.w), ("eDP-1", 1.25, 2600, 1200))

    def test_window_problems(self):
        win = geometry.window_info(active(), MONITORS)
        self.assertEqual(geometry.window_problems(win, "^vivaldi"), [])
        wrong = geometry.window_info(active(cls="kitty"), MONITORS)
        self.assertEqual(geometry.window_problems(wrong, "^vivaldi"), ["Deixe o Vivaldi com o quiz em foco"])
        off = geometry.window_info(active(), [dict(MONITORS[0], dpmsStatus=False), MONITORS[1]])
        self.assertTrue(any("apagada" in p for p in geometry.window_problems(off, "^vivaldi")))
        self.assertTrue(any("inválida" in p for p in geometry.window_problems(win, "([")))

    def test_capture_geometry_and_frames(self):
        # Janela em monitor de escala 1.25 à direita de outro: grim -g usa
        # coordenadas lógicas globais; a captura sai em pixels * 1.25.
        win = geometry.window_info(active(at=(2600, 40), size=(1200, 800)), MONITORS)
        self.assertEqual(win.geometry, "2600,40 1200x800")
        frame = geometry.Frame(win.x, win.y, win.scale)
        self.assertEqual(frame.to_global(125, 250), (2700, 240))
        self.assertEqual(frame.to_image(2700, 240), (125.0, 250.0))
        self.assertEqual(frame.px(40), 50.0)
        panel = frame.sub(250, 125)          # recorte do painel a partir de (250,125) px
        self.assertEqual((panel.ox, panel.oy), (2800.0, 140.0))
        self.assertEqual(panel.to_global(0, 0), (2800, 140))
        moved = geometry.Frame(10, 900, 1.25).sub(250, 125)
        self.assertEqual(moved.to_global(0, 0), (210, 1000), "outra posição da janela, mesma conta")

    def test_parse_point(self):
        self.assertEqual(geometry.parse_point("12,-3 1x1"), (12, -3))
        with self.assertRaises(geometry.GeometryError):
            geometry.parse_point("a,b")


@needs_tools
class ImageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ensure_fixtures()

    def test_png_matches_magick(self):
        img = image.load(fixture("single"))
        out = subprocess.run(["magick", fixture("single"), "-format", "%[pixel:p{64,186}]", "info:"],
                             capture_output=True, text=True, check=True).stdout
        self.assertEqual((img.width, img.height), (900, 720))
        r, g, b = img.pixel(64, 186)
        self.assertIn("srgb", out)
        self.assertEqual(img.pixel(5, 700), (255, 255, 255))
        self.assertTrue(r == g == b)

    def test_other_png_types_and_ppm(self):
        with tempfile.TemporaryDirectory() as tmp:
            for kind, extra in (("gray", ["-colorspace", "Gray", "-define", "png:color-type=0"]),
                                ("palette", ["-colors", "16", "-define", "png:color-type=3"]),
                                ("rgba", ["-alpha", "on", "-define", "png:color-type=6"])):
                out = Path(tmp) / f"{kind}.png"
                subprocess.run(["magick", fixture("multi_partial")] + extra + [str(out)], check=True)
                img = image.load(out)
                self.assertEqual((img.width, img.height), (900, 720), kind)
                self.assertGreater(widgets.ink_ratio(img, Box(54, 176, 21, 21)), 0.5, kind)
            ppm = Path(tmp) / "x.ppm"
            subprocess.run(["magick", fixture("single"), str(ppm)], check=True)
            self.assertEqual(image.load(ppm).pixel(10, 10), image.load(fixture("single")).pixel(10, 10))

    def test_dhash_distinguishes_questions(self):
        a = image.load(fixture("single")).dhash()
        b = image.load(fixture("single_selected")).dhash()
        c = image.load(fixture("dropdown")).dhash()
        self.assertLessEqual(image.hamming_hex(a, b), 6)
        self.assertGreater(image.hamming_hex(a, c), 20)

    def test_corrupt_file(self):
        with tempfile.NamedTemporaryFile(suffix=".png") as f:
            f.write(b"\x89PNG\r\n\x1a\nlixo")
            f.flush()
            with self.assertRaises(image.ImageError):
                image.load(f.name)


class OcrParsingTests(unittest.TestCase):
    TSV = ("level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
           "5\t1\t1\t1\t1\t1\t100\t40\t60\t24\t95.0\tPower\n"
           "5\t1\t1\t1\t1\t2\t170\t40\t80\t24\t93.0\tsupply\n"
           "5\t1\t1\t1\t1\t3\t900\t40\t80\t24\t90.0\tScanner\n"
           "5\t1\t1\t1\t1\t4\t990\t40\t2\t24\t-1\t \n")

    def test_parse_scales_back(self):
        words = ocr.parse_tsv(self.TSV, scale=2.0)
        self.assertEqual([w.text for w in words], ["Power", "supply", "Scanner"])
        self.assertEqual((words[0].box.x, words[0].box.y, words[0].box.h), (50, 20, 12))

    def test_group_lines_splits_columns(self):
        lines = ocr.group_lines(ocr.parse_tsv(self.TSV, scale=2.0))
        self.assertEqual([ln.text for ln in lines], ["Power supply", "Scanner"])

    def test_junk_words(self):
        for junk, conf in (("¢", 90), ("j;-", 80), ("0-", 70), ("r", 60), ("ok", 10)):
            self.assertTrue(page.is_junk(junk, conf), junk)
        for real, conf in (("A", 90), ("RAM", 92), ("(Choose", 91), ("two.)", 90), ("I'm", 88), ("is", 90)):
            self.assertFalse(page.is_junk(real, conf), real)


class ComponentParsingTests(unittest.TestCase):
    def test_parse_components_keeps_foreground(self):
        out = ("Objects (id: bounding-box centroid area mean-color):\n"
               "  0: 900x720+0+0 450,360 600000 gray(0)\n"
               "  117: 21x21+54+176 64.0,186.0 112 gray(255)\n"
               "  192: 111x41+32+460 87.7,480.0 4277 gray(255)\n")
        comps = page.parse_components(out)
        self.assertEqual([(c.box.w, c.area) for c in comps], [(21, 112), (111, 4277)])


if __name__ == "__main__":
    unittest.main()
