# ADR-062: A public read-only demo, and a FREE plan

**Status:** Accepted
**Date:** 2026-11-11
**Deciders:** Platform owner

## Context
Competitor research (November 2026) found the challengers get noticed by letting people try the product without a
sales call (Scrut's public tour, open-source and free tiers), while every leader is sales-led. Our live site sends a
visitor straight to single sign-on, so there is nothing to see before a call. Plans and limits exist (ADR-054) but
have no free option.

## Decision
- **Public demo.** The header `Authorization: demo` resolves, without an account and even with stub tokens off, to
  the one organisation named in the server setting `DEMO_ORG_ID`, as a COMPLIANCE_VIEWER marked `demo`. Without the
  setting there is no demo (404).
- **Every change is refused** for the demo in the same place an ended trial is (`auth._enforce_trial`), whatever role a
  route would allow: any request other than GET, HEAD or OPTIONS is a 403 saying the demo is read-only. That also
  stops model calls, which are POSTs. The sign-in page shows "Try the demo, no account" only when `GET /public/demo`
  says one exists, and every page carries a banner saying it is a sample and read-only.
- **The demo organisation must hold only made-up data.** It is seeded by the operator and named in the setting; any
  visitor can read all of it.
- **FREE plan:** one framework, three people, no end date. Set by the operator like any plan (ADR-054); nothing is
  charged and no payment code exists.

## Consequences
- Visitors can look without an account, and anything they try to change is refused with a clear reason.
- An export by the demo writes an audit event against the demo organisation (actor `demo`). That is harmless and kept.
- Not done: self-serve sign-up straight into FREE. That needs the identity provider to create the login, which is the
  invite work left open (password flow, sidelined). Until then a FREE workspace starts from "Request an audit" or a
  conversation, and the operator sets the plan.
