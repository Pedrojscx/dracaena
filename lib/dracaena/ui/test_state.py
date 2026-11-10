import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication

from dracaena.ui.state import AppState

APP = QCoreApplication.instance() or QCoreApplication([])


class AppStateTests(unittest.TestCase):
    def test_state_event_updates_run_and_emits(self):
        st, seen = AppState(), []
        st.changed.connect(seen.append)
        st.set_connected(True)
        st.apply_state_event({"event": "state", "state": "running", "site": "S", "question": 3, "max": 80, "error": ""})
        self.assertEqual((st.run.state, st.run.question, st.run.connected), ("running", 3, True))
        self.assertEqual(len(seen), 2)

    def test_unknown_state_ignored(self):
        st = AppState()
        st.apply_state_event({"state": "bogus"})
        self.assertEqual(st.run.state, "idle")


if __name__ == "__main__":
    unittest.main()
