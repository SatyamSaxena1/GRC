# ADR-043: Vendor reports back the attestation

Status: accepted

## Context
The vendor tier (ADR-042) gives one point for "personal or sensitive data with no attestation on file", but
the attestation was a tick box: anyone could tick it, and nothing showed what it rested on or when it ran out.
A SOC 2 report is only worth anything while it is current.

## Decision
- **A report is a record of its own** (`vendor_reports`, additive migration, row level security from the start),
  stored through the same storage layer as evidence and checked by the same upload gate (extension, size,
  content against extension, hashing, malware-scan hook). It is deliberately not an Evidence row: it does not
  appear in the Evidence list or move its counts, and is never read by the extraction pipeline.
- **The uploader states when it stops being valid** (the report's period end plus a year for a SOC 2, or the
  certificate's expiry for ISO 27001), with the type: SOC 2 Type II, SOC 2 Type I, ISO 27001, or other.
- **A fixed rule decides whether it counts** (`vendors.attests`): a SOC 2 or ISO 27001 report counts while its
  valid-until date has not passed. An "other" document, and any report past its date, stay on the record and do
  not count. The effective attestation is a current report first, the old manual tick second, otherwise none,
  and the tier and review use it. Expiry changes the tier with no one editing anything.
- **Immutable, like evidence.** No update and no delete. The same bytes cannot be attached twice to a vendor.
- **Download only.** A vendor's document is untrusted content: it is always served as an attachment, never
  rendered, with `nosniff` and no caching.
- **Audited with the hash, never the content**: type, valid-until, size, sha256 and whether it counts.
- Writes need an organisation admin; a compliance viewer can read and download. Another organisation's vendor
  or file is a 404.

## Consequences
- The page no longer offers the "attestation on file" toggle, so the report is the way to evidence one. The API
  still accepts the manual flag (existing vendors, and the add form's tick box) and labels it "ticked by hand".
- The valid-until date is the uploader's statement. The platform checks it has not passed; it does not read the
  report to confirm the date.
- A wrongly attached file cannot be removed. The mitigation is the attached note in the audit trail and attaching
  the right one; deletion would break the immutability the rest of the product relies on.
