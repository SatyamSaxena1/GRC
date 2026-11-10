# Sending Google Workspace evidence from your own computer (ADR-055)

No Google credential of yours is shared with us, and we call nothing in your Workspace. You run one small script and it
uploads two yes/no answers.

## One-time
1. Connections page, **Google Workspace** card, **Create my upload token**. Copy it now; it is shown once.
2. In the [Google Cloud console](https://console.cloud.google.com), in a project you own, turn on the **Admin SDK API**.
3. **APIs & Services**, **OAuth consent screen**: choose **Internal** (only your own Workspace users can sign in), add the
   two read-only scopes `https://www.googleapis.com/auth/admin.directory.user.readonly` and
   `https://www.googleapis.com/auth/admin.reports.audit.readonly`.
4. **Credentials**, **Create credentials**, **OAuth client ID**, type **Web application**, with the redirect address
   `https://developers.google.com/oauthplayground`. Copy the client ID and client secret.
5. Sign in to the [OAuth Playground](https://developers.google.com/oauthplayground) as a **super administrator**. In its
   settings (gear), tick **Use your own OAuth credentials** and paste the client ID and secret. Authorise the two scopes
   above, then **Exchange authorization code for tokens**. Copy the **refresh token**.
6. Get the script: `app/collectors/gworkspace_readonly.py` from the project repository. It needs Python 3 and nothing else.

The sign-in is a read-only view of your user list and admin audit log. You can revoke it any time at
`myaccount.google.com/permissions` (as that admin), or by deleting the OAuth client.

## Each time
```bash
export GOOGLE_CLIENT_ID="<the client id>"
export GOOGLE_CLIENT_SECRET="<the client secret>"
export GOOGLE_REFRESH_TOKEN="<the refresh token>"
export GRC_UPLOAD_TOKEN="<the upload token>"
python gworkspace_readonly.py --url https://grc.blinkedit.me --dry-run
python gworkspace_readonly.py --url https://grc.blinkedit.me
```
The first prints the answers and uploads nothing. Schedule the second for regular evidence.

For a one-off run you can skip the client and refresh token: put a short-lived access token (from the OAuth Playground,
step 2 of its flow) in `GOOGLE_ACCESS_TOKEN` instead.

Exit codes: 0 uploaded and complete, 1 refused by the server, 2 missing Google sign-in or an address that is not https,
3 uploaded but a check could not run, 4 the server could not be reached.

## What is checked
| Attribute | True when |
|---|---|
| `privileged_access_mfa` | every active super administrator has 2-step verification **enforced** |
| `access_logging_enabled` | the admin audit log recorded an event in the last 30 days |

## Honest limits
- Only super administrators are checked. Delegated administrators (a limited admin role) are not.
- Suspended super administrators are ignored, since they cannot sign in.
- "Enforced" is Google's own flag for the account. It does not tell you which policy or method (security key, phone) is used.
- It shows the admin audit log is active; it does not read the log's contents or other applications' logs.
- A Workspace with no admin changes at all in 30 days would read as false.
- A check the sign-in may not run is left out and the run is marked incomplete, never a pass or a failure.
- A service account with domain-wide delegation is not supported by this script: signing its token needs a cryptography
  library, and this file uses the standard library only. Use the OAuth route above.
