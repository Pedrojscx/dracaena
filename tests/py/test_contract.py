"""Parser tolerante e validação do contrato (resposta com raciocínio antes do JSON)."""

from __future__ import annotations

import unittest

from dracaena.core import contract
from dracaena.core.model import Choice, Item, Option, Question

Q = Question("q", "SINGLE", "enunciado sintético", options=tuple(Option(i, str(i)) for i in range(6)))
Q_MULTI = Question("q", "MULTI", "enunciado sintético", options=tuple(Option(i, str(i)) for i in range(5)), expected=2)
Q_DROP = Question("q", "DROPDOWN", "enunciado sintético", items=(
    Item("a", tuple(Choice(i, str(i)) for i in range(3))), Item("b", tuple(Choice(i, str(i)) for i in range(2)))))


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


    def test_dropdown_cobertura_total(self):
        ok = '{"type":"DROPDOWN","items":[{"item":1,"option":0},{"item":0,"option":2}]}'
        self.assertEqual(contract.parse_validated(ok, Q_DROP)["items"], [{"item": 0, "option": 2}, {"item": 1, "option": 0}])
        with self.assertRaisesRegex(contract.ContractError, "1 de 2 itens"):
            contract.parse_validated('{"type":"DROPDOWN","items":[{"item":0,"option":1}]}', Q_DROP)
        with self.assertRaisesRegex(contract.ContractError, "repetido"):
            contract.parse_validated('{"type":"DROPDOWN","items":[{"item":0,"option":1},{"item":0,"option":2}]}', Q_DROP)
        with self.assertRaisesRegex(contract.ContractError, "fora de 0..1"):
            contract.parse_validated('{"type":"DROPDOWN","items":[{"item":0,"option":1},{"item":1,"option":2}]}', Q_DROP)

    def test_tipo_diferente_e_indice_nao_inteiro(self):
        with self.assertRaisesRegex(contract.ContractError, "esperado 'SINGLE'"):
            contract.parse_validated('{"type":"MULTI","answers":[1,2]}', Q)
        with self.assertRaisesRegex(contract.ContractError, "inteiro"):
            contract.parse_validated('{"type":"SINGLE","answers":["1"]}', Q)
        with self.assertRaisesRegex(contract.ContractError, "repetido"):
            contract.parse_validated('{"type":"MULTI","answers":[1,1]}', Q_MULTI)

    def test_texto_da_questao_e_legivel(self):
        text = contract.question_text(Q_MULTI)
        self.assertIn("Tipo: MULTI", text)
        self.assertIn("Quantidade pedida: 2", text)
        self.assertIn("[4] 4", text)
        self.assertEqual(contract.readable({"type": "MULTI", "answers": [1, 3]}, Q_MULTI), "• 1\n• 3")
        self.assertIn("Item [1]: b", contract.question_text(Q_DROP))

    def test_dicionario_legado_e_aceito(self):
        legacy = {"kind": "SINGLE", "stem": "x", "options": [{"index": 0, "text": "a"}, {"index": 1, "text": "b"}]}
        self.assertEqual(contract.parse_validated('{"type":"SINGLE","answers":[1]}', legacy)["answers"], [1])


class ModelTest(unittest.TestCase):
    def test_modelo_e_retry(self):
        from dracaena.core import claude
        self.assertEqual(claude.model_for({}), "haiku")
        self.assertEqual(claude.model_for({"MODEL": "haiku", "RETRY_MODEL": ""}, retry=True), "haiku")
        self.assertEqual(claude.model_for({"MODEL": "haiku", "RETRY_MODEL": "sonnet"}), "haiku")
        self.assertEqual(claude.model_for({"MODEL": "haiku", "RETRY_MODEL": "sonnet"}, retry=True), "sonnet")


if __name__ == "__main__":
    unittest.main()
