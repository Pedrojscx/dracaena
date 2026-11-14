"""Varredura ERE com termos externos; valores encontrados nunca são impressos."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[2]
# legado específico de site; limpeza pendente, decisão do humano; NÃO acrescentar caminhos novos
LEGADO_PENDENTE = (
    "lib/quizhelper/",
    "tests/fixtures/derived.py",
    "tests/fixtures/html/sim.js",
    "tests/py/web.py",
)


def scan(roots, terms_file, excluded=()):
    """Conta arquivos com ocorrência, sem devolver nomes ou linhas encontradas."""
    patterns = [line for line in Path(terms_file).read_text(encoding="utf-8").splitlines()
                if line.strip() and not line.lstrip().startswith("#")]
    if not patterns:
        return 0
    excluded = tuple(Path(p).resolve() for p in excluded)
    files = set()
    for root in map(Path, roots):
        candidates = root.rglob("*") if root.is_dir() else (root,)
        for path in candidates:
            if not path.is_file() or "__pycache__" in path.parts or path.suffix == ".pyc":
                continue
            resolved = path.resolve()
            if any(resolved == item or resolved.is_relative_to(item) for item in excluded):
                continue
            files.add(str(path))
    files = sorted(files)
    total = 0
    with tempfile.TemporaryDirectory(prefix="gx-scan-") as temp:
        path = Path(temp) / "patterns"
        path.write_text("\n".join(patterns) + "\n", encoding="utf-8")
        for offset in range(0, len(files), 128):
            result = subprocess.run(["grep", "-I", "-i", "-l", "-Z", "-E", "-f", str(path), "--",
                                     *files[offset:offset + 128]], capture_output=True)
            if result.returncode not in (0, 1):
                raise RuntimeError("varredura ERE falhou; confira o arquivo externo e a disponibilidade dos caminhos")
            total += result.stdout.count(b"\0")
    return total


class GenericNamesTests(unittest.TestCase):
    def external_terms(self):
        configured = os.environ.get("DRACAENA_TERMS_FILE")
        if not configured:
            self.skipTest("DRACAENA_TERMS_FILE não definida; lista externa não disponível")
        path = Path(configured)
        if not path.is_file():
            self.skipTest("arquivo externo de termos não encontrado")
        self.assertIsNotNone(shutil.which("grep"), "grep necessário para regex ERE")
        return path

    def test_external_terms(self):
        path = self.external_terms()
        count = scan([REPO / "tests" / "fixtures", REPO / "lib", REPO / "tests" / "py"], path,
                     excluded=[REPO / p for p in LEGADO_PENDENTE])
        print(f"Nomes externos: {count} arquivos com ocorrência.")
        self.assertEqual(count, 0, "ocorrências encontradas fora do legado; conteúdo omitido")

    def test_legacy_exclusions_are_frozen(self):
        self.assertEqual(len(LEGADO_PENDENTE), 4)
        self.assertEqual(LEGADO_PENDENTE, (
            "lib/quizhelper/", "tests/fixtures/derived.py", "tests/fixtures/html/sim.js", "tests/py/web.py",
        ))

    def test_legacy_count_pending_cleanup(self):
        path = self.external_terms()
        count = scan([REPO / p for p in LEGADO_PENDENTE], path)
        print(f"Legado: {count} arquivos com ocorrência.")
        self.assertEqual(count, 8, "contagem do legado mudou; revisar a limpeza")
        self.skipTest("legado pendente de limpeza")

    def test_ere_comments_and_case(self):
        with tempfile.TemporaryDirectory(prefix="gx-test-") as temp:
            root = Path(temp)
            data = root / "data"
            data.mkdir()
            (data / "sample").write_text("GX-12\nTexto sintético 1\n", encoding="utf-8")
            terms = root / "patterns"
            terms.write_text("# ignored\n  # ignored\n\ngx-[[:digit:]]{2}\n", encoding="utf-8")
            self.assertEqual(scan([data], terms), 1)
            terms.write_text("gx-[[:digit:]]{3}\n", encoding="utf-8")
            self.assertEqual(scan([data], terms), 0)

    def test_exclusion_is_exact_not_a_basename_filter(self):
        with tempfile.TemporaryDirectory(prefix="gx-test-") as temp:
            root = Path(temp)
            for folder in ("one", "two"):
                (root / folder).mkdir()
                (root / folder / "sample").write_text("gx-12", encoding="utf-8")
            terms = root / "patterns"
            terms.write_text("gx-[[:digit:]]{2}\n", encoding="utf-8")
            self.assertEqual(scan([root / "one", root / "two"], terms, [root / "one"]), 1)
            self.assertEqual(scan([root / "one", root / "two"], terms, [root / "one" / "sample"]), 1)

    def test_invalid_ere_fails_without_echoing_terms(self):
        with tempfile.TemporaryDirectory(prefix="gx-test-") as temp:
            root = Path(temp)
            data = root / "data"
            data.mkdir()
            (data / "sample").write_text("Texto sintético 1", encoding="utf-8")
            terms = root / "patterns"
            terms.write_text("[\n", encoding="utf-8")
            with self.assertRaises(RuntimeError):
                scan([data], terms)
