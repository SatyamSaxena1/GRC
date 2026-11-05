"""Count the leavers who still have an active account (ADR-051), entirely on the customer's own computer.

Two CSV exports go in: the people who have left (from the HR system) and the accounts that are still active (from the
directory). The script matches them by email and uploads ONE number. No name or address leaves the machine. Standard
library only, so this one file can be downloaded and run on its own.

    python hr_leavers.py --url https://grc.example.com --leavers leavers.csv --accounts accounts.csv --dry-run
    (upload token in GRC_UPLOAD_TOKEN)

`count_leavers(leavers, accounts)` takes two lists of email addresses, so tests need no files.
"""

from __future__ import annotations

ATTRIBUTE = "terminated_users_with_active_accounts"


def _norm(email: str) -> str:
    return (email or "").strip().lower()


def count_leavers(leavers: list[str], accounts: list[str]) -> tuple[int, list[str]]:
    """(how many leavers still have an active account, those addresses). Case and surrounding spaces are ignored, and a
    person listed twice counts once."""
    active = {_norm(a) for a in accounts if _norm(a)}
    still = sorted({_norm(x) for x in leavers if _norm(x)} & active)
    return len(still), still


def read_emails(path: str, column: str) -> list[str]:
    import csv

    with open(path, newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        names = {(n or "").strip().lower(): n for n in (reader.fieldnames or [])}
        if column.lower() not in names:
            raise ValueError(f"{path} has no '{column}' column (it has: {', '.join(reader.fieldnames or []) or 'none'})")
        real = names[column.lower()]
        return [row[real] for row in reader]


def build(leavers: list[str], accounts: list[str], allow_empty: bool = False) -> dict:
    count, _ = count_leavers(leavers, accounts)
    errors: list[str] = []
    if not any(_norm(x) for x in leavers) and not allow_empty:
        errors.append("the leavers list was empty (pass --allow-empty if nobody left in the period)")
    if not any(_norm(a) for a in accounts):
        errors.append("the active accounts list was empty")
    return {"attributes": {ATTRIBUTE: count}, "collection": {"complete": not errors, "errors": errors, "region": "hrms"}}


def main(argv: list[str] | None = None) -> int:
    import argparse
    import json
    import os
    import urllib.error
    import urllib.request

    parser = argparse.ArgumentParser(description="Count leavers who still have an active account; upload only the count.")
    parser.add_argument("--url", required=True, help="your GRC address, e.g. https://grc.blinkedit.me")
    parser.add_argument("--leavers", required=True, help="CSV of people who left, with an email column")
    parser.add_argument("--accounts", required=True, help="CSV of accounts that are still active, with an email column")
    parser.add_argument("--email-column", default="email", help="the column holding the address (default: email)")
    parser.add_argument("--allow-empty", action="store_true", help="accept an empty leavers list as 'nobody left'")
    parser.add_argument("--show", action="store_true", help="print the matching addresses here, on your computer only")
    parser.add_argument("--token", default=os.environ.get("GRC_UPLOAD_TOKEN", ""), help="or set GRC_UPLOAD_TOKEN")
    parser.add_argument("--dry-run", action="store_true", help="print the answer, upload nothing")
    args = parser.parse_args(argv)

    try:
        leavers = read_emails(args.leavers, args.email_column)
        accounts = read_emails(args.accounts, args.email_column)
    except (OSError, ValueError) as exc:
        print(f"could not read the files: {exc}")
        return 2
    result = build(leavers, accounts, args.allow_empty)
    print(json.dumps(result, indent=2))
    if args.show:
        for address in count_leavers(leavers, accounts)[1]:
            print("still active:", address)
    if args.dry_run:
        return 0
    if not args.token:
        print("no upload token: pass --token or set GRC_UPLOAD_TOKEN")
        return 2
    upload = urllib.request.Request(args.url.rstrip("/") + "/ingest/hrms", data=json.dumps(result).encode(), method="POST",
                                    headers={"Content-Type": "application/json", "Authorization": f"Bearer {args.token}"})
    try:
        with urllib.request.urlopen(upload, timeout=30) as response:
            print(f"uploaded: HTTP {response.status}")
    except urllib.error.HTTPError as exc:
        print(f"upload refused: HTTP {exc.code}")
        return 1
    return 0 if result["collection"]["complete"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
