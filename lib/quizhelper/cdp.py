"""Validação somente leitura do endpoint CDP local, sem seguir redirects/proxies."""
from __future__ import annotations

import json
import sys
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, ProxyHandler, build_opener


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def version(port: int) -> dict:
    if not 1 <= port <= 65535:
        raise ValueError("porta CDP inválida")
    opener = build_opener(ProxyHandler({}), NoRedirect())
    with opener.open(f"http://127.0.0.1:{port}/json/version", timeout=2) as response:
        data = json.loads(response.read(65536))
    ws = urlparse(data.get("webSocketDebuggerUrl", ""))
    if (not data.get("Browser") or not data.get("Protocol-Version") or ws.scheme != "ws"
            or ws.hostname not in ("127.0.0.1", "localhost", "::1") or ws.port != port
            or not ws.path.startswith("/devtools/browser/") or ws.username or ws.password):
        raise ValueError("endpoint não é CDP local válido")
    return data


def main() -> int:
    try:
        version(int(sys.argv[1]))
    except Exception:
        print("endpoint /json/version indisponível ou não é CDP válido", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
