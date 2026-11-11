import unittest

from dracaena.ui.add_site import AddSitePage, AddSiteWindow
from dracaena.ui.add_site import api
from dracaena.ui.settings.testsupport import ContractFake, Resp, app, screenshot_dir, wait_for
from dracaena.ui.state import AppState

app()


def make(**kw):
    yes = kw.pop("yes", True)
    client = ContractFake(**kw)
    state = AppState()
    state.set_connected(True)
    state.set_sites(client.sites)
    answers = []
    page = AddSitePage(client, state, confirm=lambda parent, text: answers.append(text) or yes)
    page.show()
    return client, state, page, answers


class ApiTests(unittest.TestCase):
    def test_parse_probe_rejects_wrong_shapes(self):
        self.assertIsNone(api.parse_probe({"matches": 1, "questions": 1, "draft_toml": ""}))   # forma antiga
        self.assertIsNone(api.parse_probe({"matches": {"a": "x"}, "questions": 1}))
        self.assertIsNone(api.parse_probe([]))
        r = api.parse_probe({"matches": {"a": 2}, "questions": 3, "draft_toml": "x"})
        self.assertTrue(r.recognized)

    def test_progress_event_flat_and_wrapped(self):
        from dracaena.ui.settings.reply import event_parts  # noqa: F401
        class Ev:  # EventMsg do B1
            event, data = "probe", {"phase": "qualquer", "done": 2, "total": 4}
        self.assertEqual(api.probe_progress({"event": "probe", "phase": "scan", "done": 1, "total": 4}), (1, 4, "scan"))
        self.assertEqual(api.probe_progress(Ev()), (2, 4, "qualquer"))
        self.assertIsNone(api.probe_progress({"event": "state"}))


class AddSiteTests(unittest.TestCase):
    def test_success_flow_probe_review_save(self):
        client, state, page, _ = make()
        page.url.setText("https://exemplo.test/pratica")
        page.verify()
        self.assertTrue(wait_for(lambda: page.result is not None))
        self.assertEqual(client.calls[0], ("probe.start", {"url": "https://exemplo.test/pratica"}))
        self.assertIn("Página reconhecida.", page.status.text())
        self.assertEqual(page.table.rowCount(), 3)
        self.assertEqual(page.draft.toPlainText(), ContractFake.DRAFT)
        self.assertFalse(page.btn_save.isEnabled())          # falta o nome
        page.name.setText("pratica-1")
        self.assertTrue(page.btn_save.isEnabled())
        page.draft.setPlainText(ContractFake.DRAFT + "# revisado\n")   # usuário edita
        saved = []
        page.saved.connect(saved.append)
        page.save()
        self.assertTrue(wait_for(lambda: page.is_saved))
        self.assertEqual(client.calls[-2][0], "sites.save")
        self.assertEqual(client.calls[-2][1], {"name": "pratica-1", "toml": ContractFake.DRAFT + "# revisado\n"})
        self.assertEqual(saved, ["pratica-1"])
        self.assertTrue(wait_for(lambda: any(s["name"] == "pratica-1" for s in state.sites)))

    def test_empty_url_sends_no_url_arg(self):
        client, state, page, _ = make()
        page.verify()
        wait_for(lambda: page.result is not None)
        self.assertEqual(client.calls[0], ("probe.start", {}))

    def test_bad_url_is_rejected_locally(self):
        client, state, page, _ = make()
        page.url.setText("ftp://x")
        page.verify()
        self.assertEqual(client.calls, [])
        self.assertIn("http://", page.status.text())

    def test_not_recognized_shows_fixed_text_and_blocks_save(self):
        client, state, page, _ = make(probe={"matches": {"questao": 0}, "questions": 0, "draft_toml": ""})
        page.verify()
        wait_for(lambda: page.result is not None)
        self.assertIn("Não consegui reconhecer as questões", page.status.text())
        self.assertFalse(page.review.isVisible())
        self.assertFalse(page.btn_save.isEnabled())

    def test_probe_error_string_shown_whole(self):
        client, state, page, _ = make(probe=Resp(1, False, error="sem navegador dedicado aberto", code="no_browser"))
        page.verify()
        self.assertTrue(wait_for(lambda: "sem navegador dedicado aberto" in page.status.text()))
        self.assertTrue(page.btn_verify.isEnabled())

    def test_progress_event_and_cancel_discards_late_result(self):
        client, state, page, _ = make(defer_probe=True)
        page.verify()
        self.assertEqual(page.status.text(), "Verificando…")
        self.assertTrue(page.btn_verify.isEnabled() is False and page.btn_cancel.isVisible())
        client.event_received.emit({"event": "probe", "phase": "scan", "done": 1, "total": 4})
        self.assertEqual((page.progress.value(), page.progress.maximum()), (1, 4))
        self.assertEqual(page.status.text(), "Verificando… (lendo a página)")
        page.cancel()
        self.assertEqual(client.calls[-1][0], "probe.cancel")
        client.finish_probe()                       # resultado chega depois do cancelamento
        wait_for(lambda: False, 0.1)
        self.assertIsNone(page.result)
        self.assertEqual(page.status.text(), "Verificação cancelada.")

    def test_cancelled_error_code_is_not_shown_as_failure(self):
        client, state, page, _ = make(probe=Resp(1, False, error="cancelado", code="cancelled"))
        page.verify()
        self.assertTrue(wait_for(lambda: page.status.text() == "Verificação cancelada."))

    def test_toml_error_with_line_is_shown_and_not_saved(self):
        client, state, page, _ = make()
        page.verify()
        wait_for(lambda: page.result is not None)
        page.name.setText("ok")
        page.draft.setPlainText('a = 1\ndesconhecido = 2\n')
        page.save()
        self.assertTrue(wait_for(lambda: "linha 2" in page.save_status.text()))
        self.assertFalse(page.is_saved)

    def test_existing_name_asks_confirmation_before_overwrite(self):
        client, state, page, asked = make(saved={"pratica-1": "x"}, yes=False)
        page.verify()
        wait_for(lambda: page.result is not None)
        page.name.setText("pratica-1")
        page.save()
        self.assertEqual(len(asked), 1)
        self.assertFalse([c for c in client.calls if c[0] == "sites.save"])   # recusou: nada enviado
        client2, state2, page2, asked2 = make(saved={"pratica-1": "x"}, yes=True)
        page2.verify()
        wait_for(lambda: page2.result is not None)
        page2.name.setText("pratica-1")
        page2.save()
        wait_for(lambda: page2.is_saved)
        self.assertEqual([c[1] for c in client2.calls if c[0] == "sites.save"][0].get("overwrite"), True)

    def test_overwrite_asked_after_daemon_says_it_exists(self):
        """sites.list traz o nome de exibição, não o do arquivo: o daemon é quem avisa (bad_request)."""
        client, state, page, asked = make(saved={"pratica-1": "x"}, yes=True)
        state.set_sites([])                                  # a UI não sabia que o arquivo existia
        page.verify()
        wait_for(lambda: page.result is not None)
        page.name.setText("pratica-1")
        page.save()
        self.assertTrue(wait_for(lambda: page.is_saved))
        sends = [c[1] for c in client.calls if c[0] == "sites.save"]
        self.assertEqual(len(sends), 2)
        self.assertNotIn("overwrite", sends[0])
        self.assertEqual(sends[1].get("overwrite"), True)
        self.assertEqual(len(asked), 1)

    def test_overwrite_refused_after_daemon_says_it_exists(self):
        client, state, page, asked = make(saved={"pratica-1": "x"}, yes=False)
        state.set_sites([])
        page.verify()
        wait_for(lambda: page.result is not None)
        page.name.setText("pratica-1")
        page.save()
        wait_for(lambda: len(asked) == 1)
        wait_for(lambda: False, 0.1)
        self.assertFalse(page.is_saved)
        self.assertEqual(len([c for c in client.calls if c[0] == "sites.save"]), 1)
        self.assertEqual(page.save_status.text(), "Nada foi salvo.")

    def test_name_validator_blocks_invalid_chars_and_limits(self):
        client, state, page, _ = make()
        page.verify()
        wait_for(lambda: page.result is not None)
        from PySide6.QtGui import QValidator
        self.assertEqual(page.name.validator().validate("Nome Inválido", 0)[0], QValidator.Invalid)
        self.assertEqual(page.name.validator().validate("nome-ok_1", 0)[0], QValidator.Acceptable)
        page.name.setText("Nome Inválido")           # mesmo setado por código, o botão fica desligado
        self.assertFalse(page.btn_save.isEnabled())
        page.name.setText("ok")
        page.draft.setPlainText("x" * (64 * 1024 + 1))
        self.assertFalse(page.btn_save.isEnabled())

    def test_offline_blocks_verify(self):
        client, state, page, _ = make()
        state.set_connected(False)
        page.verify()
        self.assertEqual(client.calls, [])

    def test_screenshot(self):
        client, state, page, _ = make()
        win = AddSiteWindow(client, state)
        win.page.url.setText("https://exemplo.test/pratica")
        win.show()
        win.page.verify()
        wait_for(lambda: win.page.result is not None)
        win.page.name.setText("pratica-1")
        win.grab().save(str(screenshot_dir() / "add_site.png"))


if __name__ == "__main__":
    unittest.main()
