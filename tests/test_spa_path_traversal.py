"""The web-app file server must never hand out a file from outside the built web-app folder. CodeQL's path-injection check
found that an address with encoded dots (/%2e%2e/%2e%2e/pyproject.toml) climbed out of it (25 Nov 2026)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import main

# The catch-all routes exist only when a built web app was present at startup (CI's backend job may not have one), so the
# end-to-end tests run when it is, and the file-picking function is tested directly either way.
HAS_SPA = any(getattr(r, "path", "") == "/{full_path:path}" for r in main.app.routes)
needs_spa = pytest.mark.skipif(not HAS_SPA, reason="no built web app in this checkout")


@pytest.fixture()
def spa(tmp_path, monkeypatch):
    dist = tmp_path / "site" / "frontend" / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>THE APP</html>")
    (dist / "favicon.svg").write_text("<svg>icon</svg>")
    (tmp_path / "site" / "secret.txt").write_text("OUTSIDE THE FOLDER")           # two levels up from dist
    (tmp_path / "site" / "frontend" / "also-outside.txt").write_text("OUTSIDE TOO")  # one level up
    monkeypatch.setattr(main, "_SPA_DIR", dist)
    return dist


# Decoded forms of the same addresses: what the server sees after the web layer has decoded the dots.
ESCAPES = ["/../secret.txt", "/../../secret.txt", "/assets/../../../secret.txt", "/../also-outside.txt", "/../../%2e%2e/secret.txt",
           "../../secret.txt", "/..\\..\\secret.txt"]


@pytest.mark.parametrize("requested", ESCAPES)
def test_the_file_picker_refuses_anything_that_climbs_out(spa, requested):
    assert main._spa_file(requested) is None


def test_the_file_picker_returns_a_real_file_inside_and_nothing_for_a_missing_one(spa):
    assert main._spa_file("/favicon.svg") == (spa / "favicon.svg").resolve()
    assert main._spa_file("favicon.svg") == (spa / "favicon.svg").resolve()
    assert main._spa_file("/no-such-file.js") is None
    assert main._spa_file("/assets") is None            # a folder is not a file


@needs_spa
@pytest.mark.parametrize("path", [
    "/%2e%2e/secret.txt", "/%2e%2e/%2e%2e/secret.txt", "/..%2f..%2fsecret.txt", "/%252e%252e/%252e%252e/secret.txt",
    "/../../secret.txt", "/assets/../../../secret.txt", "/%2e%2e/also-outside.txt", "//%2e%2e/%2e%2e/secret.txt",
])
@pytest.mark.parametrize("accept", ["text/html", "*/*"])
def test_no_address_reaches_a_file_outside_the_web_app_folder(spa, path, accept):
    r = TestClient(main.app).get(path, headers={"accept": accept})
    assert "OUTSIDE" not in r.text


@needs_spa
def test_a_real_file_inside_the_folder_is_still_served(spa):
    c = TestClient(main.app)
    assert "icon" in c.get("/favicon.svg", headers={"accept": "*/*"}).text
    assert "icon" in c.get("/favicon.svg", headers={"accept": "text/html"}).text


@needs_spa
def test_an_unknown_page_still_gets_the_app_so_client_side_routes_work(spa):
    assert "THE APP" in TestClient(main.app).get("/policies", headers={"accept": "text/html"}).text


def test_a_link_inside_the_folder_that_points_outside_is_refused(spa):
    link = spa / "leak.txt"
    try:
        link.symlink_to(spa.parent.parent / "secret.txt")
    except (OSError, NotImplementedError):
        pytest.skip("this system does not allow symbolic links")
    assert main._spa_file("/leak.txt") is None
