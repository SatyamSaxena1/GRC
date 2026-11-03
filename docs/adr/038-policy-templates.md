# ADR-038: Policy templates whose figures come from the rules

Status: accepted

## Context
A new workspace often has no documents to upload. The sample policy on the Evidence page is one fixed file,
and any template typed by hand would drift from the packs: change a framework's threshold and the template
would quietly stop meeting it.

## Decision
`GET /templates` and `GET /templates/{id}` serve three starting documents (access control, password and
multi-factor authentication, encryption). Every figure a template states is the **strictest value any
loaded framework asks for**, read from the packs' delta conditions at request time: the largest minimum,
the smallest maximum, the union of required items. Approval, effective and review dates and the
organisation name are left as visible blanks for the organisation to fill in.

A test runs every stated value through the platform's own checker (`evaluate.check`) against every
condition on that attribute in every pack, so a template cannot ship a figure that fails a rule.

Reference data, like the glossary: no tenant rows, no RLS, signed-in callers only. The Evidence page
offers the templates as downloads beside the sample policy.

## Consequences
- The password length is now 14 where a pack asks for it, not the 12 a person might assume; changing a pack
  changes the template with no edit here.
- A template is a starting point, not proof: the dates and approver are the organisation's, and the
  uploaded, approved document is what the platform evaluates.
- Combining conditions is deliberately strict: an attribute whose conditions cannot be merged (mixed
  operators) raises, so a new kind of rule cannot produce a silently wrong template.
