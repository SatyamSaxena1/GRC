"""The email client (ADR-052): any SMTP server the operator configures; off by default; never logs or returns a body, a
password or a full address; and the invite link is emailed so the admin never handles it."""

from __future__ import annotations

import json

import pytest
from sqlalchemy.orm import Session

from app import auth0_admin, db as db_module, mailer, welcome
from app.models import AuditEvent

LINK = "https://tenant.example.auth0.com/lo/reset?ticket=SECRETLINK123"


class FakeSMTP:
    """Stands in for smtplib.SMTP / SMTP_SSL; records what the client did."""
    instances: list["FakeSMTP"] = []
    fail_on: str | None = None

    def __init__(self, host, port, timeout=None, context=None):
        self.host, self.port, self.timeout, self.context = host, port, timeout, context
        self.tls = self.logged_in = None
        self.sent = []
        FakeSMTP.instances.append(self)
        if FakeSMTP.fail_on == "connect":
            raise ConnectionRefusedError("refused by 10.0.0.5 for secret@example.com")

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self, context=None):
        self.tls = True

    def login(self, user, password):
        if FakeSMTP.fail_on == "login":
            raise Exception(f"535 bad credentials for {user}")
        self.logged_in = (user, password)

    def send_message(self, message):
        self.sent.append(message)


@pytest.fixture()
def smtp(monkeypatch):
    FakeSMTP.instances, FakeSMTP.fail_on = [], None
    monkeypatch.setattr(mailer.smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(mailer.smtplib, "SMTP_SSL", FakeSMTP)
    monkeypatch.setenv("SMTP_HOST", "mail.example.test")
    monkeypatch.setenv("SMTP_FROM", "GRC <no-reply@example.test>")
    monkeypatch.setenv("SMTP_USERNAME", "grc")
    monkeypatch.setenv("SMTP_PASSWORD", "SMTP-PASSWORD-VALUE")
    for k in ("SMTP_PORT", "SMTP_SECURITY"):
        monkeypatch.delenv(k, raising=False)
    return FakeSMTP


# --- the client -------------------------------------------------------------------------------------------------------
def test_off_until_host_and_sender_are_set(monkeypatch):
    for k in ("SMTP_HOST", "SMTP_FROM"):
        monkeypatch.delenv(k, raising=False)
    assert not mailer.enabled()
    assert mailer.send("a@example.com", "s", "b") == (False, "email is not set up on this server")
    monkeypatch.setenv("SMTP_HOST", "h")
    assert not mailer.enabled()                                   # a sender is also required


def test_a_message_is_sent_with_starttls_and_login_by_default(smtp):
    assert mailer.send("person@example.com", "Hello", "Body text") == (True, "")
    s = smtp.instances[0]
    assert (s.host, s.port, s.tls, s.logged_in) == ("mail.example.test", 587, True, ("grc", "SMTP-PASSWORD-VALUE"))
    m = s.sent[0]
    assert m["To"] == "person@example.com" and m["From"] == "GRC <no-reply@example.test>" and m["Subject"] == "Hello"
    assert "Body text" in m.get_content()


def test_ssl_and_plain_modes_and_a_custom_port(smtp, monkeypatch):
    monkeypatch.setenv("SMTP_SECURITY", "ssl")
    monkeypatch.setenv("SMTP_PORT", "465")
    assert mailer.send("p@example.com", "s", "b")[0] and smtp.instances[-1].port == 465 and smtp.instances[-1].tls is None
    monkeypatch.setenv("SMTP_SECURITY", "none")
    monkeypatch.delenv("SMTP_USERNAME")
    assert mailer.send("p@example.com", "s", "b")[0] and smtp.instances[-1].logged_in is None


@pytest.mark.parametrize("bad", ["", "no-at-sign", "a@b", "a b@example.com", "a@example.com\r\nBcc: x@evil.test",
                                 "<a@example.com>", "a@example.com,b@example.com", "x" * 300 + "@example.com"])
def test_anything_but_one_plain_address_is_refused_before_connecting(smtp, bad):
    ok, reason = mailer.send(bad, "s", "b")
    assert not ok and "address" in reason and smtp.instances == []


def test_a_newline_in_the_subject_cannot_inject_a_header(smtp):
    mailer.send("p@example.com", "Hi\r\nBcc: evil@example.test", "b")
    m = smtp.instances[0].sent[0]
    assert m["Bcc"] is None and "\n" not in m["Subject"]


@pytest.mark.parametrize("mode", ["connect", "login"])
def test_a_failure_returns_only_an_error_class_never_the_server_message(smtp, mode):
    smtp.fail_on = mode
    ok, reason = mailer.send("person@example.com", "s", "b")
    assert not ok and reason.startswith("could not send (") and "@" not in reason and "10.0.0.5" not in reason


# --- the invite ------------------------------------------------------------------------------------------------------
class FakeAuth0:
    def __call__(self, method, url, json=None, params=None, timeout=None, allow_redirects=True, headers=None):
        path = url.split("/api/v2", 1)[1] if "/api/v2" in url else url

        class R:
            def __init__(s, code, body=None):
                s.status_code, s._b, s.content = code, body, b"x" if body is not None else b""

            def json(s):
                return s._b

        if url.endswith("/oauth/token"):
            return R(200, {"access_token": "tok", "expires_in": 3600})
        if path == "/users-by-email":
            return R(200, [])
        if path == "/users":
            return R(200, {"user_id": "auth0|1", "email": json["email"]})
        if path == "/tickets/password-change":
            return R(201, {"ticket": LINK})
        return R(404, {})


@pytest.fixture()
def auth0(monkeypatch):
    monkeypatch.setenv("AUTH0_DOMAIN", "tenant.example.auth0.com")
    monkeypatch.setenv("AUTH0_M2M_CLIENT_ID", "cid")
    monkeypatch.setenv("AUTH0_M2M_CLIENT_SECRET", "SECRETVALUE")
    monkeypatch.setattr(auth0_admin.requests, "request", FakeAuth0())
    auth0_admin._cache.update(token="", until=0.0)


def _invite(client, org):
    return client.post("/admin/users", json={"email": "new.person@example.com", "org_id": org, "role": "COMPLIANCE_VIEWER"})


def _org(client):
    return client.post("/admin/organizations", json={"name": "Acme", "frameworks": ["SOC-2"]}).json()["id"]


def test_the_link_is_emailed_to_the_person_and_the_admin_never_gets_it(client, auth0, smtp):
    r = _invite(client, _org(client))
    assert r.status_code == 200 and r.json()["emailed"] is True and "password_link" not in r.json()
    assert "SECRETLINK123" not in r.text and r.headers["cache-control"] == "no-store"
    m = smtp.instances[0].sent[0]
    assert m["To"] == "new.person@example.com" and LINK in m.get_content()
    with Session(db_module.engine) as s:
        stored = json.dumps([(e.detail, e.reason) for e in s.query(AuditEvent)], default=str)
        assert "SECRETLINK123" not in stored                          # the link is never kept anywhere


def test_if_the_email_fails_the_link_is_returned_so_the_invite_is_not_lost(client, auth0, smtp):
    smtp.fail_on = "connect"
    r = _invite(client, _org(client))
    assert r.status_code == 200 and r.json()["password_link"] == LINK
    assert r.json()["email_error"].startswith("could not send (") and "emailed" not in r.json()


def test_without_email_set_up_the_link_is_returned_as_before(client, auth0, monkeypatch):
    for k in ("SMTP_HOST", "SMTP_FROM"):
        monkeypatch.delenv(k, raising=False)
    r = _invite(client, _org(client))
    assert r.json()["password_link"] == LINK and "emailed" not in r.json() and "email_error" not in r.json()


def test_without_a_login_service_the_welcome_email_still_goes_but_has_no_link(client, smtp, monkeypatch):
    for k in ("AUTH0_DOMAIN", "AUTH0_M2M_CLIENT_ID", "AUTH0_M2M_CLIENT_SECRET"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("NOTIFY_LINK_BASE_URL", "https://grc.example.test")
    r = _invite(client, _org(client))
    assert r.status_code == 200 and r.json()["emailed"] is True and "password_link" not in r.json()
    body = smtp.instances[0].sent[0].get_content()
    assert "https://grc.example.test" in body and "one-time link" not in body


# --- the welcome email: personalised, once, and a way to reach a person ---------------------------------------------
@pytest.mark.parametrize("role,expect", [
    ("ORG_ADMIN", "Connections"), ("CONTROL_OWNER", "Tasks"), ("COMPLIANCE_VIEWER", "read-only"),
    ("FIRM_ADMIN", "engagement"), ("AUDITOR", "verdict"),
])
def test_each_role_gets_its_own_first_steps(role, expect):
    subject, text = welcome.compose(role, "Acme Ltd", "https://x.test/link")
    assert "Acme Ltd" in text and expect in text and "https://x.test/link" in text and "Reply to this email" in text
    assert "\n  1. " in text and subject.startswith("Welcome")


def test_an_unknown_role_still_gets_a_safe_generic_welcome():
    _, text = welcome.compose("SOMETHING_NEW")
    assert "Sign in and open Overview" in text


def test_the_email_names_the_organisation_and_asks_replies_to_go_to_the_support_mailbox(client, auth0, smtp, monkeypatch):
    monkeypatch.setenv("SMTP_SUPPORT_REPLY_TO", "support@example.test")
    r = _invite(client, _org(client))
    m = smtp.instances[0].sent[0]
    assert r.json()["emailed"] is True and "Acme" in m.get_content() and m["Reply-To"] == "support@example.test"


def test_a_bad_reply_to_setting_stops_the_send_rather_than_sending_a_malformed_header(smtp, monkeypatch):
    monkeypatch.setenv("SMTP_SUPPORT_REPLY_TO", "not an address\r\nBcc: x@evil.test")
    ok, reason = mailer.send("p@example.com", "s", "b")
    assert not ok and "reply-to" in reason and smtp.instances == []


def test_one_welcome_per_sign_up_and_no_email_for_a_refused_invite(client, auth0, smtp):
    org = _org(client)
    assert _invite(client, org).status_code == 200 and len(smtp.instances) == 1
    assert _invite(client, org).status_code == 409                    # already invited: refused, nothing sent again
    assert len(smtp.instances) == 1
