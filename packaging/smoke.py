"""Exercise the actual Unix socket / Windows named pipe in a subprocess."""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

from dracaena.platform.ipc import connect, endpoint, request


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--executable")
    args = parser.parse_args()
    command = [str(Path(args.executable).resolve())] if args.executable else [sys.executable, "-m", "dracaena.cli"]
    with tempfile.TemporaryDirectory() as directory:
        os.environ["XDG_RUNTIME_DIR"] = directory
        os.environ["XDG_CONFIG_HOME"] = str(Path(directory) / "config")
        os.environ["XDG_DATA_HOME"] = str(Path(directory) / "data")
        os.environ["APPDATA"] = str(Path(directory) / "roaming")
        os.environ["LOCALAPPDATA"] = str(Path(directory) / "local")
        process = subprocess.Popen(command + ["daemon", "--simulate"])
        try:
            for _ in range(100):
                try:
                    conn = connect()
                    break
                except OSError:
                    if process.poll() is not None:
                        raise RuntimeError("Daemon exited during startup")
                    time.sleep(.1)
            else:
                raise RuntimeError("Daemon did not start")
            conn.send({"v": 0, "id": 42, "cmd": "subscribe", "args": {"events": ["state"]}})
            assert conn.receive()["id"] == 42
            assert conn.receive()["state"] == "idle"
            for expected in ("running", "paused", "running"):
                assert request("toggle")["data"]["state"] == expected
                assert conn.receive()["state"] == expected
            assert request("ask")["data"]["simulated"]
            assert conn.receive()["question"] == 1
            assert request("config.set", {"key": "MAX_QUESTIONS", "value": 0})["code"] == "bad_request"
            assert request("unknown")["code"] == "unknown_cmd"
            assert request("stop")["data"]["state"] == "idle"
            assert conn.receive()["state"] == "idle"
            conn.close()
            if os.name != "nt":
                assert Path(endpoint()).stat().st_mode & 0o777 == 0o600
            result = subprocess.run(command + ["doctor"], capture_output=True, text=True, timeout=30)
            import json
            assert "checks" in json.loads(result.stdout)
            assert result.returncode in (0, 1)  # missing external dependencies are diagnostic failures
            print("PASS: real IPC transport, transitions, subscriptions, validation and doctor")
        finally:
            process.terminate()
            process.wait(timeout=10)


if __name__ == "__main__":
    main()
