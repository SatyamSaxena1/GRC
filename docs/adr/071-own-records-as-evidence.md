# ADR-071: Duties our own records can prove are fixed rules over those records

**Status:** Accepted (DPDP Phase 3b, 26 Nov 2026)

## Context
The widened DPDP pack (Phase 1) listed ten duties as attestation-only although the product already keeps the proof: the
rights-request log, vendor register, training module, policy library, breach log and audit log. A person's statement is
weaker than a count the product can make itself, and asking for an upload of something we already hold is pointless.

## Decision
A built-in connector source, `platform` (`app/collectors/own_records.py`), reads those records and stores one ordinary
snapshot (`PLATFORM_RECORDS_SNAPSHOT`) through the same path as every other connector: stored, hashed, versioned, collection
run recorded, judged by the same engine. Seven clauses and one new clause ("Rule 7 - in practice", breaches reported on time)
become fixed rules over its facts. A snapshot counts for 14 days.

- Every attribute is always returned. The value is **None when there is nothing to judge** (no request ever logged, no vendor
  that handles personal data). The engine reads None as "not found", never as zero, so an empty record can never pass. The
  organisation can still mark the duty not applicable (Phase 1) with a reason.
- Labels stay honest: PASS only where a rule decided, from records the product holds. The audit-trail rule shows that the
  chain verifies end to end, which proves the events are intact, not that every action was recorded.
- Three clauses stay attestation-only because no record we keep can prove them: "every duty has live evidence" (the
  readiness record would judge itself), "every incident has a record of how it was fixed" (the breach log has no field for
  that), and "someone can answer the Board" (a record cannot show a person is able to act).
- The scheduled sync runs the source only for organisations that subscribe to DPDP.

## Consequences
- Scored lines rise from 70 to 71 (the new breach clause). Seven lines move from "attested" to "passed or failed by a rule".
- Follow-ups: a resolution note on a breach would let the incident duty become a rule; the Connections page lists the source
  with a collect button like the others.
