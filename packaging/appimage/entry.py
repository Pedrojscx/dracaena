"""Entry point do projeto com o Chromium incorporado selecionado no AppImage."""
import logging
import os
from pathlib import Path
import sys


def _restore_library_path():
    """Devolve aos processos filhos o LD_LIBRARY_PATH que o usuário tinha.

    O bootloader do PyInstaller aponta LD_LIBRARY_PATH para as bibliotecas empacotadas
    (construídas sobre a glibc 2.28). Se o Chromium ou outro navegador herdasse isso,
    carregaria, por exemplo, um libglib antigo que não casa com o libpango do host.
    O loader do próprio processo já leu o valor, então só os filhos são afetados.
    """
    if not getattr(sys, "frozen", False):
        return
    original = os.environ.pop("LD_LIBRARY_PATH_ORIG", None)
    if original is None:
        os.environ.pop("LD_LIBRARY_PATH", None)
    else:
        os.environ["LD_LIBRARY_PATH"] = original


# Pacotes de certificados das famílias Debian/Arch, Fedora/RHEL e openSUSE, nesta ordem.
_CA_BUNDLES = ("/etc/ssl/certs/ca-certificates.crt", "/etc/pki/tls/certs/ca-bundle.crt",
               "/etc/ssl/ca-bundle.pem", "/etc/pki/tls/cert.pem", "/etc/ssl/cert.pem")


def _use_host_certificates():
    """Aponta o OpenSSL embutido para os certificados do host.

    O Python do pacote é compilado na AlmaLinux 8, onde OPENSSLDIR é /etc/pki/tls; em
    Ubuntu, Debian, Arch e openSUSE esse caminho não existe. SSL_CERT_FILE/SSL_CERT_DIR
    definidos pelo usuário têm prioridade.
    """
    if not getattr(sys, "frozen", False):
        return
    if os.environ.get("SSL_CERT_FILE") or os.environ.get("SSL_CERT_DIR"):
        return
    for bundle in _CA_BUNDLES:
        if os.access(bundle, os.R_OK):
            os.environ["SSL_CERT_FILE"] = bundle
            return


def _py_selftest(https):
    """Exercita o Python embutido (módulos presentes no pacote); sai 1 se algo quebrar."""
    import hashlib
    import importlib
    import json
    results, failed = {}, False

    def check(name, function):
        nonlocal failed
        try:
            results[name] = function()
        except ImportError as error:  # módulo não empacotado: informativo, não falha
            results[name] = f"ausente: {error}"
        except Exception as error:  # noqa: BLE001 - relatório de diagnóstico
            results[name] = f"FALHA: {type(error).__name__}: {error}"
            failed = True

    def ctypes_ffi():
        import ctypes
        libc = ctypes.CDLL(None)
        values = (ctypes.c_int * 4)(3, 1, 4, 2)
        compare = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int))
        libc.qsort(values, 4, ctypes.sizeof(ctypes.c_int), compare(lambda a, b: a[0] - b[0]))
        assert list(values) == [1, 2, 3, 4], list(values)
        return f"ok (pid {libc.getpid()}, callback libffi ok)"

    def ssl_info():
        import ssl
        paths = ssl.get_default_verify_paths()
        context = ssl.create_default_context()
        stats = context.cert_store_stats()
        loaded = stats["x509_ca"]
        assert loaded > 0, f"nenhum certificado de CA carregado (cafile={paths.cafile}, capath={paths.capath})"
        return f"{ssl.OPENSSL_VERSION}; CAs={loaded}; cafile={paths.cafile or paths.openssl_cafile}"

    def https_get():
        import urllib.request
        with urllib.request.urlopen("https://pypi.org/simple/", timeout=20) as response:
            return f"HTTP {response.status}"

    def sqlite():
        import sqlite3
        db = sqlite3.connect(":memory:")
        db.execute("create table t(x)")
        db.execute("insert into t values (42)")
        assert db.execute("select x from t").fetchone() == (42,)
        return f"ok ({sqlite3.sqlite_version})"

    def compression():
        import bz2
        import lzma
        import zlib
        data = b"dracaena" * 100
        assert zlib.decompress(zlib.compress(data)) == data
        assert bz2.decompress(bz2.compress(data)) == data
        assert lzma.decompress(lzma.compress(data)) == data
        return "zlib, bz2 e lzma ok"

    def simple(module):
        return lambda: (importlib.import_module(module), "ok")[1]

    check("ctypes/libffi", ctypes_ffi)
    check("ssl", ssl_info)
    check("sqlite3", sqlite)
    check("compressao", compression)
    check("readline", simple("readline"))
    check("curses", simple("_curses"))
    check("uuid", lambda: f"ok ({__import__('uuid').uuid4()})")
    check("hashlib", lambda: hashlib.sha256(b"x").hexdigest()[:12])
    if https:
        check("https", https_get)
    print(json.dumps(results, ensure_ascii=False, indent=1))
    return 1 if failed else 0


def _use_bundled_browser():
    """Aponta o fallback do Playwright para a cópia somente leitura empacotada."""
    if not getattr(sys, "frozen", False):
        return
    root = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "dracaena-browsers"
    if root.is_dir():
        from dracaena.platform import browser
        browser.fallback_dir = lambda: root


_restore_library_path()
_use_host_certificates()
_use_bundled_browser()
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
from dracaena.cli import main

if __name__ == "__main__":
    # Verificação do Python embutido, fora do --help; não conflita com os --appimage-* do runtime.
    if len(sys.argv) == 2 and sys.argv[1] in ("--py-selftest", "--py-selftest-https"):
        raise SystemExit(_py_selftest(sys.argv[1].endswith("https")))
    raise SystemExit(main())
