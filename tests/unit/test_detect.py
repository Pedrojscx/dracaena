"""Detecção automática da página nas janelas sintéticas do Vivaldi + NetAcad."""

import unittest

from helpers import ensure_fixtures, fixture, inside, needs_tools, truth

from quizvision import detect
from quizvision.image import load
from quizvision.locate.nextarrow import chevron_direction
from quizvision.ocr import Box


def run(name: str):
    t = truth(name)
    det = detect.detect(fixture(name), t["scale"])
    arrow, why = detect.find_arrow(det) if det.panel else (None, "sem painel")
    return t, det, arrow, why


@needs_tools
class DetectTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ensure_fixtures()

    def check_panel(self, name):
        t, det, arrow, why = run(name)
        items = t["items"]
        s = t["scale"]
        self.assertIsNotNone(det.panel, (name, det.reason))
        p = det.panel
        pbox = [p.x, p.y, p.w, p.h]
        # Conteúdo do quiz dentro do painel: título, alternativas/itens, Submit.
        for key, item in items.items():
            if key in ("panel", "content", "next", "prev_green", "question", "title"):
                continue
            for field in ("control", "box"):
                if field in item and key not in ("list",) and not key.startswith("list_"):
                    b = item[field]
                    self.assertTrue(inside((b[0], b[1]), pbox, pad=2) and inside((b[0] + b[2], b[1] + b[3]), pbox, pad=2),
                                    (name, key, b, pbox))
        # Nada da lista de módulos do NetAcad nem da interface do Vivaldi.
        module_right = items["content"]["module_right"]
        self.assertGreaterEqual(p.x, module_right - 2 * s, (name, pbox))
        self.assertGreaterEqual(det.content.y, round(78 * s) - 2, "barra de endereço fora da área de conteúdo")
        return t, det, arrow, why

    def check_arrow(self, t, arrow, why, expected_method):
        nxt = t["items"].get("next")
        if expected_method is None:
            self.assertIsNone(arrow, why)
            self.assertIsNone(nxt)
            return
        self.assertIsNotNone(arrow, why)
        self.assertEqual(arrow.method, expected_method)
        self.assertTrue(inside(arrow.point, nxt["box"], pad=4), (arrow.point, nxt["box"]))

    def test_nav_bar_preferred_when_both_exist(self):
        t, det, arrow, why = self.check_panel("win_single")
        self.check_arrow(t, arrow, why, "nav")

    def test_nav_only(self):
        t, det, arrow, why = self.check_panel("win_single__nav")
        self.check_arrow(t, arrow, why, "nav")

    def test_green_button_when_no_nav_chevron(self):
        t, det, arrow, why = self.check_panel("win_single__green")
        self.check_arrow(t, arrow, why, "green")

    def test_no_arrow(self):
        t, det, arrow, why = self.check_panel("win_single__none")
        self.check_arrow(t, arrow, why, None)
        self.assertIn("0 candidato", why)

    def test_vivaldi_side_panel_open(self):
        t, det, arrow, why = self.check_panel("win_single__sidebar")
        self.assertGreaterEqual(det.content.x, 318, "painel lateral do Vivaldi fora do conteúdo")
        module_right = t["items"]["content"]["module_right"]
        self.assertIsNotNone(det.module_right, "lista de módulos reconhecida pela divisa")
        self.assertLessEqual(abs(det.module_right - module_right), 3)
        self.check_arrow(t, arrow, why, "nav")
        t, det, arrow, why = self.check_panel("win_dropdown__green_sidebar")
        self.check_arrow(t, arrow, why, "green")

    def test_scale_2(self):
        t, det, arrow, why = self.check_panel("win_single_hidpi")
        self.assertEqual(det.scale, 2.0)
        self.check_arrow(t, arrow, why, "nav")

    def test_other_question_types(self):
        for name in ("win_multi_partial", "win_dropdown", "win_match_letters", "win_match_categories__sidebar",
                     "win_long_bottom", "win_two_submits"):
            t, det, arrow, why = self.check_panel(name)
            self.check_arrow(t, arrow, why, t["items"].get("next", {}).get("kind"))

    def test_active_bubble_at_the_end_of_nav_bar(self):
        # Q10 ativa (preenchida) e Q9 ativa: a última bolha não é moldura.
        for name in ("win_submit_all", "win_multi9_done"):
            t, det, arrow, why = self.check_panel(name)
            self.check_arrow(t, arrow, why, "nav")

    def test_final_screen_has_no_panel(self):
        t, det, arrow, why = run("win_final")
        self.assertIsNone(det.panel)
        lines = [ln.text for ln in detect.content_lines_outside_modules(det)]
        self.assertIn("Assessment Complete", lines)
        self.assertFalse(any("1/1" in ln or "75%" in ln for ln in lines), "lista de módulos ignorada")

    def test_panel_crop_reuses_ocr(self):
        t, det, arrow, why = run("win_single")
        from quizvision.page import analyze
        page = analyze(det.panel_path, det.scale)
        self.assertIn("Power supply unit", [ln.text for ln in page.lines])
        img = load(det.panel_path)
        self.assertEqual((img.width, img.height), (det.panel.w, det.panel.h))

    def test_reuse_keeps_same_crop(self):
        t, det, arrow, why = run("win_single")
        again = detect.detect(fixture("win_single_selected"), 1.0, reuse=det.panel)
        self.assertEqual(again.panel, det.panel)
        self.assertEqual(again.content_path, "")

    def test_chrome_margins_override(self):
        det = detect.detect(fixture("win_single"), 1.0, {"CHROME_TOP_PX": "100", "CHROME_LEFT_PX": "40"})
        self.assertEqual((det.content.x, det.content.y), (40, 100))
        self.assertIsNotNone(det.panel)


@needs_tools
class ChevronTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ensure_fixtures()

    def test_direction_of_green_buttons(self):
        t = truth("win_single__green")
        img = load(fixture("win_single__green"))
        nxt, prev = t["items"]["next"]["box"], t["items"]["prev_green"]["box"]

        def inner(b):
            return Box(b[0] + 10, b[1] + 10, b[2] - 20, b[3] - 20)
        self.assertEqual(chevron_direction(img, inner(nxt)), "right")
        self.assertEqual(chevron_direction(img, inner(prev)), "left")


if __name__ == "__main__":
    unittest.main()
