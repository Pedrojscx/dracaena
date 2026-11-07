"""Recuperação do loop quando o iframe some ou a aba navega (sem navegador real)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from playwright.sync_api import Error as PlaywrightError

from quizhelper import browser as browsermod
from quizhelper import dom, loop


class FakePage:
    def __init__(self, title="x - Practice Final Exam Modules 1-9", frame_title="Quiz"):
        self._title = title
        self.url = browsermod.LAUNCH
        self.frames = [mock.Mock(url=browsermod.QUIZ_FRAME)]
        self.frames[0].evaluate.return_value = frame_title

    def title(self):
        return self._title

    def is_closed(self):
        return False


def make_loop(page):
    lp = loop.Loop({"RECOVER_TIMEOUT_MS": "3000"}, run_dir=Path(tempfile.mkdtemp()))
    lp.page = page
    lp.item = "Practice Final Exam Modules 1-9"
    lp.status = lambda *a, **k: None
    lp._key_now = lambda: None
    return lp


def tab(item):
    return SimpleNamespace(page=None, frame=object(), title=f"x - {item}", item=item)


class RecoveryTest(unittest.TestCase):
    def setUp(self):
        self.sleep = mock.patch.object(loop.time, "sleep", lambda s: None)
        self.sleep.start()

    def tearDown(self):
        self.sleep.stop()

    def test_mesma_atividade_retoma_sem_pausar(self):
        lp = make_loop(FakePage())
        calls = {"n": 0}

        def reval(page):
            calls["n"] += 1
            if calls["n"] < 3:
                raise PlaywrightError("Cannot find context with specified id")
            return tab(lp.item)
        with mock.patch.object(browsermod, "revalidate", reval), \
                mock.patch.object(dom, "locate", lambda f, i: SimpleNamespace(key="k1", host=object())):
            lp._handle_page_change("erro")
        self.assertFalse(lp.paused)

    def test_outra_atividade_pausa_com_mensagem(self):
        lp = make_loop(FakePage())
        with mock.patch.object(browsermod, "revalidate", lambda p: tab("Outra atividade")), \
                mock.patch.object(dom, "locate", lambda f, i: SimpleNamespace(key="k", host=object())):
            lp._handle_page_change("erro")
        self.assertTrue(lp.paused and lp.user_paused)
        self.assertEqual(lp.pause_reason,
                         "a aba mudou para x - Outra atividade; volte ao quiz e aperte SUPER+P")

    def assert_revalidates_and_recovers(self, page):
        result = browsermod.revalidate(page)
        self.assertIsInstance(result, browsermod.Tab)
        self.assertIs(result.page, page)
        self.assertIs(result.frame, page.frames[0])
        self.assertEqual(result.title, page.title())
        self.assertEqual(result.item, page.title().split(" - ", 1)[1])
        lp = make_loop(page)
        lp.item = result.item
        with mock.patch.object(dom, "locate", return_value=SimpleNamespace(key="k", host=object())) as locate:
            lp._handle_page_change("erro")
        self.assertGreaterEqual(locate.call_count, 4)
        self.assertFalse(lp.paused)
        page.frames[0].evaluate.assert_not_called()

    def test_titulo_de_prova_na_aba_permite_recuperacao(self):
        for title in ("Module Exam", "Checkpoint Exam", "Final Exam"):
            with self.subTest(title=title):
                self.assert_revalidates_and_recovers(FakePage(f"IT - 9.4. {title}"))

    def test_titulo_de_prova_no_iframe_nao_e_consultado(self):
        for title in ("Module Exam", "Checkpoint Exam", "Final Exam"):
            with self.subTest(title=title):
                self.assert_revalidates_and_recovers(FakePage(frame_title=title))

    def test_pagina_que_nao_estabiliza_pausa(self):
        lp = make_loop(FakePage())
        lp.cfg["RECOVER_TIMEOUT_MS"] = "50"

        def reval(page):
            raise PlaywrightError("Cannot find context")
        with mock.patch.object(browsermod, "revalidate", reval), \
                mock.patch.object(loop.time, "monotonic", side_effect=iter([0, 0.01, 0.02, 1, 2, 3, 4, 5, 6, 7, 8])):
            lp._handle_page_change("erro")
        self.assertIn("não estabilizou", lp.pause_reason)


if __name__ == "__main__":
    unittest.main()
