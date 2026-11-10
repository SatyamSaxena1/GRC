# ADR-054: Plans and limits, set by hand, with no payment code

**Status:** Accepted
**Date:** 2026-11-10
**Deciders:** Platform owner

## Context
GRC is sold person to person to Indian SaaS and fintech startups. The product needs to say what a customer has bought
(how many frameworks, how many people) and what happens when a trial ends, but it does not need to take money: invoices
and payment are handled outside the product.

## Decision
- An organisation has `plan` (TRIAL, DPDP_STARTER, GROWTH, SCALE), `trial_ends_at`, `frameworks_limit` and `seats_limit`.
  Defaults per plan live in `app/entitlements.py`; the operator can override either number for one organisation.
- **All four columns are nullable and nothing is backfilled.** An organisation with no plan (every existing one) has no
  limits. Limits start to apply to a row only when an operator gives it a plan, so the code ships before any behaviour
  change and no migration can lock anyone out.
- The server answers three questions in one module: may it subscribe another framework, may it add another seat, is its
  trial over. Seats are active organisation-side users; firm staff are not counted. Refusals are `402`, written through
  `authorization.deny` so each is audited.
- **An ended trial is read-only.** Every non-read request by a signed-in caller of that organisation is refused
  (in `current_actor` and `admin_or_actor`); reads, exports and the audit trail keep working and nothing is deleted.
  Moving to a plan reopens it at once.
- Lowering a plan never removes frameworks or people already over the new limit; it only stops further additions.
  Reactivating a deactivated person takes a seat again, so deactivate-and-reactivate is not a way round the limit.
- Only the operator (the shared admin key, as for the other bootstrap routes) sets plans: `GET /admin/organizations`,
  `PUT /admin/organizations/{id}/plan`, and an unlinked `/operator` page that holds the key in memory only. An org admin
  sees a read-only usage panel on Admin (`GET /admin/usage`) and can subscribe a framework (`POST /admin/frameworks`).
- An organisation created by approving an onboarding request starts on a 14 day TRIAL. Organisations made through the
  operator bootstrap route stay unplanned until an operator sets one.

## Consequences
**Good:** limits are enforced where data changes, not in the screen; no payment surface to secure; reversible by one call.
**Cost:** plan changes are manual and sales-led, and the operator key is a single shared secret. Per-user operator
accounts and billing are separate work if the sales model changes.
