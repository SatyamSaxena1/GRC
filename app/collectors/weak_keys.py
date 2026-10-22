"""Weak public keys in a client's certificates, found from the public certificate alone.

Why this exists: in October 2026 eight eMudhra intermediate CA certificates turned out to hold
private keys that were tiny numbers (4, 56, 115 ...), produced by a faulty key-ceremony script.
Anyone could recover them from the public certificates in under a second, yet two audit cycles
had passed over the paperwork. This collector checks the outcome instead of the process.

Read-only and metadata-only: it reads certificates (public by definition), never a private key.
Same contract as the change-control collectors: {"attributes": {...}} plus the per-certificate
"exceptions" rows behind the counts, served at DPDP_KEYS_COLLECTOR_URL. The rule that decides
what the counts mean lives in the content pack (ISO 27001 A.8.24), not here.

    python -m app.collectors.weak_keys certs/ more.pem --host example.com:443

What it can and cannot see (a proof of concept, deliberately cheap):
- EC keys: the public key equals k*G for a small scalar k (the eMudhra failure).
- RSA keys: shorter than 2048 bits, a modulus with a small prime factor, or a perfect square.
- Two certificates sharing one public key.
- With the optional `badkeys` package installed (`pip install badkeys && badkeys --update-bl`):
  ROCA, Fermat factoring, the blocklists of known-compromised keys and more. Without it the
  snapshot says so (`full_corpus_checked` is false) and the rule shows that as a gap, so a
  cheap check is never mistaken for the full one.
- `--host` follows each certificate's "CA Issuers" link to fetch the rest of the chain, since a
  TLS server hands over only its leaf here. Intermediates that no server ever presents (eMudhra's
  seven unused ones) must be supplied as files, e.g. from the CCADB list.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import math
import ssl
import sys
from pathlib import Path

import requests

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa

ATTRIBUTES = (
    "certificates_in_scope",
    "weak_ec_keys",
    "weak_rsa_keys",
    "short_rsa_keys",
    "duplicate_public_keys",
    "full_corpus_checked",
)

# eMudhra's recovered keys were 4..237. A key anyone can find by trying the first few thousand
# numbers is not a key. ponytail: ~0.3 s per EC certificate; raise it or switch to baby-step
# giant-step if a wider search is ever wanted.
SMALL_SCALARS = 4096
MIN_RSA_BITS = 2048
_SMALL_PRIMES = [p for p in range(2, 10_000) if all(p % q for q in range(2, int(p ** 0.5) + 1))]


def weakness(public_key) -> tuple[str, str] | None:
    """(attribute to count, why) for a weak public key, else None. The seam a fuller weak-key
    corpus plugs into."""
    if isinstance(public_key, ec.EllipticCurvePublicKey):
        target = public_key.public_numbers()
        for k in range(1, SMALL_SCALARS + 1):
            if ec.derive_private_key(k, public_key.curve).public_key().public_numbers() == target:
                return "weak_ec_keys", f"EC private key is the number {k}"
    elif isinstance(public_key, rsa.RSAPublicKey):
        n = public_key.public_numbers().n
        if n.bit_length() < MIN_RSA_BITS:
            return "short_rsa_keys", f"RSA modulus is only {n.bit_length()} bits"
        factor = next((p for p in _SMALL_PRIMES if n % p == 0), None)
        if factor:
            return "weak_rsa_keys", f"RSA modulus is divisible by {factor}"
        if math.isqrt(n) ** 2 == n:
            return "weak_rsa_keys", "RSA modulus is a perfect square"
    return None


def _corpus():
    """The optional badkeys module with its blocklist installed, else None."""
    try:
        return importlib.import_module("badkeys")
    except ImportError:
        return None


def _corpus_hits(corpus, cert: x509.Certificate) -> list[str]:
    try:
        return sorted(corpus.checkcrt(cert.public_bytes(serialization.Encoding.PEM).decode()).get("results", {}))
    except Exception:  # noqa: BLE001 - a key badkeys cannot parse is not evidence of a weak one
        return []


def summarize(certs: list[x509.Certificate]) -> dict:
    """Pure and deterministic: certificates in, attribute counts and the offending rows out."""
    corpus = _corpus()
    counts, exceptions = dict.fromkeys(ATTRIBUTES, 0), []
    counts["full_corpus_checked"] = corpus is not None
    by_fingerprint = {c.fingerprint(hashes.SHA256()).hex(): c for c in certs}  # the same cert twice is one
    first_with_key: dict[str, str] = {}
    for fingerprint, cert in sorted(by_fingerprint.items()):
        counts["certificates_in_scope"] += 1
        key = cert.public_key()
        key_id = hashlib.sha256(key.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)).hexdigest()
        reasons = []
        found = weakness(key)
        if corpus and (hits := _corpus_hits(corpus, cert)):
            kind = "weak_ec_keys" if isinstance(key, ec.EllipticCurvePublicKey) else "weak_rsa_keys"
            found = found or (kind, "")
            found = (found[0], "; ".join(filter(None, [found[1], "badkeys: " + ", ".join(hits)])))
        if found:
            counts[found[0]] += 1
            reasons.append(found[1])
        if key_id in first_with_key:
            counts["duplicate_public_keys"] += 1
            reasons.append(f"public key already used by certificate {first_with_key[key_id][:12]}")
        first_with_key.setdefault(key_id, fingerprint)
        if reasons:
            exceptions.append({"subject": cert.subject.rfc4514_string(), "sha256": fingerprint, "reason": "; ".join(reasons)})
    return {"attributes": counts, "exceptions": exceptions}


MAX_CHAIN = 5


def _served_leaf(name: str, port: int) -> x509.Certificate:
    return x509.load_pem_x509_certificate(ssl.get_server_certificate((name, port)).encode())


def _issuer_of(cert: x509.Certificate) -> x509.Certificate | None:
    """The certificate named by this one's "CA Issuers" link, if it has one and it can be fetched."""
    try:
        aia = cert.extensions.get_extension_for_class(x509.AuthorityInformationAccess).value
    except x509.ExtensionNotFound:
        return None
    for access in aia:
        if access.access_method == x509.AuthorityInformationAccessOID.CA_ISSUERS:
            try:
                body = requests.get(access.access_location.value, timeout=10).content
                return x509.load_der_x509_certificate(body) if not body.startswith(b"-----") else x509.load_pem_x509_certificate(body)
            except (requests.RequestException, ValueError):
                continue
    return None


def served_chain(host: str) -> list[x509.Certificate]:
    """The leaf a host serves plus every issuer reachable through CA Issuers links, root excluded
    when it is self-issued (a root is a trust anchor, not something the host's operator chose)."""
    name, _, port = host.partition(":")
    chain = [_served_leaf(name, int(port or 443))]
    while len(chain) < MAX_CHAIN and (issuer := _issuer_of(chain[-1])) is not None and issuer.subject != issuer.issuer:
        chain.append(issuer)
    return chain


def load_certs(paths: list[str], hosts: list[str] = ()) -> list[x509.Certificate]:
    """PEM or DER files, directories of them, and the chain each TLS host serves."""
    files = [f for p in map(Path, paths) for f in (sorted(p.rglob("*")) if p.is_dir() else [p]) if f.is_file()]
    certs = []
    for f in files:
        data = f.read_bytes()
        try:
            certs += x509.load_pem_x509_certificates(data)
        except ValueError:
            try:
                certs.append(x509.load_der_x509_certificate(data))
            except ValueError:
                continue  # not a certificate: a directory of mixed files is fine
    for host in hosts:
        certs += served_chain(host)
    return certs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.collectors.weak_keys", description=__doc__.splitlines()[0])
    parser.add_argument("paths", nargs="*", help="certificate files or directories (PEM or DER)")
    parser.add_argument("--host", action="append", default=[], help="host[:port] whose served certificate to check")
    args = parser.parse_args(argv)
    if not args.paths and not args.host:
        parser.error("give a certificate path or --host")
    json.dump(summarize(load_certs(args.paths, args.host)), sys.stdout, indent=2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
