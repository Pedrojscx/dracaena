"""Sonda de CDP com executáveis falsos (offline)."""
import json
import os
from pathlib import Path
import sys
import tempfile
import textwrap
import time
import unittest
from unittest.mock import patch

import psutil

from dracaena.platform import browser, doctor

COMMON = """
import json, os, sys
record = os.environ.get("FAKE_RECORD")
if "--version" in sys.argv:
    print(os.environ.get("FAKE_NAME", "Navegador Generico 1.0"))
    sys.exit(0)
profile = next(a.split("=", 1)[1] for a in sys.argv if a.startswith("--user-data-dir="))
def note(**extra):
    data = json.load(open(record)) if os.path.exists(record) else {}
    data.update(extra)
    json.dump(data, open(record, "w"))
note(pid=os.getpid(), argv=sys.argv, profile=profile, home=os.environ.get("HOME"))
"""

FAKES = {
    "good": """
import http.server, socket
class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = json.dumps({"Browser": "Falso/1.0", "webSocketDebuggerUrl": "ws://127.0.0.1/devtools/browser/x"}).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers()
        self.wfile.write(body)
    def log_message(self, *a): pass
server = http.server.HTTPServer(("127.0.0.1", 0), H)
with open(os.path.join(profile, "DevToolsActivePort"), "w") as f:
    f.write(f"{server.server_address[1]}\\n/devtools/browser/x\\n")
server.serve_forever()
""",
    "badjson": """
import http.server
class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers(); self.wfile.write(b'{"outra": "coisa"}')
    def log_message(self, *a): pass
server = http.server.HTTPServer(("127.0.0.1", 0), H)
with open(os.path.join(profile, "DevToolsActivePort"), "w") as f:
    f.write(f"{server.server_address[1]}\\n/devtools/browser/x\\n")
server.serve_forever()
""",
    "silent": """
import time
time.sleep(600)
""",
    "stubborn": """
import signal, subprocess, time
signal.signal(signal.SIGTERM, signal.SIG_IGN)
child = subprocess.Popen([sys.executable, "-c",
    "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(600)"])
note(child=child.pid)
time.sleep(600)
""",
    "exits": """
sys.exit(3)
""",
}


def gone(pid, wait=5):
    deadline = time.monotonic() + wait
    while True:
        try:
            if psutil.Process(pid).status() == psutil.STATUS_ZOMBIE:
                return True
        except psutil.NoSuchProcess:
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(.05)


@unittest.skipIf(os.name == "nt", "executáveis falsos em script POSIX")
class ProbeTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.record = self.root / "record.json"
        self.env = patch.dict(os.environ, {"FAKE_RECORD": str(self.record)})
        self.env.start()
        self.data = patch.object(browser, "data_dir", return_value=self.root / "data")
        self.data.start()

    def tearDown(self):
        self.data.stop()
        self.env.stop()
        if self.record.exists():
            info = json.loads(self.record.read_text())
            for key in ("pid", "child"):
                if key in info and not gone(info[key], wait=0):
                    try:
                        psutil.Process(info[key]).kill()
                    except psutil.NoSuchProcess:
                        pass
        self.directory.cleanup()

    def fake(self, kind):
        path = self.root / kind
        path.write_text(f"#!{sys.executable}\n" + COMMON + textwrap.dedent(FAKES[kind]))
        path.chmod(0o755)
        return str(path)

    def recorded(self):
        return json.loads(self.record.read_text())

    def assert_cleaned(self):
        info = self.recorded()
        self.assertTrue(gone(info["pid"]), "processo da sonda continua vivo")
        if "child" in info:
            self.assertTrue(gone(info["child"]), "filho da sonda continua vivo")
        profile = Path(info["profile"])
        self.assertFalse(profile.parent.exists(), "diretório temporário não foi apagado")
        return info

    def test_success_uses_fresh_temp_profile_and_cleans_up(self):
        started = time.monotonic()
        result = browser.probe_cdp(self.fake("good"), timeout=10)
        self.assertLess(time.monotonic() - started, 8)
        self.assertEqual(result["Browser"], "Falso/1.0")
        info = self.assert_cleaned()
        profile = Path(info["profile"])
        self.assertTrue(profile.parent.name.startswith("dracaena-probe-"))
        self.assertEqual(Path(os.path.realpath(profile.parent.parent)), Path(os.path.realpath(tempfile.gettempdir())))
        self.assertNotIn(str(self.root / "data"), info["profile"])
        self.assertTrue(info["home"].startswith(str(profile.parent)), "HOME da sonda fora do diretório temporário")
        for flag in ("--headless=new", "--remote-debugging-port=0", "--no-first-run", "--no-default-browser-check", "about:blank"):
            self.assertIn(flag, info["argv"])

    def test_timeout_kills_process_and_cleans_up(self):
        with self.assertRaises(browser.ProbeTimeout):
            browser.probe_cdp(self.fake("silent"), timeout=1)
        self.assert_cleaned()

    def test_process_ignoring_sigterm_and_its_child_are_killed(self):
        with self.assertRaises(browser.ProbeTimeout):
            browser.probe_cdp(self.fake("stubborn"), timeout=1)
        self.assertIn("child", self.assert_cleaned())

    def test_invalid_version_endpoint_is_rejected(self):
        with self.assertRaisesRegex(browser.BrowserError, "não parece"):
            browser.probe_cdp(self.fake("badjson"), timeout=10)
        self.assert_cleaned()

    def test_early_exit_is_reported(self):
        with self.assertRaisesRegex(browser.BrowserError, "encerrou"):
            browser.probe_cdp(self.fake("exits"), timeout=10)
        self.assert_cleaned()

    def test_unexpected_exception_still_cleans_up(self):
        created, real_mkdtemp = [], tempfile.mkdtemp
        def recording_mkdtemp(*args, **kwargs):
            created.append(real_mkdtemp(*args, **kwargs))
            return created[-1]
        def interrupt(profile):
            deadline = time.monotonic() + 5
            while not self.record.exists() and time.monotonic() < deadline:
                time.sleep(.05)
            raise KeyboardInterrupt
        with patch.object(browser.tempfile, "mkdtemp", recording_mkdtemp), patch.object(browser, "read_port", interrupt):
            with self.assertRaises(KeyboardInterrupt):
                browser.probe_cdp(self.fake("silent"), timeout=10)
        self.assertEqual(len(created), 1)
        self.assertFalse(Path(created[0]).exists())
        self.assert_cleaned()

    def test_unknown_name_is_accepted_by_probe(self):
        self.assertTrue(browser.is_chromium(self.fake("good")))
        self.assertFalse(browser.is_chromium(self.fake("exits")))

    def test_known_name_and_known_non_chromium_skip_probe(self):
        path = self.fake("good")
        with patch.object(browser, "probe_cdp") as probe:
            with patch.dict(os.environ, {"FAKE_NAME": "Vivaldi 7.0"}):
                self.assertTrue(browser.is_chromium(path))
            with patch.dict(os.environ, {"FAKE_NAME": "Mozilla Firefox 130.0"}):
                self.assertFalse(browser.is_chromium(path))
        probe.assert_not_called()

    def test_explicit_unknown_chromium_like_is_accepted(self):
        path = self.fake("good")
        with patch.object(browser, "default_browser") as detect:
            self.assertEqual(browser.resolve(path, ""), path)
        detect.assert_not_called()


@unittest.skipIf(os.name == "nt", "executáveis falsos em script POSIX")
class ProbeCacheTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.data = patch.object(browser, "data_dir", return_value=self.root / "data")
        self.data.start()
        self.exe = self.root / "navegador"
        self.exe.write_text("#!/bin/sh\nexit 0\n")
        self.exe.chmod(0o755)

    def tearDown(self):
        self.data.stop()
        self.directory.cleanup()

    def test_result_is_cached_by_real_path_mtime_and_size(self):
        link = self.root / "atalho"
        link.symlink_to(self.exe)
        with patch.object(browser, "probe_cdp", return_value={"Browser": "x"}) as probe:
            self.assertTrue(browser.supports_cdp(str(self.exe)))
            self.assertTrue(browser.supports_cdp(str(link)))
            self.assertEqual(probe.call_count, 1)
            cache = self.root / "data" / "browser-probe.json"
            self.assertEqual(list(json.loads(cache.read_text())), [os.path.realpath(self.exe)])
            self.assertEqual(cache.stat().st_mode & 0o777, 0o600)
            stat = self.exe.stat()
            os.utime(self.exe, ns=(stat.st_atime_ns, stat.st_mtime_ns + 10**9))
            self.assertTrue(browser.supports_cdp(str(self.exe)))
            self.assertEqual(probe.call_count, 2)
            self.exe.write_text("#!/bin/sh\nexit 0\n# maior\n")
            self.assertTrue(browser.supports_cdp(str(self.exe)))
            self.assertEqual(probe.call_count, 3)

    def test_negative_result_is_cached_but_timeout_is_not(self):
        with patch.object(browser, "probe_cdp", side_effect=browser.BrowserError("não")) as probe:
            self.assertFalse(browser.supports_cdp(str(self.exe)))
            self.assertFalse(browser.supports_cdp(str(self.exe)))
            self.assertEqual(probe.call_count, 1)
        (self.root / "data" / "browser-probe.json").unlink()
        with patch.object(browser, "probe_cdp", side_effect=browser.ProbeTimeout("lento")) as probe:
            self.assertFalse(browser.supports_cdp(str(self.exe)))
            self.assertFalse(browser.supports_cdp(str(self.exe)))
            self.assertEqual(probe.call_count, 2)

    def test_corrupt_cache_and_missing_executable(self):
        (self.root / "data").mkdir()
        (self.root / "data" / "browser-probe.json").write_text("{quebrado")
        with patch.object(browser, "probe_cdp", return_value={"Browser": "x"}) as probe:
            self.assertTrue(browser.supports_cdp(str(self.exe)))
            self.assertFalse(browser.supports_cdp(str(self.root / "nao-existe")))
        self.assertEqual(probe.call_count, 1)


class SandboxTests(unittest.TestCase):
    def test_sandboxed_default_must_pass_probe(self):
        with patch.object(browser, "default_browser", return_value="/snap/bin/navegador"), \
                patch.object(browser, "is_chromium", return_value=True) as by_name:
            with patch.object(browser, "supports_cdp", return_value=False):
                with self.assertRaisesRegex(browser.BrowserUnsupported, "Flatpak/Snap"):
                    browser.resolve("", "playwright")
            with patch.object(browser, "supports_cdp", return_value=True):
                self.assertEqual(browser.resolve("", ""), "/snap/bin/navegador")
        by_name.assert_not_called()

    def test_unwrap_env_and_flatpak_exec(self):
        with tempfile.TemporaryDirectory() as directory:
            exported = Path(directory) / "flatpak/exports/bin/org.exemplo.Navegador"
            exported.parent.mkdir(parents=True)
            exported.write_text("")
            with patch.dict(os.environ, {"XDG_DATA_HOME": directory}):
                self.assertEqual(browser._unwrap_exec(
                    ["/usr/bin/flatpak", "run", "--branch=stable", "--command=nav", "org.exemplo.Navegador", "@@u", "%U", "@@"]),
                    str(exported))
                with self.assertRaises(browser.BrowserUnsupported):
                    browser._unwrap_exec(["flatpak", "run", "org.exemplo.Outro", "%U"])
        self.assertEqual(browser._unwrap_exec(["env", "VAR=1", "-u", "/opt/nav/nav", "%U"]), "/opt/nav/nav")
        with self.assertRaises(browser.BrowserUnsupported):
            browser._unwrap_exec(["env", "VAR=1"])

    def test_doctor_hint_for_sandbox(self):
        with patch.object(browser, "resolve", side_effect=browser.BrowserUnsupported("Navegador padrão em Flatpak/Snap não respondeu ao CDP")):
            checks = {c["name"]: c for c in doctor.run()["checks"]}
        self.assertFalse(checks["browser"]["ok"])
        self.assertIn("BROWSER_BIN", checks["browser"]["hint"])
        self.assertIn("fora do sandbox", checks["browser"]["hint"])


if __name__ == "__main__":
    unittest.main()
