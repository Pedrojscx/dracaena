"""Varredura ERE com termos externos; valores encontrados nunca são impressos."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[2]


def scan(roots, terms_file):
    patterns = [line for line in Path(terms_file).read_text(encoding="utf-8").splitlines()
                if line.strip() and not line.lstrip().startswith("#")]
    if not patterns:
        return 0
    with tempfile.TemporaryDirectory(prefix="gx-scan-") as temp:
        path = Path(temp) / "patterns"
        path.write_text("\n".join(patterns) + "\n", encoding="utf-8")
        result = subprocess.run(["grep", "-r", "-I", "-i", "-n", "-E", "--exclude-dir=__pycache__",
                                 "-f", str(path), "--", *map(str, roots)], capture_output=True)
    if result.returncode not in (0, 1):
        raise RuntimeError("varredura ERE falhou; confira o arquivo externo e a disponibilidade dos caminhos")
    return len(result.stdout.splitlines())


class GenericNamesTests(unittest.TestCase):
    def test_external_terms(self):
        configured = os.environ.get("DRACAENA_TERMS_FILE")
        if not configured:
            self.skipTest("DRACAENA_TERMS_FILE não definida; lista externa não disponível")
        path = Path(configured)
        if not path.is_file():
            self.skipTest("arquivo externo de termos não encontrado")
        self.assertIsNotNone(shutil.which("grep"), "grep necessário para regex ERE")
        count = scan([REPO / "tests" / "fixtures", REPO / "lib"], path)
        print(f"Nomes externos: {count} ocorrências.")
        self.assertEqual(count, 0, "ocorrências encontradas; conteúdo omitido")

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

    def test_invalid_ere_fails_without_echoing_terms(self):
        with tempfile.TemporaryDirectory(prefix="gx-test-") as temp:
            root = Path(temp)
            data = root / "data"
            data.mkdir()
            terms = root / "patterns"
            terms.write_text("[\n", encoding="utf-8")
            with self.assertRaises(RuntimeError):
                scan([data], terms)
