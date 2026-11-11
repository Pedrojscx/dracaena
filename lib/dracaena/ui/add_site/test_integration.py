"""Adicionar site contra o daemon simulado real (SKIP se ele não subir)."""
import unittest

from dracaena.ui.add_site import AddSitePage
from dracaena.ui.settings.testsupport import SimulatedDaemon, app, wait_for
from dracaena.ui.state import AppState

app()


class AddSiteAgainstSimulatedDaemon(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.daemon = SimulatedDaemon()       # SkipTest se não subir
        cls.tr = cls.daemon.transport()

    @classmethod
    def tearDownClass(cls):
        cls.tr.close()
        cls.daemon.stop()

    def setUp(self):
        self.tr.extra_args.clear()
        self.state = AppState()
        self.state.set_connected(True)
        self.asked = []
        self.page = AddSitePage(self.tr, self.state, confirm=lambda p, t: self.asked.append(t) or True)
        self.page.show()

    def test_probe_progress_result_review_and_save(self):
        phases = []
        self.tr.event_received.connect(lambda e: phases.append(e.get("phase")) if e.get("event") == "probe" else None)
        self.page.url.setText("https://exemplo.test/pratica")
        self.page.verify()
        self.assertTrue(wait_for(lambda: self.page.result is not None, 5))
        self.assertEqual(phases, ["connect", "scan", "match", "draft", "done"])
        r = self.page.result
        self.assertTrue(r.recognized and r.matches and r.draft_toml.strip())
        self.assertEqual(self.page.table.rowCount(), len(r.matches))
        self.assertEqual(self.page.draft.toPlainText(), r.draft_toml)
        self.page.name.setText("pratica-1")
        self.page.save()
        self.assertTrue(wait_for(lambda: self.page.is_saved, 3))
        self.assertIn("pratica-1.toml", self.page.save_status.text())   # {path} do daemon

    def test_empty_url_is_accepted_by_daemon(self):
        self.page.verify()
        self.assertTrue(wait_for(lambda: self.page.result is not None, 5))

    def test_invalid_url_never_reaches_the_daemon(self):
        self.page.url.setText("javascript:alert(1)")
        self.page.verify()
        self.assertIsNone(self.page.result)
        self.assertIn("http://", self.page.status.text())

    def test_cancel_discards_result_and_daemon_confirms(self):
        got = []
        self.page.url.setText("https://exemplo.test/pratica")
        self.page.verify()
        self.assertTrue(wait_for(lambda: self.page.progress.maximum() == 4, 3))   # chegou progresso
        self.page.cancel()
        self.tr.request("probe.cancel", {}, got.append)
        wait_for(lambda: False, 1.5)
        self.assertIsNone(self.page.result)
        self.assertEqual(self.page.status.text(), "Verificação cancelada.")
        self.assertFalse(self.page.review.isVisible())

    def test_probe_errors_show_the_daemon_message_whole(self):
        for code, fragment in (("no_browser", "Nenhum navegador"), ("no_site", "Nenhum site compatível"),
                               ("internal", "Falha interna")):
            self.tr.extra_args["probe.start"] = {"simulate_error": code}
            self.page.url.setText("https://exemplo.test/pratica")
            self.page.verify()
            self.assertTrue(wait_for(lambda: fragment in self.page.status.text(), 5), code)
            self.assertTrue(wait_for(lambda: self.page.btn_verify.isEnabled(), 2))
            self.assertIsNone(self.page.result)

    def test_server_side_cancel_is_not_an_error(self):
        self.tr.extra_args["probe.start"] = {"simulate_error": "cancelled"}
        self.page.url.setText("https://exemplo.test/pratica")
        self.page.verify()
        self.assertTrue(wait_for(lambda: self.page.status.text() == "Verificação cancelada.", 5))

    def test_invalid_toml_error_with_position_is_shown(self):
        self.page.url.setText("https://exemplo.test/pratica")
        self.page.verify()
        wait_for(lambda: self.page.result is not None, 5)
        self.page.name.setText("pratica-2")
        self.page.draft.setPlainText("[site\nname = 1\n")
        self.page.save()
        self.assertTrue(wait_for(lambda: "TOML inválido" in self.page.save_status.text(), 3))
        self.assertFalse(self.page.is_saved)
        self.assertEqual(self.asked, [])            # erro de TOML não vira pedido de sobrescrever


if __name__ == "__main__":
    unittest.main()
