"""Máquina de estados do loop dirigida diretamente (sem bash)."""

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from helpers import REPO, ensure_fixtures, fixture, needs_tools, truth

from quizvision import annotate, config
from quizvision.session import Session, load_state, save_state


def new_session(tmp: str, **override) -> Session:
    cfg = config.load(REPO / "config" / "quiz-helper.conf")
    cfg.update(override)
    return Session.new(cfg, str(Path(tmp) / "run"), replay=True)


WINDOW_AT = [1920, 50]   # janela do Vivaldi num segundo monitor


def captured(s: Session, directive: dict, name: str) -> dict:
    """Entrega à sessão a captura da janela inteira (fixture win_<name>)."""
    shutil.copyfile(fixture(f"win_{name}"), directive["out"])
    return s.step({"type": "captured", "image": directive["out"], "origin": WINDOW_AT, "scale": 1.0})


@needs_tools
class SessionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ensure_fixtures()

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_invalid_json_retries_once_then_pauses(self):
        s = new_session(self.tmp)
        d = s.step({"type": "start"})
        self.assertEqual(d["do"], "capture")
        d = captured(s, d, "single")
        self.assertEqual(d["do"], "ask_claude")
        d = s.step({"type": "claude", "text": "não sei", "elapsed": 1})
        self.assertEqual(d["do"], "ask_claude")
        d = s.step({"type": "claude", "text": "{}", "elapsed": 1})
        self.assertEqual(d["do"], "capture")
        self.assertTrue(d["manual"])
        self.assertTrue(d["status"].startswith("pausado: resposta inválida"))

    def test_click_coordinates_are_global(self):
        s = new_session(self.tmp)
        d = captured(s, s.step({"type": "start"}), "single")
        d = s.step({"type": "claude", "text": json.dumps({"type": "SINGLE", "answers": ["RAM"]}), "elapsed": 1})
        d = captured(s, d, "single")
        self.assertEqual(d["do"], "input")
        click = d["actions"][0]
        # rádio do "RAM" desenhado em (64+340, 186+210) na janela; janela em (1920, 50)
        ctrl = truth("win_single")["items"]["opt0"]["click"]
        self.assertLessEqual(abs(click["x"] - (WINDOW_AT[0] + ctrl[0])), 10)
        self.assertLessEqual(abs(click["y"] - (WINDOW_AT[1] + ctrl[1])), 4)
        self.assertEqual(d["answer"], "RAM")
        self.assertEqual(d["window"], {"at": WINDOW_AT, "size": [1720, 1000]})

    def test_stale_window_recaptures(self):
        s = new_session(self.tmp)
        d = captured(s, s.step({"type": "start"}), "single")
        d = s.step({"type": "claude", "text": json.dumps({"type": "SINGLE", "answers": ["RAM"]}), "elapsed": 1})
        d = captured(s, d, "single")
        self.assertEqual(d["do"], "input")
        d = s.step({"type": "stale"})
        self.assertEqual(d["do"], "capture")
        self.assertEqual(s.st["expect"], "answer")

    def test_panel_missing_twice_pauses(self):
        s = new_session(self.tmp)
        d = captured(s, s.step({"type": "start"}), "single")
        d = s.step({"type": "claude", "text": json.dumps({"type": "SINGLE", "answers": ["RAM"]}), "elapsed": 1})
        blank = Path(self.tmp) / "blank.png"
        import subprocess
        subprocess.run(["magick", "-size", "1720x1000", "xc:white", str(blank)], check=True)
        def blank_capture(directive):
            shutil.copyfile(blank, directive["out"])
            return s.step({"type": "captured", "image": directive["out"], "origin": WINDOW_AT, "scale": 1.0})
        d = blank_capture(d)
        self.assertEqual(d["do"], "capture", "primeira falha: tenta de novo")
        self.assertFalse(d["manual"])
        d = blank_capture(d)
        self.assertTrue(d["manual"])
        self.assertIn("role até o topo da questão", d["status"])

    def test_arrow_fallback_point_is_relative_to_panel(self):
        s = new_session(self.tmp, CLICK_SUBMIT=0)
        d = captured(s, s.step({"type": "start"}), "single__none")
        answer = {"type": "SINGLE", "answers": ["Power supply unit"]}
        d = s.step({"type": "claude", "text": json.dumps(answer), "elapsed": 1})
        d = captured(s, d, "single__none")          # marca "Power supply unit"
        d = s.step({"type": "done"})
        d = captured(s, d, "single_selected__none")  # conferência
        d = captured(s, d, "single_selected__none")  # avançar: sem seta
        self.assertEqual(d["do"], "ask_point")
        d = s.step({"type": "point", "x": 3200, "y": 600})
        self.assertEqual(d["do"], "input")
        self.assertEqual((d["actions"][0]["x"], d["actions"][0]["y"]), (3200, 600))
        panel = s.st["dets"][s.st["last_win"]]["panel"]
        self.assertEqual(s.st["manual_next"], [3200 - (WINDOW_AT[0] + panel[0] + panel[2]), 600 - (WINDOW_AT[1] + panel[1])])

    def test_incomplete_beyond_max_scrolls_pauses(self):
        s = new_session(self.tmp, MAX_SCROLLS=0)
        d = captured(s, s.step({"type": "start"}), "long_top")
        d = s.step({"type": "claude", "text": '{"type":"INCOMPLETE"}', "elapsed": 1})
        self.assertTrue(d["status"].startswith("pausado: questão incompleta"))

    def test_state_roundtrip(self):
        s = new_session(self.tmp)
        d = s.step({"type": "start"})
        path = Path(self.tmp) / "state.json"
        save_state(s, path)
        s2 = load_state(path)
        self.assertEqual(s2.st["expect"], "identify")
        d2 = captured(s2, d, "final")
        self.assertEqual(d2["do"], "end")
        self.assertEqual(d2["reason"], "end_screen")

    def test_annotation_args(self):
        args = annotate.draw_args([{"kind": "click", "x": 10, "y": 20, "label": "a"},
                                   {"kind": "drag", "x": 10, "y": 20, "x2": 90, "y2": 60, "label": "b"}])
        joined = " ".join(args)
        self.assertIn("line 0,20 20,20", joined)
        self.assertIn("polygon 90,60", joined)


if __name__ == "__main__":
    unittest.main()
