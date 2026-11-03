"""scripts/smoke_live.py decides pass or fail from what a server answers; test that offline."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import requests

spec = importlib.util.spec_from_file_location("smoke_live", Path(__file__).resolve().parent.parent / "scripts" / "smoke_live.py")
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)


class Resp:
    def __init__(self, status=200, body=None, text=""):
        self.status_code, self._body, self.text = status, body, text

    def json(self):
        if self._body is None:
            raise ValueError("not json")
        return self._body


def server(ready=True, db="ok", routes=smoke.REQUIRED_ROUTES, root=True):
    def get(url, timeout=None):
        if url.endswith("/health/ready"):
            return Resp(200 if ready else 503, {"ready": ready, "checks": {"database": db, "model": "unavailable", "model_name": "m"}})
        if url.endswith("/login"):
            return Resp(200, text='<div id="root"></div>' if root else "<html></html>")
        return Resp(200, {"paths": {r: {} for r in routes}})
    return get


def test_a_healthy_current_deploy_passes_every_check():
    results = smoke.check("https://x.test/", get=server())
    assert [n for n, *_ in results] == ["health/ready", "web app", "api routes"]
    assert all(ok for _, ok, _ in results)


def test_each_kind_of_breakage_is_reported_by_name():
    assert not dict((n, ok) for n, ok, _ in smoke.check("https://x", get=server(ready=False)))["health/ready"]
    assert not dict((n, ok) for n, ok, _ in smoke.check("https://x", get=server(db="down")))["health/ready"]
    assert not dict((n, ok) for n, ok, _ in smoke.check("https://x", get=server(root=False)))["web app"]
    old = [r for r in smoke.REQUIRED_ROUTES if r != "/findings"]
    (name, ok, detail), = [c for c in smoke.check("https://x", get=server(routes=old)) if c[0] == "api routes"]
    assert not ok and "/findings" in detail


def test_an_unreachable_host_fails_instead_of_raising():
    def down(url, timeout=None):
        raise requests.ConnectionError("no route")
    results = smoke.check("https://x", get=down)
    assert results and not any(ok for _, ok, _ in results)
    assert smoke.main(["--url", "http://127.0.0.1:9"]) == 1
