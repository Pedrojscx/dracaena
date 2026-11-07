"""Funções de localização contra as telas sintéticas e seus gabaritos.

Cada teste analisa uma imagem gerada pelo make_fixtures (OCR real com
tesseract) e confere o ponto devolvido contra a posição desenhada.
"""

import unittest

from helpers import ensure_fixtures, fixture, inside, needs_tools, truth

from quizvision import image, locate, ocr, page, text

BLOCKLIST = ["all", "assessment", "exam", "finish", "end"]
CORRECT = ["Correct", "You answered correctly", "That's correct"]
INCORRECT = ["Incorrect", "Partly correct", "Not quite", "That is not right", "Try again"]


def analyze(name: str) -> page.Page:
    return page.analyze(fixture(name), truth(name)["scale"])


@needs_tools
class ChoiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ensure_fixtures()

    def check_options(self, name, kind):
        t = truth(name)
        pg = analyze(name)
        opts = locate.options(pg)
        expected = [v for k, v in sorted(t["items"].items()) if k.startswith("opt")]
        self.assertEqual(len(opts), len(expected), name)
        offset = 40 * t["scale"]
        for opt, exp in zip(opts, expected):
            self.assertGreater(text.similarity(opt.text, exp["text"]), 0.9, (name, opt.text))
            self.assertEqual(opt.checked, exp["checked"], (name, opt.text))
            point = locate.click_point_for(opt, offset)
            self.assertTrue(inside(point, exp["control"], pad=3 * t["scale"]), (name, opt.text, point))
        return opts

    def test_single(self):
        self.check_options("single", "radio")

    def test_single_selected(self):
        opts = self.check_options("single_selected", "radio")
        self.assertEqual([o.checked for o in opts], [False, False, True, False])

    def test_single_hidpi_scale_2(self):
        self.check_options("single_hidpi", "radio")

    def test_multi_without_and_with_marked(self):
        for name in ("multi", "multi_partial", "multi_wrong", "multi_done"):
            self.check_options(name, "checkbox")

    def test_map_answers(self):
        opts = locate.options(analyze("multi_partial"))
        res = locate.map_answers(["Motherboard", "CPU"], opts, 0.6)
        self.assertEqual(sorted(res["found"].values()), [0, 2])
        self.assertEqual(res["missing"], [])
        res = locate.map_answers(["Ethernet cabls"], locate.options(analyze("ambiguous")), 0.6)
        self.assertEqual(res["ambiguous"], ["Ethernet cabls"])

    def test_signature(self):
        pg = analyze("single")
        sig = locate.question_signature(pg, image.load(fixture("single")))
        self.assertEqual(sig["number"], 1)
        sel = analyze("single_correct")
        sig2 = locate.question_signature(sel, image.load(fixture("single_correct")))
        self.assertTrue(locate.same_question(sig, sig2))
        q7 = analyze("single_q7")
        self.assertFalse(locate.same_question(sig, locate.question_signature(q7, image.load(fixture("single_q7")))))


@needs_tools
class SubmitFeedbackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ensure_fixtures()

    def test_isolated_submit(self):
        res = locate.locate_submit(analyze("single"), 60, BLOCKLIST)
        self.assertEqual(res.status, "ok")
        self.assertTrue(inside(res.point, truth("single")["items"]["submit"]["box"]))

    def test_submit_all_is_final(self):
        self.assertEqual(locate.locate_submit(analyze("submit_all"), 60, BLOCKLIST).status, "final")
        self.assertEqual(len(locate.final_buttons(analyze("submit_all"), BLOCKLIST)), 1)

    def test_two_submits_refused(self):
        res = locate.locate_submit(analyze("two_submits"), 60, BLOCKLIST)
        self.assertEqual(res.status, "refused")
        self.assertIn("2 botões", res.reason)

    def test_low_confidence_refused(self):
        res = locate.locate_submit(analyze("single"), 99.9, BLOCKLIST)
        self.assertEqual(res.status, "refused")

    def test_final_screen(self):
        pg = analyze("final")
        self.assertEqual(locate.locate_submit(pg, 60, BLOCKLIST).status, "not_found")
        self.assertIsNotNone(locate.end_screen(pg, ["Assessment Complete", "Your score", "Results"]))
        self.assertIsNone(locate.end_screen(analyze("single"), ["Assessment Complete", "Your score", "Results"]))

    def test_feedback(self):
        before = analyze("single_selected")
        self.assertEqual(locate.detect_feedback(before, analyze("single_correct"), CORRECT, INCORRECT), "correct")
        self.assertEqual(locate.detect_feedback(analyze("single_sel1"), analyze("single_incorrect"),
                                                CORRECT, INCORRECT), "incorrect")
        self.assertIsNone(locate.detect_feedback(analyze("single"), before, CORRECT, INCORRECT))

    def test_reset_button(self):
        res = locate.locate_button(analyze("single_incorrect"), ["Reset", "Try again"])
        self.assertEqual(res.status, "ok")
        self.assertTrue(inside(res.point, truth("single_incorrect")["items"]["extra"]["box"]))


@needs_tools
class DropdownTests(unittest.TestCase):
    STATEMENTS = [
        "A UPS protects a computer against power outages.",
        "Thermal paste is applied between the CPU and the RAM.",
        "An ESD strap should be connected to the computer chassis.",
    ]

    @classmethod
    def setUpClass(cls):
        ensure_fixtures()

    def test_closed_dropdowns(self):
        pg, t = analyze("dropdown"), truth("dropdown")
        below = -1
        for i, statement in enumerate(self.STATEMENTS):
            st = locate.locate_statement(pg, statement, 0.6, below)
            self.assertEqual(st.status, "ok", statement)
            dd = locate.locate_dropdown(pg, st.box, [s for s in self.STATEMENTS if s != statement], 0.6)
            self.assertEqual(dd.status, "ok")
            self.assertTrue(inside(dd.point, t["items"][f"dd{i}"]["box"]), (i, dd.point))
            self.assertEqual(text.normalize(dd.value), "please select an option")
            below = dd.line.box.y2

    def test_open_list_option(self):
        before, after, t = analyze("dropdown"), analyze("dropdown_open0"), truth("dropdown_open0")
        st = locate.locate_statement(before, self.STATEMENTS[0], 0.6)
        dd = locate.locate_dropdown(before, st.box, self.STATEMENTS[1:], 0.6)
        for answer, key in (("True", "list_1"), ("False", "list_2")):
            res = locate.locate_list_option(before, after, answer, dd.line.box, 0.6)
            self.assertEqual(res.status, "ok", answer)
            self.assertTrue(inside(res.point, t["items"][key]["box"]), (answer, res.point))

    def test_value_shown(self):
        pg = analyze("dropdown_v2")
        st = locate.locate_statement(pg, self.STATEMENTS[1], 0.6)
        dd = locate.locate_dropdown(pg, st.box, [], 0.6)
        self.assertTrue(locate.dropdown_shows(pg, dd.line.box, "False"))
        self.assertFalse(locate.dropdown_shows(pg, dd.line.box, "True"))


@needs_tools
class MatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ensure_fixtures()

    def check(self, name, rights, expected_letters):
        pg, img, t = analyze(name), image.load(fixture(name)), truth(name)
        layout = locate.match_sources(pg, fixture(name), ocr.ocr_char)
        letters = sorted(s["letter"] for s in layout.sources)
        self.assertEqual(letters, expected_letters, name)
        for letter in expected_letters:
            src = locate.locate_source(layout, letter, "", 0.6)
            self.assertEqual(src.status, "ok")
            self.assertTrue(inside(src.point, t["items"][f"L{letter}"]["box"]), (name, letter))
        for i, right in enumerate(rights):
            tgt = locate.locate_target(pg, img, right, 0.6, layout.radius, [ln.box for ln in layout.header_lines])
            self.assertEqual(tgt.status, "ok", (name, right))
            item = t["items"][f"T{i}"]
            self.assertTrue(inside(tgt.point, item["box"]), (name, right, tgt.point))
            self.assertEqual(tgt.kind == "filled", bool(item["linked"]), (name, right, tgt.kind))
        return pg, img, layout

    RIGHT1 = ["Dissipates heat away from the processor", "Main printed circuit board of the computer",
              "Converts AC power into lower voltage DC power"]
    RIGHT2 = ["Scanner", "Printer", "Microphone", "Projector"]

    def test_letters_variant(self):
        self.check("match_letters", self.RIGHT1, ["A", "B", "C"])
        self.check("match_letters_2", self.RIGHT1, ["A", "B", "C"])

    def test_categories_variant_with_dark_borders(self):
        self.check("match_categories", self.RIGHT2, ["A", "B"])
        self.check("match_categories_3", self.RIGHT2, ["A", "B"])

    def test_source_by_text_when_letter_missing(self):
        layout = locate.match_sources(analyze("match_letters"), fixture("match_letters"), lambda p, b: ("", 0.0))
        src = locate.locate_source(layout, "B", "Power supply", 0.6)
        self.assertEqual(src.status, "ok")
        self.assertTrue(inside(src.point, truth("match_letters")["items"]["LB"]["box"]))

    def test_link_detection(self):
        before, after = image.load(fixture("match_letters")), image.load(fixture("match_letters_1"))
        box = ocr.Box(*truth("match_letters")["items"]["T0"]["box"])
        self.assertTrue(locate.target_linked(before, after, box))
        self.assertFalse(locate.target_linked(before, before, box))


if __name__ == "__main__":
    unittest.main()
