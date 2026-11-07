"""Parser tolerante e validação do contrato (resposta com raciocínio antes do JSON)."""

from __future__ import annotations

import unittest

from quizhelper import contract

Q = {"kind": "SINGLE", "options": [{"index": i, "text": str(i)} for i in range(6)]}
Q_MULTI = {"kind": "MULTI", "expected": 2, "options": [{"index": i, "text": str(i)} for i in range(5)]}


class ParseTest(unittest.TestCase):
    def test_json_puro(self):
        self.assertEqual(contract.parse_validated('{"type":"SINGLE","answers":[4]}', Q)["answers"], [4])

    def test_cerca_de_codigo(self):
        self.assertEqual(contract.parse_validated('```json\n{"type":"SINGLE","answers":[1]}\n```', Q)["answers"], [1])

    def test_raciocinio_antes_do_json(self):
        raw = 'Calculando o exemplo sintético...\nResultado: x\n\n{"type":"SINGLE","answers":[4]}\n'
        self.assertEqual(contract.parse_validated(raw, Q)["answers"], [4])

    def test_raciocinio_com_chaves_antes(self):
        raw = 'Formato {a} e {"type":"SINGLE","answers":[9]} descartado.\n{"type":"SINGLE","answers":[2]}'
        self.assertEqual(contract.parse_validated(raw, Q)["answers"], [2])

    def test_ultimo_valido_vence_mesmo_com_um_posterior_invalido(self):
        raw = '{"type":"SINGLE","answers":[3]}\nmas {"type":"SINGLE","answers":[99]}'
        self.assertEqual(contract.parse_validated(raw, Q)["answers"], [3])

    def test_chaves_em_string(self):
        raw = 'nota "}{" {"type":"SINGLE","answers":[0],"note":"a } b"}'
        self.assertEqual(contract.parse_validated(raw, Q)["answers"], [0])

    def test_sem_json(self):
        with self.assertRaises(contract.ContractError):
            contract.parse_validated("não sei", Q)

    def test_json_invalido_traz_motivo(self):
        with self.assertRaisesRegex(contract.ContractError, "fora de 0..5"):
            contract.parse_validated('{"type":"SINGLE","answers":[7]}', Q)

    def test_quantidade_multi(self):
        with self.assertRaisesRegex(contract.ContractError, "pedidas 2"):
            contract.parse_validated('{"type":"MULTI","answers":[1]}', Q_MULTI)

    def test_schema(self):
        sc = contract.schema_for(Q_MULTI)
        self.assertEqual(sc["properties"]["answers"]["maxItems"], 2)
        self.assertEqual(contract.schema_for(Q)["properties"]["type"], {"const": "SINGLE"})



class ModelTest(unittest.TestCase):
    def test_modelo_e_retry(self):
        from quizhelper import claude
        self.assertEqual(claude.model_for({}), "haiku")
        self.assertEqual(claude.model_for({"MODEL": "haiku", "RETRY_MODEL": ""}, retry=True), "haiku")
        self.assertEqual(claude.model_for({"MODEL": "haiku", "RETRY_MODEL": "sonnet"}), "haiku")
        self.assertEqual(claude.model_for({"MODEL": "haiku", "RETRY_MODEL": "sonnet"}, retry=True), "sonnet")


if __name__ == "__main__":
    unittest.main()
