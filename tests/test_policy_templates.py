"""Policy templates (ADR-038): every figure a template states must satisfy every framework's condition,
using the same checker the platform applies to a real document."""

from __future__ import annotations

import pytest

from app import evaluate
from app.routers import templates

AUTH = lambda org: {"authorization": f"org:{org}"}  # noqa: E731


@pytest.mark.parametrize("template_id", list(templates.TEMPLATES))
def test_every_stated_value_meets_every_frameworks_condition(template_id):
    _, stated = templates.render(template_id)
    assert stated
    for attribute, value in stated.items():
        for condition in templates.conditions(attribute):
            assert evaluate.check(condition, value), (template_id, attribute, condition, value)


@pytest.mark.parametrize("template_id", list(templates.TEMPLATES))
def test_the_text_states_the_figures_and_leaves_dates_blank(template_id):
    body, stated = templates.render(template_id)
    for value in stated.values():
        for item in (value if isinstance(value, list) else [value]):
            if not isinstance(item, bool):
                assert str(item) in body, (template_id, item)
    assert "[date]" in body and "Approved by (role)" in body


def test_the_numbers_are_the_strictest_the_packs_ask_for():
    lengths = [c.value for c in templates.conditions("password_min_length")]
    assert templates.strictest("password_min_length") == max(lengths) >= 12   # ISO 8, SOC 2 and PCI 12, at least one more
    assert templates.strictest("access_review_frequency_days") <= 183          # PCI allows at most 183
    assert set(templates.strictest("mfa_required_for")) == {"remote access", "administrative access"}


def test_the_endpoints_serve_the_list_and_the_text(client, bootstrap):
    org_id, _ = bootstrap(client)
    listing = client.get("/templates", headers=AUTH(org_id))
    assert listing.status_code == 200
    assert {t["id"] for t in listing.json()} == set(templates.TEMPLATES)

    text = client.get("/templates/password-and-mfa", headers=AUTH(org_id))
    assert text.status_code == 200 and text.headers["content-type"].startswith("text/plain")
    assert f"at least {templates.strictest('password_min_length')} characters" in text.text
    assert client.get("/templates/nope", headers=AUTH(org_id)).status_code == 404


def test_templates_need_a_signed_in_caller(client):
    assert client.get("/templates").status_code in (401, 422)
