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
