# ADR-029: Check the keys, not the paperwork: a weak-key collector

> **Status:** Proposed. A first slice is implemented: `app/collectors/weak_keys.py`, the `keys`
> connector source, UCO-CRY-001 and ISO 27001 A.8.24 (`tests/test_weak_keys.py`).

## Context
In October 2026 eight eMudhra intermediate CA certificates were found to hold private keys that
were tiny numbers (4, 56, 115 ...). A faulty step in a key ceremony in April 2025 had produced a
second, weak set of keys next to the strong ones, and the weak ones were the ones certified. Anyone
could recover them from the public certificates in under a second. The flaw survived about 17
months and two independent audit cycles, because audits read the ceremony's paperwork and the
outcome was never looked at.

Our product would not have prevented this: we do not generate keys, and a CA's key ceremony belongs
to WebTrust and the CA/Browser Forum, not to SOC 2, ISO 27001 or PCI DSS. But it exposed a gap in
what we cover. Cryptography was policy-level only: an `ENCRYPTION_POLICY` document with two yes/no
facts. The ISO 27001 pack had no cryptography clause at all.

## Decision
- **Check the outcome from public data.** A collector reads certificates (public by definition,
  never a private key) and counts weak public keys: an EC key that is a small multiple of the
  generator, an RSA key under 2048 bits or with a small factor, and a public key shared by two
  certificates. It follows the collector contract of ADR-020: `{"attributes", "exceptions"}`,
  served at `DPDP_KEYS_COLLECTOR_URL`. The rule that decides what the counts mean stays in the
  content pack, so no model decides anything (ADR-004).
- **The cheap check is not the full check, and says so.** The built-in checks cover the eMudhra
  failure. The optional `badkeys` package (`pip install .[keys]`, then `badkeys --update-bl`) adds
  ROCA, Fermat factoring, blocklists of known-compromised keys and more. Because the connector
  keeps only `attributes` and `exceptions`, whether the corpus ran is an attribute,
  `full_corpus_checked`, and the A.8.24 rule shows `false` as a gap. A snapshot made without it is
  never mistaken for one made with it. We chose an optional dependency over a hard one: the
  blocklist is large and best run in the client's own pipeline, as the change-control collector is.
- **Whole chain, not just the leaf.** `--host` follows each certificate's "CA Issuers" link
  to fetch its issuers (up to 5), excluding a self-issued root, which is a trust anchor and not the
  host operator's choice. An intermediate that no server ever presents, like seven of eMudhra's
  eight, can only be checked from a file, for example from the CCADB list.
- **Evidence, never proof.** A.8.24 asks for far more than key strength, so the mapping is
  `SUPPORTING`. A guessable key opens a gap on the clause. A clean snapshot alone never proves it
  (the verdict stays PARTIAL), and the snapshot type is whole-estate, so a clean host cannot hide
  a failing one.

## Consequences
- **It would have found eMudhra's keys.** Given the certificates, it flags keys 4, 56 and 115 in
  well under a second. It does not find a weak key that is not in a certificate it was given.
- **Not a certificate inventory.** Someone has to say which hosts and files to check. Scheduling it
  (`monitor.yml`, scoped to named organisations like the GitHub job) and a key-health view are
  follow-ups that need a customer with certificates to monitor.
- **Not yet in PCI DSS or SOC 2.** PCI DSS 3.6/3.7 key management and SOC 2 clauses would map the
  same evidence; ISO 27001 was added first because it had no cryptography clause at all.
- **The EC search is bounded.** It tries the first 4096 scalars (about 0.3 s per certificate). A
  wider search should use baby-step giant-step rather than a longer loop.
