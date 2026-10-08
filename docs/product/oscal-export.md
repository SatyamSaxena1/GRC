# OSCAL export

`GET /export/oscal/assessment-results.json?framework=SOC-2` (the **OSCAL (JSON)** menu on the
Overview page) returns one framework's current results for the organisation as an
[OSCAL](https://pages.nist.gov/OSCAL/) **assessment-results** document, version **1.2.3**, that
other GRC tools can import.

## Mapping

| GRC | OSCAL |
|---|---|
| Clause | `control-id` token `<framework>_<clause>`, lowercased (`pci-dss_6.5.1`, `soc-2_cc8.1`); the original clause is a prop. These are GRC tokens, not ids from a NIST catalog |
| Current evidence × clause | `observation`: method `TEST` for connector snapshots, `EXAMINE` for documents; props carry the verdict, the engine's verdict, the auditor's verdict, lock state and the ADR-022 rule and evaluation hashes |
| Evidence file | `back-matter` resource whose `rlinks.hashes` hold its SHA-256 |
| Control verdict | `finding` with target `objective-id`, state `satisfied` (PASS) or `not-satisfied` |
| Open gap | `risk`: `open`; `deviation-requested` while an exception is requested; `deviation-approved` with `deadline` = the exception's expiry while one is active (ADR-021) |
| Engagement | `back-matter` resource that `import-ap` points to (there is no separate OSCAL assessment plan) |
| Pack in force | metadata props: framework edition, pack hash, engine version |

Every GRC-specific prop carries `ns: https://github.com/SatyamSaxena1/GRC/ns/oscal`.

## Guarantees
- **Deterministic.** UUIDs are derived from natural keys, and `last-modified` is the latest
  timestamp in the data, not the time of export. The same state gives byte-identical files.
- **Traceable.** The response's `X-Content-SHA256` header is the file's hash, and an
  `EXPORT_GENERATED` audit event records it, so a file someone hands you can be matched to an
  export in the audit trail.
- **Valid.** `tests/test_oscal_export.py` validates against NIST's published JSON schema
  (vendored in `tests/fixtures/oscal/`, pinned by hash). NIST writes one pattern with
  ECMAScript `\p{…}` classes, which Python cannot compile; the test swaps in a stricter ASCII
  equivalent, so passing it implies passing the original.
- **Same access as the other exports.** Built from the same control and gap sweeps, so it adds
  no authorization rule.

## Not included
Superseded evidence versions, tasks, and OSCAL assessment plans, SSPs or POA&Ms.
