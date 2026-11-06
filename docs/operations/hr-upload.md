# Sending HR leaver evidence from your own computer (ADR-051)

No name or email address leaves your computer. The script counts the people who have left but still have an active
account, and uploads that one number.

## One-time
1. Connections page, **HR** card, **Create my upload token**. Copy it now; it is shown once.
2. Get the script: `app/collectors/hr_leavers.py` from the project repository. It needs Python 3 and nothing else.

## Each time
1. Export **leavers.csv** from your HR system: everyone who left in the period, with an `email` column.
2. Export **accounts.csv** from your directory (Entra, Google Workspace, Okta or similar): every account that is still
   active, with an `email` column. Use the same column name in both, or pass `--email-column`.
3. Run it:

```bash
export GRC_UPLOAD_TOKEN="<the upload token>"
python hr_leavers.py --url https://grc.blinkedit.me --leavers leavers.csv --accounts accounts.csv --dry-run --show
python hr_leavers.py --url https://grc.blinkedit.me --leavers leavers.csv --accounts accounts.csv
```
The first prints the count and, with `--show`, the matching addresses here on your computer, so you can disable those
accounts. The second uploads only the number. Exit codes: 0 uploaded and complete, 1 refused by the server, 2 missing files, token or an address that is not https,
3 uploaded but marked incomplete, 4 the server could not be reached.

## What is checked
| Attribute | Meaning |
|---|---|
| `terminated_users_with_active_accounts` | how many leavers still have an active account; the rule needs 0 |

## Honest limits
- It shows the two exports agree at the time they were exported. It cannot prove the exports are complete.
- An empty leavers list is marked incomplete unless you pass `--allow-empty` to say nobody left. An empty accounts list is
  always incomplete: it is almost certainly the wrong file.
- Rows with no usable email address (blank, or no @) are counted and the run is marked incomplete, never silently ignored.
  Addresses are matched exactly after trimming spaces and ignoring case, so `ada@x.com` and `ada@x.co.uk` are different people.
- Freshness is as recent as your last run; schedule it if you want it regular.
