# Sending Microsoft 365 evidence from your own tenant (ADR-050)

No Microsoft credential of yours is shared with us, and we call nothing in your tenant. You run one small script and it
uploads two yes/no answers.

## One-time
1. Connections page, **Microsoft 365** card, **Create my upload token**. Copy it now; it is shown once.
2. In Microsoft Entra admin centre, **App registrations**, **New registration** (any name, for example `grc-readonly`).
3. **API permissions**, **Add a permission**, **Microsoft Graph**, **Application permissions**, add **AuditLog.Read.All**,
   then **Grant admin consent**.
4. **Certificates & secrets**, **New client secret**. Copy the secret value (it is shown once).
5. Note the **Application (client) ID** and **Directory (tenant) ID** from the app's Overview page.
6. Get the script: `app/collectors/m365_readonly.py` from the project repository. It needs Python 3 and nothing else.

## Each time
```bash
export M365_CLIENT_SECRET="<the client secret>"
export GRC_UPLOAD_TOKEN="<the upload token>"
python m365_readonly.py --url https://grc.blinkedit.me --tenant <tenant id> --client-id <app id> --dry-run
python m365_readonly.py --url https://grc.blinkedit.me --tenant <tenant id> --client-id <app id>
```
The first prints the answers and uploads nothing. Schedule the second for regular evidence. Exit codes: 0 uploaded and
complete, 1 refused by the server, 2 missing credentials or an address that is not https, 3 uploaded but a check could not run,
4 the server could not be reached.

## What is checked
| Attribute | True when |
|---|---|
| `privileged_access_mfa` | every administrator account has registered multi-factor authentication |
| `access_logging_enabled` | the directory audit log recorded an event in the last 30 days |

## Honest limits
- It shows the Entra audit log is active; it does not read the Purview unified audit log setting.
- It shows MFA is registered, not that a conditional-access policy enforces it.
- A check the app may not run is left out and the run is marked incomplete, never a pass or a failure.
