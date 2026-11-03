# ADR-042: A vendor register with a rule-decided risk tier

Status: accepted

## Context
Competing compliance tools track the third parties an organisation depends on. This product had nowhere to
record a vendor, say how risky it is, or tell anyone a review is overdue. A model-assigned score would break
the rule the rest of the product follows: fixed rules decide, a human signs (ADR-004).

## Decision
A `vendors` table (additive migration, row level security from the start, like findings) and
`/vendors` endpoints, readable by an organisation admin or compliance viewer and writable only by an
organisation admin.

**The tier is points, from stated rules** (`app/vendors.py`):

| Input | Points |
|---|---|
| Data they can reach: none, internal, personal, sensitive | 0, 1, 2, 3 |
| How much the business depends on them: low, medium, high | 0, 1, 2 |
| Reaches personal or sensitive data with no SOC 2 or ISO 27001 report on file | +1 |

Five or more is HIGH, three or four is MEDIUM, otherwise LOW. These thresholds are our own baseline, shown on
the page beside each tier so the working is never hidden.

**The tier sets the review cadence**: HIGH every 90 days, MEDIUM 180, LOW 365. Review status is derived at read
time, never stored: never reviewed, overdue, due soon (within 30 days), current, or offboarded.

**Reviews carry a reason.** Recording one needs a note of at least three words saying what was checked; the
note is the reason on the audit event. Adding, changing, offboarding and reviewing a vendor are each audited,
with before and after state for changes, and a change that alters nothing writes nothing.

An owner, if set, must be a user of the same organisation.

## Consequences
- A tier can move when an input changes (an attestation arrives, data access widens); the change is in the
  audit trail with before and after.
- The register records that a review happened and what was checked. It does not hold the vendor's reports;
  uploading them as evidence is the next step and not part of this change.
- Overdue vendor reviews are shown on the Vendors page. They are not yet in the weekly report or the daily
  attention list.
