# ADR-068: Connect GitHub with a one-click App install instead of a pasted token

**Status:** Accepted
**Date:** 2026-11-25
**Deciders:** Platform owner
**Builds on:** ADR-045 (an organisation connects its own GitHub), ADR-020 (change-control evidence)

## Context
Connecting GitHub meant creating a fine-grained token by hand: name it, pick one repository, set eight permissions, copy it
once, paste it into the product. It took a long guided session on 25 Nov 2026. A hand-made token also cannot be given the
"Checks" permission, so the check-run results the rules read came through a second route. Competing tools install an app in
one click; ours should.

## Decision
- The platform is registered **once** as a GitHub App with fixed read-only permissions. An organisation clicks
  **Install the GitHub App** on Connections, chooses repositories on GitHub's own page, and returns.
- **Nothing long-lived is stored for an App connection: only the installation number.** At collection time the server
  signs a nine-minute RS256 proof that it is the App, receives a one-hour token for that installation, and reads the
  repositories the installation can see *at that moment*. A repository added or removed in GitHub is picked up with no edit.
- **A pasted token still works**, unchanged, so existing connections and organisations without the App keep working.
- **Two things stop one organisation reading another's repositories.** The installation number comes back in a browser
  address and could be swapped, so: (1) the install link carries a sealed, 15-minute value naming the organisation that
  started it (the connections key encrypts it); (2) GitHub is asked, with the person's own one-time code, whether that
  installation is among theirs (the App asks GitHub to authorise the person during installation). Both must pass, and the
  server must then be able to mint a token for it, before anything is saved.
- Every host is fixed (`api.github.com`, `github.com`). Nothing a customer types can redirect the server.
- The App's settings arrive as server settings: `GITHUB_APP_ID`, `GITHUB_APP_SLUG`, `GITHUB_APP_CLIENT_ID`,
  `GITHUB_APP_CLIENT_SECRET`, `GITHUB_APP_PRIVATE_KEY` (the PEM; a one-line form with `\n` is accepted). Without all five,
  and the connections key, the install button is not shown.
- Removing the connection here deletes the stored installation number. The App stays installed until the person removes it
  in their GitHub settings; the page says so.

## Registering the App (once, by the owner)
GitHub → Settings → Developer settings → GitHub Apps → New GitHub App.
- **Name** `GRC Evidence` (its URL name becomes `GITHUB_APP_SLUG`). **Homepage URL** `https://grc.blinkedit.me`.
- **Callback URL** `https://grc.blinkedit.me/connections`. Tick **Request user authorization (OAuth) during installation**.
  (With that ticked GitHub returns the person to the callback address with `installation_id`, `code` and our `state`.)
- **Webhook:** untick Active. Nothing is pushed to us; we only read.
- **Repository permissions, all Read-only:** Actions, Administration, Checks, Commit statuses, Contents, Deployments,
  Issues, Pull requests. Metadata is added automatically. **Account permissions:** none.
- **Where can this App be installed:** "Only on this account" while testing; "Any account" before customers use it.
- Create it, note the **App ID** and **Client ID**, generate a **client secret** and a **private key** (a `.pem` download).
- On Render set the five settings above. The private key and client secret are secrets: paste them yourself and never
  commit them.

## How it was checked
`tests/test_github_app.py` replaces GitHub with a fake: a completed install stores only the installation number and no
response carries a token, key or secret; a sealed value from another organisation, a forged value, an expired value, an
installation the person does not own, a bad one-time code, and an install with no repositories are each refused and save
nothing; the proof of identity is a short RS256 token naming the App; the PEM may be on one line; a pasted-token
connection still returns what was saved. No real GitHub App was involved: the first live install is the real test.

## Consequences
- The first live install must be done by the owner after registering the App, and the result read on the DPDP readiness
  page. Until the five settings exist, the page looks exactly as before.
- The App can read the "Checks" permission, which a hand-made token cannot, so check-run results should read more
  completely than they did on 25 Nov 2026.
- One App for all customers means one private key to protect. It lives only in the server's settings.
- A customer's repository list is read at each collection and capped at ten, as before.
