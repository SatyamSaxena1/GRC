"""The weak-key collector finds the eMudhra failure (a private key that is a tiny number) from the
public certificate alone, and the ISO 27001 A.8.24 rule turns the counts into a verdict."""

from __future__ import annotations

import datetime as dt
import json
import types

import pytest

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from cryptography.x509.oid import NameOID

from app.collectors import weak_keys
from app.content.load import load as load_content
from app.evaluate import evaluate
from app.routers import connectors

SIGNER = ec.generate_private_key(ec.SECP256R1())  # signs every test certificate; the *subject* key is what is under test


def cert_for(public_key, name="leaf.example", issuer=None, issuer_url=None) -> x509.Certificate:
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)])
    now = dt.datetime(2026, 10, 1, tzinfo=dt.timezone.utc)
    builder = (x509.CertificateBuilder().subject_name(subject).public_key(public_key)
               .issuer_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, issuer)]) if issuer else subject)
               .serial_number(x509.random_serial_number()).not_valid_before(now).not_valid_after(now + dt.timedelta(days=90)))
    if issuer_url:
        link = x509.AccessDescription(x509.AuthorityInformationAccessOID.CA_ISSUERS, x509.UniformResourceIdentifier(issuer_url))
        builder = builder.add_extension(x509.AuthorityInformationAccess([link]), critical=False)
    return builder.sign(SIGNER, hashes.SHA256())


@pytest.fixture(autouse=True)
def no_corpus(monkeypatch):
    """Tests do not depend on whether badkeys happens to be installed; one test uses the real one."""
    monkeypatch.setattr(weak_keys, "_corpus", lambda: None)


def with_corpus(monkeypatch, hits=None):
    """A stand-in badkeys that reports `hits` for every certificate (None = clean)."""
    fake = types.SimpleNamespace(checkcrt=lambda pem: {"results": hits or {}})
    monkeypatch.setattr(weak_keys, "_corpus", lambda: fake)


def ec_public(scalar: int, curve=ec.SECP384R1):
    return ec.derive_private_key(scalar, curve()).public_key()


def test_tiny_ec_private_key_is_found_like_the_emudhra_keys():
    out = weak_keys.summarize([cert_for(ec_public(4), "intermediate-a"), cert_for(ec_public(237), "intermediate-b")])
    assert out["attributes"]["weak_ec_keys"] == 2
    assert {e["reason"] for e in out["exceptions"]} == {"EC private key is the number 4", "EC private key is the number 237"}


def test_a_properly_random_ec_key_is_clean():
    out = weak_keys.summarize([cert_for(ec.generate_private_key(ec.SECP384R1()).public_key())])
    assert out == {"attributes": {"certificates_in_scope": 1, "weak_ec_keys": 0, "weak_rsa_keys": 0, "short_rsa_keys": 0,
                                  "duplicate_public_keys": 0, "full_corpus_checked": False}, "exceptions": []}


def test_rsa_weaknesses_are_told_apart():
    short = rsa.generate_private_key(65537, 1024).public_key()
    strong = rsa.generate_private_key(65537, 2048).public_key()
    small_factor = rsa.RSAPublicNumbers(65537, 3 * (2 ** 2100 + 1)).public_key()  # 3 divides it; no private key needed
    out = weak_keys.summarize([cert_for(short, "a"), cert_for(strong, "b"), cert_for(small_factor, "c")])
    assert (out["attributes"]["short_rsa_keys"], out["attributes"]["weak_rsa_keys"], out["attributes"]["certificates_in_scope"]) == (1, 1, 3)


def test_shared_public_key_is_flagged_once_and_the_same_certificate_twice_is_not_a_duplicate():
    key = ec.generate_private_key(ec.SECP256R1()).public_key()
    a, b = cert_for(key, "a"), cert_for(key, "b")
    assert weak_keys.summarize([a, b])["attributes"]["duplicate_public_keys"] == 1
    assert weak_keys.summarize([a, a])["attributes"]["duplicate_public_keys"] == 0


def a824(attributes: dict):
    return next(l for l in evaluate(attributes, "KEY_HEALTH_SNAPSHOT", ["ISO-27001"], load_content()) if l.clause == "A.8.24")


def test_a_guessable_key_opens_a_gap_and_a_clean_snapshot_alone_never_proves_the_clause(monkeypatch):
    with_corpus(monkeypatch)
    clean = a824(weak_keys.summarize([cert_for(ec.generate_private_key(ec.SECP384R1()).public_key())])["attributes"])
    weak = a824(weak_keys.summarize([cert_for(ec_public(4))])["attributes"])
    assert [g.attribute for g in weak.gaps] == ["weak_ec_keys"]
    assert clean.gaps == () and clean.verdict == "PARTIAL"  # SUPPORTING evidence only, by design


def test_a_snapshot_made_without_the_full_corpus_says_so_as_a_gap():
    clean = a824(weak_keys.summarize([cert_for(ec.generate_private_key(ec.SECP384R1()).public_key())])["attributes"])
    assert [g.attribute for g in clean.gaps] == ["full_corpus_checked"]


def test_the_corpus_adds_findings_the_builtin_checks_cannot_see(monkeypatch):
    with_corpus(monkeypatch, {"roca": {"detected": True}})
    out = weak_keys.summarize([cert_for(rsa.generate_private_key(65537, 2048).public_key())])
    assert out["attributes"]["weak_rsa_keys"] == 1 and out["attributes"]["full_corpus_checked"] is True
    assert out["exceptions"][0]["reason"] == "badkeys: roca"


def test_the_real_badkeys_catches_a_small_factor_and_passes_a_random_key():
    badkeys = pytest.importorskip("badkeys")
    hits = lambda c: weak_keys._corpus_hits(badkeys, c)
    assert hits(cert_for(ec.generate_private_key(ec.SECP384R1()).public_key())) == []
    assert hits(cert_for(rsa.RSAPublicNumbers(65537, 3 * (2 ** 2100 + 1)).public_key())) == ["smallfactors"]
    assert hits(cert_for(ec_public(4))) == ["blocklist"]  # the eMudhra-style key, from badkeys' own blocklist


def test_a_host_is_checked_along_its_whole_chain_not_just_the_leaf(monkeypatch):
    root = cert_for(ec.generate_private_key(ec.SECP256R1()).public_key(), "root")
    inter = cert_for(ec_public(4), "intermediate", issuer="root", issuer_url="http://ca.test/root.der")
    leaf = cert_for(ec.generate_private_key(ec.SECP256R1()).public_key(), "leaf", issuer="intermediate", issuer_url="http://ca.test/inter.der")
    served = {"http://ca.test/inter.der": inter, "http://ca.test/root.der": root}
    monkeypatch.setattr(weak_keys, "_served_leaf", lambda name, port: leaf)
    monkeypatch.setattr(weak_keys.requests, "get", lambda url, timeout: types.SimpleNamespace(
        content=served[url].public_bytes(serialization.Encoding.DER)))
    chain = weak_keys.served_chain("example.test")
    assert [c.subject.rfc4514_string() for c in chain] == ["CN=leaf", "CN=intermediate"]  # a self-issued root is a trust anchor, left out
    assert weak_keys.summarize(chain)["attributes"]["weak_ec_keys"] == 1


def test_it_is_a_registered_connector_source_and_the_cli_prints_the_collector_contract(tmp_path, capsys):
    assert connectors.SOURCES["keys"][1] == "KEY_HEALTH_SNAPSHOT"
    (tmp_path / "weak.pem").write_bytes(cert_for(ec_public(56)).public_bytes(serialization.Encoding.PEM))
    (tmp_path / "notes.txt").write_text("not a certificate")
    assert weak_keys.main([str(tmp_path)]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["attributes"]["weak_ec_keys"] == 1 and set(printed["attributes"]) == set(weak_keys.ATTRIBUTES)
