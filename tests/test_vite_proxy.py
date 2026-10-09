"""Every top-level API path used by the SPA client must be proxied by the dev server."""
import re
from pathlib import Path

FRONTEND = Path(__file__).resolve().parent.parent / "frontend"


def test_client_prefixes_are_proxied():
    client = (FRONTEND / "src/api/client.ts").read_text(encoding="utf-8")
    vite = (FRONTEND / "vite.config.ts").read_text(encoding="utf-8")
    proxied = set(re.findall(r'"(/[a-z-]+)"', re.search(r"PROXIED_PREFIXES = \[(.*?)\]", vite).group(1)))
    used = set(re.findall(r'[`"](/[a-z-]+)', client))
    assert used and used <= proxied, f"not proxied in vite.config.ts: {sorted(used - proxied)}"
