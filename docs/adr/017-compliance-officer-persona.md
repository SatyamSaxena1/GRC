# ADR-017: The compliance officer is `ORG_ADMIN`; the only gap worth filling is a read-only org-wide role

## Context
The auditee side of this app has two roles (`app/models.py::User.role`): `ORG_ADMIN` and
`CONTROL_OWNER`. Neither is named "compliance officer", and the question came up of whether that
persona needs its own role.

Walking the code, the compliance-officer job is already `ORG_ADMIN`:

- **Sees the whole programme.** `app/authorization.py::assigned_control_ids` returns `None` (no
  restriction) for any role except `CONTROL_OWNER`, and `visible_clauses` narrows only for a
  `CONTROL_OWNER` or an auditor. An `ORG_ADMIN` already sees every control, gap, task and
  evidence item in the org, across every subscribed framework.
- **Runs remediation.** Only `ORG_ADMIN` may create a manual task or reassign / reschedule one
  (`app/routers/controls.py:324`, `:378`), and it sees every task (`:234`) rather than only
  owned ones.
- **Is the auditee's voice to the audit firm.** It answers the auditor's `EVIDENCE_REQUEST`
  messages and posts replies on a control thread (`app/routers/controls.py:470`).
- **Owns the readiness picture.** The Overview page (readiness, open gaps, task load, evidence
  health) is the `ORG_NAV` landing screen, i.e. the `ORG_ADMIN` view.

What `ORG_ADMIN` is *not* is a sysadmin. Org, user and engagement setup lives under
`/admin/*`, which is ungated bootstrap scaffolding, explicitly "not this slice"
(`app/routers/admin.py` docstring). So renaming the role to something IT-flavoured would be
backwards — the role is already the compliance lead, the name just undersells it.

The one real gap: there is no way to give someone **org-wide visibility without any write
power**. The second-line reviewer, the external consultant the auditee hires to prep, the risk
officer, an exec who wants the dashboard — today each of them is forced into `ORG_ADMIN` (too
much: can reassign tasks, message the auditor, submit controls) or `CONTROL_OWNER` (too little:
`visible_clauses` clamps them to their `ControlAssignment` rows, so the org-wide readiness
number is not even computable for them).

## Decision
**No new "compliance officer" role.** Document that `ORG_ADMIN` *is* the compliance officer —
in `app/models.py::User.role`, in the login-page role tour copy, and in the Admin invite hint —
so the persona is named where people read about roles, without a schema change or a migration.

**Add one role: `COMPLIANCE_VIEWER`** — org-wide read, zero write. This is the only piece with a
user behind it that `ORG_ADMIN` and `CONTROL_OWNER` cannot already cover.

Minimal shape, matching how roles are already enforced here:

1. `app/models.py::User.role` docstring gains `COMPLIANCE_VIEWER` in the org-side enum. No new
   column, no new table — `role` is a free string today and the stub/OIDC actor build
   (`app/auth.py`) already carries whatever string is on the row.
2. **Read is free.** `assigned_control_ids` and `visible_clauses` restrict only `CONTROL_OWNER`
   and auditors, so a `COMPLIANCE_VIEWER` sees the whole org with no change to
   `app/authorization.py`.
3. **Write must be closed deliberately, because the existing write gates are a mix of allowlist
   and denylist.** Allowlist gates (`if actor.role != "ORG_ADMIN": 403`) already exclude the new
   role for free — manual tasks, task reassignment, task scheduling. Denylist gates
   (`if actor.is_auditor: 403`, with everyone else allowed) would let a viewer through. Add one
   computed property `Actor.can_write` (`self.role not in {"COMPLIANCE_VIEWER"}` — and `AUDITOR`
   already handled separately) and guard the four denylist write paths on it:
   - `app/routers/evidence.py::upload_evidence` and `::upload_new_version` (only block
     `is_auditor` today)
   - `app/routers/controls.py::submit_control` (control submission)
   - `app/routers/controls.py` control-thread message POST for the auditee side
   - `app/routers/connectors.py` connector run/config endpoints (gate is `is_auditor or not
     org_id`)
   Each becomes `if not actor.can_write: raise HTTPException(403, ...)`. One grep of the router
   package for `is_auditor` and `actor.role` finds every site; the list above is that grep as of
   this ADR.
4. **Frontend:** a `VIEWER_NAV` in `app/../AppShell.tsx` that reuses the `ORG_NAV` entries by
   index (as `OWNER_NAV` / `AUDITOR_NAV` already do) minus `/admin`, and drops the action
   buttons on Tasks / Evidence / Control detail when `identity.role === "COMPLIANCE_VIEWER"`.
   The API is the real gate; hiding the buttons is just so the UI doesn't offer a 403.
5. **RLS:** none. `COMPLIANCE_VIEWER` reads the same `org_id`-scoped rows as `ORG_ADMIN`; the
   Postgres policies (ADR-001) key on tenant, not role, and that stays true.

Roughly a one-file model note, one `Actor` property, four one-line guards, one nav array, plus
tests for the four guards. It is deferred build: land it when the first real read-only user
appears, not before — the design is written down here so that day is a small PR, not a debate.

## Alternatives considered
- **Do nothing; tell people to use `ORG_ADMIN`.** Fine until the first engagement where the
  auditee brings in an outside consultant to prep and does not want them reassigning tasks or
  replying to the auditor in the org's name. At that point `ORG_ADMIN` is a data-integrity and
  attribution problem, not a preference. Cheap to defer, not safe to refuse.
- **A full RBAC / permissions table** (roles → permissions, editable in the UI). Rejected as
  speculative for a four-role product — the same call ADR-012 made about a redaction framework
  for one field. Two hard-coded org roles plus one viewer is readable and auditable; a
  permission matrix is a feature nobody has asked to configure.
- **Rename `ORG_ADMIN` to `COMPLIANCE_OFFICER`.** Rejected: a rename touches the model, both
  auth paths, ~8 router checks, the frontend identity type, the login tour, and every test that
  logs in as an org admin — a wide, purely cosmetic diff. A one-line docstring saying "this
  role is the compliance officer" delivers the same clarity for none of the blast radius.
- **Split `ORG_ADMIN` into "programme owner" (compliance) and "workspace admin" (user/
  engagement setup).** Rejected now because `/admin/*` is ungated bootstrap, not a real
  product surface — there is nothing yet to split off. Revisit if and when self-serve org
  administration gets built; that is the ADR that should own the split.
- **Make `COMPLIANCE_VIEWER` a flag on `ORG_ADMIN` rather than its own role** (e.g.
  `read_only: bool`). Rejected: `role` is already the one discriminator every check reads;
  a parallel boolean means every gate has to remember to check two fields instead of one.

## Consequences
- The persona question has a written answer: `ORG_ADMIN` today, `COMPLIANCE_VIEWER` when a
  read-only user shows up. No one has to re-derive the role model from the code next time.
- `Actor.can_write` becomes the seam for "may this caller mutate auditee data" — the first
  denylist→allowlist consolidation of the org-side write gates, which are currently scattered
  and inconsistent. A future role slots into that property instead of another grep.
- Until `COMPLIANCE_VIEWER` is built, the enum note in `app/models.py` will list a role the API
  does not yet special-case. That is intentional and low-risk: an unbuilt role string on a user
  row behaves exactly like `ORG_ADMIN` minus nothing, and the day it matters is the day the
  four guards land with it.
- If the four write guards are added without `COMPLIANCE_VIEWER` existing yet, they are inert
  (`can_write` is true for every current role) — safe to land early as pure hardening if the
  inconsistent gates bother someone first.
