"""Validador do perfil TOML v0 (perfis sintéticos)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import fx  # noqa: F401 - põe lib/ no caminho

from dracaena.adapters import profile
from dracaena.adapters.profile import ProfileError

GOOD = """[site]
name = "Prática sintética"
version = 0
match = ["https://pratica.invalid/*"]

[question]
container = "div.bloco"
stem = "div.titulo"

[options]
item = "tr.alt"
text = "td.txt"
input = "input[type=radio]"

[submit]
button = "button.conferir"

[guard]
block_labels = ["encerrar treino"]
"""


class ParseTests(unittest.TestCase):
    def bad(self, text: str, fragment: str, line: int | None = None):
        with self.assertRaises(ProfileError) as ctx:
            profile.parse(text)
        self.assertIn(fragment, ctx.exception.msg)
        if line is not None:
            self.assertEqual(ctx.exception.line, line)
            self.assertIn(f"linha {line}", str(ctx.exception))

    def test_valid_profile(self):
        got = profile.parse(GOOD, slug="sintetico")
        self.assertEqual((got.name, got.slug, got.match), ("Prática sintética", "sintetico", ("https://pratica.invalid/*",)))
        self.assertEqual(got.block_labels, ("encerrar treino",))
        engine = got.to_engine()
        self.assertEqual(set(engine), {"question", "options", "submit"})
        self.assertEqual(engine["options"]["input"], "input[type=radio]")

    def test_unknown_field_and_table_have_the_line(self):
        self.bad(GOOD.replace('stem = "div.titulo"', 'stem = "div.titulo"\nscript = "x"'), "campo desconhecido: question.script", 9)
        self.bad(GOOD + '\n[hooks]\nrun = "x"\n', "tabela ou campo desconhecido: hooks", 21)
        self.bad('solto = 1\n' + GOOD, "tabela ou campo desconhecido: solto", 1)

    def test_version_and_required(self):
        self.bad(GOOD.replace("version = 0", "version = 1"), "site.version precisa ser 0", 3)
        self.bad(GOOD.replace('container = "div.bloco"\n', ""), "falta o campo question.container", 6)
        self.bad(GOOD.split("[question]")[0], "falta a tabela [question]")
        self.bad(GOOD.split("[options]")[0], "falta a tabela [options] ou [dropdown]")
        self.bad("isto não é toml = = =", "TOML inválido", 1)

    def test_no_executable_content(self):
        for value in ("<script>alert(1)</script>", "a{color:red}", "div; drop", "javascript:alert(1)", "a[href^='x']\\n",
                      "div:has(`x`)", "x" * 301, ""):
            with self.subTest(value=value):
                with self.assertRaises(ProfileError) as ctx:
                    profile.parse(GOOD.replace('"div.titulo"', repr(value).replace("'", '"') if '"' not in value else "'''" + value + "'''"))
                self.assertEqual(ctx.exception.line, 8)
        self.bad(GOOD.replace('"div.bloco"', "42"), "precisa ser um seletor CSS", 7)
        self.bad(GOOD.replace('["https://pratica.invalid/*"]', '["ftp://x"]'), "precisa começar com", 4)
        self.bad(GOOD.replace('["encerrar treino"]', "[1]"), "lista de textos curtos", 19)

    def test_dropdown_rules(self):
        native = GOOD.replace("[options]", "[dropdown]").replace('text = "td.txt"\ninput = "input[type=radio]"', "native = true")
        self.assertTrue(profile.parse(native).to_engine()["dropdown"]["native"])
        self.bad(native.replace("native = true", "native = false"), "precisa de button e option", 10)
        self.bad(native.replace("native = true", 'native = "sim"'), "true ou false", 12)

    def test_dump_round_trip(self):
        got = profile.parse(GOOD)
        again = profile.parse(profile.dump(got.tables))
        self.assertEqual(again.tables, got.tables)
        quoted = profile.parse(GOOD.replace('"input[type=radio]"', "'input[name=\"q\"]'"))
        self.assertEqual(profile.parse(profile.dump(quoted.tables)).tables["options"]["input"], 'input[name="q"]')


class MetaTests(unittest.TestCase):
    """[meta] é opcional, aceita só metadados e nunca código ou ação."""

    def with_meta(self, body: str):
        return profile.parse(GOOD + "\n[meta]\n" + body + "\n")

    def bad_meta(self, body: str, fragment: str):
        with self.assertRaises(ProfileError) as ctx:
            self.with_meta(body)
        self.assertIn(fragment, ctx.exception.msg)

    def test_absent_meta_stays_valid(self):
        self.assertEqual(profile.parse(GOOD).meta, {})
        self.assertEqual(profile.parse(GOOD).to_engine(), profile.parse(GOOD + "\n[meta]\nstatus = \"verified\"\n").to_engine())

    def test_valid_meta_is_read(self):
        got = self.with_meta('confidence = 0.876\nstatus = "unverified"\nfingerprint = "f1a2b3"\n'
                             'generator = "structure 1"\ngenerated = "2026-11-16"\n')
        self.assertEqual(got.meta, {"confidence": 0.88, "status": "unverified", "fingerprint": "f1a2b3",
                                    "generator": "structure 1", "generated": "2026-11-16"})
        self.assertEqual(self.with_meta('status = "experimental"\n').meta["status"], "experimental")

    def test_status_and_confidence_ranges(self):
        self.bad_meta('status = "ok"\n', "meta.status precisa ser um de")
        for value in ("1.5", "-0.1", '"0.5"', "true", "nan"):
            with self.subTest(value=value):
                self.bad_meta(f"confidence = {value}\n", "meta.confidence precisa ser um número de 0 a 1")

    def test_text_fields_are_short_and_plain(self):
        self.bad_meta('fingerprint = "f<script>"\n', "meta.fingerprint precisa ser")
        self.bad_meta('fingerprint = "f' + "a" * 40 + '"\n', "meta.fingerprint precisa ser")
        self.bad_meta('generator = "a@b.test"\n', "meta.generator precisa ser")
        self.bad_meta('generator = "x; alert(1)"\n', "meta.generator precisa ser")

    def test_generated_must_be_a_real_date_with_ascii_digits(self):
        self.bad_meta('generated = "2026-13-45"\n', "meta.generated não é uma data válida")
        self.bad_meta('generated = "2026-02-30"\n', "meta.generated não é uma data válida")
        self.bad_meta('generated = "٢٠٢٦-11-16"\n', "meta.generated precisa ser")

    def test_unknown_meta_field_is_rejected(self):
        self.bad_meta('code = "alert(1)"\n', "campo desconhecido: meta.code")
        self.bad_meta('action = "click"\n', "campo desconhecido: meta.action")

    def test_meta_is_not_an_engine_table(self):
        self.assertNotIn("meta", profile.ENGINE_TABLES)
        self.assertNotIn("meta", self.with_meta('status = "verified"\n').to_engine())


class LoadTests(unittest.TestCase):
    def test_invalid_files_are_skipped_with_a_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "b-bom.toml").write_text(GOOD, encoding="utf-8")
            (root / "a-ruim.toml").write_text(GOOD.replace("version = 0", "version = 9"), encoding="utf-8")
            (root / "c-binario.toml").write_bytes(b"\xff\xfe\x00")
            (root / "nota.txt").write_text("ignorado", encoding="utf-8")
            warnings = []
            loaded = profile.load_all(root, warn=warnings.append)
            self.assertEqual([p.slug for p in loaded], ["b-bom"])
            self.assertEqual(len(warnings), 2)
            self.assertIn("a-ruim.toml", warnings[0])
            self.assertEqual(profile.load_all(root / "ausente"), [])


if __name__ == "__main__":
    unittest.main()
