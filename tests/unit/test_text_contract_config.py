"""Texto, contrato da resposta do Claude e configuração (sem binários)."""

import unittest

from helpers import REPO  # noqa: F401  (ajusta sys.path)

from quizvision import config, contract, text


class TextTests(unittest.TestCase):
    def test_normalize(self):
        self.assertEqual(text.normalize("  Power  Supply—Unit! "), "power supply unit")

    def test_similarity_exact_and_partial(self):
        self.assertEqual(text.similarity("RAM", "ram"), 1.0)
        self.assertGreater(text.similarity("Power supply unit", "Power suppIy unit"), 0.85)
        self.assertLess(text.similarity("RAM", "Network interface card"), 0.3)

    def test_best_match_ok(self):
        res = text.best_match("Power supply unit", ["RAM", "Hard disk drive", "Power supply unit"], 0.6)
        self.assertEqual((res.status, res.index), ("ok", 2))

    def test_best_match_ambiguous(self):
        res = text.best_match("Ethernet cabls", ["Ethernet cable", "Ethernet cables", "Wireless"], 0.6)
        self.assertEqual(res.status, "ambiguous")

    def test_best_match_exact_wins_over_near_duplicate(self):
        res = text.best_match("Ethernet cable", ["Ethernet cable", "Ethernet cables"], 0.6)
        self.assertEqual((res.status, res.index), ("ok", 0))

    def test_best_match_not_found(self):
        self.assertEqual(text.best_match("Keyboard", ["RAM", "CPU"], 0.6).status, "not_found")

    def test_phrases_respect_word_boundaries(self):
        self.assertFalse(text.contains_phrase("Incorrect", "Correct"))
        self.assertTrue(text.contains_phrase("That's correct!", "correct"))
        self.assertEqual(text.count_phrase("Correct. correct, incorrect", "correct"), 2)


class ContractTests(unittest.TestCase):
    def test_single(self):
        self.assertEqual(contract.parse('{"type":"SINGLE","answers":["RAM"]}'),
                         {"type": "SINGLE", "answers": ["RAM"]})

    def test_fenced_json_is_accepted(self):
        self.assertEqual(contract.parse('```json\n{"type":"INCOMPLETE"}\n```')["type"], "INCOMPLETE")

    def test_text_outside_json_is_rejected(self):
        with self.assertRaises(contract.ContractError):
            contract.parse('A resposta é {"type":"SINGLE","answers":["RAM"]}')

    def test_multi_expected_must_match(self):
        with self.assertRaises(contract.ContractError):
            contract.parse('{"type":"MULTI","expected":3,"answers":["A","B"]}')
        ok = contract.parse('{"type":"MULTI","expected":2,"answers":["A","B"]}')
        self.assertEqual(ok["expected"], 2)

    def test_single_requires_one_answer(self):
        with self.assertRaises(contract.ContractError):
            contract.parse('{"type":"SINGLE","answers":["A","B"]}')

    def test_dropdown_and_match_validation(self):
        dd = contract.parse('{"type":"DROPDOWN","items":[{"statement":"S","answer":"True"}]}')
        self.assertEqual(dd["items"][0]["answer"], "True")
        with self.assertRaises(contract.ContractError):
            contract.parse('{"type":"DROPDOWN","items":[{"statement":"S"}]}')
        with self.assertRaises(contract.ContractError):
            contract.parse('{"type":"MATCH","pairs":[{"left":"a","letter":"AB","right":"x"}]}')
        m = contract.parse('{"type":"MATCH","pairs":[{"left":"a","letter":"b","right":"x"}]}')
        self.assertEqual(m["pairs"][0]["letter"], "B")

    def test_unknown_type(self):
        with self.assertRaises(contract.ContractError):
            contract.parse('{"type":"ESSAY"}')

    def test_readable(self):
        self.assertEqual(contract.readable({"type": "SINGLE", "answers": ["RAM"]}), "RAM")
        self.assertEqual(contract.readable({"type": "MULTI", "expected": 2, "answers": ["A", "B"]}), "A\nB")
        dd = {"type": "DROPDOWN", "items": [{"statement": "x", "answer": "True"},
                                            {"statement": "y", "answer": "False"}]}
        self.assertEqual(contract.readable(dd), "1. True\n2. False")
        m = {"type": "MATCH", "pairs": [{"left": "l", "letter": "C", "right": "r1"},
                                        {"left": "l", "letter": "A", "right": "r2"}]}
        self.assertEqual(contract.readable(m), "C, A")
        self.assertEqual(contract.readable(m, right_order=["r2", "r1"]), "A, C")


class ConfigTests(unittest.TestCase):
    def test_default_file_parses(self):
        cfg = config.load(REPO / "config" / "quiz-helper.conf")
        self.assertEqual(cfg["MODEL"], "sonnet")
        self.assertEqual(cfg["CLICK_OFFSET_X"], 40)
        self.assertAlmostEqual(cfg["MATCH_THRESHOLD"], 0.6)
        self.assertEqual(cfg["SUBMIT_WORDS_BLOCKLIST"], ["all", "assessment", "exam", "finish", "end"])
        self.assertIn("Incorrect", cfg["FEEDBACK_INCORRECT_WORDS"])
        for key in ("MAX_QUESTIONS", "MAX_SCROLLS", "MOUSE_ABORT_PX", "ADVANCE_TIMEOUT", "RETRY_ON_INCORRECT"):
            self.assertIsInstance(cfg[key], int)

    def test_quotes_comments_and_override(self):
        raw = config.parse_text('# c\nA="x y"\nB=\'z\'\n\nMATCH_MODE=click\n')
        self.assertEqual(raw, {"A": "x y", "B": "z", "MATCH_MODE": "click"})

    def test_invalid_values(self):
        with self.assertRaises(config.ConfigError):
            config.typed({"MAX_QUESTIONS": "muitas"})
        with self.assertRaises(config.ConfigError):
            config.typed({"MATCH_MODE": "telepatia"})
        with self.assertRaises(config.ConfigError):
            config.parse_text("isto não é chave=valor")


if __name__ == "__main__":
    unittest.main()
